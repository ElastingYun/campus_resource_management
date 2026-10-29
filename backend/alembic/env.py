import app.common.resources.models  # noqa: F401  (registers tables on Base.metadata)
import app.modules.m1_reservation.models  # noqa: F401
from alembic import context
from app.config import Settings
from app.database import Base, build_engine

# Business owners register their models above; migrations are still written by hand
# and reviewed, target_metadata only lets tests detect drift from the ORM models.
target_metadata = Base.metadata

if context.is_offline_mode():
    raise RuntimeError("Use online migrations with the configured PostgreSQL database")


def run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


# Tests pass an open connection to migrate throwaway databases; normal runs use Settings.
connection = context.config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    engine = build_engine(Settings())
    try:
        with engine.connect() as connection:
            run_migrations(connection)
    finally:
        engine.dispose()
