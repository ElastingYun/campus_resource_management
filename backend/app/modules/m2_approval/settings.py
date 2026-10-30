"""Explicit deployment policies; no production approval rules are implied."""

from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AuthConfiguration(Configuration):
    session_ttl_seconds: int = Field(gt=0)
    attempt_window_seconds: int = Field(gt=0)
    max_attempts: int = Field(gt=0)


class StepConfiguration(Configuration):
    permission: str = Field(min_length=1, max_length=128)
    timeout_seconds: int = Field(gt=0)


class WorkflowConfiguration(Configuration):
    version: str = Field(min_length=1, max_length=128)
    steps: list[StepConfiguration] = Field(min_length=1, max_length=50)
    allow_self_review: bool
    deadline_inclusive: bool
    require_rejection_reason: bool
    allow_revocation: bool


class SubmissionConfiguration(Configuration):
    timezone: str
    allow_cross_department: bool
    minimum_notice_seconds: int = Field(ge=0)
    time_granularity_seconds: int | None = Field(ge=1, le=86400)
    max_duration_seconds: int | None = Field(gt=0)
    room_access_policy: Literal["legacy", "campus_or_own_department"] = "legacy"

    @model_validator(mode="after")
    def approved_scope_does_not_allow_other_departments(self) -> Self:
        if self.room_access_policy == "campus_or_own_department" and self.allow_cross_department:
            raise ValueError("The approved room policy cannot allow cross-department applications")
        return self

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown policy timezone") from exc
        return value

    @field_validator("time_granularity_seconds")
    @classmethod
    def valid_granularity(cls, value: int | None) -> int | None:
        if value is not None and 86400 % value:
            raise ValueError("Time granularity must divide a policy day")
        return value


class EndpointConfiguration(Configuration):
    base_url: AnyHttpUrl
    token_env: str = Field(pattern=r"^CAMPUS_[A-Z0-9_]+_TOKEN$")
    timeout_seconds: FiniteFloat = Field(gt=0, le=60)

    @field_validator("base_url")
    @classmethod
    def no_embedded_secrets(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("Service URLs cannot contain credentials, query or fragment")
        return value


class ResourceConfiguration(EndpointConfiguration):
    room_path: str = Field(min_length=1)

    @field_validator("room_path")
    @classmethod
    def room_template(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value.startswith("//")
            or "{room_id}" not in value
            or "://" in value
        ):
            raise ValueError("Room path must be a relative absolute-path template")
        return value


class M1Configuration(EndpointConfiguration):
    apply_path: str = Field(min_length=1)
    release_path: str = Field(min_length=1)
    query_path: str = Field(min_length=1)
    lease_seconds: FiniteFloat = Field(gt=0)
    retry_delay_seconds: FiniteFloat = Field(gt=0)
    max_attempts: int = Field(gt=0)

    @field_validator("apply_path", "release_path", "query_path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//") or "://" in value:
            raise ValueError("Service paths must stay on the configured host")
        return value

    @model_validator(mode="after")
    def valid_delivery(self) -> Self:
        if "{operation_id}" not in self.query_path:
            raise ValueError("M1 result query needs the operation identifier")
        if self.lease_seconds <= self.timeout_seconds * 2:
            raise ValueError("Lease must exceed the bounded query plus write duration")
        return self


class AccessConfiguration(Configuration):
    same_department_only: bool


class ComponentConfiguration(Configuration):
    auth: AuthConfiguration
    workflow: WorkflowConfiguration
    submission: SubmissionConfiguration
    resources: ResourceConfiguration
    m1: M1Configuration | None = None
    access_management: AccessConfiguration | None = None
    scan_interval_seconds: FiniteFloat = Field(gt=0, le=60)
    operations_per_tick: int = Field(ge=1, le=1000)

    @classmethod
    def from_file(cls, path: Path) -> Self:
        try:
            if path.stat().st_size > 262144:
                raise ValueError("Configuration is too large")
            return cls.model_validate_json(path.read_text())
        except (OSError, ValueError):
            # Startup logs must not echo raw configuration or service credentials.
            raise ValueError("Invalid C component configuration file") from None
