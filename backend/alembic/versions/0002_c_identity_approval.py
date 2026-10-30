"""Add the frozen C baseline, preserving verified legacy C databases."""

import hashlib
from pathlib import Path

from psycopg.rows import dict_row

from alembic import op

revision = "0002_c_identity_approval"
down_revision = "0001_bootstrap"
branch_labels = None
depends_on = None

BASELINE_NAME = "001_c_foundation.sql"
BASELINE_SHA256 = "10737fc1750058bdcc4ee55886ef01901ebe8b0b386206346b0b7116ba22433b"
BASELINE_TABLES = (
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


def upgrade() -> None:
    # This revision does not import mutable application migration helpers.
    root = Path(__file__).resolve().parents[2]
    source = (root / "app/modules/m2_approval/migrations" / BASELINE_NAME).read_text()
    if hashlib.sha256(source.encode()).hexdigest() != BASELINE_SHA256:
        raise RuntimeError("The frozen C baseline was modified")
    with op.get_bind().connection.driver_connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended('c:migrations',0))")
        cursor.execute("""CREATE TABLE IF NOT EXISTS c_schema_migrations
                          (name text PRIMARY KEY, checksum char(64) NOT NULL)""")
        cursor.execute("SELECT checksum FROM c_schema_migrations WHERE name=%s", (BASELINE_NAME,))
        previous = cursor.fetchone()
        if previous is None:
            cursor.execute(source)
            cursor.execute(
                "INSERT INTO c_schema_migrations VALUES (%s,%s)", (BASELINE_NAME, BASELINE_SHA256)
            )
        elif previous["checksum"] != BASELINE_SHA256:
            raise RuntimeError("Applied C baseline checksum changed")
        for name in BASELINE_TABLES:
            cursor.execute("SELECT to_regclass(%s) AS present", (name,))
            if cursor.fetchone()["present"] is None:
                raise RuntimeError("C migration history does not match the actual schema")


def downgrade() -> None:
    raise RuntimeError("C business-data removal requires a separately approved recovery plan")
