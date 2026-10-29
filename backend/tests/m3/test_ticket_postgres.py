"""Real PostgreSQL verifies the concurrent idempotency constraint when enabled."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import build_engine
from app.modules.m3_repair.contracts import TicketActor, TicketError
from app.modules.m3_repair.schemas import TicketCreate
from app.modules.m3_repair.service import create_ticket
from app.modules.m3_repair.tables import tickets

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CAMPUS_TEST_POSTGRES") != "1",
        reason="Set CAMPUS_TEST_POSTGRES=1 with a migrated real PostgreSQL database",
    ),
]


class ConcurrentRoomPolicy:
    def __init__(self, barrier: Barrier):
        self.barrier = barrier

    def require_reportable(self, room_id: int, actor: TicketActor) -> None:
        assert room_id == 1
        self.barrier.wait(timeout=10)


class ConcurrentAudit:
    def __init__(self):
        self.ticket_ids = []

    def record_created(self, session, *, actor, ticket_id, room_id, request_id, now):
        assert session.in_transaction()
        assert room_id == "1" and actor.subject_id and request_id and now.tzinfo is not None
        self.ticket_ids.append(ticket_id)


def test_audit_failure_rolls_back_new_ticket_in_postgres():
    class RoomPolicy:
        def require_reportable(self, room_id, actor):
            assert room_id == 1 and actor.subject_id

    class FailingAudit:
        def record_created(self, session, *, actor, ticket_id, room_id, request_id, now):
            assert session.in_transaction() and ticket_id and room_id and request_id and now
            raise RuntimeError("synthetic audit failure")

    engine = build_engine(Settings(_env_file=None))
    actor = TicketActor(f"synthetic-{uuid4()}", can_create=True, can_read_own=True)
    key = f"audit-fail-{uuid4()}"
    try:
        with Session(engine) as session:
            with pytest.raises(TicketError) as error:
                create_ticket(
                    session,
                    actor,
                    RoomPolicy(),
                    FailingAudit(),
                    TicketCreate(room_id="1", description="合成审计失败故障"),
                    key,
                )
            assert error.value.detail["code"] == "audit_unavailable"
        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(tickets)
                    .where(
                        tickets.c.reporter_id == actor.subject_id,
                        tickets.c.idempotency_key == key,
                    )
                )
                == 0
            )
    finally:
        engine.dispose()


def test_two_concurrent_submissions_create_one_ticket():
    engine = build_engine(Settings(_env_file=None))
    actor = TicketActor(f"synthetic-{uuid4()}", can_create=True, can_read_own=True)
    key = f"concurrent-{uuid4()}"
    policy = ConcurrentRoomPolicy(Barrier(2))
    audit = ConcurrentAudit()
    data = TicketCreate(room_id="1", description="合成并发故障")

    def submit():
        with Session(engine) as session:
            return create_ticket(session, actor, policy, audit, data, key)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        assert results[0][0].id == results[1][0].id
        assert sorted(created for _, created in results) == [False, True]
        assert audit.ticket_ids == [results[0][0].id]
        with Session(engine) as session:
            count = session.scalar(
                select(func.count())
                .select_from(tickets)
                .where(
                    tickets.c.reporter_id == actor.subject_id,
                    tickets.c.idempotency_key == key,
                )
            )
            assert count == 1
    finally:
        with Session(engine) as session:
            session.execute(delete(tickets).where(tickets.c.reporter_id == actor.subject_id))
            session.commit()
        engine.dispose()
