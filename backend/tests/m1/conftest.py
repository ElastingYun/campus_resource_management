"""M1 fixtures: seeded synthetic rooms/seats, a controllable clock, dev identities."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.modules.m1_reservation.identity import PERM_RESERVE
from scripts.seed import apply_seeds

SH = ZoneInfo("Asia/Shanghai")
# Monday 2026-11-02 07:30 local; most tests book later the same day.
DEFAULT_NOW = datetime(2026, 11, 2, 7, 30, tzinfo=SH)


class FixedClock:
    def __init__(self, now: datetime):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now

    def advance(self, **delta) -> None:
        self._now += timedelta(**delta)


def local(day: int, hour: int, minute: int = 0) -> datetime:
    """A November 2026 local time, e.g. local(2, 10) -> 2026-11-02 10:00 +08:00."""
    return datetime(2026, 11, day, hour, minute, tzinfo=SH)


def run_together(*actions):
    """Run each action in its own thread, all released at the same instant.

    Returns their results in order; an exception in any action is re-raised here.
    """
    barrier = threading.Barrier(len(actions))

    def gated(action):
        barrier.wait()
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        futures = [pool.submit(gated, action) for action in actions]
        return [future.result() for future in futures]


def auth(user_id: str = "stu-001", department: str | None = None, perms=(PERM_RESERVE,)) -> dict:
    headers = {"X-Dev-User-Id": user_id, "X-Dev-Permissions": ",".join(perms)}
    if department:
        headers["X-Dev-Department"] = department
    return headers


@pytest.fixture
def clock(app):
    fixed = FixedClock(DEFAULT_NOW)
    app.state.clock = fixed
    return fixed


@pytest.fixture
def seeded(app, database_url, engine):
    """Apply the dev seed; return {"rooms": {code: id}, "seats": {code: id}}."""
    apply_seeds(database_url)
    with engine.connect() as conn:
        rooms = dict(conn.execute(text("SELECT code, id FROM rooms")).all())
        seats = dict(conn.execute(text("SELECT code, id FROM seats")).all())
    return {"rooms": rooms, "seats": seats}
