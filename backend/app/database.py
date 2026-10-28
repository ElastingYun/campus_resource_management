from sqlalchemy import URL, Engine, create_engine

from app.config import Settings


def build_engine(settings: Settings) -> Engine:
    if not settings.database_configured:
        raise RuntimeError("Database configuration is incomplete")
    assert settings.db_password is not None
    url = URL.create(
        "postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value(),
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=2,
        pool_timeout=3,
        connect_args={"connect_timeout": 3},
    )
