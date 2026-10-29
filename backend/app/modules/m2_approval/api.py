"""Mountable C-owned API. No global app, credentials or business policy at import."""

import json
import logging
from typing import Annotated, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
)
from sqlalchemy.exc import SQLAlchemyError

from app.common.audit.service import AuditService
from app.common.auth.domain import Principal, ServiceError, aware
from app.common.auth.service import AuthService
from app.modules.m2_approval.service import ApprovalService

logger = logging.getLogger(__name__)
Text128 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    username: Text128
    password: SecretStr = Field(min_length=1, max_length=1024)


class Submission(Input):
    room_id: Text128
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    purpose: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Decision(Input):
    decision: Literal["APPROVE", "REJECT"]
    comment: str = Field(default="", max_length=2000)
    expected_version: int = Field(strict=True, ge=1)


class Revocation(Input):
    expected_version: int = Field(strict=True, ge=1)


class AccessChange(Input):
    role_names: list[Text128] = Field(max_length=50)
    room_ids: list[Text128] = Field(max_length=1000)
    all_rooms: bool = Field(strict=True)
    enabled: bool = Field(strict=True)


class ApplicationView(BaseModel):
    id: UUID
    applicant_id: UUID
    room_id: str
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    purpose: str
    review_status: str
    integration_status: str
    step_index: int
    step_count: int
    deadline: AwareDatetime
    version: int
    revoked: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime
    effective: bool


class ActionView(BaseModel):
    application_id: UUID
    version: int
    allowed_actions: list[Literal["APPROVE", "REJECT", "REVOKE"]]


class SessionView(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"]
    expires_at: AwareDatetime


class ScopeView(BaseModel):
    room_ids: list[str]
    all_rooms: bool


class IdentityView(BaseModel):
    subject_id: UUID
    department_id: str
    roles: list[str]
    permissions: list[str]
    data_scopes: ScopeView


class AccessView(BaseModel):
    subject_id: UUID
    role_names: list[str]
    room_ids: list[str]
    all_rooms: bool
    enabled: bool


class DecisionView(BaseModel):
    id: UUID
    step_index: int
    actor_id: UUID
    decision: Literal["APPROVE", "REJECT"]
    comment: str
    occurred_at: AwareDatetime


class AuditChanges(BaseModel):
    before: str | None
    after: str | None


class AuditView(BaseModel):
    id: UUID
    actor_id: UUID | None
    action: str
    target: str
    result: str
    occurred_at: AwareDatetime
    request_id: str
    room_id: str | None
    changes: AuditChanges


class FieldError(BaseModel):
    location: list[str | int]
    type: str


class ErrorDetail(BaseModel):
    code: str
    message: str | None = None
    fields: list[FieldError] = Field(default_factory=list)


class ErrorView(BaseModel):
    request_id: UUID
    error: ErrorDetail


ERROR_RESPONSES = {
    status: {"model": ErrorView, "description": description}
    for status, description in {
        401: "A valid Bearer session is required",
        403: "Operation or object scope denied",
        404: "Object absent or not visible",
        409: "Version, state or idempotency conflict",
        422: "Invalid request fields or business input",
        429: "Login attempt limit exceeded",
        503: "Database, audit or required dependency unavailable",
    }.items()
}


def install(
    app: FastAPI, *, auth: AuthService, approval: ApprovalService, audit: AuditService
) -> None:
    """Host explicitly opts into these routes, middleware and error handlers."""
    router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)
    bearer = HTTPBearer(auto_error=False)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        request.state.actor_id = None
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    def error_response(request, status, code, message):
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": code, "message": message},
                "request_id": request.state.request_id,
            },
            headers={"Cache-Control": "no-store", "WWW-Authenticate": "Bearer"}
            if status == 401
            else {"Cache-Control": "no-store"},
        )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        # The service transaction has already rolled back. Do not log request input.
        try:
            from starlette.concurrency import run_in_threadpool

            await run_in_threadpool(
                audit.failure,
                actor=request.state.actor_id,
                code=exc.code,
                request_id=request.state.request_id,
                now=aware(auth.clock()),
            )
        except (psycopg.Error, SQLAlchemyError, ServiceError):
            logger.error(
                json.dumps(
                    {
                        "event": "audit.unavailable",
                        "request_id": request.state.request_id,
                    }
                )
            )
            return error_response(request, 503, "AUDIT_UNAVAILABLE", "暂时无法记录操作，请稍后重试")
        logger.info(
            json.dumps(
                {
                    "event": "request.denied",
                    "code": exc.code,
                    "request_id": request.state.request_id,
                }
            )
        )
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Default validation responses may echo password or request-body input.
        denied = await service_error(request, ServiceError(422, "INVALID_INPUT", "请求字段不合法"))
        if denied.status_code != 422:
            return denied
        fields = [{"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "INVALID_INPUT", "fields": fields},
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(psycopg.Error)
    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: psycopg.Error):
        logger.error(
            json.dumps(
                {
                    "event": "database.unavailable",
                    "request_id": request.state.request_id,
                }
            )
        )
        return error_response(request, 503, "DATABASE_UNAVAILABLE", "服务暂时不可用")

    def current(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        if credentials is None:
            raise ServiceError(401, "AUTHENTICATION_REQUIRED", "请先登录")
        principal = auth.authenticate(credentials.credentials)
        request.state.actor_id = principal.subject_id
        request.state.token = credentials.credentials
        return principal

    Current = Annotated[Principal, Depends(current)]

    @router.post("/auth/sessions", response_model=SessionView, tags=["identity"])
    def login(body: Login, request: Request):
        return auth.login(
            body.username,
            body.password.get_secret_value(),
            client_key=request.client.host if request.client else "unknown",
            request_id=request.state.request_id,
        )

    @router.delete("/auth/sessions/current", status_code=204, tags=["identity"])
    def logout(request: Request, principal: Current):
        auth.logout(request.state.token, principal, request.state.request_id)
        return Response(status_code=204)

    @router.get("/auth/me", response_model=IdentityView, tags=["identity"])
    def me(principal: Current):
        return {
            "subject_id": principal.subject_id,
            "department_id": principal.department_id,
            "roles": sorted(principal.roles),
            "permissions": sorted(principal.permissions),
            "data_scopes": {
                "room_ids": sorted(principal.room_ids),
                "all_rooms": principal.all_rooms,
            },
        }

    @router.post(
        "/m2/applications",
        response_model=ApplicationView,
        status_code=201,
        tags=["approval"],
    )
    def submit(body: Submission, request: Request, key: Key, principal: Current):
        return approval.submit(
            principal, **body.model_dump(), key=key, request_id=request.state.request_id
        )

    @router.put("/auth/users/{user_id}/access", response_model=AccessView, tags=["identity"])
    def access(user_id: UUID, body: AccessChange, request: Request, principal: Current):
        return auth.change_access(
            principal, user_id, **body.model_dump(), request_id=request.state.request_id
        )

    @router.get("/m2/applications", response_model=list[ApplicationView], tags=["approval"])
    def applications(
        principal: Current,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        return approval.list_applications(principal, limit=limit, offset=offset)

    @router.get("/m2/review-tasks", response_model=list[ApplicationView], tags=["approval"])
    def review_tasks(
        principal: Current,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        principal.require("m2.review")
        return approval.list_applications(principal, limit=limit, offset=offset, tasks_only=True)

    @router.get(
        "/m2/applications/{application_id}",
        response_model=ApplicationView,
        tags=["approval"],
    )
    def application(application_id: UUID, principal: Current):
        return approval.get(principal, application_id)

    @router.get(
        "/m2/applications/{application_id}/history",
        response_model=list[DecisionView],
        tags=["approval"],
    )
    def history(application_id: UUID, principal: Current):
        return jsonable_encoder(approval.history(principal, application_id))

    @router.get(
        "/m2/applications/{application_id}/actions", response_model=ActionView, tags=["approval"]
    )
    def actions(application_id: UUID, principal: Current):
        return approval.actions(principal, application_id)

    @router.post(
        "/m2/applications/{application_id}/decisions",
        response_model=ApplicationView,
        tags=["approval"],
    )
    def decide(
        application_id: UUID,
        body: Decision,
        request: Request,
        key: Key,
        principal: Current,
    ):
        return approval.decide(
            principal,
            application_id,
            **body.model_dump(),
            key=key,
            request_id=request.state.request_id,
        )

    @router.post(
        "/m2/applications/{application_id}/revocations",
        response_model=ApplicationView,
        tags=["approval"],
    )
    def revoke(
        application_id: UUID,
        body: Revocation,
        request: Request,
        key: Key,
        principal: Current,
    ):
        return approval.revoke(
            principal,
            application_id,
            **body.model_dump(),
            key=key,
            request_id=request.state.request_id,
        )

    @router.get("/audit/events", response_model=list[AuditView], tags=["audit"])
    def events(
        principal: Current,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        return jsonable_encoder(audit.list_events(principal, limit=limit, offset=offset))

    app.include_router(router)
    app.state.c_auth = auth
    app.state.c_audit = audit


def create_app(
    *, auth: AuthService, approval: ApprovalService, audit: AuditService, lifespan=None
) -> FastAPI:
    app = FastAPI(title="Classroom approval and identity", version="0.1.0", lifespan=lifespan)
    install(app, auth=auth, approval=approval, audit=audit)
    return app
