"""Apply every SQL seed file in database/seeds/ in name order, in one transaction.

Usage (from backend/, with the CAMPUS_DB_* settings): python -m scripts.seed
Run it as a module: as a plain file path Python cannot import the `app` package.
Seeds must be idempotent; run migrations (alembic upgrade head) first.
"""

from pathlib import Path

from sqlalchemy import Engine

from app.config import Settings
from app.database import build_engine

SEED_DIR = Path(__file__).resolve().parents[2] / "database" / "seeds"


def apply_seeds(engine: Engine, seed_dir: Path = SEED_DIR) -> list[str]:
    files = sorted(seed_dir.glob("*.sql"))
    with engine.begin() as conn:
        for path in files:
            conn.exec_driver_sql(path.read_text(encoding="utf-8"))
    return [p.name for p in files]


if __name__ == "__main__":
    engine = build_engine(Settings())
    try:
        for name in apply_seeds(engine):
            print(f"applied {name}")
    finally:
        engine.dispose()
