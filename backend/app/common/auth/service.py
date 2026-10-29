import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.common.audit.service import AuditService
from app.common.auth.database import Database
from app.common.auth.domain import Principal, ServiceError, aware, utcnow


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class AuthSettings:
    session_ttl: timedelta
    attempt_window: timedelta
    max_attempts: int

    def __post_init__(self):
        if (
            self.session_ttl.total_seconds() <= 0
            or self.attempt_window.total_seconds() <= 0
            or self.max_attempts < 1
        ):
            raise ValueError("Authentication limits must be explicitly positive")


class AuthService:
    def __init__(
        self,
        database: Database,
        audit: AuditService,
        settings: AuthSettings,
        clock: Callable = utcnow,
        access_policy: Callable | None = None,
    ):
        self.database, self.audit, self.settings, self.clock = (
            database,
            audit,
            settings,
            clock,
        )
        self.hasher = PasswordHasher()
        self.access_policy = access_policy
        self._dummy_hash = self.hasher.hash(secrets.token_urlsafe(32))

    def _principal(self, conn, user_id: UUID) -> Principal:
        user = conn.execute("SELECT * FROM c_users WHERE id=%s AND enabled", (user_id,)).fetchone()
        if not user:
            raise ServiceError(401, "INVALID_SESSION", "身份已失效")
        roles = conn.execute(
            """SELECT r.name, r.permissions FROM c_roles r
               JOIN c_user_roles ur ON ur.role_name=r.name WHERE ur.user_id=%s""",
            (user_id,),
        ).fetchall()
        return Principal(
            user_id,
            user["department_id"],
            frozenset(row["name"] for row in roles),
            frozenset(p for row in roles for p in row["permissions"]),
            frozenset(user["room_ids"]),
            user["all_rooms"],
        )

    def login(self, username: str, password: str, *, client_key: str, request_id: str):
        now = aware(self.clock())
        # Account and client buckets bound guessing without retaining raw addresses.
        # Gate the client before allocating a bucket for an arbitrary username.
        keys = ["client:" + digest(client_key), "account:" + digest(username)]
        failure = None
        result = None
        with self.database.transaction() as conn:
            for key in keys:
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
                conn.execute(
                    """INSERT INTO c_login_buckets (key, started_at, attempts)
                       VALUES (%s,%s,0) ON CONFLICT (key) DO NOTHING""",
                    (key, now),
                )
                conn.execute(
                    """UPDATE c_login_buckets SET attempts=0, started_at=%s
                       WHERE key=%s AND started_at <= %s""",
                    (now, key, now - self.settings.attempt_window),
                )
                bucket = conn.execute(
                    "SELECT attempts FROM c_login_buckets WHERE key=%s", (key,)
                ).fetchone()
                if bucket["attempts"] >= self.settings.max_attempts:
                    failure = ServiceError(429, "LOGIN_RATE_LIMIT", "登录尝试过于频繁")
                    break
                conn.execute(
                    "UPDATE c_login_buckets SET attempts=attempts+1 WHERE key=%s",
                    (key,),
                )
            if failure is None:
                user = conn.execute(
                    "SELECT * FROM c_users WHERE username=%s", (username,)
                ).fetchone()
                try:
                    valid = self.hasher.verify(
                        user["password_hash"] if user else self._dummy_hash, password
                    )
                except (VerificationError, InvalidHashError):
                    valid = False
                if user and user["enabled"] and valid:
                    # Argon2 runs without an account row lock. A concurrent
                    # disable/credential change must invalidate that old result.
                    # Keep this short shared lock through session+audit commit;
                    # account management takes FOR UPDATE before revoking sessions.
                    current = conn.execute(
                        "SELECT enabled,password_hash FROM c_users WHERE id=%s FOR SHARE",
                        (user["id"],),
                    ).fetchone()
                    valid = bool(
                        current
                        and current["enabled"]
                        and secrets.compare_digest(
                            current["password_hash"].encode(), user["password_hash"].encode()
                        )
                    )
                if not user or not user["enabled"] or not valid:
                    failure = ServiceError(401, "INVALID_CREDENTIALS", "账号或密码错误")
                else:
                    token = secrets.token_urlsafe(32)
                    expires = now + self.settings.session_ttl
                    conn.execute(
                        """INSERT INTO c_sessions (token_hash, user_id, expires_at)
                           VALUES (%s,%s,%s)""",
                        (digest(token), user["id"], expires),
                    )
                    result = {
                        "access_token": token,
                        "token_type": "bearer",
                        "expires_at": expires,
                    }
            self.audit.record(
                conn,
                actor=None,
                action="auth.login",
                target="session",
                result=failure.code if failure else "SUCCESS",
                now=now,
                request_id=request_id,
            )
        # Raise only after committing failed-attempt limits and the failure audit.
        if failure:
            raise failure
        return result

    def authenticate(self, token: str) -> Principal:
        now = aware(self.clock())
        if not token or len(token) > 512:
            raise ServiceError(401, "INVALID_SESSION", "身份已失效")
        with self.database.transaction() as conn:
            row = conn.execute(
                """SELECT user_id FROM c_sessions
                   WHERE token_hash=%s AND NOT revoked AND expires_at > %s""",
                (digest(token), now),
            ).fetchone()
            if not row:
                raise ServiceError(401, "INVALID_SESSION", "身份已失效")
            # Permissions and enabled state are loaded live, never from token claims.
            return self._principal(conn, row["user_id"])

    def logout(self, token: str, principal: Principal, request_id: str) -> None:
        with self.database.transaction() as conn:
            row = conn.execute(
                """UPDATE c_sessions SET revoked=true
                   WHERE token_hash=%s AND user_id=%s AND NOT revoked RETURNING user_id""",
                (digest(token), principal.subject_id),
            ).fetchone()
            if row:
                self.audit.record(
                    conn,
                    actor=principal.subject_id,
                    action="auth.logout",
                    target="session",
                    result="SUCCESS",
                    now=aware(self.clock()),
                    request_id=request_id,
                )

    def provision_user(
        self,
        *,
        username: str,
        password: str,
        department_id: str,
        roles: dict[str, frozenset[str]],
        room_ids: frozenset[str],
        all_rooms: bool = False,
    ) -> UUID:
        """Trusted bootstrap API only. Never expose this method as a public route."""
        if not username.strip() or len(username) > 128 or not password or len(password) > 1024:
            raise ValueError("Invalid bootstrap credentials")
        user_id = uuid4()
        password_hash = self.hasher.hash(password)
        with self.database.transaction() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("user:" + username,),
            )
            for name, permissions in sorted(roles.items()):
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ("role:" + name,),
                )
                row = conn.execute(
                    "SELECT permissions FROM c_roles WHERE name=%s", (name,)
                ).fetchone()
                if row and set(row["permissions"]) != set(permissions):
                    raise ValueError("Existing role has different permissions")
                conn.execute(
                    "INSERT INTO c_roles (name,permissions) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (name, sorted(permissions)),
                )
            existing = conn.execute(
                "SELECT * FROM c_users WHERE username=%s", (username,)
            ).fetchone()
            if existing:
                current_roles = conn.execute(
                    "SELECT role_name FROM c_user_roles WHERE user_id=%s",
                    (existing["id"],),
                ).fetchall()
                try:
                    same_password = self.hasher.verify(existing["password_hash"], password)
                except (VerificationError, InvalidHashError):
                    same_password = False
                if (
                    not same_password
                    or not existing["enabled"]
                    or existing["department_id"] != department_id
                    or set(existing["room_ids"]) != set(room_ids)
                    or existing["all_rooms"] != all_rooms
                    or {row["role_name"] for row in current_roles} != set(roles)
                ):
                    raise ValueError("Existing bootstrap user has different configuration")
                return existing["id"]
            conn.execute(
                """INSERT INTO c_users
                   (id,username,password_hash,department_id,room_ids,all_rooms)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (
                    user_id,
                    username,
                    password_hash,
                    department_id,
                    sorted(room_ids),
                    all_rooms,
                ),
            )
            for name in roles:
                conn.execute("INSERT INTO c_user_roles VALUES (%s,%s)", (user_id, name))
            self.audit.record(
                conn,
                actor=None,
                action="auth.provision",
                target=str(user_id),
                result="SUCCESS",
                now=aware(self.clock()),
                request_id=str(uuid4()),
            )
        return user_id

    def change_access(
        self,
        principal: Principal,
        user_id: UUID,
        *,
        role_names: list[str],
        room_ids: list[str],
        all_rooms: bool,
        enabled: bool,
        request_id: str,
    ):
        principal.require("auth.manage")
        if self.access_policy is None:
            raise ServiceError(403, "ACCESS_MANAGEMENT_DISABLED", "尚未配置账号管理范围规则")
        with self.database.transaction() as conn:
            user = conn.execute(
                "SELECT * FROM c_users WHERE id=%s FOR UPDATE", (user_id,)
            ).fetchone()
            if not user:
                raise ServiceError(404, "NOT_FOUND", "用户不存在或不可见")
            roles = conn.execute(
                "SELECT name,permissions FROM c_roles WHERE name=ANY(%s)", (role_names,)
            ).fetchall()
            if {row["name"] for row in roles} != set(role_names):
                raise ServiceError(422, "UNKNOWN_ROLE", "包含未定义的角色")
            delegated = {permission for row in roles for permission in row["permissions"]}
            if not delegated.issubset(principal.permissions):
                raise ServiceError(403, "DELEGATION_FORBIDDEN", "不能授予自身不具备的权限")
            old_roles = [
                row["role_name"]
                for row in conn.execute(
                    "SELECT role_name FROM c_user_roles WHERE user_id=%s",
                    (user_id,),
                ).fetchall()
            ]
            before = {
                "role_names": sorted(old_roles),
                "room_ids": sorted(user["room_ids"]),
                "all_rooms": user["all_rooms"],
                "enabled": user["enabled"],
            }
            after = {
                "role_names": sorted(set(role_names)),
                "room_ids": sorted(set(room_ids)),
                "all_rooms": all_rooms,
                "enabled": enabled,
            }
            target = {
                "subject_id": str(user_id),
                "department_id": user["department_id"],
                **before,
            }
            # Pure host policy must approve both the old target and requested scope.
            if self.access_policy(principal, target, after) is not True:
                raise ServiceError(403, "ACCOUNT_OUT_OF_SCOPE", "账号或授权范围不在管理权限内")
            if before != after:
                conn.execute("DELETE FROM c_user_roles WHERE user_id=%s", (user_id,))
                for name in after["role_names"]:
                    conn.execute("INSERT INTO c_user_roles VALUES (%s,%s)", (user_id, name))
                conn.execute(
                    "UPDATE c_users SET room_ids=%s,all_rooms=%s,enabled=%s WHERE id=%s",
                    (after["room_ids"], all_rooms, enabled, user_id),
                )
                if not enabled:
                    conn.execute(
                        "UPDATE c_sessions SET revoked=true WHERE user_id=%s",
                        (user_id,),
                    )
                self.audit.record(
                    conn,
                    actor=principal.subject_id,
                    action="auth.access_changed",
                    target=str(user_id),
                    result="SUCCESS",
                    now=aware(self.clock()),
                    request_id=request_id,
                    before=json.dumps(before, sort_keys=True),
                    after=json.dumps(after, sort_keys=True),
                )
            return {"subject_id": str(user_id), **after}
