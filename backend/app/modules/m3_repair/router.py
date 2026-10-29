"""Explicit M3 mounting seam; the bootstrap app does not enable these routes."""

from collections.abc import Callable, Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.modules.m3_repair import assignment, service, work_start
from app.modules.m3_repair.contracts import (
    AssignmentAudit,
    AssignmentPolicy,
    RestrictionConfirmation,
    RoomPolicy,
    TicketActor,
    TicketAudit,
    TicketError,
    WorkStartAudit,
    get_assignment_audit,
    get_assignment_policy,
    get_restriction_confirmation,
    get_room_policy,
    get_ticket_actor,
    get_ticket_audit,
    get_work_start_audit,
)
from app.modules.m3_repair.schemas import (
    AssignmentOut,
    AssignmentRequest,
    TicketCreate,
    TicketOut,
    TicketPage,
    WorkStartOut,
    WorkStartRequest,
)


def get_ticket_session(request: Request) -> Iterator[Session]:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise TicketError(503, "database_unconfigured", "报修数据库尚未接入")
    with Session(engine) as session:
        yield session


def create_router(
    *,
    actor_dependency: Callable = get_ticket_actor,
    room_policy_dependency: Callable = get_room_policy,
    audit_dependency: Callable = get_ticket_audit,
    assignment_policy_dependency: Callable = get_assignment_policy,
    assignment_audit_dependency: Callable = get_assignment_audit,
    restriction_confirmation_dependency: Callable = get_restriction_confirmation,
    work_start_audit_dependency: Callable = get_work_start_audit,
    session_dependency: Callable = get_ticket_session,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/m3", tags=["m3"])
    Actor = Annotated[TicketActor, Depends(actor_dependency)]
    DbSession = Annotated[Session, Depends(session_dependency)]

    @router.post("/tickets", response_model=TicketOut, status_code=201)
    def create(
        data: TicketCreate,
        response: Response,
        actor: Actor,
        room_policy: Annotated[RoomPolicy, Depends(room_policy_dependency)],
        audit: Annotated[TicketAudit, Depends(audit_dependency)],
        session: DbSession,
        idempotency_key: Annotated[str, Header(pattern=r"^[!-~]{1,128}$")],
    ) -> TicketOut:
        ticket, created = service.create_ticket(
            session, actor, room_policy, audit, data, idempotency_key
        )
        if not created:
            response.status_code = 200
        response.headers["Cache-Control"] = "no-store"
        return ticket

    @router.get("/tickets", response_model=TicketPage)
    def list_own(
        response: Response,
        actor: Actor,
        session: DbSession,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> TicketPage:
        response.headers["Cache-Control"] = "no-store"
        return service.list_own_tickets(session, actor, limit, offset)

    @router.get("/tickets/{ticket_id}", response_model=TicketOut)
    def detail(ticket_id: UUID, response: Response, actor: Actor, session: DbSession) -> TicketOut:
        response.headers["Cache-Control"] = "no-store"
        return service.get_own_ticket(session, actor, str(ticket_id))

    @router.post("/tickets/{ticket_id}/assign", response_model=AssignmentOut, status_code=201)
    def assign(
        ticket_id: UUID,
        data: AssignmentRequest,
        response: Response,
        actor: Actor,
        policy: Annotated[AssignmentPolicy, Depends(assignment_policy_dependency)],
        audit: Annotated[AssignmentAudit, Depends(assignment_audit_dependency)],
        session: DbSession,
        operation_id: Annotated[UUID, Header(alias="Operation-Id")],
    ) -> AssignmentOut:
        result, created = assignment.assign_ticket(
            session, actor, policy, audit, str(ticket_id), str(operation_id), data
        )
        if not created:
            response.status_code = 200
        response.headers["Cache-Control"] = "no-store"
        return result

    @router.post("/tickets/{ticket_id}/work-starts", response_model=WorkStartOut, status_code=201)
    def start(
        ticket_id: UUID,
        data: WorkStartRequest,
        response: Response,
        actor: Actor,
        restriction: Annotated[
            RestrictionConfirmation, Depends(restriction_confirmation_dependency)
        ],
        audit: Annotated[WorkStartAudit, Depends(work_start_audit_dependency)],
        session: DbSession,
        operation_id: Annotated[UUID, Header(alias="Operation-Id")],
    ) -> WorkStartOut:
        result, created = work_start.start_work(
            session, actor, restriction, audit, str(ticket_id), str(operation_id), data
        )
        if not created:
            response.status_code = 200
        response.headers["Cache-Control"] = "no-store"
        return result

    return router
