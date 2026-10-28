"""FastAPI application factory.

Run locally with: uvicorn app.main:create_app --factory --reload
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import AppConfig, load_config
from app.db import make_engine, make_sessionmaker


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or load_config()
    engine = make_engine(config.database_url)

    app = FastAPI(title="Campus Resource Management", version="0.1.0")
    app.state.config = config
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)

    @app.get("/api/health", tags=["health"])
    def health() -> JSONResponse:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return JSONResponse({"status": "degraded", "database": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok", "database": "ok"})

    return app
