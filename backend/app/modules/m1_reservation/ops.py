"""Operations views for room/ops administrators: aggregates, not personal records."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.resources.models import Room, Seat
from app.modules.m1_reservation.models import Reservation, SeatStateEvent


def daily_usage(session: Session, day: date, tz: ZoneInfo) -> list[dict]:
    start = datetime.combine(day, time(0), tzinfo=tz)
    end = start + timedelta(days=1)
    hours = func.extract("epoch", Reservation.end_at - Reservation.start_at) / 3600
    stats = session.execute(
        select(
            Reservation.room_id, Reservation.status, func.count(), func.coalesce(func.sum(hours), 0)
        )
        .where(Reservation.start_at >= start, Reservation.start_at < end)
        .group_by(Reservation.room_id, Reservation.status)
    ).all()
    seat_counts = dict(
        session.execute(
            select(Seat.room_id, func.count()).where(Seat.enabled).group_by(Seat.room_id)
        ).all()
    )
    by_room: dict[int, dict[str, tuple[int, float]]] = {}
    for room_id, status, count, total_hours in stats:
        by_room.setdefault(room_id, {})[status] = (count, float(total_hours))

    report = []
    for room in session.scalars(select(Room).order_by(Room.code)):
        counts = by_room.get(room.id, {})
        open_hours = (
            datetime.combine(day, room.close_time) - datetime.combine(day, room.open_time)
        ).total_seconds() / 3600
        capacity = seat_counts.get(room.id, 0) * open_hours
        used = counts.get("checked_in", (0, 0.0))[1]
        report.append(
            {
                "room_id": room.id,
                "room_code": room.code,
                "seat_count": seat_counts.get(room.id, 0),
                "reservations": {
                    s: counts.get(s, (0, 0.0))[0]
                    for s in ("booked", "checked_in", "cancelled", "no_show")
                },
                "checked_in_seat_hours": used,
                "capacity_seat_hours": capacity,
                "utilization": round(used / capacity, 4) if capacity else 0.0,
            }
        )
    return report


def seat_events(
    session: Session, room_id: int, seat_id: int | None, limit: int
) -> list[SeatStateEvent]:
    query = select(SeatStateEvent).where(SeatStateEvent.room_id == room_id)
    if seat_id is not None:
        # Room-wide events (seat_id NULL) affect every seat, so they belong in a seat's trail too.
        query = query.where((SeatStateEvent.seat_id == seat_id) | SeatStateEvent.seat_id.is_(None))
    return list(
        session.scalars(
            query.order_by(SeatStateEvent.occurred_at.desc(), SeatStateEvent.id.desc()).limit(limit)
        )
    )


def public_actor(event: SeatStateEvent) -> str | None:
    """Services and the system are named; students are not shown to ops staff."""
    if event.source_type != "m1_reservation" or event.actor_id.startswith("system:"):
        return event.actor_id
    return None
