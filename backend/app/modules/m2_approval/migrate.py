"""Explicit, checksum-verified baseline runner until the host migration tool exists."""

import hashlib
from pathlib import Path

from psycopg.rows import dict_row

from app.common.auth.database import Database

OWNED_TABLES = (
    "c_users",
    "c_roles",
    "c_user_roles",
    "c_sessions",
    "c_login_buckets",
    "c_audit_events",
    "c_applications",
    "c_decisions",
    "c_receipts",
    "c_m1_operations",
    "c_business_events",
)
BASELINE_NAME = "001_c_foundation.sql"


def baseline_path() -> Path:
    return Path(__file__).parent / "migrations" / BASELINE_NAME


def verify_schema(conn) -> None:
    for name in OWNED_TABLES:
        if conn.execute("SELECT to_regclass(%s) AS present", (name,)).fetchone()["present"] is None:
            raise RuntimeError("C migration history does not match the actual schema")
    for path in (baseline_path(),):
        row = conn.execute(
            "SELECT checksum FROM c_schema_migrations WHERE name=%s", (path.name,)
        ).fetchone()
        if row is None or row["checksum"] != hashlib.sha256(path.read_text().encode()).hexdigest():
            raise RuntimeError("C migration ledger is incomplete or incompatible")


def apply_migrations(conn) -> None:
    """Join the caller's transaction and safely adopt the existing C baseline."""
    previous_factory = conn.row_factory
    conn.row_factory = dict_row
    try:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('c:migrations',0))")
        conn.execute("""CREATE TABLE IF NOT EXISTS c_schema_migrations
                        (name text PRIMARY KEY, checksum char(64) NOT NULL)""")
        # Freeze revision 0002 to this baseline; future SQL needs a new Alembic revision.
        for path in (baseline_path(),):
            source = path.read_text()
            checksum = hashlib.sha256(source.encode()).hexdigest()
            previous = conn.execute(
                "SELECT checksum FROM c_schema_migrations WHERE name=%s",
                (path.name,),
            ).fetchone()
            if previous:
                if previous["checksum"] != checksum:
                    raise RuntimeError("Applied migration checksum changed")
                continue
            conn.execute(source)
            conn.execute("INSERT INTO c_schema_migrations VALUES (%s,%s)", (path.name, checksum))
        verify_schema(conn)
    finally:
        conn.row_factory = previous_factory


def migrate(database: Database) -> None:
    """Standalone compatibility entry point; hosted apps use Alembic."""
    with database.transaction() as conn:
        apply_migrations(conn)
