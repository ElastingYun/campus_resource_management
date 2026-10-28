from alembic import context
from app.config import Settings
from app.database import build_engine

# Business owners will register their approved metadata in a separate migration PR.
target_metadata = None

if context.is_offline_mode():
    raise RuntimeError("Use online migrations with the configured PostgreSQL database")

engine = build_engine(Settings())
try:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
