"""Request/response models of the M1 public HTTP API (contract: docs/architecture/a-m1-api-v1.md)."""

from datetime import datetime

from pydantic import BaseModel, Field


class SeatAvailabilityOut(BaseModel):
    seat_id: int
    seat_code: str
    room_id: int
    room_code: str
    room_name: str
    outlet_type: str
    available: bool
    # e.g. {"code": "reserved"}; restriction reasons also carry source_type/source_id.
    reasons: list[dict[str, str]]


class AvailabilityOut(BaseModel):
    start_at: datetime
    end_at: datetime
    hours: int
    seats: list[SeatAvailabilityOut]


class SettingsOut(BaseModel):
    max_hours: int
    booking_horizon_days: int
    remind_before_minutes: int
    late_remind_minutes: int
    no_show_minutes: int
    checkin_open_before_minutes: int


class ReservationCreate(BaseModel):
    seat_id: int
    # Naive values are business-local time; offsets are honoured.
    start_at: datetime
    hours: int


class ReservationOut(BaseModel):
    """What a student may see about their own reservation. Never includes check-in codes."""

    id: int
    seat_id: int
    seat_code: str
    room_id: int
    room_code: str
    room_name: str
    start_at: datetime
    end_at: datetime
    status: str
    checked_in_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime


class ReservationList(BaseModel):
    items: list[ReservationOut]
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class CheckInRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class RoomCodeOut(BaseModel):
    room_id: int
    date: str
    code: str
    valid_until: datetime


class ViolationOut(BaseModel):
    id: int
    reservation_id: int
    reason: str
    occurred_at: datetime


class RestrictionApply(BaseModel):
    room_id: int
    seat_id: int | None = None  # omit to restrict the whole room
    start_at: datetime
    end_at: datetime | None = None  # omit for "until released" (repairs only)
    note: str = Field(default="", max_length=200)


class RestrictionRelease(BaseModel):
    reason: str = Field(min_length=1, max_length=64)


class RestrictionOut(BaseModel):
    source_type: str
    source_id: str
    room_id: int
    seat_id: int | None
    start_at: datetime
    end_at: datetime | None
    status: str
    note: str
    created_at: datetime
    released_at: datetime | None
    release_reason: str | None
    # Active personal reservations overlapping this restriction (apply responses only).
    affected_reservation_ids: list[int] | None = None
