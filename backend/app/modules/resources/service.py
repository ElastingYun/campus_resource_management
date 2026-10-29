"""Resource operations own their request session's commit/rollback boundary."""

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Table, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.resources.contracts import (
    AuditSink,
    NewRoomSettings,
    ResourceActor,
    ResourceError,
    ResourceMutation,
    RoomCreate,
    RoomPatch,
    SeatCreate,
    SeatPatch,
)
from app.modules.resources.tables import rooms, seats

ROOM_AUDIT_FIELDS = (
    "code",
    "name",
    "location",
    "access_scope",
    "department_id",
    "open_time",
    "close_time",
    "enabled",
)
SEAT_AUDIT_FIELDS = ("code", "outlet_type", "enabled")


def _valid_request_id(value: str | None) -> bool:
    if not isinstance(value, str) or len(value) != 36:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _view(row: Mapping[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(dict(row), sort_keys=True, default=str, ensure_ascii=False)
    result = dict(row)
    result["id"] = str(result["id"])
    if "room_id" in result:
        result["room_id"] = str(result["room_id"])
    result["revision"] = hashlib.sha256(canonical.encode()).hexdigest()
    result.pop("created_at", None)
    result.pop("updated_at", None)
    return result


class ResourceService:
    def __init__(
        self,
        session: Session,
        actor: ResourceActor,
        new_room_settings: NewRoomSettings | None = None,
        audit_sink: AuditSink | None = None,
        request_id: str | None = None,
    ):
        self.session = session
        self.actor = actor
        self.new_room_settings = new_room_settings
        self.audit_sink = audit_sink
        self.request_id = request_id

    def _authorize(self, *, write: bool = False, create: bool = False):
        if not self.actor.subject or not self.actor.can_read:
            raise ResourceError(403, "forbidden", "没有读取资源的权限")
        if write and not self.actor.can_manage:
            raise ResourceError(403, "forbidden", "没有管理资源的权限")
        if create and (not self.actor.can_create_rooms or self.actor.room_ids is not None):
            raise ResourceError(403, "forbidden", "没有新增教室的权限")
        if write and self.audit_sink is None:
            raise ResourceError(503, "audit_unconfigured", "资源审计尚未接入，暂不能修改")
        if write and not _valid_request_id(self.request_id):
            raise ResourceError(503, "audit_context_unconfigured", "资源审计请求上下文尚未接入")

    def _room(self, room_id: int):
        if self.actor.room_ids is not None and room_id not in self.actor.room_ids:
            raise ResourceError(404, "room_not_found", "教室不存在或不可访问")
        row = self.session.execute(select(rooms).where(rooms.c.id == room_id)).mappings().first()
        if row is None:
            raise ResourceError(404, "room_not_found", "教室不存在或不可访问")
        return row

    def list_rooms(self, q: str, limit: int, offset: int):
        self._authorize()
        conditions = []
        if self.actor.room_ids is not None:
            conditions.append(rooms.c.id.in_(self.actor.room_ids))
        if q:
            conditions.append(
                or_(
                    *(
                        func.lower(rooms.c[key]).contains(q.lower(), autoescape=True)
                        for key in ("code", "name", "location")
                    )
                )
            )
        query = select(rooms).where(*conditions)
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = self.session.execute(
            query.order_by(rooms.c.id).limit(limit).offset(offset)
        ).mappings()
        return {
            "items": [_view(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_room(self, room_id: int):
        self._authorize()
        return _view(self._room(room_id))

    def list_seats(self, room_id: int, q: str, outlet_type: str | None, limit: int, offset: int):
        self._authorize()
        self._room(room_id)
        query = select(seats).where(seats.c.room_id == room_id)
        if q:
            query = query.where(func.lower(seats.c.code).contains(q.lower(), autoescape=True))
        if outlet_type is not None:
            query = query.where(seats.c.outlet_type == outlet_type)
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = self.session.execute(
            query.order_by(seats.c.id).limit(limit).offset(offset)
        ).mappings()
        return {
            "items": [_view(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_seat(self, seat_id: int):
        self._authorize()
        row = self.session.execute(select(seats).where(seats.c.id == seat_id)).mappings().first()
        if row is None:
            raise ResourceError(404, "seat_not_found", "座位不存在或不可访问")
        self._room(row["room_id"])
        return _view(row)

    def _write(self, operation: Callable[[], dict[str, Any]]):
        try:
            result = operation()
            self.session.commit()
            return result
        except IntegrityError as error:
            self.session.rollback()
            raise ResourceError(409, "resource_conflict", "编号重复或资源关联已变化") from error
        except ResourceError:
            self.session.rollback()
            raise
        except Exception as error:
            self.session.rollback()
            raise ResourceError(
                503, "resource_unavailable", "资源服务暂不可用，请查询结果后重试"
            ) from error

    def _audit(
        self, action, table: Table, before: Mapping[str, Any] | None, after: Mapping[str, Any]
    ):
        assert self.audit_sink is not None
        assert self.request_id is not None
        fields = ROOM_AUDIT_FIELDS if table is rooms else SEAT_AUDIT_FIELDS
        changed = [key for key in fields if before is None or before[key] != after[key]]

        def snapshot(row):
            if row is None:
                return None
            return json.dumps(
                {key: row[key] for key in changed},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            )

        mutation = ResourceMutation(
            actor_id=self.actor.subject,
            action=action,
            resource_id=after["id"],
            request_id=self.request_id,
            room_id=after["id"] if table is rooms else after["room_id"],
            before=snapshot(before),
            after=snapshot(after),
        )
        try:
            self.audit_sink(self.session, mutation)
        except Exception as error:
            # Audit storage constraints are a dependency failure, not a duplicate
            # room/seat. _write rolls back the same transaction in either case.
            raise ResourceError(
                503, "audit_unavailable", "资源审计暂不可用，请查询结果后重试"
            ) from error

    def create_room(self, data: RoomCreate):
        self._authorize(write=True, create=True)
        policy = self.new_room_settings
        if policy is None:
            raise ResourceError(503, "creation_unconfigured", "教室创建配置尚未确认")

        def operation():
            resource_id = self.session.scalar(
                insert(rooms)
                .values(
                    **data.model_dump(),
                    access_scope=policy.access_scope,
                    department_id=policy.department_id,
                    open_time=policy.open_time,
                    close_time=policy.close_time,
                    enabled=policy.enabled,
                )
                .returning(rooms.c.id)
            )
            row = self._room(resource_id)
            self._audit("room.create", rooms, None, row)
            return _view(row)

        return self._write(operation)

    def create_seat(self, room_id: int, data: SeatCreate):
        self._authorize(write=True)

        def operation():
            self._room(room_id)
            resource_id = self.session.scalar(
                insert(seats)
                .values(**data.model_dump(), room_id=room_id, enabled=True)
                .returning(seats.c.id)
            )
            row = (
                self.session.execute(select(seats).where(seats.c.id == resource_id))
                .mappings()
                .one()
            )
            self._audit("seat.create", seats, None, row)
            return _view(row)

        return self._write(operation)

    def _patch(self, table: Table, resource_id: int, data: RoomPatch | SeatPatch, action):
        self._authorize(write=True)

        def operation():
            row = (
                self.session.execute(
                    select(table).where(table.c.id == resource_id).with_for_update()
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ResourceError(404, "resource_not_found", "资源不存在或不可访问")
            self._room(resource_id if table is rooms else row["room_id"])
            if _view(row)["revision"] != data.expected_revision:
                raise ResourceError(409, "stale_revision", "资料已更新，请重新加载后确认修改")
            changes = data.model_dump(exclude_unset=True, exclude={"expected_revision"})
            self.session.execute(
                update(table)
                .where(table.c.id == resource_id)
                .values(**changes, updated_at=datetime.now(UTC))
            )
            after = (
                self.session.execute(select(table).where(table.c.id == resource_id))
                .mappings()
                .one()
            )
            self._audit(action, table, row, after)
            return _view(after)

        return self._write(operation)

    def update_room(self, room_id: int, data: RoomPatch):
        return self._patch(rooms, room_id, data, "room.update")

    def update_seat(self, seat_id: int, data: SeatPatch):
        return self._patch(seats, seat_id, data, "seat.update")


def safe_read(operation: Callable[[], Any]):
    try:
        return operation()
    except SQLAlchemyError as error:
        raise ResourceError(503, "resource_unavailable", "资源服务暂不可用") from error
