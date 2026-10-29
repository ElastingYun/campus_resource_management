"""Booking slot rules: whole business-timezone hours, bounded duration and window.

Intervals are half-open [start_at, end_at): a slot ending at 10:00 does not
overlap one starting at 10:00. All stored datetimes are timezone-aware.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.m1_reservation.errors import M1Error
from app.modules.m1_reservation.settings import M1Settings


@dataclass(frozen=True)
class Slot:
    start_at: datetime
    end_at: datetime
    hours: int


def to_business_time(value: datetime, tz: ZoneInfo) -> datetime:
    """Interpret naive input as business-local time; convert aware input."""
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def make_slot(start_at: datetime, hours: int, tz: ZoneInfo, settings: M1Settings) -> Slot:
    local = to_business_time(start_at, tz)
    if (local.minute, local.second, local.microsecond) != (0, 0, 0):
        raise M1Error(422, "not_whole_hour", "预约必须从整点开始")
    if not 1 <= hours <= settings.max_hours:
        raise M1Error(
            422,
            "invalid_duration",
            f"单次预约时长必须为 1 到 {settings.max_hours} 小时",
            {"max_hours": settings.max_hours},
        )
    start = local.astimezone(UTC)
    return Slot(start_at=start, end_at=start + timedelta(hours=hours), hours=hours)


def check_booking_window(slot: Slot, now: datetime, settings: M1Settings) -> None:
    if slot.start_at <= now:
        raise M1Error(422, "start_not_in_future", "只能预约尚未开始的时段")
    if slot.start_at > now + timedelta(days=settings.booking_horizon_days):
        raise M1Error(
            422,
            "beyond_booking_horizon",
            f"最多只能预约 {settings.booking_horizon_days} 天内的时段",
            {"booking_horizon_days": settings.booking_horizon_days},
        )


def within_opening_hours(slot: Slot, open_time: time, close_time: time, tz: ZoneInfo) -> bool:
    start = slot.start_at.astimezone(tz)
    end = slot.end_at.astimezone(tz)
    # Same local day only: rooms have daily hours and cross-day booking is not approved.
    return start.date() == end.date() and start.time() >= open_time and end.time() <= close_time
