from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

# Import every model module so Base.metadata describes the full schema.
import app.common.resources.models  # noqa: F401
import app.modules.m1_reservation.models  # noqa: F401
from app.common.auth.database import Database
from app.database import Base
from app.modules.m2_approval.migrate import OWNED_TABLES, verify_schema
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
    # C owns a frozen SQL baseline rather than ORM models. Exclude only its
    # named tables from A's ORM comparison; independently verify the C ledger.
    c_tables = {*OWNED_TABLES, "c_schema_migrations"}

    def include_object(obj, name, type_, reflected, compare_to):
        return not (type_ == "table" and name in c_tables)

    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"include_object": include_object}), Base.metadata
        )
    assert diff == []
    with Database(engine_provider=lambda: engine).transaction() as conn:
        verify_schema(conn)


def test_schema_replays_from_empty_after_full_downgrade(postgres_server):
    settings = create_database(postgres_server, "crm_migr")
    eng = create_engine(database_url(settings), poolclass=NullPool)
    try:
        # Preserve A's reversible-chain check before the non-destructive C
        # baseline is adopted; C downgrade is intentionally refused.
        run_alembic(settings, "upgrade", "0006_m1_seat_restrictions")
        run_alembic(settings, "downgrade", "base")
        assert set(inspect(eng).get_table_names()) == {"alembic_version"}
        run_alembic(settings, "upgrade", "head")
        assert {"rooms", "seats", "m1_reservations"} <= set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
        drop_database(postgres_server, settings)
