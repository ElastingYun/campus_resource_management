"""Synthetic isolated-CI data and server-only resource session, never startup seed."""

import os
import sys
from datetime import time, timedelta
from pathlib import Path
from uuid import uuid4


def main():
    if (
        os.environ.get("CI") != "true"
        or not os.environ.get("GITHUB_RUN_ID")
        or os.environ.get("CAMPUS_DB_NAME") != "campus_m2_live"
    ):
        raise SystemExit("Requires the dedicated disposable M2 CI database")
    from app.common.audit.service import AuditService
    from app.common.auth.database import Database
    from app.common.auth.service import AuthService, AuthSettings
    from app.config import Settings
    from app.database import build_engine
    from app.modules.m2_approval.settings import ComponentConfiguration
    from app.modules.resources.tables import rooms
    from sqlalchemy import insert

    settings = Settings()
    configuration = ComponentConfiguration.from_file(settings.c_config_file)
    engine = build_engine(settings)
    try:
        rows = [
            {
                "id": index,
                "code": f"CAMPUS-{index:03}",
                "name": f"Synthetic campus room {index:03}",
                "location": "CI campus floor",
                "access_scope": "campus",
                "department_id": None,
                "enabled": True,
                "open_time": time(8),
                "close_time": time(22),
            }
            for index in range(1, 121)
        ]
        rows.extend(
            {
                "id": identifier,
                "code": code,
                "name": name,
                "location": "CI department floor",
                "access_scope": "department",
                "department_id": department,
                "enabled": enabled,
                "open_time": time(8),
                "close_time": time(22),
            }
            for identifier, code, name, department, enabled in (
                (
                    9007199254740993,
                    "OWN-BIGINT",
                    "Synthetic own-department room",
                    "synthetic-department",
                    True,
                ),
                (
                    200,
                    "OTHER-DEPARTMENT",
                    "Synthetic other department",
                    "synthetic-other",
                    True,
                ),
                (
                    201,
                    "DISABLED-ROOM",
                    "Synthetic disabled room",
                    "synthetic-department",
                    False,
                ),
            )
        )
        with engine.begin() as connection:
            connection.execute(insert(rooms), rows)
        database = Database(engine_provider=lambda: engine)
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
        session = service.login(
            "m2-live-resource-reader",
            os.environ["CAMPUS_BOOTSTRAP_PASSWORD"],
            client_key="synthetic-m2-ci-resource-reader",
            request_id=str(uuid4()),
        )
        token_file = Path(os.environ["RUNNER_TEMP"]) / "m2-resource-session"
        token_file.touch(mode=0o600, exist_ok=False)
        token_file.write_text(session["access_token"])
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"::error file=infra/scripts/seed-m2-room-acceptance.py::Synthetic seed failed with {type(error).__name__}",
            file=sys.stderr,
        )
        raise
