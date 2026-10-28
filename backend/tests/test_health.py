from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app


def test_health_reports_database_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


def test_health_reports_unreachable_database_as_503():
    # Port 1 on loopback refuses connections, so the probe must fail.
    app = create_app(AppConfig(database_url="postgresql+psycopg://x:y@127.0.0.1:1/none"))
    with TestClient(app) as c:
        resp = c.get("/api/health")
    assert resp.status_code == 503
    assert resp.json()["database"] == "unavailable"
