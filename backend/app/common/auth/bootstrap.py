"""Explicit operator-only account setup; never invoked by application startup."""

import argparse
import getpass
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import psycopg
from sqlalchemy.exc import SQLAlchemyError

from app.common.audit.service import AuditService
from app.common.auth.database import Database
from app.common.auth.service import AuthService, AuthSettings
from app.config import Settings
from app.database import build_engine
from app.modules.m2_approval.migrate import verify_schema
from app.modules.m2_approval.settings import ComponentConfiguration


def role_definitions(path: Path, selected: list[str]) -> dict[str, frozenset[str]]:
    if path.stat().st_size > 262144:
        raise ValueError("Role file is too large")
    roles = json.loads(path.read_text())
    if not isinstance(roles, dict) or not 1 <= len(roles) <= 50:
        raise ValueError("Invalid role definitions")
    for name, permissions in roles.items():
        if not isinstance(permissions, list) or len(permissions) > 1000:
            raise ValueError("Invalid permission list")
        for code in (name, *permissions):
            if not isinstance(code, str) or not code.strip() or len(code) > 128:
                raise ValueError("Invalid role or permission code")
            if code != code.strip() or any(ord(c) < 32 for c in code):
                raise ValueError("Invalid role or permission code")
    if not set(selected).issubset(roles):
        raise ValueError("Selected role is not defined")
    return {name: frozenset(roles[name]) for name in selected}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create an explicitly configured C account")
    parser.add_argument("--username", required=True)
    parser.add_argument("--department-id", required=True)
    parser.add_argument("--roles-file", type=Path, required=True)
    parser.add_argument("--role", action="append", required=True)
    parser.add_argument("--room", action="append", default=[])
    parser.add_argument("--all-rooms", action="store_true")
    parser.add_argument(
        "--password-env",
        help="Read a password from this environment variable, never an argument value",
    )
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        if not settings.database_configured or settings.c_config_file is None:
            raise ValueError("Explicit database and C policy configuration required")
        configuration = ComponentConfiguration.from_file(settings.c_config_file)
        roles = role_definitions(args.roles_file, args.role)
        if args.password_env:
            if not args.password_env.startswith("CAMPUS_"):
                raise ValueError(
                    "Bootstrap credential environment variable must use CAMPUS_ prefix"
                )
            password = os.environ.get(args.password_env, "")
        else:
            password = getpass.getpass("Account password: ")
            if password != getpass.getpass("Repeat password: "):
                raise ValueError("Passwords differ")
        if not 12 <= len(password) <= 1024:
            raise ValueError("Password must contain 12 to 1024 characters")
        engine = build_engine(settings)
        try:
            database = Database(engine_provider=lambda: engine)
            with database.transaction() as conn:
                verify_schema(conn)
            auth = configuration.auth
            service = AuthService(
                database,
                AuditService(database),
                AuthSettings(
                    timedelta(seconds=auth.session_ttl_seconds),
                    timedelta(seconds=auth.attempt_window_seconds),
                    auth.max_attempts,
                ),
            )
            user_id = service.provision_user(
                username=args.username,
                password=password,
                department_id=args.department_id,
                roles=roles,
                room_ids=frozenset(args.room),
                all_rooms=args.all_rooms,
            )
        finally:
            engine.dispose()
    except (ValueError, OSError, psycopg.Error, SQLAlchemyError, RuntimeError):
        print(
            "Account setup failed; check explicit configuration and migration state",
            file=sys.stderr,
        )
        return 1
    print(user_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
