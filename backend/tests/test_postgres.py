import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.database import build_engine
from app.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CAMPUS_TEST_POSTGRES") != "1",
        reason="Set CAMPUS_TEST_POSTGRES=1 with a migrated real PostgreSQL database",
    ),
]


def test_postgres_readiness_and_migration_version():
    settings = Settings(_env_file=None)
    assert settings.database_configured, "Integration mode requires real database configuration"
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "database": "connected", "scope": "bootstrap"}
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            versions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            heads = ScriptDirectory.from_config(
                Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            ).get_heads()
            assert len(heads) == 1, "Coordinate parallel migration heads before integration"
            assert set(versions) == set(heads)
    finally:
        engine.dispose()
