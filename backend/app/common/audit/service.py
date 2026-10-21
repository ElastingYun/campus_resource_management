from datetime import datetime
from uuid import UUID, uuid4

from app.common.auth.database import Database
from app.common.auth.domain import Principal
from psycopg.types.json import Jsonb


class AuditService:
    def __init__(self, database: Database):
        self.database = database

    def record(self, conn, *, actor: UUID | None, action: str, target: str,
               result: str, now: datetime, request_id: str,
               room_id: str | None = None, before: str | None = None,
               after: str | None = None) -> None:
        # Only explicit metadata is accepted. Never accept arbitrary request bodies.
        conn.execute(
            """INSERT INTO c_audit_events
               (id, actor_id, action, target, result, occurred_at, request_id,
                room_id, changes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (uuid4(), actor, action, target, result, now, request_id, room_id,
             Jsonb({"before": before, "after": after})),
        )

    def failure(self, *, actor: UUID | None, code: str,
                request_id: str, now: datetime) -> None:
        # This separate transaction runs after the business transaction rolled back.
        with self.database.transaction() as conn:
            self.record(conn, actor=actor, action="request.denied", target="request",
                        result=code, now=now, request_id=request_id)

    def list_events(self, principal: Principal, *, limit: int, offset: int):
        principal.require("audit.read")
        with self.database.transaction() as conn:
            return conn.execute(
                """SELECT id, actor_id, action, target, result, occurred_at,
                          request_id, room_id, changes
                   FROM c_audit_events
                   WHERE (%s OR room_id = ANY(%s))
                   ORDER BY occurred_at DESC, id DESC LIMIT %s OFFSET %s""",
                (principal.all_rooms, list(principal.room_ids), limit, offset),
            ).fetchall()
