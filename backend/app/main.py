from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router
from app.config import Settings
from app.database import build_engine
from app.modules.m1_reservation import router as m1_router
from app.modules.m2_approval.runtime import ComponentRuntime
from app.modules.m2_approval.settings import ComponentConfiguration


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    component = None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(configuration) if configuration.database_configured else None
        application.state.engine = engine
        try:
            if component is not None:
                await component.start()
            yield
        finally:
            try:
                if component is not None:
                    await component.stop()
            finally:
                if engine is not None:
                    engine.dispose()

    title = (
        "Campus Resource Management"
        if configuration.c_enabled
        else "Campus Resource Management bootstrap"
    )
    application = FastAPI(title=title, lifespan=lifespan)
    application.include_router(router)
    m1_router.register(application)
    if configuration.c_enabled:
        component = ComponentRuntime(
            application,
            ComponentConfiguration.from_file(configuration.c_config_file),
            credentials={
                "CAMPUS_RESOURCES_SERVICE_TOKEN": configuration.resources_service_token,
                "CAMPUS_M1_SERVICE_TOKEN": configuration.m1_service_token,
            },
        )
    application.state.c_runtime = component
    return application


app = create_app()
