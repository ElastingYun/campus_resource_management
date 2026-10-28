"""Shared fixtures: a throwaway PostgreSQL database migrated from empty.

Tests need a real PostgreSQL server because M1 relies on PostgreSQL features
(exclusion constraints, advisory locks). Point TEST_DATABASE_URL at a server
where the user may create databases, e.g.

    docker run -d --name crm-test-pg -e POSTGRES_USER=m1 -e POSTGRES_PASSWORD=m1test \
        -p 127.0.0.1:56432:5432 postgres:16-alpine
    export TEST_DATABASE_URL=postgresql+psycopg://m1:m1test@127.0.0.1:56432/m1

A database named crm_test_<random> is created for the session and dropped after.
"""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import AppConfig
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _server_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set; database tests cannot run (see tests/conftest.py)")
    return url


def create_database(prefix: str = "crm_test") -> str:
    server = make_url(_server_url())
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return server.set(database=name).render_as_string(hide_password=False)


def drop_database(url: str) -> None:
    server = make_url(_server_url())
    name = make_url(url).database
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def database_url():
    url = create_database()
    command.upgrade(alembic_config(url), "head")
    yield url
    drop_database(url)


@pytest.fixture(scope="session")
def engine(database_url):
    eng = create_engine(database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def clean_db(engine):
    """Empty every application table (keeps the migration version)."""
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            )
        ).scalars().all()
        if tables:
            joined = ", ".join(f'"{t}"' for t in tables)
            conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def app_config(database_url):
    return AppConfig(
        database_url=database_url,
        business_timezone="Asia/Shanghai",
        auth_mode="dev-headers",
        checkin_code_secret="test-secret-not-for-production",
    )


@pytest.fixture
def app(app_config, clean_db):
    application = create_app(app_config)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
