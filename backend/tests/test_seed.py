from sqlalchemy import text

from scripts.seed import apply_seeds


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
