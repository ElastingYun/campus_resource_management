"""Per-request database session for M1, on the engine D's app factory manages."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.modules.m1_reservation.errors import M1Error


def get_session(request: Request) -> Iterator[Session]:
    """One session per request; services own commit, closing rolls back anything else."""
    engine = request.app.state.engine
    if engine is None:
        raise M1Error(503, "database_unavailable", "数据库未配置，暂时无法处理请求")
    with Session(engine, expire_on_commit=False) as session:
        yield session
