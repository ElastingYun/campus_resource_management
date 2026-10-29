"""M1 on D's app factory, without a database (these run in CI's unit-test stage)."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.modules.m1_reservation.config import M1Config
from tests.m1.conftest import auth


@pytest.fixture
def no_db_app(monkeypatch):
    for key in ("HOST", "PORT", "NAME", "USER", "PASSWORD"):
        monkeypatch.delenv(f"CAMPUS_DB_{key}", raising=False)
    return create_app(Settings(_env_file=None))


def test_m1_routes_are_mounted_on_the_shared_app(no_db_app):
    paths = no_db_app.openapi()["paths"]
    assert "/api/v1/m1/reservations" in paths
    assert "/api/v1/m1/restrictions/{source_type}/{source_id}/release" in paths


def test_default_config_rejects_every_identity(no_db_app, monkeypatch):
    monkeypatch.delenv("CAMPUS_M1_AUTH_MODE", raising=False)
    no_db_app.state.m1_config = M1Config(_env_file=None)
    with TestClient(no_db_app) as client:
        resp = client.get("/api/v1/m1/settings", headers=auth())
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthenticated"


def test_m1_answers_503_without_database_configuration(no_db_app):
    no_db_app.state.m1_config = M1Config(_env_file=None, auth_mode="dev-headers")
    with TestClient(no_db_app) as client:
        resp = client.get("/api/v1/m1/settings", headers=auth())
        assert client.get("/health/live").status_code == 200
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "database_unavailable"


@pytest.mark.parametrize(
    "overrides",
    [{"timezone": "Mars/Olympus"}, {"auth_mode": "trust-everyone"}, {"checkin_code_secret": ""}],
)
def test_invalid_m1_config_is_rejected(overrides):
    with pytest.raises(ValidationError):
        M1Config(_env_file=None, **overrides)


def test_checkin_secret_is_not_exposed_by_repr():
    config = M1Config(_env_file=None, checkin_code_secret="synthetic-secret-do-not-expose")
    assert "synthetic-secret" not in repr(config)
    assert config.checkin_secret() == "synthetic-secret-do-not-expose"
