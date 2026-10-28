"""Opt-in local demonstration. Its synthetic policies are not production rules."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import timedelta

import psycopg

from app.common.audit.service import AuditService
from app.common.auth.database import Database
from app.common.auth.domain import ServiceError
from app.common.auth.service import AuthService, AuthSettings
from app.modules.m2_approval.api import create_app
from app.modules.m2_approval.domain import Room, Step, Workflow
from app.modules.m2_approval.migrate import migrate
from app.modules.m2_approval.service import ApprovalService


class DemoResources:
    def get_room(self, room_id):
        if room_id != "demo-room":
            raise ServiceError(404, "ROOM_NOT_FOUND", "演示教室不存在")
        return Room("demo-room", "demo-department", True)


def create_demo_app():
    if os.environ.get("C_DEMO_MODE") != "1":
        raise RuntimeError("Set C_DEMO_MODE=1 explicitly to enable synthetic demo policies")
    dsn, password = (
        os.environ.get("C_DEMO_DATABASE_URL"),
        os.environ.get("C_DEMO_PASSWORD", ""),
    )
    if not dsn or len(password) < 12:
        raise RuntimeError(
            "Provide a dedicated demo database and a password of at least 12 characters"
        )
    database = Database(dsn)
    migrate(database)
    audit = AuditService(database)
    auth = AuthService(
        database, audit, AuthSettings(timedelta(minutes=10), timedelta(minutes=5), 30)
    )
    roles = {
        "demo-applicant": frozenset({"m2.submit"}),
        "demo-first": frozenset(
            {"m2.review", "demo.review.first", "m2.read_all", "m2.revoke", "audit.read"}
        ),
        "demo-second": frozenset({"m2.review", "demo.review.second", "m2.read_all"}),
    }
    for username, role in (
        ("demo-student", "demo-applicant"),
        ("demo-reviewer-1", "demo-first"),
        ("demo-reviewer-2", "demo-second"),
    ):
        auth.provision_user(
            username=username,
            password=password,
            department_id="demo-department",
            roles={role: roles[role]},
            room_ids=frozenset({"demo-room"}),
        )
    workflow = Workflow(
        "synthetic-demo-v1",
        (
            Step("demo.review.first", timedelta(minutes=1)),
            Step("demo.review.second", timedelta(minutes=1)),
        ),
        allow_self_review=False,
        deadline_inclusive=True,
        require_rejection_reason=True,
        allow_revocation=True,
    )

    def validate(principal, room, starts_at, ends_at, now):
        if principal.department_id != room.department_id:
            raise ServiceError(403, "DEPARTMENT_DENIED", "演示院系不匹配")
        if starts_at < now:
            raise ServiceError(422, "START_IN_PAST", "请选择未来时段")

    approval = ApprovalService(database, audit, DemoResources(), lambda *_: workflow, validate)

    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()

        async def scan():
            while not stop.is_set():
                try:
                    await asyncio.to_thread(approval.expire_due)
                    app.state.expiry_healthy = True
                except psycopg.Error:
                    app.state.expiry_healthy = False
                    logging.getLogger(__name__).error(
                        '{"event":"demo.expiry_database_unavailable"}'
                    )
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=1)

        app.state.expiry_healthy = True
        task = asyncio.create_task(scan())
        app.state.expiry_task = task
        try:
            yield
        finally:
            stop.set()
            await task

    app = create_app(auth=auth, approval=approval, audit=audit, lifespan=lifespan)

    @app.get("/health")
    def health():
        with database.transaction() as conn:
            conn.execute("SELECT 1")
        if not app.state.expiry_healthy or app.state.expiry_task.done():
            raise ServiceError(503, "EXPIRY_UNAVAILABLE", "演示超时扫描不可用")
        return {"status": "ok", "mode": "synthetic-demo", "m1_connected": False}

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.modules.m2_approval.demo:create_demo_app",
        factory=True,
        host="127.0.0.1",
        port=8082,
    )
