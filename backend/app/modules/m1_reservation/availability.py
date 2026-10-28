"""Why a seat can or cannot be booked for a slot.

`blockers` is the single source of truth shared by search and booking, so the
search page can never show a seat as bookable that booking would refuse
(apart from races, which booking re-checks inside its transaction).
"""

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.common.resources.models import Room, Seat
from app.modules.m1_reservation import repository
from app.modules.m1_reservation.identity import CurrentUser
from app.modules.m1_reservation.timeslots import Slot, within_opening_hours


@dataclass
class SeatAvailability:
    seat: Seat
    room: Room
    reasons: list[dict[str, str]] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return not self.reasons


def static_blockers(seat: Seat, room: Room, slot: Slot, user: CurrentUser, tz: ZoneInfo) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    if not room.enabled:
        reasons.append({"code": "room_disabled"})
    if not seat.enabled:
        reasons.append({"code": "seat_disabled"})
    if room.access_scope == "department" and user.department_id != room.department_id:
        reasons.append({"code": "department_restricted"})
    if not within_opening_hours(slot, room.open_time, room.close_time, tz):
        reasons.append({"code": "outside_opening_hours"})
    return reasons


def evaluate(
    session: Session,
    pairs: list[tuple[Seat, Room]],
    slot: Slot,
    user: CurrentUser,
    tz: ZoneInfo,
) -> list[SeatAvailability]:
    reserved = repository.reserved_seat_ids(session, (seat.id for seat, _ in pairs), slot)
    restrictions = repository.restrictions_in_effect(
        session, {room.id for _, room in pairs}, slot.start_at, slot.end_at
    )
    results = []
    for seat, room in pairs:
        reasons = static_blockers(seat, room, slot, user, tz)
        if seat.id in reserved:
            reasons.append({"code": "reserved"})
        # Every source is listed: lifting one leaves the seat blocked by the others.
        for r in restrictions:
            if r.room_id == room.id and r.seat_id in (None, seat.id):
                reasons.append({"code": r.source_type, "source_type": r.source_type, "source_id": r.source_id})
        results.append(SeatAvailability(seat=seat, room=room, reasons=reasons))
    return results
