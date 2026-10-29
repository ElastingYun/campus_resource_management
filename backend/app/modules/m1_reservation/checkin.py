"""Check-in with each room's daily code (shown on the room's screen, or as a QR code).

The code is derived from a server secret, the room and the business-local date,
so it rotates at local midnight and needs no storage. Reservation responses never
include it: a student must be in the room to read it.
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.common.resources.models import Room
from app.modules.m1_reservation import events, repository
from app.modules.m1_reservation.errors import M1Error
from app.modules.m1_reservation.identity import CurrentUser
from app.modules.m1_reservation.models import Reservation
from app.modules.m1_reservation.settings import load_settings


@dataclass(frozen=True)
class RoomCode:
    room_id: int
    day: date
    code: str
    valid_until: datetime


def daily_code(secret: str, room_id: int, day: date) -> str:
    message = f"m1-checkin:{room_id}:{day.isoformat()}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


def _require_secret(secret: str) -> None:
    if not secret:
        raise M1Error(503, "checkin_not_configured", "签到码密钥未配置（M1_CHECKIN_CODE_SECRET）")


def room_code(
    session: Session, secret: str, room_id: int, *, now: datetime, tz: ZoneInfo
) -> RoomCode:
    _require_secret(secret)
    if session.get(Room, room_id) is None:
        raise M1Error(404, "room_not_found", "自习室不存在")
    day = now.astimezone(tz).date()
    valid_until = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    return RoomCode(
        room_id=room_id, day=day, code=daily_code(secret, room_id, day), valid_until=valid_until
    )


def check_in(
    session: Session,
    user: CurrentUser,
    reservation_id: int,
    code: str,
    *,
    now: datetime,
    tz: ZoneInfo,
    secret: str,
) -> Reservation:
    _require_secret(secret)
    # Row lock: a concurrent no-show job waits for us (or we see its result).
    reservation = repository.reservation_for_update(session, reservation_id)
    if reservation is None or reservation.user_id != user.id:
        raise M1Error(404, "reservation_not_found", "预约不存在")
    if reservation.status == "checked_in":
        raise M1Error(409, "already_checked_in", "该预约已签到")
    if reservation.status != "booked":
        raise M1Error(
            409, "not_checkinable", "该预约已取消或已违约，不能签到", {"status": reservation.status}
        )

    settings = load_settings(session)
    opens_at = reservation.start_at - timedelta(minutes=settings.checkin_open_before_minutes)
    closes_at = reservation.start_at + timedelta(minutes=settings.no_show_minutes)
    if now < opens_at:
        raise M1Error(
            409,
            "checkin_not_open",
            "尚未到签到时间",
            {"opens_at": opens_at.astimezone(tz).isoformat()},
        )
    if now >= closes_at:
        raise M1Error(409, "checkin_closed", "已超过签到截止时间")

    expected = daily_code(secret, reservation.room_id, now.astimezone(tz).date())
    if not hmac.compare_digest(code.strip().encode(), expected.encode()):
        raise M1Error(422, "invalid_checkin_code", "签到码不正确或已过期")

    reservation.status = "checked_in"
    reservation.checked_in_at = now
    reservation.updated_at = now
    events.record_reservation(session, reservation, "checked_in", user.id, now)
    session.commit()
    return reservation
