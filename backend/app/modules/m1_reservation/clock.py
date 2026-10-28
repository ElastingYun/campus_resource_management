"""Injectable clock so time rules (reminders, no-show, booking window) are testable."""

from datetime import datetime, timezone
from typing import Protocol

from fastapi import Request


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as an aware datetime."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def get_clock(request: Request) -> Clock:
    return request.app.state.clock
