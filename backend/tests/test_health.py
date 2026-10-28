from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_live_and_missing_database_configuration(monkeypatch):
    for key in ("HOST", "PORT", "NAME", "USER", "PASSWORD"):
        monkeypatch.delenv(f"CAMPUS_DB_{key}", raising=False)
    application = create_app(Settings(_env_file=None))
    with TestClient(application) as client:
        assert client.get("/health/live").json() == {"status": "alive", "scope": "bootstrap"}
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["database"] == "unconfigured"
        assert client.get("/api/v1/approvals").status_code == 404


def test_database_connection_failure_does_not_break_liveness_or_leak_credentials():
    secret = "synthetic-secret-do-not-expose"
    application = create_app(
        Settings(
            _env_file=None,
            db_host="127.0.0.1",
            db_port=1,
            db_name="campus_test",
            db_user="synthetic_user",
            db_password=secret,
        )
    )
    with TestClient(application) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "database": "unavailable",
            "scope": "bootstrap",
        }
        assert secret not in response.text
        assert "synthetic_user" not in response.text
        assert "127.0.0.1" not in response.text
        assert client.get("/health/live").status_code == 200
    assert application.state.engine.pool.checkedout() == 0
