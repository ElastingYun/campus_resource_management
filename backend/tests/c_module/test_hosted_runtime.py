import json
import time
from datetime import timedelta
from pathlib import Path

import httpx
import psycopg
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from alembic import command
from app.config import Settings
from app.main import create_app
from app.modules.m2_approval.domain import Room
from app.modules.m2_approval.migrate import migrate

from .conftest import submit
from .test_approval import decide
from .test_identity import login
from .test_runtime_settings import EXAMPLE


def scoped_engine(database):
    # Real PostgreSQL engine, isolated to this test's random schema, not mocked SQL.
    return create_engine(
        "postgresql+psycopg://",
        creator=lambda: psycopg.connect(database.dsn),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
        pool_timeout=1,
    )


def alembic_config():
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return config


def hosted(database, tmp_path, monkeypatch, *, with_m1=False, room_policy="legacy"):
    policy = json.loads(EXAMPLE.read_text())
    policy["scan_interval_seconds"] = 0.05
    policy["submission"]["room_access_policy"] = room_policy
    if with_m1:
        policy["m1"] = {
            "base_url": "http://m1.contract.test",
            "token_env": "CAMPUS_M1_SERVICE_TOKEN",
            "timeout_seconds": 0.1,
            "apply_path": "/apply",
            "release_path": "/release",
            "query_path": "/operations/{operation_id}",
            "lease_seconds": 1.0,
            "retry_delay_seconds": 0.05,
            "max_attempts": 3,
        }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    monkeypatch.setenv("CAMPUS_RESOURCES_SERVICE_TOKEN", "synthetic-resource-token")
    monkeypatch.setenv("CAMPUS_M1_SERVICE_TOKEN", "synthetic-m1-token")
    engine = scoped_engine(database)
    monkeypatch.setattr("app.main.build_engine", lambda _: engine)
    application = create_app(
        Settings(
            _env_file=None,
            db_host="unused.test",
            db_password="synthetic",
            c_enabled=True,
            c_config_file=path,
        )
    )
    return application, engine


def test_shared_pool_preserves_sqlalchemy_rows_and_restarts_lifecycle(case, tmp_path, monkeypatch):
    application, engine = hosted(case.db, tmp_path, monkeypatch)
    assert engine.pool.checkedout() == 0
    for _ in range(2):
        with TestClient(application) as client:
            assert client.get("/health/ready").json() == {
                "status": "ready",
                "database": "connected",
                "scope": "m2",
            }
            token = login(client)
            assert client.get(
                "/api/v1/auth/me", headers={"Authorization": "Bearer " + token}
            ).json()["subject_id"] == str(case.ids["student"])
            with engine.connect() as conn:
                assert conn.execute(text("SELECT count(*) FROM c_users")).scalar_one() == 4
            assert client.get("/health/ready").status_code == 200
            assert client.get("/api/v1/m1/settings").status_code == 401
        assert engine.pool.checkedout() == 0
        assert application.state.c_runtime.resources.client.is_closed


def test_missing_business_schema_is_not_ready_but_process_is_live(
    empty_database, tmp_path, monkeypatch
):
    application, engine = hosted(empty_database, tmp_path, monkeypatch)
    with TestClient(application) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        response = client.post(
            "/api/v1/auth/sessions", json={"username": "missing", "password": "synthetic"}
        )
        assert response.status_code == 503
        assert "unused.test" not in response.text and "c_users" not in response.text
    assert engine.pool.checkedout() == 0


def test_background_deadline_does_not_need_a_business_request(case, tmp_path, monkeypatch):
    application, _ = hosted(case.db, tmp_path, monkeypatch)
    component = application.state.c_runtime
    component.approval.clock = case.clock
    monkeypatch.setattr(
        component.resources, "get_room", lambda identifier: Room(identifier, "D1", True)
    )
    with TestClient(application) as client:
        token = login(client)
        response = client.post(
            "/api/v1/m2/applications",
            headers={"Authorization": "Bearer " + token, "Idempotency-Key": "host-submit"},
            json={
                "room_id": "R1",
                "starts_at": (case.clock() + timedelta(hours=2)).isoformat(),
                "ends_at": (case.clock() + timedelta(hours=3)).isoformat(),
                "purpose": "合成申请",
            },
        )
        assert response.status_code == 201
        case.clock.now += timedelta(minutes=10)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            stored = case.approval.get(case.principals["student"], response.json()["id"])
            if stored["review_status"] == "TIMED_OUT":
                break
            time.sleep(0.02)
        assert stored["review_status"] == "TIMED_OUT"
        assert client.get("/health/ready").status_code == 200


def test_background_delivery_uses_persisted_work(case, tmp_path, monkeypatch):
    application, _ = hosted(case.db, tmp_path, monkeypatch, with_m1=True)
    component = application.state.c_runtime
    component.worker.clock = case.clock
    component.approval.clock = case.clock
    component.gateway.client.close()
    calls = []

    def reply(request):
        body = json.loads(request.content)
        calls.append(body["operation_id"])
        return httpx.Response(200, json={"operation_id": body["operation_id"], "result": "APPLIED"})

    component.gateway.client = httpx.Client(
        base_url="http://m1.contract.test", transport=httpx.MockTransport(reply)
    )
    approved = decide(case, decide(case, submit(case)), reviewer="second", key="second")
    with TestClient(application):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            stored = case.approval.get(case.principals["student"], approved["id"])
            if stored["effective"]:
                break
            time.sleep(0.02)
        assert stored["effective"] and len(calls) == 1


@pytest.mark.parametrize("legacy", [False, True])
def test_alembic_empty_or_legacy_baseline_replays_without_losing_data(empty_database, legacy):
    if legacy:
        migrate(empty_database)
        with empty_database.transaction() as conn:
            conn.execute("INSERT INTO c_roles (name,permissions) VALUES ('preserve-me', '{}')")
    engine = scoped_engine(empty_database)
    try:
        config = alembic_config()
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "0002_c_identity_approval")
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "0002_c_identity_approval")
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0002_c_identity_approval"
            )
            assert conn.execute(text("SELECT count(*) FROM c_schema_migrations")).scalar_one() == 1
            assert conn.execute(
                text("SELECT count(*) FROM c_roles WHERE name='preserve-me'")
            ).scalar_one() == int(legacy)
    finally:
        engine.dispose()


def test_alembic_rejects_inconsistent_legacy_schema(database):
    with database.transaction() as conn:
        conn.execute("DROP TABLE c_receipts")
    engine = scoped_engine(database)
    try:
        with pytest.raises(RuntimeError, match="actual schema"):
            with engine.begin() as conn:
                config = alembic_config()
                config.attributes["connection"] = conn
                command.upgrade(config, "0002_c_identity_approval")
    finally:
        engine.dispose()


def test_alembic_rejects_legacy_checksum_without_overwriting_users(case):
    with case.db.transaction() as conn:
        conn.execute("UPDATE c_schema_migrations SET checksum=%s", ("0" * 64,))
    engine = scoped_engine(case.db)
    try:
        with pytest.raises(RuntimeError, match="checksum"):
            with engine.begin() as conn:
                config = alembic_config()
                config.attributes["connection"] = conn
                command.upgrade(config, "0002_c_identity_approval")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM c_users")).scalar_one() == 4
            assert (
                conn.execute(text("SELECT checksum FROM c_schema_migrations")).scalar_one()
                == "0" * 64
            )
            assert conn.execute(text("SELECT to_regclass('alembic_version')")).scalar_one() is None
    finally:
        engine.dispose()
