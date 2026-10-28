"""M1 HTTP routes. Routes parse input and authorize; services hold the rules."""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.modules.m1_reservation import availability, checkin, repository, reservations
from app.modules.m1_reservation.clock import Clock, get_clock
from app.modules.m1_reservation.errors import M1Error, m1_error_handler
from app.modules.m1_reservation.identity import (
    PERM_CHECKIN_CODE_VIEW,
    PERM_RESERVE,
    CurrentUser,
    get_current_user,
    require,
)
from app.modules.m1_reservation.models import Reservation
from app.modules.m1_reservation.schemas import (
    AvailabilityOut,
    CheckInRequest,
    ReservationCreate,
    ReservationList,
    ReservationOut,
    RoomCodeOut,
    SeatAvailabilityOut,
    SettingsOut,
)
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


def _reservation_out(session: Session, reservation: Reservation, tz: ZoneInfo) -> ReservationOut:
    found = repository.reservation_with_place(session, reservation.id)
    assert found is not None
    return _to_out(*found, tz)


def _to_out(reservation, seat, room, tz: ZoneInfo) -> ReservationOut:
    def local(value):
        return value.astimezone(tz) if value is not None else None

    return ReservationOut(
        id=reservation.id,
        seat_id=seat.id,
        seat_code=seat.code,
        room_id=room.id,
        room_code=room.code,
        room_name=room.name,
        start_at=local(reservation.start_at),
        end_at=local(reservation.end_at),
        status=reservation.status,
        checked_in_at=local(reservation.checked_in_at),
        cancelled_at=local(reservation.cancelled_at),
        cancel_reason=reservation.cancel_reason,
        created_at=local(reservation.created_at),
    )


@router.post("/reservations", response_model=ReservationOut, status_code=201)
def create_reservation(
    body: ReservationCreate,
    response: Response,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=128
    ),
    user: CurrentUser = Depends(require(PERM_RESERVE)),
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    tz: ZoneInfo = Depends(business_tz),
) -> ReservationOut:
    reservation, created = reservations.create(
        session,
        user,
        seat_id=body.seat_id,
        start_at=body.start_at,
        hours=body.hours,
        idempotency_key=idempotency_key,
        now=clock.now(),
        tz=tz,
    )
    if not created:
        response.status_code = 200
    return _reservation_out(session, reservation, tz)


@router.get("/reservations/me", response_model=ReservationList)
def my_reservations(
    status: Literal["booked", "checked_in", "cancelled", "no_show"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require(PERM_RESERVE)),
    session: Session = Depends(get_session),
    tz: ZoneInfo = Depends(business_tz),
) -> ReservationList:
    rows = repository.user_reservations(session, user.id, status=status, limit=limit, offset=offset)
    return ReservationList(items=[_to_out(*row, tz) for row in rows], limit=limit, offset=offset)


@router.get("/reservations/{reservation_id}", response_model=ReservationOut)
def get_reservation(
    reservation_id: int,
    user: CurrentUser = Depends(require(PERM_RESERVE)),
    session: Session = Depends(get_session),
    tz: ZoneInfo = Depends(business_tz),
) -> ReservationOut:
    found = repository.reservation_with_place(session, reservation_id)
    if found is None or found[0].user_id != user.id:
        raise M1Error(404, "reservation_not_found", "预约不存在")
    return _to_out(*found, tz)


@router.post("/reservations/{reservation_id}/cancel", response_model=ReservationOut)
def cancel_reservation(
    reservation_id: int,
    user: CurrentUser = Depends(require(PERM_RESERVE)),
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    tz: ZoneInfo = Depends(business_tz),
) -> ReservationOut:
    reservation = reservations.cancel(session, user, reservation_id, now=clock.now())
    return _reservation_out(session, reservation, tz)


@router.post("/reservations/{reservation_id}/check-in", response_model=ReservationOut)
def check_in(
    reservation_id: int,
    body: CheckInRequest,
    request: Request,
    user: CurrentUser = Depends(require(PERM_RESERVE)),
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    tz: ZoneInfo = Depends(business_tz),
) -> ReservationOut:
    reservation = checkin.check_in(
        session,
        user,
        reservation_id,
        body.code,
        now=clock.now(),
        tz=tz,
        secret=request.app.state.config.checkin_code_secret,
    )
    return _reservation_out(session, reservation, tz)


@router.get("/rooms/{room_id}/checkin-code", response_model=RoomCodeOut)
def room_checkin_code(
    room_id: int,
    request: Request,
    _user: CurrentUser = Depends(require(PERM_CHECKIN_CODE_VIEW)),
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    tz: ZoneInfo = Depends(business_tz),
) -> RoomCodeOut:
    """For the room's display terminal or room admins, not for students."""
    result = checkin.room_code(
        session, request.app.state.config.checkin_code_secret, room_id, now=clock.now(), tz=tz
    )
    return RoomCodeOut(
        room_id=result.room_id, date=result.day.isoformat(), code=result.code, valid_until=result.valid_until
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
