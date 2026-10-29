"""C Bearer -> actual fixed E router/service -> same PostgreSQL audit transaction."""

import importlib.util
import os
import runpy
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient

from app.common.auth.m3_adapter import M3Permissions, install_m3_identity

from .test_hosted_runtime import scoped_engine
from .test_identity import login

try:
    e_available = importlib.util.find_spec("app.modules.m3_repair.contracts") is not None
except ModuleNotFoundError:
    e_available = False
if not e_available:
    if os.environ.get("CAMPUS_REQUIRE_M3_ACCEPTANCE") == "1":
        raise RuntimeError("Required fixed E sources were not prepared")
    pytest.skip("E ports run in the separate fixed C/E acceptance job", allow_module_level=True)

from app.modules.m3_repair.contracts import TicketError

BIG_ROOM = "9007199254740993"
PERMISSIONS = M3Permissions(create="m3.ticket.create", read_own="m3.ticket.read_own")
PAYLOAD = {"room_id": BIG_ROOM, "description": "合成报修描述，不进入公共审计"}


@pytest.fixture
def integrated(case):
    engine = scoped_engine(case.db)
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                for name in ("e02_m3_tickets.py", "e03_m3_assignment.py"):
                    original = Path(__file__).resolve().parents[2] / "alembic" / "versions" / name
                    fallback = Path(__file__).with_name("pinned_" + name[:3] + "_migration.py")
                    runpy.run_path(str(original if original.is_file() else fallback))["upgrade"]()
        case.app.state.engine = engine
        for name in ("reporter", "other"):
            case.ids[name] = case.auth.provision_user(
                username=name,
                password="synthetic-password-123",
                department_id="synthetic-m3",
                roles={"synthetic-m3": frozenset({PERMISSIONS.create, PERMISSIONS.read_own})},
                room_ids=frozenset({BIG_ROOM}),
            )
        principals = []

        def room_policy_factory(principal):
            principals.append(principal)

            class SyntheticPolicy:
                def require_reportable(self, room_id, actor):
                    assert actor.subject_id == str(principal.subject_id)
                    assert principal.department_id == "synthetic-m3"
                    if not principal.covers(str(room_id)):
                        raise TicketError(403, "room_denied", "合成资格拒绝")

            return SyntheticPolicy()

        with TestClient(case.app) as client:
            yield SimpleNamespace(
                case=case,
                client=client,
                principals=principals,
                policy=room_policy_factory,
                engine=engine,
            )
    finally:
        engine.dispose()


def install(s, *, with_policy=True):
    install_m3_identity(
        s.case.app,
        auth=s.case.auth,
        audit=s.case.audit,
        permissions=PERMISSIONS,
        room_policy_factory=s.policy if with_policy else None,
    )


def headers(s, name="reporter", key="synthetic-m3"):
    return {
        "Authorization": "Bearer " + login(s.client, name),
        "Idempotency-Key": key,
        "X-Request-ID": "untrusted-request-id",
        "X-Dev-User-Id": str(s.case.ids["other"]),
    }


def facts(s):
    with s.case.db.transaction() as conn:
        return (
            conn.execute("SELECT * FROM m3_tickets").fetchall(),
            conn.execute("SELECT * FROM c_audit_events WHERE action='m3.ticket.create'").fetchall(),
        )


def test_real_create_replay_own_reads_and_minimal_audit(integrated):
    s = integrated
    install(s)
    h = headers(s)
    first = s.client.post("/api/v1/m3/tickets", headers=h, json=PAYLOAD)
    assert first.status_code == 201, first.text
    identifier = first.json()["id"]
    replay = s.client.post("/api/v1/m3/tickets", headers=h, json=PAYLOAD)
    assert replay.status_code == 200 and replay.json() == first.json()
    assert s.client.get("/api/v1/m3/tickets/" + identifier, headers=h).json() == first.json()
    assert s.client.get("/api/v1/m3/tickets", headers=h).json()["items"] == [first.json()]
    other = headers(s, "other")
    assert s.client.get("/api/v1/m3/tickets/" + identifier, headers=other).status_code == 404
    assert s.client.get("/api/v1/m3/tickets", headers=other).json()["items"] == []
    tickets, events = facts(s)
    assert len(tickets) == len(events) == 1
    event = events[0]
    assert event["actor_id"] == s.case.ids["reporter"]
    assert event["target"] == identifier and event["room_id"] == BIG_ROOM
    assert event["changes"] == {"before": None, "after": "REPORTED"}
    assert event["result"] == "SUCCESS" and UUID(event["request_id"])
    assert PAYLOAD["description"] not in str(event)
    assert h["Authorization"] not in str(event)
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["X-Request-ID"] != h["X-Request-ID"]
    assert all(p.subject_id == s.case.ids["reporter"] for p in s.principals[:2])


def test_audit_database_failure_rolls_back_ticket_then_same_key_recovers(integrated):
    s = integrated
    install(s)
    h = headers(s)
    with s.case.db.transaction() as conn:
        conn.execute(
            "ALTER TABLE c_audit_events ADD CONSTRAINT synthetic_m3_audit_failure "
            "CHECK (action <> 'm3.ticket.create')"
        )
    response = s.client.post("/api/v1/m3/tickets", headers=h, json=PAYLOAD)
    assert response.status_code == 503 and response.json()["detail"]["code"] == "audit_unavailable"
    assert facts(s) == ([], [])
    with s.case.db.transaction() as conn:
        conn.execute("ALTER TABLE c_audit_events DROP CONSTRAINT synthetic_m3_audit_failure")
    assert s.client.post("/api/v1/m3/tickets", headers=h, json=PAYLOAD).status_code == 201
    assert tuple(map(len, facts(s))) == (1, 1)


def test_current_permissions_and_logout_are_checked_on_each_request(integrated):
    s = integrated
    install(s)
    assert s.client.get("/api/v1/m3/tickets").status_code == 401
    # M2 submission alone never grants M3 creation or own-ticket access.
    student = headers(s, "student")
    assert s.client.get("/api/v1/m3/tickets", headers=student).status_code == 403
    assert s.client.post("/api/v1/m3/tickets", headers=student, json=PAYLOAD).status_code == 403
    h = headers(s)
    with s.case.db.transaction() as conn:
        conn.execute("UPDATE c_roles SET permissions='{}' WHERE name='synthetic-m3'")
    assert s.client.post("/api/v1/m3/tickets", headers=h, json=PAYLOAD).status_code == 403
    assert s.client.get("/api/v1/m3/tickets", headers=h).status_code == 403
    assert s.client.delete("/api/v1/auth/sessions/current", headers=h).status_code == 204
    assert s.client.get("/api/v1/m3/tickets", headers=h).status_code == 401
    assert facts(s) == ([], [])


def test_missing_or_rejecting_room_policy_does_not_write(integrated):
    s = integrated
    install(s, with_policy=False)
    h = headers(s)
    response = s.client.post("/api/v1/m3/tickets", headers=h, json=PAYLOAD)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "room_policy_unconfigured"
    assert facts(s) == ([], [])


def test_room_policy_gets_current_principal_and_bigint_scope(integrated):
    s = integrated
    install(s)
    h = headers(s)
    denied = {**PAYLOAD, "room_id": "2"}
    assert s.client.post("/api/v1/m3/tickets", headers=h, json=denied).status_code == 403
    assert facts(s) == ([], [])
    with s.case.db.transaction() as conn:
        conn.execute("UPDATE c_users SET room_ids='{}' WHERE id=%s", (s.case.ids["reporter"],))
    assert s.client.post("/api/v1/m3/tickets", headers=h, json=PAYLOAD).status_code == 403
    assert s.principals[-1].room_ids == frozenset()


def test_without_installation_no_routes_and_duplicate_install_rejected(integrated):
    s = integrated
    assert s.client.get("/api/v1/m3/tickets").status_code == 404
    install(s)
    with pytest.raises(ValueError, match="already be mounted"):
        install(s)


def test_actual_tcp_login_create_read_logout(integrated):
    s = integrated
    install(s)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(s.case.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{sock.getsockname()[1]}", timeout=3, trust_env=False
        ) as client:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            token = login(client, "reporter")
            h = {"Authorization": "Bearer " + token, "Idempotency-Key": "tcp-m3"}
            created = client.post("/api/v1/m3/tickets", headers=h, json=PAYLOAD)
            assert created.status_code == 201
            assert client.get("/api/v1/m3/tickets", headers=h).json()["items"] == [created.json()]
            assert client.delete("/api/v1/auth/sessions/current", headers=h).status_code == 204
            assert client.get("/api/v1/m3/tickets", headers=h).status_code == 401
            assert tuple(map(len, facts(s))) == (1, 1)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


def test_new_e_actions_are_not_enabled_by_creation_identity(integrated):
    s = integrated
    install(s)
    h = headers(s)
    created = s.client.post("/api/v1/m3/tickets", headers=h, json=PAYLOAD)
    assert created.status_code == 201
    path = "/api/v1/m3/tickets/" + created.json()["id"]
    for action, data, code in (
        (
            "/assign",
            {"expected_version": 0, "assignee_id": str(s.case.ids["reporter"])},
            "assignment_policy_unconfigured",
        ),
        ("/work-starts", {"expected_version": 1}, "restriction_confirmation_unconfigured"),
    ):
        response = s.client.post(
            path + action, headers={**h, "Operation-Id": str(uuid4())}, json=data
        )
        assert response.status_code == 503 and response.json()["detail"]["code"] == code
    tickets, events = facts(s)
    assert len(tickets) == len(events) == 1
    assert tickets[0]["status"] == "REPORTED" and tickets[0]["version"] == 0
