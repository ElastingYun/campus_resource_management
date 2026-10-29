"""Ordinary room choices: an explicitly authorized, server-filtered read port."""

from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.modules.resources.contracts import ResourceError
from app.modules.resources.tables import rooms


@dataclass(frozen=True)
class RoomOptionsActor:
    """C constructs this from a current principal, never browser department/role data.

    can_choose is distinct from management read. No room scope or role name grants
    this capability implicitly. A missing department allows campus choices only.
    """

    subject: str
    can_choose: bool = False
    department_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise ValueError("A trusted subject is required")
        if type(self.can_choose) is not bool:
            raise ValueError("An explicit choice capability is required")
        if self.department_id is not None and (
            not isinstance(self.department_id, str)
            or not 1 <= len(self.department_id) <= 64
            or self.department_id.strip() != self.department_id
            or not self.department_id.strip()
        ):
            raise ValueError("Invalid trusted department")


class RoomOption(BaseModel):
    id: str
    code: str
    name: str
    location: str


class RoomOptionsPage(BaseModel):
    items: list[RoomOption]
    total: int
    limit: int
    offset: int


def get_room_options_actor() -> RoomOptionsActor:
    raise ResourceError(503, "identity_unconfigured", "普通教室目录身份与权限尚未接入")


def list_room_options(session: Session, actor: RoomOptionsActor, q: str, limit: int, offset: int):
    if not actor.can_choose:
        raise ResourceError(403, "forbidden", "没有选择教室的权限")
    # Both eligibility and literal search run before count/limit/offset. The
    # browser never receives other departments' or disabled management rows.
    eligible = rooms.c.access_scope == "campus"
    if actor.department_id is not None:
        eligible = or_(
            eligible,
            and_(
                rooms.c.access_scope == "department",
                rooms.c.department_id == actor.department_id,
            ),
        )
    query = select(rooms.c.id, rooms.c.code, rooms.c.name, rooms.c.location).where(
        rooms.c.enabled.is_(True), eligible
    )
    if q:
        query = query.where(
            or_(
                *(
                    func.lower(rooms.c[key]).contains(q.lower(), autoescape=True)
                    for key in ("code", "name", "location")
                )
            )
        )
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.execute(query.order_by(rooms.c.id).limit(limit).offset(offset)).mappings()
    return {
        "items": [{**row, "id": str(row["id"])} for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
