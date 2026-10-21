import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable
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
        if (self.session_ttl.total_seconds() <= 0 or
                self.attempt_window.total_seconds() <= 0 or self.max_attempts < 1):
            raise ValueError("Authentication limits must be explicitly positive")


class AuthService:
    def __init__(self, database: Database, audit: AuditService,
                 settings: AuthSettings, clock: Callable = utcnow):
        self.database, self.audit, self.settings, self.clock = database, audit, settings, clock
        self.hasher = PasswordHasher()
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
        return Principal(user_id, user["department_id"],
                         frozenset(row["name"] for row in roles),
                         frozenset(p for row in roles for p in row["permissions"]),
                         frozenset(user["room_ids"]), user["all_rooms"])

    def login(self, username: str, password: str, *, client_key: str, request_id: str):
        now = aware(self.clock())
        # Account and client buckets bound guessing without retaining raw addresses.
        keys = sorted(["account:" + digest(username), "client:" + digest(client_key)])
        failure = None
        result = None
        with self.database.transaction() as conn:
            for key in keys:
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
                conn.execute(
                    """INSERT INTO c_login_buckets (key, started_at, attempts)
                       VALUES (%s,%s,0) ON CONFLICT (key) DO NOTHING""", (key, now),
                )
                conn.execute(
                    """UPDATE c_login_buckets SET attempts=0, started_at=%s
                       WHERE key=%s AND started_at <= %s""",
                    (now, key, now - self.settings.attempt_window),
                )
            buckets = conn.execute(
                "SELECT attempts FROM c_login_buckets WHERE key=ANY(%s)", (keys,),
            ).fetchall()
            if any(row["attempts"] >= self.settings.max_attempts for row in buckets):
                failure = ServiceError(429, "LOGIN_RATE_LIMIT", "登录尝试过于频繁")
            else:
                conn.execute("UPDATE c_login_buckets SET attempts=attempts+1 WHERE key=ANY(%s)", (keys,))
                user = conn.execute("SELECT * FROM c_users WHERE username=%s", (username,)).fetchone()
                try:
                    valid = self.hasher.verify(user["password_hash"] if user else self._dummy_hash, password)
                except (VerificationError, InvalidHashError):
                    valid = False
                if not user or not user["enabled"] or not valid:
                    failure = ServiceError(401, "INVALID_CREDENTIALS", "账号或密码错误")
                else:
                    token = secrets.token_urlsafe(32)
                    expires = now + self.settings.session_ttl
                    conn.execute(
                        """INSERT INTO c_sessions (token_hash, user_id, expires_at)
                           VALUES (%s,%s,%s)""", (digest(token), user["id"], expires),
                    )
                    result = {"access_token": token, "token_type": "bearer", "expires_at": expires}
            self.audit.record(conn, actor=None, action="auth.login", target="session",
                              result=failure.code if failure else "SUCCESS", now=now,
                              request_id=request_id)
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
                self.audit.record(conn, actor=principal.subject_id, action="auth.logout",
                                  target="session", result="SUCCESS", now=aware(self.clock()),
                                  request_id=request_id)

    def provision_user(self, *, username: str, password: str, department_id: str,
                       roles: dict[str, frozenset[str]], room_ids: frozenset[str],
                       all_rooms: bool = False) -> UUID:
        """Trusted bootstrap API only. Never expose this method as a public route."""
        if not username.strip() or len(username) > 128 or not password or len(password) > 1024:
            raise ValueError("Invalid bootstrap credentials")
        user_id = uuid4()
        password_hash = self.hasher.hash(password)
        with self.database.transaction() as conn:
            for name, permissions in sorted(roles.items()):
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("role:" + name,))
                row = conn.execute("SELECT permissions FROM c_roles WHERE name=%s", (name,)).fetchone()
                if row and set(row["permissions"]) != set(permissions):
                    raise ValueError("Existing role has different permissions")
                conn.execute(
                    "INSERT INTO c_roles (name,permissions) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (name, sorted(permissions)),
                )
            conn.execute(
                """INSERT INTO c_users
                   (id,username,password_hash,department_id,room_ids,all_rooms)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (user_id, username, password_hash, department_id, sorted(room_ids), all_rooms),
            )
            for name in roles:
                conn.execute("INSERT INTO c_user_roles VALUES (%s,%s)", (user_id, name))
            self.audit.record(conn, actor=None, action="auth.provision", target=str(user_id),
                              result="SUCCESS", now=aware(self.clock()), request_id=str(uuid4()))
        return user_id
