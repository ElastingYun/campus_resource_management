"""Caller identity and permission checks for M1 endpoints.

Authentication belongs to C (backend/app/common/auth/). Until it is integrated,
the only identity source is the "dev-headers" mode, which trusts X-Dev-* request
headers and must never be enabled outside local development and tests. M1 code
depends only on CurrentUser, so C can replace get_current_user without touching
business logic.
"""

import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.modules.m1_reservation.errors import M1Error

PERM_RESERVE = "m1:reservation:use"
PERM_CHECKIN_CODE_VIEW = "m1:checkin_code:view"
PERM_OPS_VIEW = "m1:ops:view"
PERM_SETTINGS_MANAGE = "m1:settings:manage"

_USER_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@dataclass(frozen=True)
class CurrentUser:
    id: str
    department_id: str | None
    permissions: frozenset[str]

    def has(self, permission: str) -> bool:
        return permission in self.permissions


def get_current_user(request: Request) -> CurrentUser:
    if request.app.state.config.auth_mode != "dev-headers":
        raise M1Error(401, "unauthenticated", "认证服务尚未接入，当前不接受任何身份")
    user_id = request.headers.get("X-Dev-User-Id", "")
    if not _USER_ID.fullmatch(user_id):
        raise M1Error(401, "unauthenticated", "缺少或无效的用户身份")
    department = request.headers.get("X-Dev-Department") or None
    raw = request.headers.get("X-Dev-Permissions", "")
    permissions = frozenset(p.strip() for p in raw.split(",") if p.strip())
    return CurrentUser(id=user_id, department_id=department, permissions=permissions)


def require(permission: str):
    def dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if not user.has(permission):
            raise M1Error(403, "forbidden", "没有执行该操作的权限", {"required": permission})
        return user

    return dependency
