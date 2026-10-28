"""Data access for M1: overlap lookups and row locks used by the services."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.resources.models import Room, Seat
from app.modules.m1_reservation.models import ACTIVE_STATUSES, Reservation
from app.modules.m1_reservation.timeslots import Slot


def seats_with_rooms(
    session: Session,
    *,
    room_id: int | None = None,
    seat_id: int | None = None,
    outlet_type: str | None = None,
    has_outlet: bool | None = None,
) -> list[tuple[Seat, Room]]:
    query = select(Seat, Room).join(Room, Seat.room_id == Room.id)
    if room_id is not None:
        query = query.where(Seat.room_id == room_id)
    if seat_id is not None:
        query = query.where(Seat.id == seat_id)
    if outlet_type is not None:
        query = query.where(Seat.outlet_type == outlet_type)
    if has_outlet is True:
        query = query.where(Seat.outlet_type != "none")
    elif has_outlet is False:
        query = query.where(Seat.outlet_type == "none")
    return list(session.execute(query.order_by(Room.code, Seat.code)).tuples())


def reserved_seat_ids(session: Session, seat_ids: Iterable[int], slot: Slot) -> set[int]:
    ids = list(seat_ids)
    if not ids:
        return set()
    query = select(Reservation.seat_id).where(
        Reservation.seat_id.in_(ids),
        Reservation.status.in_(ACTIVE_STATUSES),
        Reservation.start_at < slot.end_at,
        Reservation.end_at > slot.start_at,
    )
    return set(session.scalars(query))
