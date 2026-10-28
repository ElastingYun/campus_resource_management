"""M1 HTTP routes. Routes parse input and authorize; services hold the rules."""

from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.modules.m1_reservation import (
    availability,
    checkin,
    ops,
    repository,
    reservations,
    restrictions,
)
from app.modules.m1_reservation import settings as m1_settings
from app.modules.m1_reservation.clock import Clock, get_clock
from app.modules.m1_reservation.errors import M1Error, m1_error_handler
from app.modules.m1_reservation.identity import (
    PERM_CHECKIN_CODE_VIEW,
    PERM_OPS_VIEW,
    PERM_RESERVE,
    PERM_SETTINGS_MANAGE,
    CurrentUser,
    get_current_user,
    require,
)
from app.modules.m1_reservation.models import Reservation, SeatRestriction
from app.modules.m1_reservation.schemas import (
    AvailabilityOut,
    CheckInRequest,
    ReservationCreate,
    ReservationList,
    ReservationOut,
    RestrictionApply,
    RestrictionOut,
    RestrictionRelease,
    RoomCodeOut,
    RoomUsageOut,
    SeatAvailabilityOut,
    SeatEventOut,
    SettingsOut,
    SettingsUpdate,
    UsageOut,
    ViolationOut,
)
from app.modules.m1_reservation.settings import as_dict, load_settings
from app.modules.m1_reservation.timeslots import check_booking_window, make_slot

router = APIRouter(prefix="/api/v1/m1", tags=["m1"])


def business_tz(request: Request) -> ZoneInfo:
    return ZoneInfo(request.app.state.config.business_timezone)


DbSession = Annotated[Session, Depends(get_session)]
AppClock = Annotated[Clock, Depends(get_clock)]
BusinessTz = Annotated[ZoneInfo, Depends(business_tz)]
AnyUser = Annotated[CurrentUser, Depends(get_current_user)]
Student = Annotated[CurrentUser, Depends(require(PERM_RESERVE))]
CheckinCodeViewer = Annotated[CurrentUser, Depends(require(PERM_CHECKIN_CODE_VIEW))]
OpsViewer = Annotated[CurrentUser, Depends(require(PERM_OPS_VIEW))]
SettingsAdmin = Annotated[CurrentUser, Depends(require(PERM_SETTINGS_MANAGE))]


@router.get("/seats/availability", response_model=AvailabilityOut)
def seat_availability(
    start_at: datetime,
    hours: int,
    user: Student,
    session: DbSession,
    clock: AppClock,
    tz: BusinessTz,
    room_id: int | None = None,
    outlet_type: Literal["none", "fixed", "rail"] | None = None,
    has_outlet: bool | None = None,
    only_available: bool = False,
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
    user: Student,
    session: DbSession,
    clock: AppClock,
    tz: BusinessTz,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ] = None,
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
    user: Student,
    session: DbSession,
    tz: BusinessTz,
    status: Literal["booked", "checked_in", "cancelled", "no_show"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReservationList:
    rows = repository.user_reservations(session, user.id, status=status, limit=limit, offset=offset)
    return ReservationList(items=[_to_out(*row, tz) for row in rows], limit=limit, offset=offset)


@router.get("/reservations/{reservation_id}", response_model=ReservationOut)
def get_reservation(
    reservation_id: int,
    user: Student,
    session: DbSession,
    tz: BusinessTz,
) -> ReservationOut:
    found = repository.reservation_with_place(session, reservation_id)
    if found is None or found[0].user_id != user.id:
        raise M1Error(404, "reservation_not_found", "预约不存在")
    return _to_out(*found, tz)


@router.post("/reservations/{reservation_id}/cancel", response_model=ReservationOut)
def cancel_reservation(
    reservation_id: int,
    user: Student,
    session: DbSession,
    clock: AppClock,
    tz: BusinessTz,
) -> ReservationOut:
    reservation = reservations.cancel(session, user, reservation_id, now=clock.now())
    return _reservation_out(session, reservation, tz)


@router.post("/reservations/{reservation_id}/check-in", response_model=ReservationOut)
def check_in(
    reservation_id: int,
    body: CheckInRequest,
    request: Request,
    user: Student,
    session: DbSession,
    clock: AppClock,
    tz: BusinessTz,
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
    _user: CheckinCodeViewer,
    session: DbSession,
    clock: AppClock,
    tz: BusinessTz,
) -> RoomCodeOut:
    """For the room's display terminal or room admins, not for students."""
    result = checkin.room_code(
        session, request.app.state.config.checkin_code_secret, room_id, now=clock.now(), tz=tz
    )
    return RoomCodeOut(
        room_id=result.room_id,
        date=result.day.isoformat(),
        code=result.code,
        valid_until=result.valid_until,
    )


@router.get("/violations/me", response_model=list[ViolationOut])
def my_violations(
    user: Student,
    session: DbSession,
    tz: BusinessTz,
) -> list[ViolationOut]:
    return [
        ViolationOut(
            id=v.id,
            reservation_id=v.reservation_id,
            reason=v.reason,
            occurred_at=v.occurred_at.astimezone(tz),
        )
        for v in repository.user_violations(session, user.id)
    ]


RestrictionSource = Literal["m2_approval", "m3_repair"]


def _restriction_out(
    r: SeatRestriction, tz: ZoneInfo, affected: list[int] | None = None
) -> RestrictionOut:
    def local(value):
        return value.astimezone(tz) if value is not None else None

    return RestrictionOut(
        source_type=r.source_type,
        source_id=r.source_id,
        room_id=r.room_id,
        seat_id=r.seat_id,
        start_at=local(r.start_at),
        end_at=local(r.end_at),
        status=r.status,
        note=r.note,
        created_at=local(r.created_at),
        released_at=local(r.released_at),
        release_reason=r.release_reason,
        affected_reservation_ids=affected,
    )


@router.put(
    "/restrictions/{source_type}/{source_id}", response_model=RestrictionOut, status_code=201
)
def apply_restriction(
    source_type: RestrictionSource,
    source_id: str,
    body: RestrictionApply,
    response: Response,
    user: AnyUser,
    session: DbSession,
    clock: AppClock,
    tz: BusinessTz,
) -> RestrictionOut:
    """Called by M2 when an approval occupies a room, and by M3 when a repair starts."""
    restriction, created, affected = restrictions.apply(
        session,
        user,
        source_type,
        source_id,
        room_id=body.room_id,
        seat_id=body.seat_id,
        start_at=body.start_at,
        end_at=body.end_at,
        note=body.note,
        now=clock.now(),
        tz=tz,
    )
    if not created:
        response.status_code = 200
    return _restriction_out(restriction, tz, affected)


@router.get("/restrictions/{source_type}/{source_id}", response_model=RestrictionOut)
def read_restriction(
    source_type: RestrictionSource,
    source_id: str,
    user: AnyUser,
    session: DbSession,
    tz: BusinessTz,
) -> RestrictionOut:
    """Lets the caller confirm the outcome after a timeout before retrying."""
    return _restriction_out(restrictions.get(session, user, source_type, source_id), tz)


@router.post("/restrictions/{source_type}/{source_id}/release", response_model=RestrictionOut)
def release_restriction(
    source_type: RestrictionSource,
    source_id: str,
    body: RestrictionRelease,
    user: AnyUser,
    session: DbSession,
    clock: AppClock,
    tz: BusinessTz,
) -> RestrictionOut:
    """Called by M2 on rejection/revocation and by M3 when a repair passes acceptance."""
    restriction, _ = restrictions.release(
        session, user, source_type, source_id, reason=body.reason, now=clock.now()
    )
    return _restriction_out(restriction, tz)


@router.get("/settings", response_model=SettingsOut)
def read_settings(
    _user: AnyUser,
    session: DbSession,
) -> SettingsOut:
    return SettingsOut(**as_dict(load_settings(session)))


@router.put("/settings", response_model=SettingsOut)
def update_settings(
    body: SettingsUpdate,
    user: SettingsAdmin,
    session: DbSession,
    clock: AppClock,
) -> SettingsOut:
    changes = body.model_dump(exclude_none=True)
    updated = m1_settings.update(session, changes, actor_id=user.id, now=clock.now())
    return SettingsOut(**as_dict(updated))


@router.get("/ops/usage", response_model=UsageOut)
def usage(
    day: Annotated[date, Query(alias="date")],
    _user: OpsViewer,
    session: DbSession,
    tz: BusinessTz,
) -> UsageOut:
    rooms = [RoomUsageOut(**row) for row in ops.daily_usage(session, day, tz)]
    return UsageOut(date=day.isoformat(), rooms=rooms)


@router.get("/ops/seat-events", response_model=list[SeatEventOut])
def seat_events(
    room_id: int,
    _user: OpsViewer,
    session: DbSession,
    tz: BusinessTz,
    seat_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SeatEventOut]:
    """Where each availability change came from: M1 booking, M2 approval or M3 repair."""
    return [
        SeatEventOut(
            occurred_at=e.occurred_at.astimezone(tz),
            source_type=e.source_type,
            source_id=e.source_id,
            action=e.action,
            room_id=e.room_id,
            seat_id=e.seat_id,
            start_at=e.start_at.astimezone(tz),
            end_at=e.end_at.astimezone(tz) if e.end_at else None,
            actor_id=ops.public_actor(e),
        )
        for e in ops.seat_events(session, room_id, seat_id, limit)
    ]


def register(app: FastAPI) -> None:
    app.include_router(router)
    app.add_exception_handler(M1Error, m1_error_handler)
