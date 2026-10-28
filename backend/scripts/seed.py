"""Apply every SQL seed file in database/seeds/ in name order, in one transaction.

Usage (from backend/): DATABASE_URL=... python scripts/seed.py
Seeds must be idempotent; run migrations (alembic upgrade head) first.
"""

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine

SEED_DIR = Path(__file__).resolve().parents[2] / "database" / "seeds"


def apply_seeds(database_url: str, seed_dir: Path = SEED_DIR) -> list[str]:
    files = sorted(seed_dir.glob("*.sql"))
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            for path in files:
                conn.exec_driver_sql(path.read_text(encoding="utf-8"))
    finally:
        engine.dispose()
    return [p.name for p in files]


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL first")
    for name in apply_seeds(url):
        print(f"applied {name}")
