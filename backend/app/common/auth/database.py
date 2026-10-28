"""Small PostgreSQL transaction boundary shared only by C's components."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row
from sqlalchemy import Engine


@dataclass(frozen=True)
class Database:
    dsn: str | None = field(default=None, repr=False)
    engine_provider: Callable[[], Engine] | None = field(default=None, repr=False)

    def __post_init__(self):
        if (self.dsn is None) == (self.engine_provider is None):
            raise ValueError("Provide exactly one database connection source")

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        if self.engine_provider is None:
            with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5) as conn:
                self._limits(conn)
                yield conn
            return
        pooled = self.engine_provider().raw_connection()
        conn = pooled.driver_connection
        previous_factory = conn.row_factory
        try:
            conn.row_factory = dict_row
            with conn.transaction():
                self._limits(conn)
                yield conn
        finally:
            conn.row_factory = previous_factory
            pooled.close()

    @staticmethod
    def _limits(conn):
        conn.execute("SET LOCAL statement_timeout = '10s'")
        conn.execute("SET LOCAL lock_timeout = '5s'")
