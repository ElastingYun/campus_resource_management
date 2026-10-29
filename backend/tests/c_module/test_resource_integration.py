"""Actual B-v2/C-auth/C-audit integration, enabled in a pinned combined workspace."""

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time as wall_time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import insert, text, update

from app.common.audit.service import AuditService
from app.common.auth.resource_adapter import (
    NewRoomPolicy,
    ResourceManagementConfiguration,
    ResourcePermissions,
    install_resource_management,
)
from app.common.auth.service import AuthService

if importlib.util.find_spec("app.modules.resources") is None:
    if os.environ.get("CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE") == "1":
        raise RuntimeError("Required B v2 source was not prepared; acceptance cannot skip")
    pytest.skip("B v2 is tested by the separate pinned C/B acceptance job", allow_module_level=True)

from app.modules.resources.tables import metadata, rooms

from .test_hosted_runtime import hosted
from .test_runtime_settings import EXAMPLE

BIG_ROOM = 9007199254740993
PERMISSIONS = ResourcePermissions(
    read="synthetic.resource.read",
    manage="synthetic.resource.manage",
    create_rooms="synthetic.resource.create",
)


def configuration(create=True):
    return ResourceManagementConfiguration(
        permissions=PERMISSIONS,
        new_room=NewRoomPolicy(
            open_time=time(8),
            close_time=time(22),
            access_scope="campus",
            department_id=None,
            enabled=True,
        )
        if create
        else None,
    )


@pytest.fixture
def integrated(database, tmp_path, monkeypatch, request):
    application, engine = hosted(database, tmp_path, monkeypatch)
    request.addfinalizer(engine.dispose)
    component = application.state.c_runtime
    bootstrap = AuthService(database, AuditService(database), component.auth.settings)
    # Only this fixture's random schema, never application startup or shared tables.
    metadata.create_all(engine)
    with engine.begin() as conn:
        for identifier, code in ((BIG_ROOM, "BIG"), (2, "OTHER")):
            conn.execute(
                insert(rooms).values(
                    id=identifier,
                    code=code,
                    name="合成教室",
                    location="合成区域",
                    access_scope="campus",
                    department_id=None,
                    open_time=time(8),
                    close_time=time(22),
                    enabled=True,
                )
            )
    ids = {}
    for name, allowed, scope, global_scope in (
        (
            "manager",
            {
                PERMISSIONS.read,
                PERMISSIONS.manage,
                PERMISSIONS.create_rooms,
                "audit.read",
                "auth.manage",
            },
            frozenset(),
            True,
        ),
        ("reader", {PERMISSIONS.read}, frozenset({str(BIG_ROOM)}), False),
        ("outsider", {PERMISSIONS.read, PERMISSIONS.manage}, frozenset({"2"}), False),
        ("ordinary", set(), frozenset(), False),
    ):
        ids[name] = bootstrap.provision_user(
            username=name,
            password="synthetic-resource-password",
            department_id="synthetic",
            roles={"synthetic-" + name: frozenset(allowed)},
            room_ids=scope,
            all_rooms=global_scope,
        )
    install_resource_management(
        application, auth=component.auth, audit=component.audit, configuration=configuration()
    )
    with TestClient(application) as client:

        def headers(name="manager"):
            response = client.post(
                "/api/v1/auth/sessions",
                json={"username": name, "password": "synthetic-resource-password"},
            )
            assert response.status_code == 200
            return {"Authorization": "Bearer " + response.json()["access_token"]}

        yield SimpleNamespace(
            client=client,
            component=component,
            db=database,
            engine=engine,
            ids=ids,
            headers=headers,
            app=application,
        )


def test_real_identity_scope_and_untrusted_headers(integrated):
    s = integrated
    endpoint = "/api/v1/resources/rooms"
    response = s.client.get(
        endpoint, headers={"X-Dev-User-Id": str(s.ids["manager"]), "X-Dev-Permissions": "*"}
    )
    assert response.status_code == 401
    response = s.client.get(endpoint, headers=s.headers("ordinary"))
    assert response.status_code == 403 and response.json()["detail"]["code"] == "forbidden"
    reader = s.headers("reader")
    response = s.client.get(endpoint, headers=reader)
    assert [r["id"] for r in response.json()["items"]] == [str(BIG_ROOM)]
    assert s.client.get(endpoint + "/2", headers=reader).status_code == 404
    response = s.client.patch(
        endpoint + "/" + str(BIG_ROOM),
        headers=reader,
        json={"name": "拒绝写入", "expected_revision": response.json()["items"][0]["revision"]},
    )
    assert response.status_code == 403
    with s.db.transaction() as conn:
        codes = {
            row["result"]
            for row in conn.execute(
                "SELECT result FROM c_audit_events WHERE action='request.denied'"
            ).fetchall()
        }
    assert {"AUTHENTICATION_REQUIRED", "resources.forbidden", "resources.room_not_found"}.issubset(
        codes
    )


def test_crud_persists_exact_c_audit_and_server_request_id(integrated):
    s = integrated
    headers = s.headers() | {"X-Request-ID": "00000000-0000-4000-8000-000000000099"}
    room = s.client.post(
        "/api/v1/resources/rooms",
        headers=headers,
        json={"code": "NEW", "name": "新合成教室", "location": "合成一层"},
    )
    assert room.status_code == 201
    rid = room.json()["id"]
    seat = s.client.post(
        f"/api/v1/resources/rooms/{rid}/seats",
        headers=headers,
        json={"code": "01", "outlet_type": "fixed"},
    )
    assert seat.status_code == 201
    changed = s.client.patch(
        f"/api/v1/resources/seats/{seat.json()['id']}",
        headers=headers,
        json={"outlet_type": "rail", "expected_revision": seat.json()["revision"]},
    )
    assert changed.status_code == 200
    with s.db.transaction() as conn:
        events = conn.execute(
            "SELECT * FROM c_audit_events WHERE action LIKE 'resources.%%' ORDER BY occurred_at,id"
        ).fetchall()
    assert {e["action"] for e in events} == {
        "resources.room.create",
        "resources.seat.create",
        "resources.seat.update",
    }
    assert len(events) == 3
    for event in events:
        assert event["actor_id"] == s.ids["manager"] and event["room_id"] == rid
        assert event["request_id"] != headers["X-Request-ID"]
        assert str(UUID(event["request_id"])) == event["request_id"]
        assert event["result"] == "SUCCESS"
    update = next(e for e in events if e["action"] == "resources.seat.update")
    assert json.loads(update["changes"]["before"]) == {"outlet_type": "fixed"}
    assert json.loads(update["changes"]["after"]) == {"outlet_type": "rail"}
    assert (
        s.client.get(f"/api/v1/resources/seats/{seat.json()['id']}", headers=headers).json()[
            "outlet_type"
        ]
        == "rail"
    )
    view = s.client.get("/api/v1/audit/events", headers=headers)
    assert view.status_code == 200
    assert any(e["request_id"] == changed.headers["X-Request-ID"] for e in view.json())


@pytest.mark.parametrize("fault", ["exception", "constraint"])
def test_audit_insert_then_failure_rolls_back_resource_and_success_audit(
    integrated, monkeypatch, fault
):
    s = integrated
    original = s.component.audit.record_in_session

    def fail(session, **fields):
        original(session, **fields)
        if fault == "constraint":
            session.execute(
                text(
                    "INSERT INTO c_audit_events SELECT * FROM c_audit_events "
                    "WHERE action='resources.room.update'"
                )
            )
        raise RuntimeError("synthetic-private-error-must-not-escape")

    monkeypatch.setattr(s.component.audit, "record_in_session", fail)
    headers = s.headers()
    current = s.client.get(f"/api/v1/resources/rooms/{BIG_ROOM}", headers=headers).json()
    response = s.client.patch(
        f"/api/v1/resources/rooms/{BIG_ROOM}",
        headers=headers,
        json={"name": "不能提交", "expected_revision": current["revision"]},
    )
    assert response.status_code == 503 and response.json()["detail"]["code"] == "audit_unavailable"
    assert "synthetic-private" not in response.text and "c_audit_events" not in response.text
    with s.db.transaction() as conn:
        assert (
            conn.execute("SELECT name FROM rooms WHERE id=%s", (BIG_ROOM,)).fetchone()["name"]
            == current["name"]
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_audit_events WHERE action='resources.room.update'"
            ).fetchone()["n"]
            == 0
        )
        event = conn.execute(
            "SELECT * FROM c_audit_events WHERE result='resources.audit_unavailable'"
        ).fetchone()
        assert event["request_id"] == response.headers["X-Request-ID"]


def test_scope_and_disable_changes_apply_to_existing_resource_session(integrated):
    s = integrated
    reader = s.headers("reader")
    component = s.component
    component.auth.access_policy = lambda actor, *_: (
        actor.all_rooms
    )  # Explicit synthetic test policy.
    manager = component.auth.authenticate(s.headers()["Authorization"].split()[1])
    component.auth.change_access(
        manager,
        s.ids["reader"],
        role_names=["synthetic-reader"],
        room_ids=frozenset({"2"}),
        all_rooms=False,
        enabled=True,
        request_id="synthetic-scope-change",
    )
    assert s.client.get(f"/api/v1/resources/rooms/{BIG_ROOM}", headers=reader).status_code == 404
    assert s.client.get("/api/v1/resources/rooms/2", headers=reader).status_code == 200
    component.auth.change_access(
        manager,
        s.ids["reader"],
        role_names=["synthetic-reader"],
        room_ids=frozenset({"2"}),
        all_rooms=False,
        enabled=False,
        request_id="synthetic-disable",
    )
    assert s.client.get("/api/v1/resources/rooms/2", headers=reader).status_code == 401


def test_competing_edits_only_commit_one_success_audit(integrated):
    s = integrated
    headers = s.headers()
    path = f"/api/v1/resources/rooms/{BIG_ROOM}"
    revision = s.client.get(path, headers=headers).json()["revision"]

    def update(name):
        return s.client.patch(
            path, headers=headers, json={"name": name, "expected_revision": revision}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["竞争一", "竞争二"]))
    assert sorted(r.status_code for r in results) == [200, 409]
    with s.db.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_audit_events WHERE action='resources.room.update'"
            ).fetchone()["n"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_audit_events WHERE result='resources.stale_revision'"
            ).fetchone()["n"]
            == 1
        )


def test_missing_creation_policy_and_duplicate_mount_fail_closed(integrated, tmp_path, monkeypatch):
    s = integrated
    with pytest.raises(ValueError, match="already installed"):
        install_resource_management(
            s.app, auth=s.component.auth, audit=s.component.audit, configuration=configuration()
        )
    with pytest.raises(ValueError, match="matching C request context"):
        install_resource_management(
            FastAPI(), auth=s.component.auth, audit=s.component.audit, configuration=configuration()
        )
    application, _ = hosted(s.db, tmp_path, monkeypatch)
    component = application.state.c_runtime
    install_resource_management(
        application,
        auth=component.auth,
        audit=component.audit,
        configuration=configuration(create=False),
    )
    headers = s.headers()
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/resources/rooms",
            headers=headers,
            json={"code": "MISSING", "name": "拒绝创建", "location": "测试"},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "creation_unconfigured"
    with s.db.transaction() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM rooms WHERE code='MISSING'").fetchone()["n"]
            == 0
        )


def test_failed_denial_audit_is_reported_without_private_exception(integrated, monkeypatch, caplog):
    s = integrated
    headers = s.headers("ordinary")

    def unavailable(**_):
        raise psycopg.OperationalError("synthetic-private-database-detail")

    monkeypatch.setattr(s.component.audit, "failure", unavailable)
    response = s.client.get("/api/v1/resources/rooms", headers=headers)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "audit_unavailable"
    assert "synthetic-private" not in response.text and "synthetic-private" not in caplog.text


def test_real_tcp_login_resource_write_audit_and_logout(integrated, tmp_path):
    s = integrated
    with socket.socket() as socket_probe:
        socket_probe.bind(("127.0.0.1", 0))
        port = socket_probe.getsockname()[1]
    log_path = tmp_path / "resource-server.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "resource_acceptance_app:build",
                "--factory",
                "--app-dir",
                "tests/c_module",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=Path(__file__).resolve().parents[2],
            env=os.environ
            | {
                "CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE": "1",
                "C24_TEST_DB_URI": s.db.dsn,
                "CAMPUS_C_ENABLED": "false",
            },
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
            ) as client:
                deadline = wall_time.monotonic() + 15
                while wall_time.monotonic() < deadline:
                    if process.poll() is not None:
                        pytest.fail("Isolated C/B HTTP service exited before readiness")
                    try:
                        if client.get("/health/ready").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    wall_time.sleep(0.05)
                else:
                    pytest.fail("Isolated C/B HTTP service did not become ready")
                login = client.post(
                    "/api/v1/auth/sessions",
                    json={"username": "manager", "password": "synthetic-resource-password"},
                )
                assert login.status_code == 200
                headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                created = client.post(
                    "/api/v1/resources/rooms",
                    headers=headers,
                    json={"code": "TCP", "name": "网络合成教室", "location": "测试"},
                )
                assert created.status_code == 201
                assert (
                    client.get(
                        "/api/v1/resources/rooms/" + created.json()["id"], headers=headers
                    ).json()["name"]
                    == "网络合成教室"
                )
                events = client.get("/api/v1/audit/events", headers=headers).json()
                assert any(
                    e["request_id"] == created.headers["X-Request-ID"]
                    and e["action"] == "resources.room.create"
                    for e in events
                )
                assert (
                    client.delete("/api/v1/auth/sessions/current", headers=headers).status_code
                    == 204
                )
                assert client.get("/api/v1/resources/rooms", headers=headers).status_code == 401
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_two_process_approved_qualification_uses_real_b_http_without_student_admin_grant(
    integrated,
    tmp_path,
):
    s = integrated
    for username, permissions, global_scope in (
        ("policy-service", frozenset({PERMISSIONS.read}), True),
        ("policy-applicant", frozenset({"m2.submit"}), False),
    ):
        s.component.auth.provision_user(
            username=username,
            password="synthetic-policy-password",
            department_id="synthetic",
            roles={"synthetic-" + username: permissions},
            room_ids=frozenset(),
            all_rooms=global_scope,
        )
    service_token = s.component.auth.login(
        "policy-service",
        "synthetic-policy-password",
        client_key="policy-service-fixture",
        request_id="policy-service-fixture",
    )["access_token"]
    # Test-only B data in the fixture's private schema; B implementation remains pinned.
    with s.engine.begin() as conn:
        conn.execute(
            update(rooms)
            .where(rooms.c.id == 2)
            .values(access_scope="department", department_id="other-department")
        )
        for identifier, scope, department, enabled in (
            (3, "department", "synthetic", True),
            (4, "campus", None, False),
        ):
            conn.execute(
                insert(rooms).values(
                    id=identifier,
                    code="POLICY-" + str(identifier),
                    name="合成资格教室",
                    location="测试",
                    access_scope=scope,
                    department_id=department,
                    open_time=time(8),
                    close_time=time(22),
                    enabled=enabled,
                )
            )

    @contextmanager
    def server(name, extra_env):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with (tmp_path / (name + ".log")).open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "resource_acceptance_app:build",
                    "--factory",
                    "--app-dir",
                    "tests/c_module",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=Path(__file__).resolve().parents[2],
                env=os.environ
                | {
                    "CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE": "1",
                    "CAMPUS_C_ENABLED": "false",
                    "C24_TEST_DB_URI": s.db.dsn,
                }
                | extra_env,
                stdout=log,
                stderr=log,
            )
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
                ) as client:
                    deadline = wall_time.monotonic() + 15
                    while wall_time.monotonic() < deadline:
                        if process.poll() is not None:
                            pytest.fail("Isolated policy HTTP service exited")
                        try:
                            if client.get("/health/ready").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        wall_time.sleep(0.05)
                    else:
                        pytest.fail("Isolated policy HTTP service did not become ready")
                    yield client, port
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    with server("b-resources", {}) as (resources, port):
        policy = json.loads(EXAMPLE.read_text())
        policy["submission"]["room_access_policy"] = "campus_or_own_department"
        policy["resources"]["base_url"] = f"http://127.0.0.1:{port}"
        policy_path = tmp_path / "approved-policy.json"
        policy_path.write_text(json.dumps(policy))
        with server(
            "c-approval",
            {
                "C24_TEST_C_ONLY": "1",
                "C24_TEST_POLICY_FILE": str(policy_path),
                "C24_TEST_RESOURCE_TOKEN": service_token,
            },
        ) as (approval, _):
            session = approval.post(
                "/api/v1/auth/sessions",
                json={"username": "policy-applicant", "password": "synthetic-policy-password"},
            )
            assert session.status_code == 200
            headers = {"Authorization": "Bearer " + session.json()["access_token"]}
            assert resources.get("/api/v1/resources/rooms", headers=headers).status_code == 403
            source = resources.get(
                f"/api/v1/resources/rooms/{BIG_ROOM}",
                headers={"Authorization": "Bearer " + service_token},
            )
            assert source.status_code == 200 and source.json()["department_id"] is None
            from datetime import UTC, datetime, timedelta

            start = datetime.now(UTC) + timedelta(hours=2)
            payload = {
                "room_id": str(BIG_ROOM),
                "starts_at": start.isoformat(),
                "ends_at": (start + timedelta(hours=1)).isoformat(),
                "purpose": "合成已批准政策",
            }
            first = approval.post(
                "/api/v1/m2/applications",
                headers=headers | {"Idempotency-Key": "campus-policy"},
                json=payload,
            )
            assert first.status_code == 201 and first.json()["effective"] is False
            own = approval.post(
                "/api/v1/m2/applications",
                headers=headers | {"Idempotency-Key": "own-department-policy"},
                json=payload | {"room_id": "3"},
            )
            assert own.status_code == 201 and own.json()["id"] != first.json()["id"]
            for identifier, expected in (("2", 403), ("4", 409), ("999", 404)):
                response = approval.post(
                    "/api/v1/m2/applications",
                    headers=headers | {"Idempotency-Key": "denied-" + identifier},
                    json=payload | {"room_id": identifier},
                )
                assert response.status_code == expected
            with s.engine.begin() as conn:
                conn.execute(update(rooms).where(rooms.c.id == BIG_ROOM).values(enabled=False))
            replay = approval.post(
                "/api/v1/m2/applications",
                headers=headers | {"Idempotency-Key": "campus-policy"},
                json=payload,
            )
            assert replay.status_code == 201 and replay.json()["id"] == first.json()["id"]
            assert (
                approval.post(
                    "/api/v1/m2/applications",
                    headers=headers | {"Idempotency-Key": "after-disable"},
                    json=payload,
                ).status_code
                == 409
            )
            principal = s.component.auth.authenticate(service_token)
            s.component.auth.logout(service_token, principal, "synthetic-service-logout")
            unavailable = approval.post(
                "/api/v1/m2/applications",
                headers=headers | {"Idempotency-Key": "unavailable-resource-service"},
                json=payload | {"room_id": "3"},
            )
            assert unavailable.status_code == 503
            assert unavailable.json()["error"]["code"] == "RESOURCE_UNAVAILABLE"
    with s.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_applications").fetchone()["n"] == 2
        assert conn.execute("SELECT count(*) AS n FROM c_m1_operations").fetchone()["n"] == 0
