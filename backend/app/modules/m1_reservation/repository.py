"""Data access for M1: overlap lookups and row locks used by the services."""

from collections.abc import Iterable

from datetime import datetime

from sqlalchemy import Integer, cast, func, or_, select
from sqlalchemy.orm import Session

from app.common.resources.models import Room, Seat
from app.modules.m1_reservation.models import ACTIVE_STATUSES, Reservation, SeatRestriction, Violation
from app.modules.m1_reservation.timeslots import Slot

# Advisory lock namespaces (first key of the two-int form).
_LOCK_ROOM = 7101
_LOCK_USER = 7102


def lock_user(session: Session, user_id: str) -> None:
    """Serialize one user's bookings so per-user rules hold under concurrency."""
    session.execute(select(func.pg_advisory_xact_lock(_LOCK_USER, func.hashtext(user_id))))


def lock_room_shared(session: Session, room_id: int) -> None:
    """Bookings share the room lock; writers of room-wide restrictions take it exclusively."""
    session.execute(select(func.pg_advisory_xact_lock_shared(_LOCK_ROOM, cast(room_id, Integer))))


def lock_room_exclusive(session: Session, room_id: int) -> None:
    session.execute(select(func.pg_advisory_xact_lock(_LOCK_ROOM, cast(room_id, Integer))))


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


def user_has_overlap(session: Session, user_id: str, slot: Slot) -> bool:
    query = select(Reservation.id).where(
        Reservation.user_id == user_id,
        Reservation.status.in_(ACTIVE_STATUSES),
        Reservation.start_at < slot.end_at,
        Reservation.end_at > slot.start_at,
    )
    return session.scalar(query.limit(1)) is not None


def reservation_for_update(session: Session, reservation_id: int) -> Reservation | None:
    return session.get(Reservation, reservation_id, with_for_update=True)


def user_reservations(
    session: Session, user_id: str, *, status: str | None, limit: int, offset: int
) -> list[tuple[Reservation, Seat, Room]]:
    query = (
        select(Reservation, Seat, Room)
        .join(Seat, Reservation.seat_id == Seat.id)
        .join(Room, Reservation.room_id == Room.id)
        .where(Reservation.user_id == user_id)
    )
    if status is not None:
        query = query.where(Reservation.status == status)
    query = query.order_by(Reservation.start_at.desc(), Reservation.id.desc()).limit(limit).offset(offset)
    return list(session.execute(query).tuples())


def reservation_with_place(session: Session, reservation_id: int) -> tuple[Reservation, Seat, Room] | None:
    query = (
        select(Reservation, Seat, Room)
        .join(Seat, Reservation.seat_id == Seat.id)
        .join(Room, Reservation.room_id == Room.id)
        .where(Reservation.id == reservation_id)
    )
    return session.execute(query).tuples().first()


def user_violations(session: Session, user_id: str) -> list[Violation]:
    query = select(Violation).where(Violation.user_id == user_id).order_by(Violation.occurred_at.desc())
    return list(session.scalars(query))


def restrictions_in_effect(
    session: Session, room_ids: Iterable[int], start_at: datetime, end_at: datetime, *, since: datetime | None = None
) -> list[SeatRestriction]:
    """Restrictions on these rooms overlapping [start_at, end_at).

    Only active ones by default; with `since`, also those released after that
    moment (i.e. still in force at `since`).
    """
    ids = list(room_ids)
    if not ids:
        return []
    in_force = SeatRestriction.status == "active"
    if since is not None:
        in_force = or_(in_force, SeatRestriction.released_at > since)
    query = select(SeatRestriction).where(
        SeatRestriction.room_id.in_(ids),
        in_force,
        SeatRestriction.start_at < end_at,
        or_(SeatRestriction.end_at.is_(None), SeatRestriction.end_at > start_at),
    )
    return list(session.scalars(query.order_by(SeatRestriction.id)))


def active_reservations_under(session: Session, restriction: SeatRestriction) -> list[int]:
    query = select(Reservation.id).where(
        Reservation.room_id == restriction.room_id,
        Reservation.status.in_(ACTIVE_STATUSES),
        Reservation.end_at > restriction.start_at,
    )
    if restriction.end_at is not None:
        query = query.where(Reservation.start_at < restriction.end_at)
    if restriction.seat_id is not None:
        query = query.where(Reservation.seat_id == restriction.seat_id)
    return list(session.scalars(query.order_by(Reservation.id)))


def restriction_by_source(
    session: Session, source_type: str, source_id: str, *, for_update: bool = False
) -> SeatRestriction | None:
    query = select(SeatRestriction).where(
        SeatRestriction.source_type == source_type, SeatRestriction.source_id == source_id
    )
    if for_update:
        query = query.with_for_update()
    return session.scalar(query)
