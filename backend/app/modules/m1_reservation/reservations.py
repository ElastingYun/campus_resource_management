"""Personal reservations: create, cancel, read. Every write commits its own transaction."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.m1_reservation import availability, events, repository
from app.modules.m1_reservation.errors import M1Error
from app.modules.m1_reservation.identity import CurrentUser
from app.modules.m1_reservation.models import Reservation
from app.modules.m1_reservation.settings import load_settings
from app.modules.m1_reservation.timeslots import check_booking_window, make_slot

SEAT_OVERLAP_CONSTRAINT = "ex_m1_reservations_seat_overlap"

# Blocker reason -> (HTTP status, error code, message). The first reason found wins.
_BLOCKER_ERRORS = {
    "room_disabled": (409, "room_disabled", "该自习室已停用"),
    "seat_disabled": (409, "seat_disabled", "该座位已停用"),
    "department_restricted": (403, "department_restricted", "该自习室仅对所属院系开放"),
    "outside_opening_hours": (422, "outside_opening_hours", "所选时段超出自习室开放时间"),
    "reserved": (409, "seat_conflict", "该座位在所选时段已被预约"),
    "m2_approval": (409, "seat_restricted", "该教室在所选时段已被整间占用"),
    "m3_repair": (409, "seat_restricted", "该教室正在维修，暂停预约"),
}


def _blocker_error(reasons: list[dict[str, str]]) -> M1Error:
    status, code, message = _BLOCKER_ERRORS[reasons[0]["code"]]
    return M1Error(status, code, message, {"reasons": reasons})


def create(
    session: Session,
    user: CurrentUser,
    *,
    seat_id: int,
    start_at: datetime,
    hours: int,
    idempotency_key: str | None,
    now: datetime,
    tz: ZoneInfo,
) -> tuple[Reservation, bool]:
    """Book a seat. Returns (reservation, created); created is False for an idempotent replay."""
    settings = load_settings(session)
    slot = make_slot(start_at, hours, tz, settings)

    # Held until commit: one user's concurrent requests run one after another.
    repository.lock_user(session, user.id)
    if idempotency_key is not None:
        previous = session.scalar(
            select(Reservation).where(
                Reservation.user_id == user.id, Reservation.idempotency_key == idempotency_key
            )
        )
        if previous is not None:
            if (previous.seat_id, previous.start_at, previous.end_at) == (
                seat_id,
                slot.start_at,
                slot.end_at,
            ):
                return previous, False
            raise M1Error(409, "idempotency_key_reused", "该幂等键已用于另一笔不同的预约")

    check_booking_window(slot, now, settings)
    found = repository.seats_with_rooms(session, seat_id=seat_id)
    if not found:
        raise M1Error(404, "seat_not_found", "座位不存在")
    seat, room = found[0]
    # Lock order (user -> room shared -> seat) is the same everywhere: no cycles.
    repository.lock_room_shared(session, room.id)
    repository.lock_seat(session, seat.id)

    result = availability.evaluate(session, [(seat, room)], slot, user, tz)[0]
    if not result.available:
        raise _blocker_error(result.reasons)
    if repository.user_has_overlap(session, user.id, slot):
        raise M1Error(409, "user_overlap", "你在该时段已有其他有效预约")

    reservation = Reservation(
        user_id=user.id,
        seat_id=seat.id,
        room_id=room.id,
        start_at=slot.start_at,
        end_at=slot.end_at,
        status="booked",
        idempotency_key=idempotency_key,
        created_at=now,
        updated_at=now,
    )
    session.add(reservation)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig.diag, "constraint_name", None) == SEAT_OVERLAP_CONSTRAINT:
            # Another booking for this seat committed after our check: same answer as the check.
            raise _blocker_error([{"code": "reserved"}]) from exc
        raise
    events.record_reservation(session, reservation, "reserved", user.id, now)
    session.commit()
    return reservation, True


def cancel(
    session: Session, user: CurrentUser, reservation_id: int, *, now: datetime
) -> Reservation:
    reservation = repository.reservation_for_update(session, reservation_id)
    if reservation is None or reservation.user_id != user.id:
        # Same answer for "missing" and "someone else's" so ids reveal nothing.
        raise M1Error(404, "reservation_not_found", "预约不存在")
    if reservation.status != "booked":
        raise M1Error(
            409, "not_cancellable", "只有待签到的预约可以取消", {"status": reservation.status}
        )
    if now >= reservation.start_at:
        raise M1Error(409, "cancel_window_closed", "预约开始后不能再取消")
    reservation.status = "cancelled"
    reservation.cancelled_at = now
    reservation.cancel_reason = "user_cancelled"
    reservation.updated_at = now
    events.record_reservation(session, reservation, "cancelled", user.id, now)
    session.commit()
    return reservation
