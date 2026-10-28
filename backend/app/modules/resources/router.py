"""Explicit mounting seam for D/C; no global route, database or dev identity setup."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.modules.resources.contracts import (
    AuditSink,
    NewRoomSettings,
    OutletType,
    ResourceActor,
    ResourceError,
    RoomCreate,
    RoomPage,
    RoomPatch,
    RoomView,
    SeatCreate,
    SeatPage,
    SeatPatch,
    SeatView,
)
from app.modules.resources.service import ResourceService, safe_read

ResourceId = Annotated[int, Path(ge=1, le=9223372036854775807)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
Search = Annotated[str, Query(max_length=100)]


def get_resource_actor() -> ResourceActor:
    raise ResourceError(503, "identity_unconfigured", "资源身份与权限尚未接入")


def get_resource_session(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise ResourceError(503, "database_unconfigured", "资源数据库尚未接入")
    with Session(engine) as session:
        yield session


def get_resource_request_id(request: Request) -> str | None:
    """Read trusted host middleware state, never X-Request-ID or a request body.

    C's current middleware creates request.state.request_id on the server. A host
    with a different context can inject its own dependency explicitly.
    """
    return getattr(request.state, "request_id", None)


def create_resources_router(
    *,
    actor_dependency: Callable = get_resource_actor,
    session_dependency: Callable = get_resource_session,
    new_room_settings: NewRoomSettings | None = None,
    audit_sink: AuditSink | None = None,
    request_id_dependency: Callable = get_resource_request_id,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/resources", tags=["resources"])

    def service(
        actor: Annotated[ResourceActor, Depends(actor_dependency)],
        session: Annotated[Session, Depends(session_dependency)],
        request_id: Annotated[str | None, Depends(request_id_dependency)],
    ):
        return ResourceService(session, actor, new_room_settings, audit_sink, request_id)

    Service = Annotated[ResourceService, Depends(service)]

    @router.get("/rooms", response_model=RoomPage)
    def list_rooms(
        resources: Service,
        q: Search = "",
        limit: Limit = 20,
        offset: Offset = 0,
    ):
        return safe_read(lambda: resources.list_rooms(q.strip(), limit, offset))

    @router.post("/rooms", response_model=RoomView, status_code=201)
    def create_room(data: RoomCreate, resources: Service):
        return resources.create_room(data)

    @router.get("/rooms/{room_id}", response_model=RoomView)
    def get_room(room_id: ResourceId, resources: Service):
        return safe_read(lambda: resources.get_room(room_id))

    @router.patch("/rooms/{room_id}", response_model=RoomView)
    def update_room(room_id: ResourceId, data: RoomPatch, resources: Service):
        return resources.update_room(room_id, data)

    @router.get("/rooms/{room_id}/seats", response_model=SeatPage)
    def list_seats(
        room_id: ResourceId,
        resources: Service,
        q: Search = "",
        outlet_type: OutletType | None = None,
        limit: Limit = 20,
        offset: Offset = 0,
    ):
        return safe_read(
            lambda: resources.list_seats(room_id, q.strip(), outlet_type, limit, offset)
        )

    @router.post("/rooms/{room_id}/seats", response_model=SeatView, status_code=201)
    def create_seat(room_id: ResourceId, data: SeatCreate, resources: Service):
        return resources.create_seat(room_id, data)

    @router.get("/seats/{seat_id}", response_model=SeatView)
    def get_seat(seat_id: ResourceId, resources: Service):
        return safe_read(lambda: resources.get_seat(seat_id))

    @router.patch("/seats/{seat_id}", response_model=SeatView)
    def update_seat(seat_id: ResourceId, data: SeatPatch, resources: Service):
        return resources.update_seat(seat_id, data)

    return router
