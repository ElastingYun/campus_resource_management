import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.common.audit.service import AuditService
from app.common.auth.database import Database
from app.common.auth.domain import ServiceError
from app.common.auth.service import AuthService, AuthSettings
from app.modules.m2_approval.api import create_app
from app.modules.m2_approval.domain import Room, Step, Workflow
from app.modules.m2_approval.migrate import migrate
from app.modules.m2_approval.service import ApprovalService
from psycopg import sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_url():
    supplied = os.environ.get("C_TEST_DATABASE_URL")
    if supplied:
        yield supplied
        return
    pgserver = pytest.importorskip(
        "pgserver",
        reason="Set C_TEST_DATABASE_URL to a dedicated PostgreSQL test database",
    )
    with tempfile.TemporaryDirectory(
        prefix="c-pg-", dir="/private/tmp" if Path("/private/tmp").exists() else None
    ) as folder:
        server = pgserver.get_server(folder, cleanup_mode="stop")
        try:
            yield server.get_uri()
        finally:
            server.cleanup()


@pytest.fixture
def database(postgres_url):
    schema = "c_test_" + uuid4().hex
    base = Database(postgres_url)
    with base.transaction() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    db = Database(make_conninfo(postgres_url, options=f"-csearch_path={schema}"))
    migrate(db)
    try:
        yield db
    finally:
        with base.transaction() as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


class Clock:
    def __init__(self):
        self.now = datetime(2030, 1, 1, 8, tzinfo=UTC)

    def __call__(self):
        return self.now


class Resources:
    def get_room(self, room_id):
        if room_id not in ("R1", "R2", "R0"):
            raise ServiceError(404, "ROOM_NOT_FOUND", "教室不存在")
        return Room(room_id, "D2" if room_id == "R2" else "D1", room_id != "R0")


@pytest.fixture
def case(database):
    clock, audit = Clock(), AuditService(database)
    auth = AuthService(
        database,
        audit,
        AuthSettings(timedelta(hours=1), timedelta(minutes=5), 100),
        clock,
    )
    roles = {
        "applicant": frozenset({"m2.submit"}),
        "first": frozenset(
            {"m2.review", "review.first", "m2.read_all", "m2.revoke", "audit.read"}
        ),
        "second": frozenset({"m2.review", "review.second", "m2.read_all"}),
    }
    ids, principals = {}, {}
    for username, role, rooms in (
        ("student", "applicant", []),
        ("first", "first", ["R1"]),
        ("second", "second", ["R1"]),
        ("outsider", "first", ["R2"]),
    ):
        ids[username] = auth.provision_user(
            username=username,
            password="synthetic-password-123",
            department_id="D1",
            roles={role: roles[role]},
            room_ids=frozenset(rooms),
        )
        with database.transaction() as conn:
            principals[username] = auth._principal(conn, ids[username])
    workflow = Workflow(
        "test-only-v1",
        (
            Step("review.first", timedelta(minutes=10)),
            Step("review.second", timedelta(minutes=20)),
        ),
        allow_self_review=False,
        deadline_inclusive=True,
        require_rejection_reason=True,
        allow_revocation=True,
    )

    def validate(principal, room, starts_at, ends_at, now):
        if principal.department_id != room.department_id:
            raise ServiceError(403, "DEPARTMENT_DENIED", "测试资格拒绝")
        if starts_at < now:
            raise ServiceError(422, "START_IN_PAST", "开始时间已过")

    approval = ApprovalService(
        database, audit, Resources(), lambda principal, room: workflow, validate, clock
    )
    app = create_app(auth=auth, approval=approval, audit=audit)
    return SimpleNamespace(
        db=database,
        clock=clock,
        audit=audit,
        auth=auth,
        approval=approval,
        app=app,
        ids=ids,
        principals=principals,
        workflow=workflow,
    )


def submit(case, key="submit-1", **updates):
    payload = {
        "room_id": "R1",
        "starts_at": case.clock() + timedelta(hours=2),
        "ends_at": case.clock() + timedelta(hours=3),
        "purpose": "合成数据测试",
    }
    payload.update(updates)
    return case.approval.submit(
        case.principals["student"], **payload, key=key, request_id=key
    )
