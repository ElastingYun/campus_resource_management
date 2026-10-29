import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.common.audit.service import AuditService
from app.common.auth.database import Database
from app.common.auth.domain import Principal, ServiceError, aware, utcnow
from app.modules.m2_approval.domain import ResourceGateway, Workflow, clean_text

PUBLIC_FIELDS = (
    "id",
    "applicant_id",
    "room_id",
    "starts_at",
    "ends_at",
    "purpose",
    "review_status",
    "integration_status",
    "step_index",
    "deadline",
    "version",
    "revoked",
    "created_at",
    "updated_at",
)


def public(row):
    # Receipts and HTTP responses use the same JSON-safe representation.
    result = {key: row[key] for key in PUBLIC_FIELDS}
    result["step_count"] = len(row["steps"])
    for key, value in result.items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    result["effective"] = (
        row["review_status"] == "PASSED"
        and row["integration_status"] == "APPLIED"
        and not row["revoked"]
    )
    return result


class ApprovalService:
    def __init__(
        self,
        database: Database,
        audit: AuditService,
        resources: ResourceGateway,
        workflow_for: Callable[..., Workflow],
        validate_submission: Callable,
        clock: Callable = utcnow,
    ):
        self.database, self.audit, self.resources = database, audit, resources
        self.workflow_for, self.validate_submission, self.clock = (
            workflow_for,
            validate_submission,
            clock,
        )

    def _receipt(self, conn, principal, action, key, payload):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key):
            raise ServiceError(422, "INVALID_IDEMPOTENCY_KEY", "幂等键格式不合法")
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        scope = f"{principal.subject_id}:{action}:{key}"
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (scope,))
        row = conn.execute(
            "SELECT * FROM c_receipts WHERE actor_id=%s AND action=%s AND key=%s",
            (principal.subject_id, action, key),
        ).fetchone()
        if row and row["fingerprint"] != fingerprint:
            raise ServiceError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同请求")
        return fingerprint, row["response"] if row else None

    def _save_receipt(self, conn, principal, action, key, fingerprint, row):
        result = public(row)
        conn.execute(
            "INSERT INTO c_receipts VALUES (%s,%s,%s,%s,%s)",
            (principal.subject_id, action, key, fingerprint, Jsonb(result)),
        )
        return result

    def _load(self, conn, application_id, *, lock=False):
        row = conn.execute(
            "SELECT * FROM c_applications WHERE id=%s" + (" FOR UPDATE" if lock else ""),
            (application_id,),
        ).fetchone()
        if not row:
            raise ServiceError(404, "NOT_FOUND", "申请不存在或不可见")
        return row

    def _can_review(self, principal, row):
        return (
            not row["revoked"]
            and row["review_status"] == "REVIEWING"
            and "m2.review" in principal.permissions
            and principal.covers(row["room_id"])
            and row["steps"][row["step_index"]]["permission"] in principal.permissions
            and (row["rules"]["allow_self_review"] or row["applicant_id"] != principal.subject_id)
        )

    def _readable(self, principal, row):
        if (
            row["applicant_id"] == principal.subject_id
            or self._can_review(principal, row)
            or ("m2.read_all" in principal.permissions and principal.covers(row["room_id"]))
        ):
            return
        raise ServiceError(404, "NOT_FOUND", "申请不存在或不可见")

    def _expired(self, row, now):
        return (
            now >= row["deadline"] if row["rules"]["deadline_inclusive"] else now > row["deadline"]
        )

    def _event(self, conn, row, event_type, now):
        conn.execute(
            "INSERT INTO c_business_events VALUES (%s,%s,%s,%s,%s)",
            (
                uuid4(),
                row["id"],
                event_type,
                Jsonb(
                    {
                        "application_id": str(row["id"]),
                        "version": row["version"],
                        "review_status": row["review_status"],
                        "integration_status": row["integration_status"],
                    }
                ),
                now,
            ),
        )

    def _audit(self, conn, principal, row, action, before, now, request_id):
        self.audit.record(
            conn,
            actor=principal.subject_id if principal else None,
            action=action,
            target=str(row["id"]),
            result="SUCCESS",
            now=now,
            request_id=request_id,
            room_id=row["room_id"],
            before=before,
            after=row["review_status"] + "/" + row["integration_status"],
        )

    def _operation(self, conn, row, kind, now):
        operation_id = uuid4()
        payload = {
            "operation_id": str(operation_id),
            "source": "M2",
            "source_id": str(row["id"]),
            "room_id": row["room_id"],
            "starts_at": row["starts_at"].isoformat(),
            "ends_at": row["ends_at"].isoformat(),
            "generation": row["generation"],
            "kind": kind,
        }
        conn.execute(
            """INSERT INTO c_m1_operations
               (id,application_id,generation,kind,payload,due_at) VALUES (%s,%s,%s,%s,%s,%s)""",
            (operation_id, row["id"], row["generation"], kind, Jsonb(payload), now),
        )

    def submit(
        self,
        principal: Principal,
        *,
        room_id,
        starts_at,
        ends_at,
        purpose,
        key: str,
        request_id: str,
    ):
        principal.require("m2.submit")
        room_id = clean_text(room_id, "教室标识", 128)
        purpose = clean_text(purpose, "用途", 2000)
        starts_at, ends_at = aware(starts_at), aware(ends_at)
        if ends_at <= starts_at:
            raise ServiceError(422, "INVALID_INTERVAL", "结束时间必须晚于开始时间")
        payload = {
            "room_id": room_id,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "purpose": purpose,
        }
        # Fast replay before external resource lookup; check again under the write lock.
        with self.database.transaction() as conn:
            _, previous = self._receipt(conn, principal, "submit", key, payload)
            if previous is not None:
                return previous
        room = self.resources.get_room(room_id)
        if room.id != room_id or not room.enabled:
            raise ServiceError(409, "ROOM_UNAVAILABLE", "教室当前不可申请")
        now = aware(self.clock())
        self.validate_submission(principal, room, starts_at, ends_at, now)
        workflow = self.workflow_for(principal, room)
        if not isinstance(workflow, Workflow):
            raise TypeError("Host must resolve an explicit Workflow")
        steps = [
            {"permission": s.permission, "timeout_seconds": s.timeout.total_seconds()}
            for s in workflow.steps
        ]
        rules = {k: v for k, v in asdict(workflow).items() if k != "steps"}
        with self.database.transaction() as conn:
            fingerprint, previous = self._receipt(conn, principal, "submit", key, payload)
            if previous is not None:
                return previous
            row = conn.execute(
                """INSERT INTO c_applications
                   (id,applicant_id,room_id,starts_at,ends_at,purpose,review_status,
                    integration_status,step_index,steps,rules,deadline,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,'REVIEWING','NONE',0,%s,%s,%s,%s,%s) RETURNING *""",
                (
                    uuid4(),
                    principal.subject_id,
                    room_id,
                    starts_at,
                    ends_at,
                    purpose,
                    Jsonb(steps),
                    Jsonb(rules),
                    now + workflow.steps[0].timeout,
                    now,
                    now,
                ),
            ).fetchone()
            self._audit(conn, principal, row, "m2.submit", None, now, request_id)
            self._event(conn, row, "application.submitted", now)
            return self._save_receipt(conn, principal, "submit", key, fingerprint, row)

    def get(self, principal, application_id):
        with self.database.transaction() as conn:
            row = self._load(conn, application_id)
            self._readable(principal, row)
            return public(row)

    def integration_progress(self, principal, application_id):
        with self.database.transaction() as conn:
            # One statement gives the application and its operations one snapshot,
            # including when a concurrent revocation creates the next generation.
            row = conn.execute(
                """SELECT a.*,COALESCE((
                     SELECT jsonb_agg(jsonb_build_object(
                       'id',o.id,'generation',o.generation,'kind',o.kind,
                       'state',o.state,'attempts',o.attempts,'error_code',o.error_code
                     ) ORDER BY o.generation,o.id)
                     FROM c_m1_operations o WHERE o.application_id=a.id
                   ),'[]'::jsonb) AS operations
                   FROM c_applications a WHERE a.id=%s""",
                (application_id,),
            ).fetchone()
            if not row:
                raise ServiceError(404, "NOT_FOUND", "申请不存在或不可见")
            self._readable(principal, row)
            return {
                "application_id": row["id"],
                "version": row["version"],
                "generation": row["generation"],
                "integration_status": row["integration_status"],
                "effective": public(row)["effective"],
                "operations": row["operations"],
            }

    def actions(self, principal, application_id):
        with self.database.transaction() as conn:
            row = self._load(conn, application_id)
            self._readable(principal, row)
            allowed = []
            if self._can_review(principal, row) and not self._expired(row, aware(self.clock())):
                allowed.extend(("APPROVE", "REJECT"))
            if (
                "m2.revoke" in principal.permissions
                and principal.covers(row["room_id"])
                and row["rules"]["allow_revocation"]
                and not row["revoked"]
                and row["review_status"] in ("REVIEWING", "PASSED")
            ):
                allowed.append("REVOKE")
            return {
                "application_id": row["id"],
                "version": row["version"],
                "allowed_actions": allowed,
            }

    def list_applications(self, principal, *, limit, offset, tasks_only=False):
        with self.database.transaction() as conn:
            rows = conn.execute(
                """SELECT * FROM c_applications a WHERE
                   ((NOT %s AND applicant_id=%s) OR
                    (NOT %s AND %s AND (%s OR room_id=ANY(%s))) OR
                    (%s AND (%s OR room_id=ANY(%s)) AND review_status='REVIEWING' AND NOT revoked
                     AND (steps->step_index->>'permission')=ANY(%s)
                     AND ((rules->>'allow_self_review')::boolean OR applicant_id<>%s)))
                   ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s""",
                (
                    tasks_only,
                    principal.subject_id,
                    tasks_only,
                    "m2.read_all" in principal.permissions,
                    principal.all_rooms,
                    list(principal.room_ids),
                    "m2.review" in principal.permissions,
                    principal.all_rooms,
                    list(principal.room_ids),
                    list(principal.permissions),
                    principal.subject_id,
                    limit,
                    offset,
                ),
            ).fetchall()
            return [public(row) for row in rows]

    def history(self, principal, application_id):
        with self.database.transaction() as conn:
            row = self._load(conn, application_id)
            self._readable(principal, row)
            return conn.execute(
                """SELECT id,step_index,actor_id,decision,comment,occurred_at
                   FROM c_decisions WHERE application_id=%s ORDER BY step_index""",
                (application_id,),
            ).fetchall()

    def decide(
        self,
        principal,
        application_id,
        *,
        decision,
        comment,
        expected_version,
        key,
        request_id,
    ):
        principal.require("m2.review")
        if decision not in ("APPROVE", "REJECT"):
            raise ServiceError(422, "INVALID_DECISION", "审批决定不合法")
        comment = clean_text(comment, "意见", 2000, required=False)
        payload = {
            "decision": decision,
            "comment": comment,
            "expected_version": expected_version,
        }
        action = "decision:" + str(application_id)
        with self.database.transaction() as conn:
            fingerprint, previous = self._receipt(conn, principal, action, key, payload)
            if previous is not None:
                principal.require("m2.review", previous["room_id"])
                return previous
            row = self._load(conn, application_id, lock=True)
            self._readable(principal, row)
            if row["version"] != expected_version:
                raise ServiceError(409, "STALE_VERSION", "申请已更新，请刷新后重试")
            if row["review_status"] != "REVIEWING" or row["revoked"]:
                raise ServiceError(409, "INVALID_STATE", "申请已不能审批")
            if not self._can_review(principal, row):
                raise ServiceError(403, "WRONG_REVIEWER", "无权处理当前节点")
            now = aware(self.clock())
            if self._expired(row, now):
                raise ServiceError(409, "REVIEW_EXPIRED", "审批期限已到")
            if decision == "REJECT" and row["rules"]["require_rejection_reason"] and not comment:
                raise ServiceError(422, "REASON_REQUIRED", "请填写驳回理由")
            before = row["review_status"] + "/" + row["integration_status"]
            conn.execute(
                "INSERT INTO c_decisions VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    uuid4(),
                    row["id"],
                    row["step_index"],
                    principal.subject_id,
                    decision,
                    comment,
                    now,
                ),
            )
            status, integration, index = (
                row["review_status"],
                row["integration_status"],
                row["step_index"],
            )
            deadline, generation = row["deadline"], row["generation"]
            if decision == "REJECT":
                status = "REJECTED"
            elif index + 1 < len(row["steps"]):
                index += 1
                deadline = now + timedelta(seconds=row["steps"][index]["timeout_seconds"])
            else:
                status, integration, generation = (
                    "PASSED",
                    "APPLY_PENDING",
                    generation + 1,
                )
            row = conn.execute(
                """UPDATE c_applications SET review_status=%s,integration_status=%s,
                   step_index=%s,deadline=%s,generation=%s,version=version+1,updated_at=%s
                   WHERE id=%s RETURNING *""",
                (status, integration, index, deadline, generation, now, row["id"]),
            ).fetchone()
            if integration == "APPLY_PENDING":
                self._operation(conn, row, "APPLY", now)
            self._audit(conn, principal, row, "m2." + decision.lower(), before, now, request_id)
            self._event(conn, row, "application." + decision.lower(), now)
            return self._save_receipt(conn, principal, action, key, fingerprint, row)

    def expire_due(self, *, limit=100):
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid scan batch size")
        now, count = aware(self.clock()), 0
        with self.database.transaction() as conn:
            rows = conn.execute(
                """SELECT * FROM c_applications WHERE review_status='REVIEWING'
                   AND NOT revoked AND deadline<=%s ORDER BY deadline,id
                   LIMIT %s FOR UPDATE SKIP LOCKED""",
                (now, limit),
            ).fetchall()
            for original in rows:
                if not self._expired(original, now):
                    continue
                row = conn.execute(
                    """UPDATE c_applications SET review_status='TIMED_OUT',version=version+1,
                       updated_at=%s WHERE id=%s RETURNING *""",
                    (now, original["id"]),
                ).fetchone()
                self._audit(conn, None, row, "m2.timeout", "REVIEWING/NONE", now, str(uuid4()))
                self._event(conn, row, "application.timed_out", now)
                count += 1
        return count

    def revoke(self, principal, application_id, *, expected_version, key, request_id):
        principal.require("m2.revoke")
        action = "revoke:" + str(application_id)
        with self.database.transaction() as conn:
            fingerprint, previous = self._receipt(
                conn, principal, action, key, {"expected_version": expected_version}
            )
            if previous is not None:
                principal.require("m2.revoke", previous["room_id"])
                return previous
            row = self._load(conn, application_id, lock=True)
            principal.require("m2.revoke", row["room_id"])
            if not row["rules"]["allow_revocation"]:
                raise ServiceError(403, "REVOCATION_DISABLED", "当前流程未开放撤销")
            if row["version"] != expected_version:
                raise ServiceError(409, "STALE_VERSION", "申请已更新，请刷新后重试")
            if row["revoked"] or row["review_status"] not in ("REVIEWING", "PASSED"):
                raise ServiceError(409, "INVALID_STATE", "当前申请不能撤销")
            now = aware(self.clock())
            before = row["review_status"] + "/" + row["integration_status"]
            has_operation = row["generation"] > 0
            row = conn.execute(
                """UPDATE c_applications SET revoked=true,version=version+1,
                   generation=generation+%s,integration_status=%s,updated_at=%s
                   WHERE id=%s RETURNING *""",
                (
                    1 if has_operation else 0,
                    "RELEASE_PENDING" if has_operation else "NONE",
                    now,
                    row["id"],
                ),
            ).fetchone()
            if has_operation:
                self._operation(conn, row, "RELEASE", now)
            self._audit(conn, principal, row, "m2.revoke", before, now, request_id)
            self._event(conn, row, "application.revoked", now)
            return self._save_receipt(conn, principal, action, key, fingerprint, row)
