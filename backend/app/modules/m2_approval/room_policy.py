"""The owner-approved campus/department rule on public resource metadata."""

from app.modules.m2_approval.domain import Room


def validate_access_metadata(room: Room) -> None:
    if type(room.enabled) is not bool or room.access_scope not in ("campus", "department"):
        raise ValueError("Resource access metadata is missing or invalid")
    department = room.department_id
    if department is not None and (
        not isinstance(department, str)
        or not 1 <= len(department) <= 64
        or department != department.strip()
    ):
        raise ValueError("Resource department metadata is invalid")
    if room.access_scope == "department" and department is None:
        raise ValueError("Department-scoped resource needs a department")


def room_is_eligible(room: Room, department_id: str) -> bool:
    validate_access_metadata(room)
    return room.enabled and (room.access_scope == "campus" or room.department_id == department_id)
