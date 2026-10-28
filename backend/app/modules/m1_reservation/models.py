"""M1-owned tables. Other modules must use M1's HTTP API, never these tables."""

from datetime import datetime

from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ACTIVE_STATUSES = ("booked", "checked_in")
SOURCE_TYPES = ("m1_reservation", "m2_approval", "m3_repair")


class Reservation(Base):
    """A personal seat reservation over a half-open interval [start_at, end_at).

    Migration 0002 also adds a GiST exclusion constraint so two active
    reservations can never overlap on the same seat, even under concurrency.
    """

    __tablename__ = "m1_reservations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('booked', 'checked_in', 'cancelled', 'no_show')", name="status"
        ),
        CheckConstraint("start_at < end_at", name="start_before_end"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_m1_reservations_user_idem"),
        Index("ix_m1_reservations_user_start", "user_id", "start_at"),
        Index("ix_m1_reservations_status_start", "status", "start_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64))
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id"))
    # Copied from the seat at booking time so room-wide rules need no join;
    # seats cannot move between rooms (B's draft offers no such operation).
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="booked")
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Setting(Base):
    """Runtime-adjustable M1 parameters; a missing row means the code default."""

    __tablename__ = "m1_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SeatStateEvent(Base):
    """Append-only trail of every change to seat availability and who caused it.

    Written in the same transaction as the change it describes, so the trail
    cannot disagree with the state. source_type says which module wrote it.
    """

    __tablename__ = "m1_seat_state_events"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('m1_reservation', 'm2_approval', 'm3_repair')", name="source_type"
        ),
        Index("ix_m1_seat_state_events_room_time", "room_id", "occurred_at"),
        Index("ix_m1_seat_state_events_source", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    room_id: Mapped[int] = mapped_column(BigInteger)
    seat_id: Mapped[int | None] = mapped_column(BigInteger)  # NULL: whole room
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL: open-ended
    actor_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
