"""Opt-in B frontend -> real C/B HTTP -> disposable PostgreSQL acceptance.

No production DB argument or environment fallback is accepted. pgserver is an
optional local test utility, never an application dependency. The combined source
comes from C's pinned acceptance preparer (see B's accompanying test document).
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import time as clock_time
from datetime import timedelta
from pathlib import Path

C_REVISION = "51b65bfedd87c85cd9295fdeb01b92e9460e7c5c"
B_REVISION = "4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3"


def verify_source(root: Path) -> None:
    manifest = json.loads((root / "acceptance-source-manifest.json").read_text())
    if (manifest["c_revision"], manifest["b_revision"]) != (C_REVISION, B_REVISION):
        raise ValueError("Acceptance requires the documented fixed C/B revisions")
    expected = {
        "backend/app/common/auth/service.py",
        "backend/app/modules/resources/router.py",
        "backend/tests/c_module/resource_acceptance_app.py",
    }
    if not expected.issubset(manifest["sha256"]):
        raise ValueError("Incomplete acceptance source manifest")
    for name, checksum in manifest["sha256"].items():
        path = root / name
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError("Unexpected source path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError("Acceptance source differs from its pinned manifest")


def initialize(uri: str) -> None:
    import psycopg
    from app.common.audit.service import AuditService
    from app.common.auth.database import Database
    from app.common.auth.service import AuthService, AuthSettings
    from app.modules.m2_approval.migrate import migrate
    from sqlalchemy import create_engine, insert, text

    from app.modules.resources.tables import metadata, rooms

    database = Database(uri)
    # C's frozen standalone baseline and B's private test fixture only. This does
    # not claim to migrate or validate the full A/C/E shared Alembic graph.
    migrate(database)
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(uri))
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            for identifier, code in ((1, "B-LOCAL"), (9007199254740993, "B-BIG")):
                connection.execute(
                    insert(rooms).values(
                        id=identifier,
                        code=code,
                        name="合成教室",
                        location="合成测试区域",
                        access_scope="campus",
                        department_id=None,
                        open_time=clock_time(8),
                        close_time=clock_time(22),
                        enabled=True,
                    )
                )
            connection.execute(text("SELECT setval('rooms_id_seq', 2, false)"))
        auth = AuthService(
            database,
            AuditService(database),
            AuthSettings(timedelta(minutes=10), timedelta(minutes=5), 30),
        )
        management = frozenset(
            {"synthetic.resource.read", "synthetic.resource.manage", "synthetic.resource.create"}
        )
        for name, permissions, all_rooms in (
            ("b-manager", management, True),
            ("b-reader", frozenset({"synthetic.resource.read"}), False),
            ("b-scoped", management, False),
        ):
            auth.provision_user(
                username=name,
                password="synthetic-b-resource-password",
                department_id="synthetic-b",
                roles={"synthetic-" + name: permissions},
                room_ids=frozenset() if all_rooms else frozenset({"1"}),
                all_rooms=all_rooms,
            )
    finally:
        engine.dispose()


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def stop(process) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_browser(frontend: Path, origin: str, temporary: Path, channel: str | None) -> int:
    import httpx

    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js required for browser acceptance")
    browser_origin = f"http://127.0.0.1:{free_port()}"
    environment = dict(os.environ)
    environment.update(
        CAMPUS_DEV_BACKEND_URL=origin,
        VITE_B_RESOURCE_BROWSER_ACCEPTANCE="1",
        B_RESOURCE_BROWSER_ORIGIN=browser_origin,
    )
    environment.pop("VITE_B_RESOURCE_ACCEPTANCE_ORIGIN", None)
    environment.pop("B_RESOURCE_BROWSER_CHANNEL", None)
    if channel:
        environment["B_RESOURCE_BROWSER_CHANNEL"] = channel
    process = None
    with (temporary / "vite.log").open("wb") as log:
        try:
            process = subprocess.Popen(
                [
                    node,
                    str(frontend / "node_modules/vite/bin/vite.js"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    browser_origin.rsplit(":", 1)[1],
                    "--strictPort",
                ],
                cwd=frontend,
                env=environment,
                stdout=log,
                stderr=log,
            )
            with httpx.Client(base_url=browser_origin, trust_env=False, timeout=0.2) as client:
                for _ in range(150):
                    if process.poll() is not None:
                        raise RuntimeError("Isolated Vite service exited before readiness")
                    try:
                        response = client.get(
                            "/src/modules/m1-reservation/resources/browser/index.html"
                        )
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Isolated Vite readiness timed out")
            return subprocess.run(
                [
                    node,
                    str(frontend / "node_modules/@playwright/test/cli.js"),
                    "test",
                    "--config",
                    "src/modules/m1-reservation/resources/browser/playwright.config.mts",
                ],
                cwd=frontend,
                env=environment,
                check=False,
            ).returncode
        finally:
            stop(process)


def run(source: Path, frontend: Path, browser: bool = False, channel: str | None = None) -> int:
    import httpx
    import pgserver
    import psycopg

    verify_source(source)
    backend = source / "backend"
    sys.path.insert(0, str(backend))
    with tempfile.TemporaryDirectory(prefix="b-resource-http-") as temporary:
        server = pgserver.get_server(Path(temporary) / "pg", cleanup_mode="stop")
        process = None
        try:
            uri = server.get_uri()
            with psycopg.connect(uri) as connection:
                version = connection.execute("SHOW server_version").fetchone()[0]
            print(f"Isolated PostgreSQL {version}; fixed C 51b65bf / B 4ee2fe5", flush=True)
            initialize(uri)
            port = free_port()
            origin = f"http://127.0.0.1:{port}"
            environment = dict(os.environ)
            environment.update(
                CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE="1",
                CAMPUS_C_ENABLED="false",
                C24_TEST_DB_URI=uri,
                C24_TEST_RESOURCE_TOKEN="synthetic-fixture-resource-token",
                PYTHONPATH=str(backend),
            )
            # Do not inherit overrides that could alter the isolated C fixture.
            for name in ("C24_TEST_C_ONLY", "C24_TEST_POLICY_FILE", "C24_TEST_ROOM_OPTIONS"):
                environment.pop(name, None)
            with (Path(temporary) / "http.log").open("wb") as log:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "tests.c_module.resource_acceptance_app:build",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                    ],
                    cwd=backend,
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
                with httpx.Client(base_url=origin, trust_env=False, timeout=0.2) as client:
                    for _ in range(150):
                        if process.poll() is not None:
                            raise RuntimeError("Isolated C/B HTTP service exited before readiness")
                        try:
                            if client.get("/health/ready").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Isolated C/B HTTP readiness timed out")
                frontend_environment = dict(os.environ)
                frontend_environment["VITE_B_RESOURCE_ACCEPTANCE_ORIGIN"] = origin
                result = subprocess.run(
                    [
                        "npm",
                        "test",
                        "--",
                        "src/modules/m1-reservation/resources/access.acceptance.test.ts",
                    ],
                    cwd=frontend,
                    env=frontend_environment,
                    check=False,
                )
            if result.returncode or not browser:
                return result.returncode
            return run_browser(frontend, origin, Path(temporary), channel)
        finally:
            stop(process)
            server.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--combined-source", type=Path, required=True)
    parser.add_argument(
        "--frontend",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "frontend",
    )
    parser.add_argument(
        "--browser", action="store_true", help="Also run actual desktop/mobile Chromium"
    )
    parser.add_argument(
        "--browser-channel",
        choices=["chrome"],
        help="Use an installed Chrome; default uses Playwright Chromium",
    )
    arguments = parser.parse_args()
    if arguments.browser_channel and not arguments.browser:
        parser.error("--browser-channel requires --browser")
    raise SystemExit(
        run(
            arguments.combined_source.resolve(),
            arguments.frontend.resolve(),
            arguments.browser,
            arguments.browser_channel,
        )
    )
