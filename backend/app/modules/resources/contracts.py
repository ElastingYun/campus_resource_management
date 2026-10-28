"""Transport contracts and trusted integration ports, not role assignments."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from typing import Annotated, Literal, Self

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

OutletType = Literal["none", "fixed", "rail"]
Code = Annotated[str, Field(min_length=1, max_length=32)]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Location = Annotated[str, Field(min_length=1, max_length=200)]
Revision = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ResourceError(HTTPException):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(status_code=status, detail={"code": code, "message": message})


@dataclass(frozen=True)
class ResourceActor:
    """Constructed by C's trusted adapter, never from browser-supplied identity headers.

    None explicitly grants all-room scope; the default empty set grants no rooms.
    These capabilities do not map a student or administrator role to permissions.
    """

    subject: str
    can_read: bool = False
    can_manage: bool = False
    can_create_rooms: bool = False
    room_ids: frozenset[int] | None = frozenset()


@dataclass(frozen=True)
class NewRoomSettings:
    """Explicit server-side creation policy; no implicit opening/access defaults."""

    open_time: time
    close_time: time
    access_scope: Literal["campus", "department"]
    enabled: bool
    department_id: str | None = None

    def __post_init__(self):
        if self.open_time.tzinfo or self.close_time.tzinfo or self.open_time >= self.close_time:
            raise ValueError("Opening hours must be a same-day, timezone-free interval")
        if self.access_scope not in ("campus", "department"):
            raise ValueError("Unknown access scope")
        if self.access_scope == "department" and not self.department_id:
            raise ValueError("Department scope requires an approved department identifier")
        if self.department_id is not None and not 1 <= len(self.department_id) <= 64:
            raise ValueError("Invalid department identifier")


@dataclass(frozen=True)
class ResourceMutation:
    actor_id: str
    action: Literal["room.create", "room.update", "seat.create", "seat.update"]
    resource_id: int


AuditSink = Callable[[Session, ResourceMutation], None]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class RoomCreate(InputModel):
    code: Code
    name: Name
    location: Location


class SeatCreate(InputModel):
    code: Code
    outlet_type: OutletType


class PatchModel(InputModel):
    expected_revision: Revision

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        changes = self.model_fields_set - {"expected_revision"}
        if not changes or any(getattr(self, field) is None for field in changes):
            raise ValueError("Supply at least one non-null editable field")
        return self


class RoomPatch(PatchModel):
    code: Code | None = None
    name: Name | None = None
    location: Location | None = None


class SeatPatch(PatchModel):
    code: Code | None = None
    outlet_type: OutletType | None = None


class RoomView(BaseModel):
    id: str
    code: str
    name: str
    location: str
    access_scope: str
    department_id: str | None
    open_time: time
    close_time: time
    enabled: bool
    revision: str


class SeatView(BaseModel):
    id: str
    room_id: str
    code: str
    outlet_type: OutletType
    enabled: bool
    revision: str


class RoomPage(BaseModel):
    items: list[RoomView]
    total: int
    limit: int
    offset: int


class SeatPage(BaseModel):
    items: list[SeatView]
    total: int
    limit: int
    offset: int
