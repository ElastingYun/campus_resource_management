"""Runtime M1 parameters ("系统参数可调"): code defaults, overridden by m1_settings rows."""

from dataclasses import asdict, dataclass, fields, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.m1_reservation.errors import M1Error
from app.modules.m1_reservation.models import Setting


@dataclass(frozen=True)
class M1Settings:
    max_hours: int = 4  # course brief: at most 4 whole hours per booking, adjustable
    booking_horizon_days: int = 7  # provisional: how far ahead a slot may start
    remind_before_minutes: int = 15  # course brief
    late_remind_minutes: int = 10  # course brief
    no_show_minutes: int = 15  # course brief
    checkin_open_before_minutes: int = 15  # provisional: earliest check-in before start


# Inclusive bounds; values outside them are rejected rather than clamped.
BOUNDS: dict[str, tuple[int, int]] = {
    "max_hours": (1, 12),
    "booking_horizon_days": (1, 60),
    "remind_before_minutes": (1, 120),
    "late_remind_minutes": (1, 60),
    "no_show_minutes": (1, 60),
    "checkin_open_before_minutes": (0, 60),
}
KEYS = tuple(f.name for f in fields(M1Settings))


def load_settings(session: Session) -> M1Settings:
    overrides = {row.key: row.value for row in session.scalars(select(Setting)) if row.key in KEYS}
    return replace(M1Settings(), **overrides)


def validate(candidate: M1Settings) -> None:
    for key, (low, high) in BOUNDS.items():
        value = getattr(candidate, key)
        if not low <= value <= high:
            raise M1Error(422, "invalid_setting", f"{key} 必须在 {low} 到 {high} 之间", {"key": key})
    if candidate.late_remind_minutes >= candidate.no_show_minutes:
        raise M1Error(
            422,
            "invalid_setting",
            "迟到提醒必须早于自动取消",
            {"key": "late_remind_minutes"},
        )


def as_dict(settings: M1Settings) -> dict[str, int]:
    return asdict(settings)
