from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

# Import every model module so Base.metadata describes the full schema.
import app.common.resources.models  # noqa: F401
import app.modules.m1_reservation.models  # noqa: F401
from app.database import Base
from tests.conftest import (
    BACKEND_DIR,
    create_database,
    database_url,
    drop_database,
    run_alembic,
)


def test_migrations_form_one_chain_from_d_bootstrap():
    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert len(script.get_heads()) == 1, "parallel migration heads must be coordinated first"
    assert script.get_bases() == ["0001_bootstrap"]


def test_orm_models_match_migrated_schema(engine):
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_schema_replays_from_empty_after_full_downgrade():
    settings = create_database("crm_migr")
    eng = create_engine(database_url(settings), poolclass=NullPool)
    try:
        run_alembic(settings, "upgrade", "head")
        run_alembic(settings, "downgrade", "base")
        assert set(inspect(eng).get_table_names()) == {"alembic_version"}
        run_alembic(settings, "upgrade", "head")
        assert {"rooms", "seats", "m1_reservations"} <= set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
        drop_database(settings)
