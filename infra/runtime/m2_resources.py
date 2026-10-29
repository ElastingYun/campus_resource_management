"""Explicit host wiring for the published C runtime and B resource ports.

Requires those reviewed modules to be installed; it does not copy business code,
grant roles, create tables, or enable the resource adapter without configuration.
"""

import os
from pathlib import Path


def create_app():
    from app.main import create_app as create_base_app

    application = create_base_app()
    path = os.environ.get("CAMPUS_RESOURCE_HOST_CONFIG")
    if not path:
        return application
    from app.common.auth.resource_adapter import (
        ResourceManagementConfiguration,
        install_resource_management,
    )

    runtime = application.state.c_runtime
    if runtime is None:
        raise RuntimeError("Explicit resource host requires the C runtime")
    configuration = ResourceManagementConfiguration.model_validate_json(
        Path(path).read_text()
    )
    install_resource_management(
        application,
        auth=runtime.auth,
        audit=runtime.audit,
        configuration=configuration,
    )
    return application
