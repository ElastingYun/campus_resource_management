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


class ReportPolicy:
    def require_reportable(self, room_id, actor):
        assert room_id == 1 and actor.subject_id == "reporter-2"


class ReportAudit:
    def record_created(self, session, *, actor, ticket_id, room_id, request_id, now):
        assert session.in_transaction()
        assert room_id == "1" and now.tzinfo is not None
        session.execute(
            insert(audit_entries).values(
                event_id=request_id, ticket_id=ticket_id, actor_id=actor.subject_id
            )
        )


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


class RestrictionConfirmation:
    def __init__(self):
        self.active = True
        self.calls = 0

    def require_active(self, ticket_id, room_id):
        self.calls += 1
        assert ticket_id and room_id == 1
        if not self.active:
            raise TicketError(503, "restriction_unconfirmed", "尚未确认整室下架")


class WorkStartAudit:
    def __init__(self):
        self.fail_after_write = False

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
        assert session.in_transaction()
        assert room_id == "1" and actor.subject_id and now.tzinfo is not None
        assert (before_status, after_status) == ("ASSIGNED", "REPAIRING")
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
    holder = {
        "actor": TicketActor("dispatcher-1", can_assign=True),
        "audit": AssignmentAudit(),
        "report_audit": ReportAudit(),
        "restriction": RestrictionConfirmation(),
        "work_start_audit": WorkStartAudit(),
    }
    policy = AssignmentPolicy()
    app = FastAPI()
    app.state.engine = engine
    app.include_router(
        create_router(
            actor_dependency=lambda: holder["actor"],
            room_policy_dependency=ReportPolicy,
            audit_dependency=lambda: holder["report_audit"],
            assignment_policy_dependency=lambda: policy,
            assignment_audit_dependency=lambda: holder["audit"],
            restriction_confirmation_dependency=lambda: holder["restriction"],
            work_start_audit_dependency=lambda: holder["work_start_audit"],
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


def start_work(client, ticket_id, *, operation_id=None, version=1):
    operation_id = operation_id or str(uuid4())
    return client.post(
        f"/api/v1/m3/tickets/{ticket_id}/work-starts",
        headers={"Operation-Id": operation_id},
        json={"expected_version": version},
    )


def counts(engine):
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(ticket_events)),
            session.scalar(select(func.count()).select_from(audit_entries)),
        )


def test_first_review_report_read_assign_and_start_http_flow(assignment_client):
    client, holder, _, engine, _ = assignment_client
    holder["actor"] = TicketActor("reporter-2", can_create=True, can_read_own=True)
    created = client.post(
        "/api/v1/m3/tickets",
        headers={"Idempotency-Key": "first-review-report"},
        json={"room_id": "1", "description": "合成灯具故障"},
    )
    assert created.status_code == 201
    ticket_id = created.json()["id"]
    assert created.json()["status"] == "REPORTED"
    own = client.get(f"/api/v1/m3/tickets/{ticket_id}")
    assert own.status_code == 200 and own.json()["id"] == ticket_id

    holder["actor"] = TicketActor("dispatcher-1", can_assign=True)
    assigned = assign(client, ticket_id)
    assert assigned.status_code == 201
    assert assigned.json()["status"] == "ASSIGNED"
    assert assigned.json()["version"] == 1
    assert counts(engine) == (1, 2)

    holder["actor"] = TicketActor("repairer-1", can_start_repair=True)
    started = start_work(client, ticket_id)
    assert started.status_code == 201
    assert started.json()["status"] == "REPAIRING"
    assert started.json()["version"] == 2
    assert counts(engine) == (2, 3)

    holder["actor"] = TicketActor("reporter-2", can_read_own=True)
    after = client.get(f"/api/v1/m3/tickets/{ticket_id}")
    assert after.status_code == 200 and after.json()["status"] == "REPAIRING"
    holder["actor"] = TicketActor("other-reporter", can_read_own=True)
    assert client.get(f"/api/v1/m3/tickets/{ticket_id}").status_code == 404


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


def test_work_start_requires_assignee_and_confirmed_restriction(assignment_client):
    client, holder, _, engine, ticket_id = assignment_client
    assert assign(client, ticket_id).status_code == 201

    holder["actor"] = TicketActor("other-repairer", can_start_repair=True)
    assert start_work(client, ticket_id).status_code == 403
    holder["actor"] = TicketActor("repairer-1")
    assert start_work(client, ticket_id).status_code == 403
    assert holder["restriction"].calls == 0

    holder["actor"] = TicketActor("repairer-1", can_start_repair=True)
    holder["restriction"].active = False
    blocked = start_work(client, ticket_id)
    assert blocked.status_code == 503
    assert blocked.json()["detail"]["code"] == "restriction_unconfirmed"
    assert counts(engine) == (1, 1)
    with Session(engine) as session:
        row = session.execute(select(tickets).where(tickets.c.id == ticket_id)).one()
        assert (row.status, row.version) == ("ASSIGNED", 1)

    holder["restriction"].active = True
    assert start_work(client, ticket_id).status_code == 201
    assert counts(engine) == (2, 2)


def test_work_start_replay_conflicts_and_audit_rollback(assignment_client):
    client, holder, _, engine, ticket_id = assignment_client
    assignment_id = str(uuid4())
    assert assign(client, ticket_id, operation_id=assignment_id).status_code == 201
    holder["actor"] = TicketActor("repairer-1", can_start_repair=True)
    reused_assignment_id = start_work(client, ticket_id, operation_id=assignment_id)
    assert reused_assignment_id.status_code == 409
    assert reused_assignment_id.json()["detail"]["code"] == "operation_id_reused"

    start_id = str(uuid4())
    holder["work_start_audit"].fail_after_write = True
    failed = start_work(client, ticket_id, operation_id=start_id)
    assert failed.status_code == 503
    assert failed.json()["detail"]["code"] == "audit_unavailable"
    assert counts(engine) == (1, 1)
    with Session(engine) as session:
        row = session.execute(select(tickets).where(tickets.c.id == ticket_id)).one()
        assert (row.status, row.version) == ("ASSIGNED", 1)

    holder["work_start_audit"].fail_after_write = False
    first = start_work(client, ticket_id, operation_id=start_id)
    assert first.status_code == 201
    replay = start_work(client, ticket_id, operation_id=start_id)
    assert replay.status_code == 200 and replay.json() == first.json()
    assert holder["restriction"].calls == 2
    assert start_work(client, ticket_id, operation_id=start_id, version=2).status_code == 409
    assert start_work(client, ticket_id).status_code == 409
    assert counts(engine) == (2, 2)

    holder["actor"] = TicketActor("dispatcher-1", can_assign=True)
    reused_start_id = assign(client, ticket_id, operation_id=start_id)
    assert reused_start_id.status_code == 409
    assert reused_start_id.json()["detail"]["code"] == "operation_id_reused"


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


def test_work_start_default_restriction_is_closed():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tickets.create(engine)
    ticket_events.create(engine)
    app = FastAPI()
    app.state.engine = engine
    app.include_router(
        create_router(actor_dependency=lambda: TicketActor("repairer", can_start_repair=True))
    )
    with TestClient(app) as client:
        response = start_work(client, str(uuid4()))
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "restriction_confirmation_unconfigured"
    engine.dispose()
