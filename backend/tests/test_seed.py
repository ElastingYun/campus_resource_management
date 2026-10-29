import os
import subprocess
import sys

from sqlalchemy import text

from scripts.seed import apply_seeds
from tests.conftest import BACKEND_DIR


def _counts(engine):
    with engine.connect() as conn:
        rooms = conn.execute(text("SELECT count(*) FROM rooms")).scalar_one()
        seats = conn.execute(text("SELECT count(*) FROM seats")).scalar_one()
        ids = conn.execute(text("SELECT array_agg(id ORDER BY id) FROM seats")).scalar_one()
    return rooms, seats, ids


def test_dev_seed_is_idempotent(engine, clean_db):
    apply_seeds(engine)
    first = _counts(engine)
    apply_seeds(engine)
    assert _counts(engine) == first
    assert first[:2] == (3, 36)


def test_dev_seed_marks_outlet_seats(engine, clean_db):
    apply_seeds(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT outlet_type, count(*) FROM seats GROUP BY outlet_type")
        ).all()
    assert dict(rows) == {"fixed": 12, "rail": 6, "none": 18}


def test_seed_command_runs_against_the_configured_database(db_settings, engine, clean_db):
    """The documented command, run as a separate process with D's CAMPUS_DB_* settings."""
    env = {
        **os.environ,
        "CAMPUS_DB_HOST": db_settings.db_host,
        "CAMPUS_DB_PORT": str(db_settings.db_port),
        "CAMPUS_DB_NAME": db_settings.db_name,
        "CAMPUS_DB_USER": db_settings.db_user,
        "CAMPUS_DB_PASSWORD": db_settings.db_password.get_secret_value(),
    }
    command = [sys.executable, "-m", "scripts.seed"]
    for _ in range(2):  # idempotent: the second run adds nothing
        result = subprocess.run(
            command, cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr
        assert "applied 0001_dev_resources.sql" in result.stdout
    assert _counts(engine)[:2] == (3, 36)
