"""M1 HTTP routes. Routes parse input and authorize; services hold the rules."""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.modules.m1_reservation import availability, repository
from app.modules.m1_reservation.clock import Clock, get_clock
from app.modules.m1_reservation.errors import M1Error, m1_error_handler
from app.modules.m1_reservation.identity import PERM_RESERVE, CurrentUser, get_current_user, require
from app.modules.m1_reservation.schemas import AvailabilityOut, SeatAvailabilityOut, SettingsOut
from app.modules.m1_reservation.settings import as_dict, load_settings
from app.modules.m1_reservation.timeslots import check_booking_window, make_slot

router = APIRouter(prefix="/api/v1/m1", tags=["m1"])


def business_tz(request: Request) -> ZoneInfo:
    return ZoneInfo(request.app.state.config.business_timezone)


@router.get("/seats/availability", response_model=AvailabilityOut)
def seat_availability(
    start_at: datetime,
    hours: int,
    room_id: int | None = None,
    outlet_type: Literal["none", "fixed", "rail"] | None = None,
    has_outlet: bool | None = None,
    only_available: bool = False,
    user: CurrentUser = Depends(require(PERM_RESERVE)),
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    tz: ZoneInfo = Depends(business_tz),
) -> AvailabilityOut:
    settings = load_settings(session)
    slot = make_slot(start_at, hours, tz, settings)
    check_booking_window(slot, clock.now(), settings)
    pairs = repository.seats_with_rooms(
        session, room_id=room_id, outlet_type=outlet_type, has_outlet=has_outlet
    )
    results = availability.evaluate(session, pairs, slot, user, tz)
    if only_available:
        results = [r for r in results if r.available]
    return AvailabilityOut(
        start_at=slot.start_at.astimezone(tz),
        end_at=slot.end_at.astimezone(tz),
        hours=slot.hours,
        seats=[
            SeatAvailabilityOut(
                seat_id=r.seat.id,
                seat_code=r.seat.code,
                room_id=r.room.id,
                room_code=r.room.code,
                room_name=r.room.name,
                outlet_type=r.seat.outlet_type,
                available=r.available,
                reasons=r.reasons,
            )
            for r in results
        ],
    )


@router.get("/settings", response_model=SettingsOut)
def read_settings(
    _user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> SettingsOut:
    return SettingsOut(**as_dict(load_settings(session)))


def register(app: FastAPI) -> None:
    app.include_router(router)
    app.add_exception_handler(M1Error, m1_error_handler)
