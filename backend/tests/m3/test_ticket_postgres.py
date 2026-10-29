"""Real PostgreSQL verifies the concurrent idempotency constraint when enabled."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import build_engine
from app.modules.m3_repair.assignment import assign_ticket
from app.modules.m3_repair.contracts import TicketActor, TicketError
from app.modules.m3_repair.schemas import AssignmentRequest, TicketCreate, WorkStartRequest
from app.modules.m3_repair.service import create_ticket
from app.modules.m3_repair.tables import ticket_events, tickets
from app.modules.m3_repair.work_start import start_work

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


def test_two_concurrent_assignments_have_one_version_winner():
    engine = build_engine(Settings(_env_file=None))
    ticket_id = None
    reporter = TicketActor(f"synthetic-{uuid4()}", can_create=True)
    dispatcher = TicketActor(f"synthetic-{uuid4()}", can_assign=True)
    key = f"assignment-{uuid4()}"

    class RoomPolicy:
        def require_reportable(self, room_id, actor):
            assert room_id == 1 and actor.subject_id == reporter.subject_id

    class CreateAudit:
        def record_created(self, session, *, actor, ticket_id, room_id, request_id, now):
            assert session.in_transaction() and ticket_id and room_id and request_id and now

    class AssignPolicy:
        def __init__(self):
            self.barrier = Barrier(2)

        def require_assignable(self, room_id, actor, assignee_id):
            assert room_id == 1 and actor.subject_id == dispatcher.subject_id and assignee_id
            self.barrier.wait(timeout=10)

    class AssignAudit:
        def record_assigned(
            self,
            session,
            *,
            actor,
            ticket_id,
            room_id,
            assignee_id,
            operation_id,
            before_status,
            after_status,
            now,
        ):
            assert session.in_transaction() and actor.subject_id == dispatcher.subject_id
            assert ticket_id and room_id and assignee_id and operation_id and now
            assert (before_status, after_status) == ("REPORTED", "ASSIGNED")

    try:
        with Session(engine) as session:
            ticket, created = create_ticket(
                session,
                reporter,
                RoomPolicy(),
                CreateAudit(),
                TicketCreate(room_id="1", description="合成并发派单故障"),
                key,
            )
            assert created
            ticket_id = ticket.id

        policy = AssignPolicy()
        audit = AssignAudit()

        def assign(index):
            with Session(engine) as session:
                try:
                    result, created = assign_ticket(
                        session,
                        dispatcher,
                        policy,
                        audit,
                        ticket.id,
                        str(uuid4()),
                        AssignmentRequest(assignee_id=f"repairer-{index}", expected_version=0),
                    )
                    return result.status, created
                except TicketError as exc:
                    return exc.detail["code"], False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(assign, range(2)))
        assert sorted(results) == [("ASSIGNED", True), ("ticket_changed", False)]
        with Session(engine) as session:
            row = session.execute(select(tickets).where(tickets.c.id == ticket.id)).one()
            count = session.scalar(
                select(func.count())
                .select_from(ticket_events)
                .where(ticket_events.c.ticket_id == ticket.id)
            )
            assert row.version == 1 and row.status == "ASSIGNED" and count == 1
    finally:
        if ticket_id is not None:
            with Session(engine) as session:
                session.execute(delete(ticket_events).where(ticket_events.c.ticket_id == ticket_id))
                session.execute(delete(tickets).where(tickets.c.id == ticket_id))
                session.commit()
        engine.dispose()


def test_two_concurrent_work_starts_have_one_version_winner():
    engine = build_engine(Settings(_env_file=None))
    ticket_id = str(uuid4())
    repairer = TicketActor(f"synthetic-{uuid4()}", can_start_repair=True)
    now = datetime.now(UTC)
    barrier = Barrier(2)

    class Restriction:
        def require_active(self, source_id, room_id):
            assert source_id == ticket_id and room_id == 1
            barrier.wait(timeout=10)

    class Audit:
        def record_started(
            self,
            session,
            *,
            actor,
            ticket_id,
            room_id,
            operation_id,
            before_status,
            after_status,
            now,
        ):
            assert session.in_transaction() and actor == repairer
            assert ticket_id and room_id == "1" and operation_id and now
            assert (before_status, after_status) == ("ASSIGNED", "REPAIRING")

    try:
        with Session(engine) as session:
            session.execute(
                insert(tickets).values(
                    id=ticket_id,
                    room_id=1,
                    reporter_id=f"synthetic-{uuid4()}",
                    description="合成并发开工故障",
                    status="ASSIGNED",
                    version=1,
                    assignee_id=repairer.subject_id,
                    idempotency_key=f"work-start-{uuid4()}",
                    request_fingerprint="0" * 64,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        def start(_):
            with Session(engine) as session:
                try:
                    result, created = start_work(
                        session,
                        repairer,
                        Restriction(),
                        Audit(),
                        ticket_id,
                        str(uuid4()),
                        WorkStartRequest(expected_version=1),
                    )
                    return result.status, created
                except TicketError as exc:
                    return exc.detail["code"], False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(start, range(2)))
        assert sorted(results) == [("REPAIRING", True), ("ticket_changed", False)]
        with Session(engine) as session:
            row = session.execute(select(tickets).where(tickets.c.id == ticket_id)).one()
            events = session.execute(
                select(ticket_events).where(ticket_events.c.ticket_id == ticket_id)
            ).all()
            assert row.status == "REPAIRING" and row.version == 2
            assert len(events) == 1 and events[0].action == "start"
    finally:
        with Session(engine) as session:
            session.execute(delete(ticket_events).where(ticket_events.c.ticket_id == ticket_id))
            session.execute(delete(tickets).where(tickets.c.id == ticket_id))
            session.commit()
        engine.dispose()
