"""Small PostgreSQL transaction boundary shared only by C's components."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class Database:
    dsn: str = field(repr=False)

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        # Connection contexts commit on success, roll back on error, and close.
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5) as conn:
            conn.execute("SET LOCAL statement_timeout = '10s'")
            conn.execute("SET LOCAL lock_timeout = '5s'")
            yield conn
