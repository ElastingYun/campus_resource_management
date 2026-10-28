"""C lifecycle integration: shared pool, explicit policy and durable background work."""

import asyncio
import logging
import os
from collections.abc import Mapping
from contextlib import suppress
from datetime import timedelta
from zoneinfo import ZoneInfo

import httpx
import psycopg
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from app.common.audit.service import AuditService
from app.common.auth.database import Database
from app.common.auth.domain import ServiceError
from app.common.auth.service import AuthService, AuthSettings
from app.modules.m2_approval.api import install
from app.modules.m2_approval.clients import HttpM1Gateway, HttpResourceGateway
from app.modules.m2_approval.domain import Step, Workflow
from app.modules.m2_approval.migrate import verify_schema
from app.modules.m2_approval.service import ApprovalService
from app.modules.m2_approval.settings import ComponentConfiguration, EndpointConfiguration
from app.modules.m2_approval.worker import OperationWorker, RetrySettings

logger = logging.getLogger(__name__)


class ComponentRuntime:
    def __init__(
        self,
        application: FastAPI,
        configuration: ComponentConfiguration,
        credentials: Mapping[str, SecretStr | None] | None = None,
    ):
        self.application, self.configuration = application, configuration
        self._credentials = credentials or {}
        self.database = Database(engine_provider=self._engine)
        self.audit = AuditService(self.database)
        auth = configuration.auth
        self.auth = AuthService(
            self.database,
            self.audit,
            AuthSettings(
                timedelta(seconds=auth.session_ttl_seconds),
                timedelta(seconds=auth.attempt_window_seconds),
                auth.max_attempts,
            ),
            access_policy=self._access if configuration.access_management else None,
        )
        self._tokens = {"resources": self._token(configuration.resources)}
        if configuration.m1:
            self._tokens["m1"] = self._token(configuration.m1)
        self.resources = HttpResourceGateway(
            self._client(configuration.resources),
            room_path=configuration.resources.room_path,
            service_token=self._tokens["resources"],
            timeout_seconds=configuration.resources.timeout_seconds,
        )
        flow = configuration.workflow
        self.workflow = Workflow(
            flow.version,
            tuple(Step(s.permission, timedelta(seconds=s.timeout_seconds)) for s in flow.steps),
            flow.allow_self_review,
            flow.deadline_inclusive,
            flow.require_rejection_reason,
            flow.allow_revocation,
        )
        self.approval = ApprovalService(
            self.database,
            self.audit,
            self.resources,
            lambda *_: self.workflow,
            self._submission,
        )
        self.worker = None
        self.gateway = None
        if remote := configuration.m1:
            self.gateway = HttpM1Gateway(
                self._client(remote),
                apply_path=remote.apply_path,
                release_path=remote.release_path,
                query_path=remote.query_path,
                service_token=self._tokens["m1"],
                timeout_seconds=remote.timeout_seconds,
            )
            self.worker = OperationWorker(
                self.database,
                self.audit,
                self.gateway,
                RetrySettings(
                    timedelta(seconds=remote.lease_seconds),
                    timedelta(seconds=remote.retry_delay_seconds),
                    remote.max_attempts,
                ),
            )
        self.task = None
        self.stop_event = None
        self.degraded = False
        install(application, auth=self.auth, approval=self.approval, audit=self.audit)

    def _token(self, endpoint: EndpointConfiguration) -> str:
        if endpoint.token_env in self._credentials:
            secret = self._credentials[endpoint.token_env]
            value = secret.get_secret_value() if secret is not None else ""
        else:
            value = os.environ.get(endpoint.token_env, "")
        if not value or len(value) > 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
            raise ValueError("Configured C service credential is missing or invalid")
        return value

    @staticmethod
    def _client(endpoint: EndpointConfiguration) -> httpx.Client:
        return httpx.Client(
            base_url=str(endpoint.base_url),
            trust_env=False,
            timeout=endpoint.timeout_seconds,
            follow_redirects=False,
        )

    def _engine(self):
        engine = getattr(self.application.state, "engine", None)
        if engine is None:
            raise ServiceError(503, "DATABASE_UNAVAILABLE", "数据库暂时不可用")
        return engine

    def _submission(self, principal, room, starts_at, ends_at, now):
        rules = self.configuration.submission
        if not rules.allow_cross_department and principal.department_id != room.department_id:
            raise ServiceError(403, "DEPARTMENT_DENIED", "不满足该教室的申请资格")
        if starts_at < now + timedelta(seconds=rules.minimum_notice_seconds):
            raise ServiceError(422, "START_TOO_EARLY", "不满足申请提前量要求")
        if rules.max_duration_seconds is not None and ends_at - starts_at > timedelta(
            seconds=rules.max_duration_seconds
        ):
            raise ServiceError(422, "DURATION_EXCEEDED", "申请时长超出配置上限")
        if rules.time_granularity_seconds is not None:
            zone = ZoneInfo(rules.timezone)
            for value in (starts_at, ends_at):
                local = value.astimezone(zone)
                seconds = local.hour * 3600 + local.minute * 60 + local.second
                if local.microsecond or seconds % rules.time_granularity_seconds:
                    raise ServiceError(422, "TIME_GRANULARITY", "申请时段不符合配置粒度")

    def _access(self, actor, target, desired):
        policy = self.configuration.access_management
        if policy.same_department_only and actor.department_id != target["department_id"]:
            return False
        if actor.all_rooms:
            return True
        return (
            not target["all_rooms"]
            and not desired["all_rooms"]
            and set(target["room_ids"]).issubset(actor.room_ids)
            and set(desired["room_ids"]).issubset(actor.room_ids)
        )

    def _tick(self):
        self.approval.expire_due()
        if self.worker:
            for _ in range(self.configuration.operations_per_tick):
                if not self.worker.run_once():
                    break

    async def _run(self):
        while not self.stop_event.is_set():
            try:
                await asyncio.to_thread(self._tick)
            except (psycopg.Error, SQLAlchemyError):
                self.degraded = True
                logger.error('{"event":"c.background_database_unavailable"}')
            except Exception:
                self.degraded = True
                logger.error('{"event":"c.background_failed"}')
                raise
            else:
                self.degraded = False
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self.stop_event.wait(), self.configuration.scan_interval_seconds
                )

    async def start(self):
        if self.resources.client.is_closed:
            self.resources.client = self._client(self.configuration.resources)
        if self.gateway and self.gateway.client.is_closed:
            self.gateway.client = self._client(self.configuration.m1)
        self.degraded = False
        self.stop_event = asyncio.Event()
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.stop_event:
            self.stop_event.set()
        try:
            if self.task:
                await self.task
        finally:
            self.resources.client.close()
            if self.gateway:
                self.gateway.client.close()

    def ready(self) -> bool:
        if self.degraded or self.task is None or self.task.done():
            return False
        try:
            with self.database.transaction() as conn:
                verify_schema(conn)
        except (psycopg.Error, SQLAlchemyError, RuntimeError, ServiceError):
            return False
        return True
