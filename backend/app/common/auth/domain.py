from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ServiceError(422, "TIMEZONE_REQUIRED", "时间必须带时区")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Principal:
    subject_id: UUID
    department_id: str
    roles: frozenset[str]
    permissions: frozenset[str]
    room_ids: frozenset[str]
    all_rooms: bool = False

    def require(self, permission: str, room_id: str | None = None) -> None:
        if permission not in self.permissions:
            raise ServiceError(403, "FORBIDDEN", "无权执行此操作")
        if room_id is not None and not self.covers(room_id):
            raise ServiceError(403, "OUT_OF_SCOPE", "资源不在授权范围内")

    def covers(self, room_id: str) -> bool:
        return self.all_rooms or room_id in self.room_ids
