from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router
from app.config import Settings
from app.database import build_engine
from app.modules.m1_reservation import router as m1_router


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(configuration) if configuration.database_configured else None
        application.state.engine = engine
        try:
            yield
        finally:
            if engine is not None:
                engine.dispose()

    application = FastAPI(title="Campus Resource Management bootstrap", lifespan=lifespan)
    application.include_router(router)
    m1_router.register(application)
    return application


app = create_app()
