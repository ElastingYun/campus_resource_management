"""E-03 assignment API and transaction behavior with trusted test ports."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, String, Table, create_engine, func, insert, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.modules.m3_repair.contracts import TicketActor, TicketError
from app.modules.m3_repair.router import create_router
from app.modules.m3_repair.tables import ticket_events, tickets

audit_entries = Table(
    "test_m3_assignment_audit",
    MetaData(),
    Column("event_id", String(36), primary_key=True),
    Column("ticket_id", String(36), nullable=False),
    Column("actor_id", String(64), nullable=False),
)


class AssignmentPolicy:
    def __init__(self):
        self.allowed = True
        self.calls = 0

    def require_assignable(self, room_id, actor, assignee_id):
        self.calls += 1
        assert room_id == 1 and actor.subject_id and assignee_id
        if not self.allowed:
            raise TicketError(403, "out_of_scope", "无权派发该教室工单")


class AssignmentAudit:
    def __init__(self):
        self.fail_after_write = False

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
        assert session.in_transaction()
        assert room_id == "1" and assignee_id and now.tzinfo is not None
        assert (before_status, after_status) == ("REPORTED", "ASSIGNED")
        session.execute(
            insert(audit_entries).values(
                event_id=operation_id, ticket_id=ticket_id, actor_id=actor.subject_id
            )
        )
        if self.fail_after_write:
            raise RuntimeError("synthetic audit failure")


@pytest.fixture
def assignment_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tickets.create(engine)
    ticket_events.create(engine)
    audit_entries.create(engine)
    ticket_id = str(uuid4())
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.execute(
            insert(tickets).values(
                id=ticket_id,
                room_id=1,
                reporter_id="reporter-1",
                description="合成故障描述",
                status="REPORTED",
                idempotency_key="report-1",
                request_fingerprint="0" * 64,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    holder = {"actor": TicketActor("dispatcher-1", can_assign=True), "audit": AssignmentAudit()}
    policy = AssignmentPolicy()
    app = FastAPI()
    app.state.engine = engine
    app.include_router(
        create_router(
            actor_dependency=lambda: holder["actor"],
            assignment_policy_dependency=lambda: policy,
            assignment_audit_dependency=lambda: holder["audit"],
        )
    )
    with TestClient(app) as client:
        yield client, holder, policy, engine, ticket_id
    engine.dispose()


def assign(client, ticket_id, *, operation_id=None, assignee="repairer-1", version=0):
    operation_id = operation_id or str(uuid4())
    return client.post(
        f"/api/v1/m3/tickets/{ticket_id}/assign",
        headers={"Operation-Id": operation_id},
        json={"assignee_id": assignee, "expected_version": version},
    )


def counts(engine):
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(ticket_events)),
            session.scalar(select(func.count()).select_from(audit_entries)),
        )


def test_assignment_replay_and_version_conflict(assignment_client):
    client, _, policy, engine, ticket_id = assignment_client
    operation_id = str(uuid4())
    first = assign(client, ticket_id, operation_id=operation_id)
    assert first.status_code == 201
    assert first.headers["cache-control"] == "no-store"
    assert first.json()["status"] == "ASSIGNED"
    assert first.json()["version"] == 1
    assert first.json()["assignee_id"] == "repairer-1"
    assert assign(client, ticket_id, operation_id=operation_id).status_code == 200
    assert assign(client, ticket_id, operation_id=operation_id).json() == first.json()
    assert policy.calls == 1
    reused = assign(client, ticket_id, operation_id=operation_id, assignee="repairer-2")
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "operation_id_reused"
    stale = assign(client, ticket_id, assignee="repairer-2")
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "ticket_changed"
    assert counts(engine) == (1, 1)
    with Session(engine) as session:
        row = session.execute(select(tickets).where(tickets.c.id == ticket_id)).one()
        assert (row.status, row.assignee_id, row.version) == ("ASSIGNED", "repairer-1", 1)


def test_audit_failure_rolls_back_and_operation_can_retry(assignment_client):
    client, holder, _, engine, ticket_id = assignment_client
    operation_id = str(uuid4())
    holder["audit"].fail_after_write = True
    failed = assign(client, ticket_id, operation_id=operation_id)
    assert failed.status_code == 503
    assert failed.json()["detail"]["code"] == "audit_unavailable"
    assert counts(engine) == (0, 0)
    with Session(engine) as session:
        row = session.execute(select(tickets).where(tickets.c.id == ticket_id)).one()
        assert (row.status, row.assignee_id, row.version) == ("REPORTED", None, 0)
    holder["audit"].fail_after_write = False
    assert assign(client, ticket_id, operation_id=operation_id).status_code == 201
    assert counts(engine) == (1, 1)


def test_permission_scope_and_invalid_input_do_not_write(assignment_client):
    client, holder, policy, engine, ticket_id = assignment_client
    holder["actor"] = TicketActor("reporter-1", can_read_own=True)
    assert assign(client, ticket_id).status_code == 403
    holder["actor"] = TicketActor("dispatcher-1", can_assign=True)
    policy.allowed = False
    assert assign(client, ticket_id).status_code == 403
    policy.allowed = True
    assert assign(client, str(uuid4())).status_code == 404
    assert assign(client, ticket_id, assignee="bad id").status_code == 422
    assert assign(client, ticket_id, version=-1).status_code == 422
    response = client.post(
        f"/api/v1/m3/tickets/{ticket_id}/assign",
        json={"assignee_id": "repairer-1", "expected_version": 0},
    )
    assert response.status_code == 422
    assert counts(engine) == (0, 0)


def test_assignment_default_policy_is_closed():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tickets.create(engine)
    ticket_events.create(engine)
    app = FastAPI()
    app.state.engine = engine
    app.include_router(
        create_router(actor_dependency=lambda: TicketActor("dispatcher", can_assign=True))
    )
    with TestClient(app) as client:
        response = assign(client, str(uuid4()))
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "assignment_policy_unconfigured"
    engine.dispose()
