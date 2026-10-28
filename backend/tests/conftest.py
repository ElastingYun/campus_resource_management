"""Shared fixtures: a throwaway PostgreSQL database migrated from empty.

Database tests read the same CAMPUS_DB_* variables as the app (docs/development.md)
and need a real PostgreSQL server: M1 relies on exclusion constraints and advisory
locks. The configured user must be allowed to create databases. Each run creates
crm_test_<random>, migrates it from empty and drops it afterwards; the configured
database itself is never written to.
"""

import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine, text
from sqlalchemy.pool import NullPool

from alembic import command
from app.config import Settings
from app.main import create_app
from app.modules.m1_reservation.config import M1Config

BACKEND_DIR = Path(__file__).resolve().parents[1]


def database_url(settings: Settings) -> URL:
    assert settings.db_password is not None
    return URL.create(
        "postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value(),
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )


def server_settings() -> Settings:
    settings = Settings(_env_file=None)
    if not settings.database_configured:
        pytest.fail("Database tests need CAMPUS_DB_HOST and CAMPUS_DB_PASSWORD (see conftest.py)")
    return settings


def create_database(prefix: str = "crm_test") -> Settings:
    server = server_settings()
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    admin = create_engine(database_url(server), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return server.model_copy(update={"db_name": name})


def drop_database(settings: Settings) -> None:
    admin = create_engine(
        database_url(server_settings()), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{settings.db_name}" WITH (FORCE)'))
    admin.dispose()


def run_alembic(settings: Settings, action: str, revision: str) -> None:
    """Run `alembic upgrade|downgrade <revision>` against the given database."""
    engine = create_engine(database_url(settings), poolclass=NullPool)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    try:
        with engine.begin() as connection:
            cfg.attributes["connection"] = connection
            getattr(command, action)(cfg, revision)
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def db_settings():
    settings = create_database()
    run_alembic(settings, "upgrade", "head")
    yield settings
    drop_database(settings)


@pytest.fixture(scope="session")
def engine(db_settings):
    # Larger pool than the app's: concurrency tests hold one connection per racing thread.
    eng = create_engine(database_url(db_settings), pool_size=20)
    yield eng
    eng.dispose()


@pytest.fixture
def clean_db(engine):
    """Empty every application table (keeps the migration version)."""
    with engine.begin() as conn:
        tables = (
            conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        if tables:
            joined = ", ".join(f'"{t}"' for t in tables)
            conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def m1_config():
    return M1Config(
        _env_file=None,
        timezone="Asia/Shanghai",
        auth_mode="dev-headers",
        checkin_code_secret="test-secret-not-for-production",
    )


@pytest.fixture
def app(db_settings, m1_config, clean_db):
    application = create_app(db_settings)
    application.state.m1_config = m1_config
    return application


@pytest.fixture
def client(app):
    # Entering the client runs D's lifespan, which creates and disposes the engine.
    with TestClient(app) as c:
        yield c
