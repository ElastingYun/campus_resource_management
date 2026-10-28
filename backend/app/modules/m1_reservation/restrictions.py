"""Write-back API for M2 (whole-room approvals) and M3 (repairs) — see the API contract.

Applying is idempotent per (source_type, source_id); releasing is idempotent and
only ever affects its own source. Existing personal reservations under a new
restriction are reported to the caller, not cancelled: that policy is undecided.
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.common.resources.models import Room
from app.modules.m1_reservation import events, repository
from app.modules.m1_reservation.errors import M1Error
from app.modules.m1_reservation.identity import CurrentUser
from app.modules.m1_reservation.models import SeatRestriction
from app.modules.m1_reservation.timeslots import to_business_time

PERMISSIONS = {
    "m2_approval": "m1:restriction:m2_approval",
    "m3_repair": "m1:restriction:m3_repair",
}
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _authorize(user: CurrentUser, source_type: str, source_id: str) -> None:
    if not user.has(PERMISSIONS[source_type]):
        # A caller may only touch its own module's restrictions (M2 cannot lift M3's).
        raise M1Error(403, "forbidden", "无权写入该来源的座位限制", {"required": PERMISSIONS[source_type]})
    if not _SOURCE_ID.fullmatch(source_id):
        raise M1Error(422, "invalid_source_id", "来源业务 ID 格式不正确")


def get(session: Session, user: CurrentUser, source_type: str, source_id: str) -> SeatRestriction:
    _authorize(user, source_type, source_id)
    restriction = repository.restriction_by_source(session, source_type, source_id)
    if restriction is None:
        raise M1Error(404, "restriction_not_found", "该来源的座位限制不存在")
    return restriction


def apply(
    session: Session,
    user: CurrentUser,
    source_type: str,
    source_id: str,
    *,
    room_id: int,
    seat_id: int | None,
    start_at: datetime,
    end_at: datetime | None,
    note: str,
    now: datetime,
    tz: ZoneInfo,
) -> tuple[SeatRestriction, bool, list[int]]:
    """Returns (restriction, created, ids of active reservations it overlaps)."""
    _authorize(user, source_type, source_id)
    if seat_id is not None:
        raise M1Error(422, "room_scope_required", "审批占用和维修下架必须作用于整间教室")
    if source_type == "m3_repair" and end_at is not None:
        raise M1Error(422, "repair_end_forbidden", "维修下架必须持续至验收通过，不可按结束时间自动恢复")
    start = to_business_time(start_at, tz)
    end = to_business_time(end_at, tz) if end_at is not None else None
    if end is None and source_type == "m2_approval":
        raise M1Error(422, "end_required", "整教室占用必须给出结束时间")
    if end is not None and end <= start:
        raise M1Error(422, "invalid_interval", "结束时间必须晚于开始时间")
    if session.get(Room, room_id) is None:
        raise M1Error(404, "room_not_found", "自习室不存在")

    # Exclusive room lock: bookings in flight for this room finish first, so
    # they are either refused by this restriction or listed as affected.
    repository.lock_room_exclusive(session, room_id)
    existing = repository.restriction_by_source(session, source_type, source_id)
    if existing is not None:
        if existing.status == "released":
            raise M1Error(409, "restriction_released", "该来源的限制已解除，不能再次生效；请使用新的业务 ID")
        if (existing.room_id, existing.seat_id, existing.start_at, existing.end_at) != (room_id, seat_id, start, end):
            raise M1Error(409, "restriction_conflict", "同一来源已存在参数不同的限制")
        return existing, False, repository.active_reservations_under(session, existing)

    restriction = SeatRestriction(
        source_type=source_type,
        source_id=source_id,
        room_id=room_id,
        seat_id=seat_id,
        start_at=start,
        end_at=end,
        status="active",
        note=note,
        created_by=user.id,
        created_at=now,
    )
    session.add(restriction)
    session.flush()
    affected = repository.active_reservations_under(session, restriction)
    events.record(
        session,
        source_type=source_type,
        source_id=source_id,
        action="restriction_applied",
        room_id=room_id,
        seat_id=seat_id,
        start_at=start,
        end_at=end,
        actor_id=user.id,
        occurred_at=now,
        detail={"affected_reservation_ids": affected},
    )
    session.commit()
    return restriction, True, affected


def release(
    session: Session, user: CurrentUser, source_type: str, source_id: str, *, reason: str, now: datetime
) -> tuple[SeatRestriction, bool]:
    """Returns (restriction, released_now). Releasing twice is a no-op, not an error."""
    _authorize(user, source_type, source_id)
    if source_type == "m3_repair" and reason != "accepted":
        raise M1Error(422, "repair_acceptance_required", "维修下架仅可在验收通过后解除")
    restriction = repository.restriction_by_source(session, source_type, source_id, for_update=True)
    if restriction is None:
        raise M1Error(404, "restriction_not_found", "该来源的座位限制不存在")
    if restriction.status == "released":
        return restriction, False
    restriction.status = "released"
    restriction.released_at = now
    restriction.released_by = user.id
    restriction.release_reason = reason
    events.record(
        session,
        source_type=source_type,
        source_id=source_id,
        action="restriction_released",
        room_id=restriction.room_id,
        seat_id=restriction.seat_id,
        start_at=restriction.start_at,
        end_at=restriction.end_at,
        actor_id=user.id,
        occurred_at=now,
        detail={"reason": reason},
    )
    session.commit()
    return restriction, True
