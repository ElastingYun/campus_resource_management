"""Guarded subprocess fixture for actual TCP acceptance, never a deployment entry."""

import os
from datetime import time
from pathlib import Path

import psycopg
from sqlalchemy import create_engine

from app.common.auth.resource_adapter import (
    NewRoomPolicy,
    ResourceManagementConfiguration,
    ResourcePermissions,
    install_resource_management,
)
from app.config import Settings


def build():
    if os.environ.get("CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE") != "1":
        raise RuntimeError("This entry point is restricted to isolated acceptance tests")
    import app.main as main

    uri = os.environ["C24_TEST_DB_URI"]
    engine = create_engine(
        "postgresql+psycopg://",
        creator=lambda: psycopg.connect(uri),
        pool_pre_ping=True,
    )
    main.build_engine = lambda _: engine  # Private test process, not application code.
    application = main.create_app(
        Settings(
            _env_file=None,
            db_host="synthetic-fixture",
            db_password="synthetic-fixture-password",
            c_enabled=True,
            c_config_file=Path(os.environ["C24_TEST_POLICY_FILE"])
            if os.environ.get("C24_TEST_POLICY_FILE")
            else Path(__file__).resolve().parents[2]
            / "app/modules/m2_approval/examples/runtime.synthetic.json",
            resources_service_token=os.environ.get(
                "C24_TEST_RESOURCE_TOKEN", "synthetic-fixture-resource-token"
            ),
        )
    )
    component = application.state.c_runtime
    if os.environ.get("C24_TEST_C_ONLY") == "1":
        return application
    install_resource_management(
        application,
        auth=component.auth,
        audit=component.audit,
        configuration=ResourceManagementConfiguration(
            permissions=ResourcePermissions(
                read="synthetic.resource.read",
                manage="synthetic.resource.manage",
                create_rooms="synthetic.resource.create",
            ),
            new_room=NewRoomPolicy(
                open_time=time(8),
                close_time=time(22),
                access_scope="campus",
                department_id=None,
                enabled=True,
            ),
        ),
    )
    return application
