from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db import Base
from tests.conftest import alembic_config, create_database, drop_database

# Import every model module so Base.metadata describes the full schema.
import app.common.resources.models  # noqa: F401,E402
import app.modules.m1_reservation.models  # noqa: F401,E402


def test_orm_models_match_migrated_schema(engine):
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_schema_replays_from_empty_after_full_downgrade():
    url = create_database("crm_migr")
    cfg = alembic_config(url)
    eng = create_engine(url)
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        assert set(inspect(eng).get_table_names()) == {"alembic_version"}
        command.upgrade(cfg, "head")
        assert {"rooms", "seats"} <= set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
        drop_database(url)
