"""Dedicated CI: current tree, complete migrations and D's actual C/B host.

Only creates/writes/drops a fresh generated database; the configured disposable
CI database is only an admin connection. There is no production URL argument.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from run_frontend_acceptance import free_port, initialize, run_browser, stop


def run() -> int:
    if (
        os.environ.get("CI") != "true"
        or not os.environ.get("GITHUB_RUN_ID")
        or os.environ.get("CAMPUS_DB_NAME") != "campus_b_host_acceptance"
        or os.environ.get("CAMPUS_DB_HOST") != "127.0.0.1"
        or os.environ.get("B_RESOURCE_HOST_ACCEPTANCE") != "1"
    ):
        raise RuntimeError("Requires the dedicated disposable loopback B host CI service")
    root = Path(__file__).resolve().parents[3]
    backend, frontend = root / "backend", root / "frontend"
    sys.path.insert(0, str(backend))

    import httpx
    from alembic.config import Config
    from sqlalchemy import URL, create_engine, text
    from sqlalchemy.pool import NullPool

    from alembic import command
    from app.common.audit.service import AuditService
    from app.common.auth.database import Database
    from app.common.auth.service import AuthService, AuthSettings
    from app.config import Settings

    server = Settings(_env_file=None, c_enabled=False, c_config_file=None)
    assert server.db_password is not None
    name = "b_host_test_" + uuid4().hex
    base = URL.create(
        "postgresql+psycopg",
        username=server.db_user,
        password=server.db_password.get_secret_value(),
        host=server.db_host,
        port=server.db_port,
        database=server.db_name,
    )
    admin = create_engine(base, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    engine = None
    process = None
    created = False
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        created = True
        engine = create_engine(base.set(database=name), poolclass=NullPool)
        cfg = Config(str(backend / "alembic.ini"))
        # Use the actual committed migration graph, never metadata.create_all.
        for _ in range(2):
            with engine.begin() as connection:
                cfg.attributes["connection"] = connection
                command.upgrade(cfg, "head")
        uri = base.set(drivername="postgresql", database=name).render_as_string(hide_password=False)
        initialize(uri, migrated=True)
        print(
            "Current-tree Alembic upgraded twice; synthetic B resources and accounts seeded",
            flush=True,
        )
        database = Database(engine_provider=lambda: engine)
        auth = AuthService(
            database,
            AuditService(database),
            AuthSettings(
                timedelta(minutes=10),
                timedelta(minutes=5),
                100,
            ),
        )
        # Real server-side C session; never written into a frontend variable or log.
        service_session = auth.login(
            "b-service",
            "synthetic-b-resource-password",
            client_key="synthetic-b-host-service",
            request_id=str(uuid4()),
        )["access_token"]
        origin = f"http://127.0.0.1:{free_port()}"
        with tempfile.TemporaryDirectory(prefix="b-shared-host-") as temporary:
            directory = Path(temporary)
            configuration = json.loads(
                (backend / "app/modules/m2_approval/examples/runtime.synthetic.json").read_text()
            )
            configuration["resources"]["base_url"] = origin
            configuration["submission"]["room_access_policy"] = "campus_or_own_department"
            configuration["auth"]["max_attempts"] = 100
            policy = directory / "c-policy.json"
            policy.write_text(json.dumps(configuration))
            host = directory / "resource-policy.json"
            host.write_text(
                json.dumps(
                    {
                        "permissions": {
                            "read": "synthetic.resource.read",
                            "manage": "synthetic.resource.manage",
                            "create_rooms": "synthetic.resource.create",
                        },
                        "room_options_permission": "m2.submit",
                        "new_room": {
                            "open_time": "08:00:00",
                            "close_time": "22:00:00",
                            "access_scope": "campus",
                            "department_id": None,
                            "enabled": True,
                        },
                    }
                )
            )
            environment = dict(os.environ)
            environment.update(
                CAMPUS_DB_NAME=name,
                CAMPUS_C_ENABLED="true",
                CAMPUS_C_CONFIG_FILE=str(policy),
                CAMPUS_RESOURCE_HOST_CONFIG=str(host),
                CAMPUS_RESOURCES_SERVICE_TOKEN=service_session,
                PYTHONPATH=os.pathsep.join((str(root / "infra/runtime"), str(backend))),
            )
            with (directory / "host.log").open("wb") as log:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "m2_resources:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        origin.rsplit(":", 1)[1],
                        "--no-access-log",
                    ],
                    cwd=backend,
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
                with httpx.Client(base_url=origin, trust_env=False, timeout=0.5) as client:
                    for _ in range(150):
                        if process.poll() is not None:
                            raise RuntimeError("Actual C/B host exited before readiness")
                        try:
                            response = client.get("/health/ready")
                            if response.status_code == 200 and response.json().get("scope") == "m2":
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Actual C/B host readiness timed out")
                http_environment = dict(os.environ, VITE_B_RESOURCE_ACCEPTANCE_ORIGIN=origin)
                result = subprocess.run(
                    [
                        "npm",
                        "test",
                        "--",
                        "src/modules/m1-reservation/resources/access.acceptance.test.ts",
                    ],
                    cwd=frontend,
                    env=http_environment,
                    check=False,
                )
                if result.returncode:
                    return result.returncode
                return run_browser(frontend, origin, directory, None, shared_host=True)
    finally:
        stop(process)
        if engine is not None:
            engine.dispose()
        try:
            if created:
                with admin.connect() as connection:
                    connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        finally:
            admin.dispose()


if __name__ == "__main__":
    raise SystemExit(run())
