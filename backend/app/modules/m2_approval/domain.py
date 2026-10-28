from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from app.common.auth.domain import ServiceError


@dataclass(frozen=True)
class Room:
    id: str
    department_id: str
    enabled: bool


class ResourceGateway(Protocol):
    def get_room(self, room_id: str) -> Room: ...


@dataclass(frozen=True)
class Step:
    permission: str
    timeout: timedelta

    def __post_init__(self):
        if not self.permission or self.timeout.total_seconds() <= 0:
            raise ValueError("Each review step needs a permission and a positive deadline")


@dataclass(frozen=True)
class Workflow:
    version: str
    steps: tuple[Step, ...]
    allow_self_review: bool
    deadline_inclusive: bool
    require_rejection_reason: bool
    allow_revocation: bool

    def __post_init__(self):
        if not self.version or not self.steps:
            raise ValueError("A versioned, nonempty workflow must be supplied by the host")
        if not all(isinstance(step, Step) for step in self.steps):
            raise TypeError("Workflow steps must be validated Step objects")
        flags = (
            self.allow_self_review,
            self.deadline_inclusive,
            self.require_rejection_reason,
            self.allow_revocation,
        )
        if any(type(flag) is not bool for flag in flags):
            raise TypeError("Workflow flags must be booleans, not truthy configuration strings")


def clean_text(value: str, name: str, maximum: int, *, required: bool = True) -> str:
    value = value.strip()
    if (
        len(value) > maximum
        or (required and not value)
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise ServiceError(422, "INVALID_INPUT", f"{name}不合法")
    return value
