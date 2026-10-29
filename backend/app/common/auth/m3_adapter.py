"""Opt-in identity and transaction audit for E's published ticket ports."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from app.common.audit.service import AuditService
from app.common.auth.domain import Principal, ServiceError, aware
from app.common.auth.resource_adapter import MAX_RESOURCE_ID, canonical_uuid
from app.common.auth.service import AuthService

Permission = Annotated[str, Field(pattern=r"^m3\.[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$")]


class M3Permissions(BaseModel):
    """The host names capabilities; installing this adapter grants none."""

    model_config = ConfigDict(extra="forbid", strict=True)
    create: Permission
    read_own: Permission


class M3TicketAudit:
    def __init__(self, audit: AuditService, subject_id: UUID):
        self.audit, self.subject_id = audit, subject_id

    def record_created(self, session, *, actor, ticket_id, room_id, request_id, now):
        if canonical_uuid(actor.subject_id) != self.subject_id:
            raise ValueError("Ticket audit actor differs from the authenticated principal")
        canonical_uuid(ticket_id)
        canonical_uuid(request_id)
        if (
            not isinstance(room_id, str)
            or not room_id.isascii()
            or not room_id.isdecimal()
            or room_id.startswith("0")
            or len(room_id) > 19
            or int(room_id) > MAX_RESOURCE_ID
        ):
            raise ValueError("Ticket room ID must be a canonical positive BIGINT")
        self.audit.record_in_session(
            session,
            actor=self.subject_id,
            action="m3.ticket.create",
            target=ticket_id,
            result="SUCCESS",
            now=aware(now),
            request_id=request_id,
            room_id=room_id,
            before=None,
            after="REPORTED",
        )


def install_m3_identity(
    application: FastAPI,
    *,
    auth: AuthService,
    audit: AuditService,
    permissions: M3Permissions,
    room_policy_factory: Callable | None = None,
) -> None:
    """A host supplies an approved room policy bound to this request's Principal.

    Missing room policy keeps creation closed while own-ticket reads can work.
    E still owns its Session and commit; neither schema nor roles are installed.
    """
    try:
        from app.modules.m3_repair.contracts import TicketActor, get_room_policy
        from app.modules.m3_repair.router import create_router
    except ImportError:
        raise RuntimeError(
            "E's reviewed M3 ticket and precommit audit ports are required"
        ) from None
    if (
        getattr(application.state, "c_auth", None) is not auth
        or getattr(application.state, "c_audit", None) is not audit
    ):
        raise ValueError("The matching C request context and audit handlers must be installed")
    if getattr(application.state, "m3_auth_installed", False) or any(
        getattr(route, "path", "").startswith("/api/v1/m3/") for route in application.routes
    ):
        raise ValueError("M3 routes must not already be mounted")
    bearer = HTTPBearer(auto_error=False)

    def principal_for_request(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Principal:
        if credentials is None:
            raise ServiceError(401, "AUTHENTICATION_REQUIRED", "请先登录")
        principal = auth.authenticate(credentials.credentials)
        request.state.actor_id = principal.subject_id
        return principal

    def actor(principal: Annotated[Principal, Depends(principal_for_request)]):
        return TicketActor(
            subject_id=str(principal.subject_id),
            can_create=permissions.create in principal.permissions,
            can_read_own=permissions.read_own in principal.permissions,
        )

    def ticket_audit(principal: Annotated[Principal, Depends(principal_for_request)]):
        return M3TicketAudit(audit, principal.subject_id)

    def room_policy(principal: Annotated[Principal, Depends(principal_for_request)]):
        if room_policy_factory is None:
            return get_room_policy()
        return room_policy_factory(principal)

    application.include_router(
        create_router(
            actor_dependency=actor,
            room_policy_dependency=room_policy,
            audit_dependency=ticket_audit,
        )
    )
    application.state.m3_auth_installed = True
