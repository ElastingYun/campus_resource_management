from alembic import context
from app.config import Settings
from app.database import build_engine

# Business owners will register their approved metadata in a separate migration PR.
target_metadata = None

if context.is_offline_mode():
    raise RuntimeError("Use online migrations with the configured PostgreSQL database")


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


# Tests and maintenance tools may supply their own explicitly scoped connection.
provided_connection = context.config.attributes.get("connection")
if provided_connection is not None:
    run_migrations(provided_connection)
else:
    engine = build_engine(Settings())
    try:
        with engine.connect() as connection:
            run_migrations(connection)
    finally:
        engine.dispose()
