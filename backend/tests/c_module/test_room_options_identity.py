"""C's actual Bearer mapping to the separately authorized B room catalog."""

import os
import socket
import subprocess
import sys
import time as wall_time
from datetime import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import insert, update

from .test_resource_integration import BIG_ROOM, metadata, rooms
from .test_resource_integration import integrated as integrated

pytestmark = pytest.mark.parametrize("integrated", [True], indirect=True)
PATH = "/api/v1/resources/room-options"


@pytest.fixture
def catalog(integrated):
    s = integrated
    user_id = s.component.auth.provision_user(
        username="applicant",
        password="synthetic-catalog-password",
        department_id="synthetic",
        roles={"synthetic-applicant": frozenset({"m2.submit"})},
        room_ids=frozenset(),
        all_rooms=False,
    )
    with s.engine.begin() as conn:
        conn.execute(
            update(rooms)
            .where(rooms.c.id == 2)
            .values(access_scope="department", department_id="other-department")
        )
        for identifier, code, scope, department, enabled in (
            (3, "OWN", "department", "synthetic", True),
            (4, "DISABLED", "campus", None, False),
        ):
            conn.execute(
                insert(rooms).values(
                    id=identifier,
                    code=code,
                    name="合成目录教室",
                    location="测试",
                    access_scope=scope,
                    department_id=department,
                    open_time=time(8),
                    close_time=time(22),
                    enabled=enabled,
                )
            )
    response = s.client.post(
        "/api/v1/auth/sessions",
        json={"username": "applicant", "password": "synthetic-catalog-password"},
    )
    assert response.status_code == 200
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    return SimpleNamespace(s=s, headers=headers, user_id=user_id)


def test_actual_applicant_filters_before_count_and_page_without_management_grant(catalog):
    s, headers = catalog.s, catalog.headers
    first = s.client.get(PATH, headers=headers, params={"limit": 1, "offset": 0})
    assert first.status_code == 200
    assert first.json() == {
        "items": [{"id": "3", "code": "OWN", "name": "合成目录教室", "location": "测试"}],
        "total": 2,
        "limit": 1,
        "offset": 0,
    }
    second = s.client.get(PATH, headers=headers, params={"limit": 1, "offset": 1})
    assert [row["id"] for row in second.json()["items"]] == [str(BIG_ROOM)]
    assert second.json()["total"] == 2
    beyond = s.client.get(PATH, headers=headers, params={"offset": 2})
    assert beyond.json() == {"items": [], "total": 2, "limit": 20, "offset": 2}
    assert s.client.get("/api/v1/resources/rooms", headers=headers).status_code == 403
    assert s.client.get(f"/api/v1/resources/rooms/{BIG_ROOM}", headers=headers).status_code == 403
    assert first.headers["Cache-Control"] == "no-store"
    assert first.headers["X-Request-ID"]


@pytest.mark.parametrize("identity", ["manager", "reader", "ordinary"])
def test_management_permissions_and_global_scope_never_grant_selection(catalog, identity):
    response = catalog.s.client.get(PATH, headers=catalog.s.headers(identity))
    assert response.status_code == 403 and response.json()["detail"]["code"] == "forbidden"


def test_browser_identity_and_department_cannot_override_trusted_principal(catalog):
    s = catalog.s
    fake = {
        "X-Dev-User-Id": str(s.ids["manager"]),
        "X-Dev-Department": "other-department",
        "X-Dev-Permissions": "m2.submit",
        "X-Request-ID": "00000000-0000-4000-8000-000000000099",
    }
    assert s.client.get(PATH, headers=fake).status_code == 401
    denied = s.client.get(PATH, headers=s.headers("ordinary") | fake)
    assert denied.status_code == 403
    visible = s.client.get(
        PATH,
        headers=catalog.headers | fake,
        params={"department_id": "other-department", "role": "admin"},
    )
    assert visible.status_code == 200
    assert {row["id"] for row in visible.json()["items"]} == {"3", str(BIG_ROOM)}
    assert visible.headers["X-Request-ID"] != fake["X-Request-ID"]
    with s.db.transaction() as conn:
        event = conn.execute(
            "SELECT * FROM c_audit_events WHERE request_id=%s",
            (denied.headers["X-Request-ID"],),
        ).fetchone()
        assert event["result"] == "resources.forbidden"
        assert event["actor_id"] == s.ids["ordinary"]


def test_existing_session_rechecks_revoked_choice_permission(catalog):
    s = catalog.s
    assert s.client.get(PATH, headers=catalog.headers).status_code == 200
    s.component.auth.access_policy = lambda actor, *_: actor.all_rooms
    manager = s.component.auth.authenticate(s.headers()["Authorization"].split()[1])
    s.component.auth.change_access(
        manager,
        catalog.user_id,
        role_names=[],
        room_ids=[],
        all_rooms=False,
        enabled=True,
        request_id="synthetic-revoke-selection",
    )
    assert s.client.get(PATH, headers=catalog.headers).status_code == 403
    assert s.client.get("/api/v1/auth/me", headers=catalog.headers).status_code == 200


@pytest.mark.parametrize("termination", ["disable", "logout", "expire"])
def test_terminated_session_cannot_query_catalog(catalog, termination):
    s = catalog.s
    assert s.client.get(PATH, headers=catalog.headers).status_code == 200
    if termination == "disable":
        s.component.auth.access_policy = lambda actor, *_: actor.all_rooms
        manager = s.component.auth.authenticate(s.headers()["Authorization"].split()[1])
        s.component.auth.change_access(
            manager,
            catalog.user_id,
            role_names=[],
            room_ids=[],
            all_rooms=False,
            enabled=False,
            request_id="synthetic-disable-applicant",
        )
    elif termination == "logout":
        assert (
            s.client.delete("/api/v1/auth/sessions/current", headers=catalog.headers).status_code
            == 204
        )
    else:
        # Test-only credential expiry in this fixture's private C schema.
        with s.db.transaction() as conn:
            conn.execute(
                "UPDATE c_sessions SET expires_at='2000-01-01T00:00:00Z' WHERE user_id=%s",
                (catalog.user_id,),
            )
    assert s.client.get(PATH, headers=catalog.headers).status_code == 401


def test_each_read_uses_current_trusted_department_and_resource_eligibility(catalog):
    s = catalog.s
    assert {r["id"] for r in s.client.get(PATH, headers=catalog.headers).json()["items"]} == {
        "3",
        str(BIG_ROOM),
    }
    # Trusted administrative update fixture, not a new department-management API.
    with s.db.transaction() as conn:
        conn.execute(
            "UPDATE c_users SET department_id='other-department' WHERE id=%s", (catalog.user_id,)
        )
    assert {r["id"] for r in s.client.get(PATH, headers=catalog.headers).json()["items"]} == {
        "2",
        str(BIG_ROOM),
    }
    with s.engine.begin() as conn:
        conn.execute(update(rooms).where(rooms.c.id == BIG_ROOM).values(enabled=False))
    response = s.client.get(PATH, headers=catalog.headers)
    assert [r["id"] for r in response.json()["items"]] == ["2"]
    assert response.json()["total"] == 1


@pytest.mark.parametrize("department", ["", " synthetic", "synthetic "])
def test_invalid_trusted_department_fails_safely_without_inferring_campus_only(catalog, department):
    s = catalog.s
    with s.db.transaction() as conn:
        conn.execute(
            "UPDATE c_users SET department_id=%s WHERE id=%s", (department, catalog.user_id)
        )
    response = s.client.get(PATH, headers=catalog.headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RESOURCE_IDENTITY_UNAVAILABLE"
    assert response.json()["error"]["message"] == "暂时无法确认教室目录身份"


def test_catalog_database_failure_is_safe_and_independently_audited(catalog):
    s = catalog.s
    metadata.drop_all(s.engine)  # Only B tables in this test-owned random schema.
    response = s.client.get(PATH, headers=catalog.headers)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "resource_unavailable"
    assert "SELECT" not in response.text and "Traceback" not in response.text
    with s.db.transaction() as conn:
        event = conn.execute(
            "SELECT * FROM c_audit_events WHERE request_id=%s",
            (response.headers["X-Request-ID"],),
        ).fetchone()
        assert event["result"] == "resources.resource_unavailable"
        assert event["actor_id"] == catalog.user_id


@pytest.mark.parametrize("query,expected", [("OWN", ["3"]), ("%", []), ("unmatched", [])])
def test_trusted_catalog_search_has_minimal_projection_and_no_business_writes(
    catalog, query, expected
):
    s = catalog.s
    with s.db.transaction() as conn:
        before = conn.execute("SELECT count(*) AS n FROM c_audit_events").fetchone()["n"]
    response = s.client.get(PATH, headers=catalog.headers, params={"q": query})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["items"]] == expected
    for row in response.json()["items"]:
        assert set(row) == {"id", "code", "name", "location"}
    with s.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_audit_events").fetchone()["n"] == before
        assert conn.execute("SELECT count(*) AS n FROM c_applications").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM c_m1_operations").fetchone()["n"] == 0


def test_real_tcp_login_catalog_and_revoked_identity(catalog, tmp_path):
    s = catalog.s
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with (tmp_path / "catalog-service.log").open("w") as log:
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
                "C24_TEST_ROOM_OPTIONS": "1",
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
                        pytest.fail("Isolated directory service exited before readiness")
                    try:
                        if client.get("/health/ready").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    wall_time.sleep(0.05)
                else:
                    pytest.fail("Isolated directory service did not become ready")
                login = client.post(
                    "/api/v1/auth/sessions",
                    json={"username": "applicant", "password": "synthetic-catalog-password"},
                )
                assert login.status_code == 200
                headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                response = client.get(PATH, headers=headers, params={"limit": 1})
                assert response.status_code == 200 and response.json()["total"] == 2
                assert response.json()["items"][0]["id"] == "3"
                assert client.get("/api/v1/resources/rooms", headers=headers).status_code == 403
                assert (
                    client.delete("/api/v1/auth/sessions/current", headers=headers).status_code
                    == 204
                )
                assert client.get(PATH, headers=headers).status_code == 401
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
