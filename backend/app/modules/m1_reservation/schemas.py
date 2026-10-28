"""Request/response models of the M1 public HTTP API (contract: docs/architecture/a-m1-api-v1.md)."""

from datetime import datetime

from pydantic import BaseModel


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
