"""Small E-02 API: report a fault and read one's own reports."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOM_MAX_ID = 9_223_372_036_854_775_807


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    room_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    description: str = Field(min_length=1, max_length=2000)

    @field_validator("room_id")
    @classmethod
    def validate_room_id(cls, value: str) -> str:
        if int(value) > ROOM_MAX_ID:
            raise ValueError("Room ID exceeds BIGINT range")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Description contains control characters")
        return value


class TicketOut(BaseModel):
    id: str
    room_id: str
    description: str
    status: str
    created_at: datetime


class TicketPage(BaseModel):
    items: list[TicketOut]
    limit: int
    offset: int
