"""Explicit, checksum-verified baseline runner until the host migration tool exists."""

import hashlib
from pathlib import Path

from app.common.auth.database import Database


def migrate(database: Database) -> None:
    with database.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('c:migrations',0))")
        conn.execute("""CREATE TABLE IF NOT EXISTS c_schema_migrations
                        (name text PRIMARY KEY, checksum char(64) NOT NULL)""")
        for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
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
            conn.execute(
                "INSERT INTO c_schema_migrations VALUES (%s,%s)", (path.name, checksum)
            )
