from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(prefix="/health", tags=["engineering health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "alive", "scope": "bootstrap"}


@router.get("/ready", response_model=None)
def ready(request: Request) -> dict[str, str] | JSONResponse:
    engine = request.app.state.engine
    if engine is None:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unconfigured", "scope": "bootstrap"},
        )
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError:
        # Do not expose exception text: drivers may include hostnames or credentials.
        result = None
    if result != 1:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unavailable", "scope": "bootstrap"},
        )
    return {"status": "ready", "database": "connected", "scope": "bootstrap"}
