"""Room and seat master data.

PROVISIONAL PLACEHOLDER written by A so M1 can be developed and tested. The
owner is B (see docs/architecture/b01-resource-api-draft.md); field names follow
that draft and B may rename or replace them through a reviewed migration. M1
only reads these tables and never writes them.
"""

from datetime import datetime, time

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, String, Time
from sqlalchemy import UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ACCESS_SCOPES = ("campus", "department")
OUTLET_TYPES = ("none", "fixed", "rail")


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("access_scope IN ('campus', 'department')", name="access_scope"),
        CheckConstraint(
            "access_scope = 'campus' OR department_id IS NOT NULL", name="department_scope_has_id"
        ),
        CheckConstraint("open_time < close_time", name="open_before_close"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(200), default="")
    access_scope: Mapped[str] = mapped_column(String(16), default="campus")
    department_id: Mapped[str | None] = mapped_column(String(64))
    # Daily opening hours in the business timezone; same every day for now.
    open_time: Mapped[time] = mapped_column(Time)
    close_time: Mapped[time] = mapped_column(Time)
    # Static configuration only; never the dynamic "bookable now" answer.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Seat(Base):
    __tablename__ = "seats"
    __table_args__ = (
        UniqueConstraint("room_id", "code", name="uq_seats_room_id_code"),
        CheckConstraint("outlet_type IN ('none', 'fixed', 'rail')", name="outlet_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    outlet_type: Mapped[str] = mapped_column(String(16), default="none")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
