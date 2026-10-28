import pytest
from fastapi.testclient import TestClient

from app.modules.m2_approval.demo import create_demo_app


def test_demo_requires_explicit_mode_and_credentials(monkeypatch):
    monkeypatch.delenv("C_DEMO_MODE", raising=False)
    with pytest.raises(RuntimeError, match="explicitly"):
        create_demo_app()
    monkeypatch.setenv("C_DEMO_MODE", "1")
    monkeypatch.delenv("C_DEMO_DATABASE_URL", raising=False)
    monkeypatch.delenv("C_DEMO_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="dedicated demo database"):
        create_demo_app()


def test_demo_factory_seeds_repeatably_and_serves_identity(database, monkeypatch):
    monkeypatch.setenv("C_DEMO_MODE", "1")
    monkeypatch.setenv("C_DEMO_DATABASE_URL", database.dsn)
    monkeypatch.setenv("C_DEMO_PASSWORD", "synthetic-demo-password")
    app = create_demo_app()
    create_demo_app()  # Same schema and account configuration: no duplicate seed rows.
    with TestClient(app) as client:
        assert client.get("/health").json() == {
            "status": "ok",
            "mode": "synthetic-demo",
            "m1_connected": False,
        }
        response = client.post(
            "/api/v1/auth/sessions",
            json={"username": "demo-student", "password": "synthetic-demo-password"},
        )
        assert response.status_code == 200
        token = response.json()["access_token"]
        assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token}).json()[
            "permissions"
        ] == ["m2.submit"]
    with database.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_users").fetchone()["n"] == 3
