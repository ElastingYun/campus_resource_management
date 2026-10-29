"""The approved main/C join must preserve both migration histories and data."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from app.common.auth.database import Database
from app.modules.m2_approval.migrate import migrate, verify_schema
from tests.conftest import create_database, database_url, drop_database, run_alembic

MERGE_HEAD = "0007_merge_m1_c"


@pytest.mark.parametrize(
    "starting_revision",
    ["base", "0006_m1_seat_restrictions", "0002_c_identity_approval", "legacy_c"],
)
def test_join_replays_empty_a_c_and_legacy_c_databases_without_losing_data(
    postgres_server, starting_revision
):
    settings = create_database(postgres_server, "crm_c_join")
    engine = create_engine(database_url(settings), poolclass=NullPool)
    c_db = Database(engine_provider=lambda: engine)
    user_id = uuid4()
    try:
        if starting_revision == "legacy_c":
            migrate(c_db)
        elif starting_revision != "base":
            run_alembic(settings, "upgrade", starting_revision)
        if starting_revision == "0006_m1_seat_restrictions":
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO rooms "
                        "(id,code,name,location,access_scope,open_time,close_time,enabled) "
                        "VALUES (9123,'JOIN','合成教室','测试','campus','08:00','22:00',true)"
                    )
                )
        c_started = starting_revision in ("0002_c_identity_approval", "legacy_c")
        if c_started:
            with c_db.transaction() as conn:
                conn.execute(
                    """INSERT INTO c_users
                       (id,username,password_hash,department_id,room_ids,all_rooms)
                       VALUES (%s,'join-synthetic-user','synthetic-unusable-hash',
                               'synthetic',%s,false)""",
                    (user_id, ["9123"]),
                )
                ledger_before = conn.execute("SELECT * FROM c_schema_migrations").fetchall()
        run_alembic(settings, "upgrade", "head")
        run_alembic(settings, "upgrade", "head")
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all() == [MERGE_HEAD]
            tables = set(inspect(conn).get_table_names())
            assert {"rooms", "seats", "m1_reservations", "c_users", "c_business_events"} <= tables
            if starting_revision == "0006_m1_seat_restrictions":
                assert conn.execute(text("SELECT name FROM rooms WHERE id=9123")).scalar_one() == (
                    "合成教室"
                )
        with c_db.transaction() as conn:
            verify_schema(conn)
            if c_started:
                row = conn.execute("SELECT * FROM c_users WHERE id=%s", (user_id,)).fetchone()
                assert row["username"] == "join-synthetic-user" and row["room_ids"] == ["9123"]
                assert conn.execute("SELECT * FROM c_schema_migrations").fetchall() == ledger_before
    finally:
        engine.dispose()
        drop_database(postgres_server, settings)


def test_combined_downgrade_remains_refused_and_keeps_existing_tables(postgres_server):
    settings = create_database(postgres_server, "crm_c_no_drop")
    engine = create_engine(database_url(settings), poolclass=NullPool)
    try:
        run_alembic(settings, "upgrade", "head")
        before = set(inspect(engine).get_table_names())
        with pytest.raises(RuntimeError, match="separately approved recovery plan"):
            run_alembic(settings, "downgrade", "base")
        assert set(inspect(engine).get_table_names()) == before
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
                MERGE_HEAD
            )
        with Database(engine_provider=lambda: engine).transaction() as conn:
            verify_schema(conn)
    finally:
        engine.dispose()
        drop_database(postgres_server, settings)


@pytest.mark.parametrize("corruption", ["checksum", "missing_table"])
def test_combined_upgrade_failure_keeps_legacy_c_data_and_rolls_back_a_tables(
    postgres_server, corruption
):
    settings = create_database(postgres_server, "crm_c_bad_join")
    engine = create_engine(database_url(settings), poolclass=NullPool)
    c_db = Database(engine_provider=lambda: engine)
    try:
        migrate(c_db)
        with c_db.transaction() as conn:
            conn.execute(
                "INSERT INTO c_roles(name,permissions) VALUES ('synthetic-preserve',%s)",
                (["m2.submit"],),
            )
            if corruption == "checksum":
                conn.execute("UPDATE c_schema_migrations SET checksum=%s", ("0" * 64,))
            else:
                conn.execute("DROP TABLE c_receipts")
        before = set(inspect(engine).get_table_names())
        expected = "checksum" if corruption == "checksum" else "actual schema"
        with pytest.raises(RuntimeError, match=expected):
            run_alembic(settings, "upgrade", "head")
        assert set(inspect(engine).get_table_names()) == before
        with c_db.transaction() as conn:
            assert conn.execute(
                "SELECT permissions FROM c_roles WHERE name='synthetic-preserve'"
            ).fetchone()["permissions"] == ["m2.submit"]
            assert (
                conn.execute("SELECT to_regclass('alembic_version')").fetchone()["to_regclass"]
                is None
            )
    finally:
        engine.dispose()
        drop_database(postgres_server, settings)
