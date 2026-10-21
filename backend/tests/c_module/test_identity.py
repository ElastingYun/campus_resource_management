from dataclasses import replace
from datetime import timedelta

import pytest
from app.common.auth.domain import ServiceError
from app.common.auth.service import AuthSettings, digest
from app.modules.m2_approval.migrate import migrate
from fastapi.testclient import TestClient


def login(client, username="student"):
    response = client.post(
        "/api/v1/auth/sessions",
        json={"username": username, "password": "synthetic-password-123"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_login_live_permissions_logout_and_no_secret_storage(case):
    with TestClient(case.app) as client:
        token = login(client)
        headers = {"Authorization": "Bearer " + token}
        response = client.get("/api/v1/auth/me", headers=headers)
        assert response.json()["subject_id"] == str(case.ids["student"])
        assert response.json()["permissions"] == ["m2.submit"]
        assert response.headers["cache-control"] == "no-store"
        with case.db.transaction() as conn:
            row = conn.execute("SELECT token_hash FROM c_sessions").fetchone()
            assert row["token_hash"] == digest(token) and row["token_hash"] != token
            conn.execute("UPDATE c_roles SET permissions='{}' WHERE name='applicant'")
        assert (
            client.get("/api/v1/auth/me", headers=headers).json()["permissions"] == []
        )
        assert (
            client.delete("/api/v1/auth/sessions/current", headers=headers).status_code
            == 204
        )
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
        with case.db.transaction() as conn:
            events = str(conn.execute("SELECT * FROM c_audit_events").fetchall())
            assert token not in events and "synthetic-password-123" not in events


@pytest.mark.parametrize("disabled", [True, False])
def test_disabled_and_expired_sessions_are_denied(case, disabled):
    token = case.auth.login(
        "student", "synthetic-password-123", client_key="test", request_id="login"
    )["access_token"]
    if disabled:
        with case.db.transaction() as conn:
            conn.execute(
                "UPDATE c_users SET enabled=false WHERE id=%s", (case.ids["student"],)
            )
    else:
        case.clock.now += timedelta(hours=1)
    with pytest.raises(ServiceError) as error:
        case.auth.authenticate(token)
    assert error.value.status == 401


def test_failed_login_limits_are_durable_and_reset(case):
    case.auth.settings = AuthSettings(timedelta(hours=1), timedelta(minutes=5), 3)
    for _ in range(3):
        with pytest.raises(ServiceError) as error:
            case.auth.login(
                "student", "wrong", client_key="client", request_id="failed"
            )
        assert error.value.code == "INVALID_CREDENTIALS"
    with pytest.raises(ServiceError) as error:
        case.auth.login(
            "student",
            "synthetic-password-123",
            client_key="client",
            request_id="limited",
        )
    assert error.value.status == 429
    with case.db.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_audit_events WHERE action='auth.login'"
            ).fetchone()["n"]
            == 4
        )
    case.clock.now += timedelta(minutes=5)
    assert case.auth.login(
        "student", "synthetic-password-123", client_key="client", request_id="retry"
    )["access_token"]


def test_validation_does_not_echo_password(case):
    secret = "secret-not-to-echo" * 100
    with TestClient(case.app) as client:
        response = client.post(
            "/api/v1/auth/sessions", json={"username": "student", "password": secret}
        )
        assert response.status_code == 422
        assert secret not in response.text and '"input"' not in response.text
        assert client.get("/api/v1/auth/me").status_code == 401


def test_migrations_replay_and_reject_modified_history(database):
    migrate(database)
    with database.transaction() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM c_schema_migrations").fetchone()[
                "n"
            ]
            == 1
        )
        conn.execute("UPDATE c_schema_migrations SET checksum=%s", ("0" * 64,))
    with pytest.raises(RuntimeError, match="checksum"):
        migrate(database)


def test_bootstrap_role_conflict_rolls_back(case):
    with pytest.raises(ValueError, match="different permissions"):
        case.auth.provision_user(
            username="new",
            password="synthetic-password-123",
            department_id="D1",
            roles={"applicant": frozenset({"auth.manage"})},
            room_ids=frozenset(),
        )
    with case.db.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_users WHERE username='new'"
            ).fetchone()["n"]
            == 0
        )
        assert conn.execute(
            "SELECT permissions FROM c_roles WHERE name='applicant'"
        ).fetchone()["permissions"] == ["m2.submit"]


def test_bootstrap_is_idempotent_and_never_overwrites_existing_access(case):
    again = case.auth.provision_user(
        username="student",
        password="synthetic-password-123",
        department_id="D1",
        roles={"applicant": frozenset({"m2.submit"})},
        room_ids=frozenset(),
    )
    assert again == case.ids["student"]
    with pytest.raises(ValueError, match="different configuration"):
        case.auth.provision_user(
            username="student",
            password="changed-password",
            department_id="D1",
            roles={"applicant": frozenset({"m2.submit"})},
            room_ids=frozenset(),
        )
    with case.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_users").fetchone()["n"] == 4
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_audit_events WHERE action='auth.provision'"
            ).fetchone()["n"]
            == 4
        )


def test_scoped_audit_read_and_denial(case):
    from conftest import submit

    application = submit(case)
    rows = case.audit.list_events(case.principals["first"], limit=100, offset=0)
    assert len(rows) == 1 and rows[0]["target"] == application["id"]
    assert (
        case.audit.list_events(case.principals["outsider"], limit=100, offset=0) == []
    )
    with pytest.raises(ServiceError) as error:
        case.audit.list_events(case.principals["student"], limit=100, offset=0)
    assert error.value.status == 403


def test_account_management_requires_explicit_policy_and_blocks_delegation(case):
    manager = replace(
        case.principals["first"], permissions=frozenset({"auth.manage", "m2.submit"})
    )
    change = {
        "role_names": ["applicant"],
        "room_ids": [],
        "all_rooms": False,
        "enabled": False,
        "request_id": "manage",
    }
    with pytest.raises(ServiceError) as error:
        case.auth.change_access(manager, case.ids["student"], **change)
    assert error.value.code == "ACCESS_MANAGEMENT_DISABLED"
    case.auth.access_policy = lambda *_: False
    with pytest.raises(ServiceError) as error:
        case.auth.change_access(manager, case.ids["student"], **change)
    assert error.value.code == "ACCOUNT_OUT_OF_SCOPE"
    case.auth.access_policy = lambda *_: True
    with pytest.raises(ServiceError) as error:
        case.auth.change_access(
            manager, case.ids["student"], **{**change, "role_names": ["first"]}
        )
    assert error.value.code == "DELEGATION_FORBIDDEN"


def test_account_disable_revokes_existing_sessions_and_is_idempotent(case):
    manager = replace(
        case.principals["first"], permissions=frozenset({"auth.manage", "m2.submit"})
    )
    token = case.auth.login(
        "student", "synthetic-password-123", client_key="client", request_id="login"
    )["access_token"]
    case.auth.access_policy = lambda *_: True  # Explicit test-only grant.
    change = {
        "role_names": ["applicant"],
        "room_ids": [],
        "all_rooms": False,
        "enabled": False,
        "request_id": "manage",
    }
    case.auth.change_access(manager, case.ids["student"], **change)
    case.auth.change_access(manager, case.ids["student"], **change)
    with pytest.raises(ServiceError):
        case.auth.authenticate(token)
    case.auth.change_access(manager, case.ids["student"], **{**change, "enabled": True})
    with pytest.raises(ServiceError):
        case.auth.authenticate(token)
    with case.db.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_audit_events WHERE action='auth.access_changed'"
            ).fetchone()["n"]
            == 2
        )


def test_access_management_http_api_obeys_host_scope_policy(case):
    operator_id = case.auth.provision_user(
        username="operator",
        password="synthetic-password-123",
        department_id="D1",
        roles={"operator": frozenset({"auth.manage", "m2.submit"})},
        room_ids=frozenset({"R1"}),
    )

    case.auth.access_policy = lambda actor, target, desired: (
        actor.subject_id == operator_id
        and target["department_id"] == "D1"
        and set(desired["room_ids"]).issubset(actor.room_ids)
        and not desired["all_rooms"]
    )
    with TestClient(case.app) as client:
        token = login(client, "operator")
        headers = {"Authorization": "Bearer " + token}
        body = {
            "role_names": ["applicant"],
            "room_ids": ["R1"],
            "all_rooms": False,
            "enabled": True,
        }
        path = f"/api/v1/auth/users/{case.ids['student']}/access"
        assert client.put(path, headers=headers, json=body).status_code == 200
        assert (
            client.put(
                path, headers=headers, json={**body, "room_ids": ["R2"]}
            ).status_code
            == 403
        )
        assert (
            client.put(
                path, headers=headers, json={**body, "enabled": "false"}
            ).status_code
            == 422
        )
        assert (
            client.put(
                path, headers=headers, json={**body, "role_names": ["missing"]}
            ).status_code
            == 422
        )
        with case.db.transaction() as conn:
            assert conn.execute(
                "SELECT room_ids FROM c_users WHERE id=%s", (case.ids["student"],)
            ).fetchone()["room_ids"] == ["R1"]


def test_exhausted_client_does_not_allocate_arbitrary_account_buckets(case):
    case.auth.settings = AuthSettings(timedelta(hours=1), timedelta(minutes=5), 1)
    with pytest.raises(ServiceError):
        case.auth.login(
            "unknown-user-1", "wrong", client_key="client", request_id="first"
        )
    with pytest.raises(ServiceError) as error:
        case.auth.login(
            "unknown-user-2", "wrong", client_key="client", request_id="second"
        )
    assert error.value.code == "LOGIN_RATE_LIMIT"
    with case.db.transaction() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM c_login_buckets").fetchone()["n"]
            == 2
        )
