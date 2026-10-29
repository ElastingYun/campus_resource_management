"""Synthetic audit storage for atomicity tests; never maps C's private tables."""

from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, insert, select
from sqlalchemy.orm import Session


@pytest.fixture
def audit_store():
    def create(engine):
        table = Table(
            "resource_audit_test_only",
            MetaData(),
            Column("id", Integer, primary_key=True),
            Column("actor_id", String, nullable=False),
            Column("action", String, nullable=False),
            Column("resource_id", String, nullable=False),
            Column("room_id", String, nullable=False),
            Column("request_id", String, nullable=False),
            Column("before", Text),
            Column("after", Text, nullable=False),
        )
        table.create(engine)

        def write(session, mutation):
            session.execute(
                insert(table).values(
                    actor_id=mutation.actor_id,
                    action=mutation.action,
                    resource_id=str(mutation.resource_id),
                    room_id=str(mutation.room_id),
                    request_id=mutation.request_id,
                    before=mutation.before,
                    after=mutation.after,
                )
            )

        def read():
            with Session(engine) as session:
                return [
                    dict(row)
                    for row in session.execute(select(table).order_by(table.c.id)).mappings()
                ]

        return SimpleNamespace(table=table, write=write, read=read)

    return create
