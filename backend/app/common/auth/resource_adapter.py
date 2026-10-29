"""Explicit C integration with B's versioned resource ports; no default grants."""

import json
import logging
import re
from dataclasses import fields
from datetime import time
from inspect import signature
from typing import Annotated, Literal, Self
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.common.audit.service import AuditService
from app.common.auth.domain import Principal, ServiceError, aware
from app.common.auth.service import AuthService

logger = logging.getLogger(__name__)
Permission = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
MAX_RESOURCE_ID = 9223372036854775807
ROOM_FIELDS = frozenset(
    {
        "code",
        "name",
        "location",
        "access_scope",
        "department_id",
        "open_time",
        "close_time",
        "enabled",
    }
)
SEAT_FIELDS = frozenset({"code", "outlet_type", "enabled"})


class StrictConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResourcePermissions(StrictConfiguration):
    read: Permission
    manage: Permission
    create_rooms: Permission


class NewRoomPolicy(StrictConfiguration):
    open_time: time
    close_time: time
    access_scope: Literal["campus", "department"]
    department_id: str | None = Field(min_length=1, max_length=64)
    enabled: bool

    @model_validator(mode="after")
    def explicit_creation_policy(self) -> Self:
        if self.open_time.tzinfo or self.close_time.tzinfo or self.open_time >= self.close_time:
            raise ValueError("Opening hours must be an explicit same-day local interval")
        if self.access_scope == "department" and not self.department_id:
            raise ValueError("Department access requires an explicit department")
        return self


class ResourceManagementConfiguration(StrictConfiguration):
    permissions: ResourcePermissions
    new_room: NewRoomPolicy | None = None
    room_options_permission: Literal["m2.submit"] | None = None


def resource_scopes(principal: Principal) -> frozenset[int] | None:
    if principal.all_rooms:
        return None
    result = set()
    for identifier in principal.room_ids:
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[1-9][0-9]{0,18}", identifier) is None
            or int(identifier) > MAX_RESOURCE_ID
        ):
            raise ServiceError(403, "RESOURCE_SCOPE_INVALID", "当前资源授权范围尚未正确配置")
        result.add(int(identifier))
    return frozenset(result)


def canonical_uuid(value: str) -> UUID:
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("Invalid trusted identifier")
    identifier = UUID(value)
    if str(identifier) != value:
        raise ValueError("Invalid trusted identifier")
    return identifier


def resource_audit_sink(audit: AuditService, clock):
    def sink(session, mutation):
        if type(mutation.schema_version) is not int or mutation.schema_version != 2:
            raise ValueError("Unsupported resource audit port")
        if mutation.action not in {"room.create", "room.update", "seat.create", "seat.update"}:
            raise ValueError("Unknown resource action")
        for identifier in (mutation.resource_id, mutation.room_id):
            if type(identifier) is not int or not 1 <= identifier <= MAX_RESOURCE_ID:
                raise ValueError("Invalid resource identifier")
        if mutation.action.startswith("room.") and mutation.resource_id != mutation.room_id:
            raise ValueError("A room event must identify its own room scope")
        allowed = ROOM_FIELDS if mutation.action.startswith("room.") else SEAT_FIELDS
        for snapshot, nullable in ((mutation.before, True), (mutation.after, False)):
            if snapshot is None and nullable:
                continue
            if not isinstance(snapshot, str) or len(snapshot) > 65536:
                raise ValueError("Invalid resource audit snapshot")
            value = json.loads(snapshot)
            if not isinstance(value, dict) or not set(value).issubset(allowed):
                raise ValueError("Unexpected resource audit fields")
            if any(isinstance(item, (list, dict)) for item in value.values()):
                raise ValueError("Nested resource audit fields are not supported")
        if mutation.action.endswith(".create") != (mutation.before is None):
            raise ValueError("Invalid resource change boundary")
        actor_id = canonical_uuid(mutation.actor_id)
        request_id = str(canonical_uuid(mutation.request_id))
        audit.record_in_session(
            session,
            actor=actor_id,
            action="resources." + mutation.action,
            target=mutation.action.split(".")[0] + ":" + str(mutation.resource_id),
            result="SUCCESS",
            now=aware(clock()),
            request_id=request_id,
            room_id=str(mutation.room_id),
            before=mutation.before,
            after=mutation.after,
        )

    return sink


def install_resource_management(
    application: FastAPI,
    *,
    auth: AuthService,
    audit: AuditService,
    configuration: ResourceManagementConfiguration,
) -> None:
    """Host explicitly installs this after C middleware and B v2 are available."""
    try:
        from app.modules.resources import create_resources_router
        from app.modules.resources.contracts import (
            NewRoomSettings,
            ResourceActor,
            ResourceError,
            ResourceMutation,
        )
    except ImportError:
        raise RuntimeError("B resource audit port v2 must be installed explicitly") from None
    required = {"request_id", "room_id", "before", "after", "schema_version"}
    port_fields = {field.name: field for field in fields(ResourceMutation)}
    if not required.issubset(port_fields) or port_fields["schema_version"].default != 2:
        raise RuntimeError("B resource audit port v2 is required")
    if (
        getattr(application.state, "c_auth", None) is not auth
        or getattr(application.state, "c_audit", None) is not audit
    ):
        raise ValueError("The matching C request context and audit handlers must be installed")
    if getattr(application.state, "resource_auth_installed", False):
        raise ValueError("Resource identity adapter is already installed")
    if any(
        getattr(route, "path", "").startswith("/api/v1/resources/") for route in application.routes
    ):
        raise ValueError("Resource routes must not already be mounted")
    catalog_actor = None
    if configuration.room_options_permission is not None:
        try:
            from app.modules.resources.catalog import RoomOptionsActor
        except ImportError:
            raise RuntimeError("B room options port must be installed explicitly") from None
        if "room_options_actor_dependency" not in signature(create_resources_router).parameters:
            raise RuntimeError("B room options dependency port is required")
        if not {"subject", "can_choose", "department_id"}.issubset(
            {field.name for field in fields(RoomOptionsActor)}
        ):
            raise RuntimeError("B room options identity port is incompatible")
        catalog_actor = RoomOptionsActor
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
        permissions = configuration.permissions
        return ResourceActor(
            subject=str(principal.subject_id),
            can_read=permissions.read in principal.permissions,
            can_manage=permissions.manage in principal.permissions,
            can_create_rooms=permissions.create_rooms in principal.permissions,
            room_ids=resource_scopes(principal),
        )

    def room_options_actor(principal: Annotated[Principal, Depends(principal_for_request)]):
        try:
            return catalog_actor(
                subject=str(principal.subject_id),
                can_choose=configuration.room_options_permission in principal.permissions,
                department_id=principal.department_id,
            )
        except ValueError:
            raise ServiceError(
                503, "RESOURCE_IDENTITY_UNAVAILABLE", "暂时无法确认教室目录身份"
            ) from None

    async def resource_error(request: Request, exc):
        detail = exc.detail
        if (
            not isinstance(detail, dict)
            or not isinstance(detail.get("code"), str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", detail["code"]) is None
            or not isinstance(detail.get("message"), str)
            or len(detail["message"]) > 512
        ):
            status, code, message = 503, "resource_unavailable", "资源服务暂不可用"
        else:
            status, code, message = exc.status_code, detail["code"], detail["message"]
        try:
            await run_in_threadpool(
                audit.failure,
                actor=request.state.actor_id,
                code="resources." + code,
                request_id=request.state.request_id,
                now=aware(auth.clock()),
            )
        except (psycopg.Error, SQLAlchemyError, ServiceError):
            logger.error(
                json.dumps(
                    {
                        "event": "resources.denied_audit_unavailable",
                        "request_id": request.state.request_id,
                    }
                )
            )
            status, code, message = 503, "audit_unavailable", "暂时无法记录操作，请稍后重试"
        return JSONResponse(
            status_code=status,
            content={
                "detail": {"code": code, "message": message},
                "request_id": request.state.request_id,
            },
            headers={"Cache-Control": "no-store"},
        )

    policy = configuration.new_room
    application.include_router(
        create_resources_router(
            actor_dependency=actor,
            audit_sink=resource_audit_sink(audit, auth.clock),
            new_room_settings=NewRoomSettings(**policy.model_dump()) if policy else None,
            **({"room_options_actor_dependency": room_options_actor} if catalog_actor else {}),
        )
    )
    application.add_exception_handler(ResourceError, resource_error)
    application.state.resource_auth_installed = True
