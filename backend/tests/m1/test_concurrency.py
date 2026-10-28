"""Real concurrent transactions against PostgreSQL (no mocks, no shared session)."""

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.modules.m1_reservation import reservations
from app.modules.m1_reservation.errors import M1Error
from app.modules.m1_reservation.identity import PERM_RESERVE, CurrentUser
from tests.m1.conftest import DEFAULT_NOW, SH, local


def _race(engine, attempts):
    """Run each (user_id, seat_id, start, hours, key) booking in its own thread and session at once."""
    factory = sessionmaker(engine, expire_on_commit=False)
    barrier = threading.Barrier(len(attempts))

    def attempt(args):
        user_id, seat_id, start, hours, key = args
        user = CurrentUser(user_id, None, frozenset({PERM_RESERVE}))
        with factory() as session:
            barrier.wait()
            try:
                reservation, created = reservations.create(
                    session, user, seat_id=seat_id, start_at=start, hours=hours,
                    idempotency_key=key, now=DEFAULT_NOW, tz=SH,
                )
                return ("created" if created else "replayed", reservation.id)
            except M1Error as err:
                return (err.code, None)

    with ThreadPoolExecutor(max_workers=len(attempts)) as pool:
        return list(pool.map(attempt, attempts))


def _active_count(engine):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM m1_reservations WHERE status IN ('booked', 'checked_in')")
        ).scalar_one()


def test_many_users_racing_for_one_seat_yield_exactly_one_booking(engine, seeded):
    seat = seeded["seats"]["LIB-101-01"]
    results = _race(engine, [(f"stu-{i:03d}", seat, local(2, 10), 2, None) for i in range(10)])
    outcomes = [code for code, _ in results]
    assert outcomes.count("created") == 1
    assert outcomes.count("seat_conflict") == 9
    assert _active_count(engine) == 1


def _overlapping_active_pairs(engine):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM m1_reservations a JOIN m1_reservations b "
                "ON a.seat_id = b.seat_id AND a.id < b.id "
                "AND a.start_at < b.end_at AND b.start_at < a.end_at "
                "WHERE a.status IN ('booked', 'checked_in') AND b.status IN ('booked', 'checked_in')"
            )
        ).scalar_one()


def test_partially_overlapping_races_still_cannot_double_book(engine, seeded):
    seat = seeded["seats"]["LIB-101-01"]
    # Every pair shares 10:00-11:00, so at most one may win.
    attempts = [("stu-a", seat, local(2, 10), 2, None), ("stu-b", seat, local(2, 9), 2, None),
                ("stu-c", seat, local(2, 10), 1, None), ("stu-d", seat, local(2, 8), 4, None)]
    results = _race(engine, attempts)
    assert [code for code, _ in results].count("created") == 1
    assert _active_count(engine) == 1
    assert _overlapping_active_pairs(engine) == 0


def test_one_user_racing_for_two_seats_gets_only_one(engine, seeded):
    seats = seeded["seats"]
    attempts = [("stu-a", seats["LIB-101-01"], local(2, 10), 2, None),
                ("stu-a", seats["A-201-01"], local(2, 10), 2, None)]
    outcomes = sorted(code for code, _ in _race(engine, attempts))
    assert outcomes == ["created", "user_overlap"]


def test_duplicate_submissions_with_one_key_create_one_reservation(engine, seeded):
    seat = seeded["seats"]["LIB-101-01"]
    results = _race(engine, [("stu-a", seat, local(2, 10), 2, "dup-key")] * 5)
    assert sorted(code for code, _ in results) == ["created"] + ["replayed"] * 4
    assert len({rid for _, rid in results}) == 1
    assert _active_count(engine) == 1
