from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from app.common.audit.service import AuditService
from app.common.auth.database import Database
from app.common.auth.domain import aware, utcnow
from app.modules.m2_approval.clients import M1Gateway, Outcome, RemoteUnavailable
from app.modules.m2_approval.events import record_business_event


@dataclass(frozen=True)
class RetrySettings:
    lease: timedelta
    delay: timedelta
    max_attempts: int

    def __post_init__(self):
        if (
            self.lease.total_seconds() <= 0
            or self.delay.total_seconds() <= 0
            or self.max_attempts < 1
        ):
            raise ValueError("Positive lease, retry delay and attempt limit are required")


class OperationWorker:
    def __init__(
        self,
        database: Database,
        audit: AuditService,
        gateway: M1Gateway,
        settings: RetrySettings,
        clock: Callable = utcnow,
    ):
        self.database, self.audit, self.gateway = database, audit, gateway
        self.settings, self.clock = settings, clock

    def _claim(self):
        now = aware(self.clock())
        with self.database.transaction() as conn:
            row = conn.execute(
                """SELECT * FROM c_m1_operations
                   WHERE state IN ('PENDING','UNKNOWN','RUNNING') AND due_at<=%s
                   AND (lease_until IS NULL OR lease_until<=%s)
                   ORDER BY due_at,id LIMIT 1 FOR UPDATE SKIP LOCKED""",
                (now, now),
            ).fetchone()
            if not row:
                return None
            if row["attempts"] >= self.settings.max_attempts:
                application = conn.execute(
                    "SELECT room_id FROM c_applications WHERE id=%s", (row["application_id"],)
                ).fetchone()
                conn.execute(
                    """UPDATE c_m1_operations SET state='ATTENTION',lease_until=NULL,
                       lease_token=NULL,error_code='RETRY_LIMIT' WHERE id=%s""",
                    (row["id"],),
                )
                self.audit.record(
                    conn,
                    actor=None,
                    action="m1.attention",
                    target=str(row["id"]),
                    room_id=application["room_id"],
                    result="RETRY_LIMIT",
                    now=now,
                    request_id=str(row["id"]),
                )
                return {"attention": True}
            row["previous_state"], row["lease_token"] = row["state"], uuid4()
            conn.execute(
                """UPDATE c_m1_operations SET state='RUNNING',attempts=attempts+1,
                   lease_until=%s,lease_token=%s WHERE id=%s""",
                (now + self.settings.lease, row["lease_token"], row["id"]),
            )
            return row

    def run_once(self) -> bool:
        operation = self._claim()
        if operation is None:
            return False
        if operation.get("attention"):
            return True
        error = None
        try:
            if operation["previous_state"] in ("UNKNOWN", "RUNNING"):
                outcome = self.gateway.query(str(operation["id"]))
                if outcome == Outcome.NOT_FOUND:
                    # Same operation and content, never a fresh idempotency key.
                    outcome = self.gateway.execute(operation["payload"])
            else:
                outcome = self.gateway.execute(operation["payload"])
        except RemoteUnavailable:
            outcome, error = Outcome.PENDING, "REMOTE_UNCONFIRMED"
        expected = Outcome.APPLIED if operation["kind"] == "APPLY" else Outcome.RELEASED
        conflict = operation["kind"] == "APPLY" and outcome == Outcome.CONFLICT
        confirmed = outcome == expected or conflict
        now = aware(self.clock())
        with self.database.transaction() as conn:
            row = conn.execute(
                """UPDATE c_m1_operations SET state=%s,due_at=%s,lease_until=NULL,
                   lease_token=NULL,error_code=%s WHERE id=%s AND lease_token=%s RETURNING *""",
                (
                    "CONFLICT" if conflict else "DONE" if confirmed else "UNKNOWN",
                    now + self.settings.delay,
                    error or (None if confirmed else "REMOTE_UNCONFIRMED"),
                    operation["id"],
                    operation["lease_token"],
                ),
            ).fetchone()
            if not row:
                # A reclaimed lease fences out the old worker's late response.
                return True
            application = conn.execute(
                "SELECT * FROM c_applications WHERE id=%s FOR UPDATE",
                (operation["application_id"],),
            ).fetchone()
            if operation["generation"] == application["generation"]:
                status = (
                    "APPLY_CONFLICT"
                    if conflict
                    else "APPLIED"
                    if confirmed and operation["kind"] == "APPLY"
                    else "RELEASED"
                    if confirmed
                    else "APPLY_UNKNOWN"
                    if operation["kind"] == "APPLY"
                    else "RELEASE_UNKNOWN"
                )
                if status != application["integration_status"]:
                    updated = conn.execute(
                        """UPDATE c_applications SET integration_status=%s,version=version+1,
                           updated_at=%s WHERE id=%s RETURNING *""",
                        (status, now, application["id"]),
                    ).fetchone()
                    event_type = {
                        "APPLIED": "application.occupancy_confirmed",
                        "APPLY_CONFLICT": "application.occupancy_conflict",
                        "RELEASED": "application.occupancy_released",
                    }.get(status)
                    if event_type is not None:
                        record_business_event(
                            conn, updated, event_type, now, operation_id=operation["id"]
                        )
                    self.audit.record(
                        conn,
                        actor=None,
                        action="m1." + operation["kind"].lower(),
                        target=str(application["id"]),
                        room_id=application["room_id"],
                        result="CONFIRMED" if confirmed else "UNKNOWN",
                        now=now,
                        request_id=str(operation["id"]),
                        before=application["integration_status"],
                        after=status,
                    )
            # A late result may finish its operation, but cannot overwrite a newer intent.
        return True
