"""Recording seat state events; callers commit them with the change itself."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.m1_reservation.models import Reservation, SeatStateEvent


def record(
    session: Session,
    *,
    source_type: str,
    source_id: str,
    action: str,
    room_id: int,
    seat_id: int | None,
    start_at: datetime,
    end_at: datetime | None,
    actor_id: str,
    occurred_at: datetime,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        SeatStateEvent(
            occurred_at=occurred_at,
            source_type=source_type,
            source_id=source_id,
            action=action,
            room_id=room_id,
            seat_id=seat_id,
            start_at=start_at,
            end_at=end_at,
            actor_id=actor_id,
            detail=detail or {},
        )
    )


def record_reservation(
    session: Session, reservation: Reservation, action: str, actor_id: str, occurred_at: datetime
) -> None:
    record(
        session,
        source_type="m1_reservation",
        source_id=str(reservation.id),
        action=action,
        room_id=reservation.room_id,
        seat_id=reservation.seat_id,
        start_at=reservation.start_at,
        end_at=reservation.end_at,
        actor_id=actor_id,
        occurred_at=occurred_at,
    )
