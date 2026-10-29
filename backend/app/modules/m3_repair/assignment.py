"""Isolated E-03 assignment transition; production adapters remain explicit ports."""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.m3_repair.contracts import (
    AssignmentAudit,
    AssignmentPolicy,
    TicketActor,
    TicketError,
)
from app.modules.m3_repair.schemas import AssignmentOut, AssignmentRequest
from app.modules.m3_repair.tables import ticket_events, tickets


def _fingerprint(data: AssignmentRequest) -> str:
    payload = f"{data.expected_version}\0{data.assignee_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _event(session: Session, ticket_id: str, operation_id: str):
    return session.execute(
        select(ticket_events).where(
            ticket_events.c.ticket_id == ticket_id,
            ticket_events.c.operation_id == operation_id,
        )
    ).one_or_none()


def _replay(row, actor: TicketActor, fingerprint: str) -> AssignmentOut:
    if row.actor_id != actor.subject_id or row.request_fingerprint != fingerprint:
        raise TicketError(409, "operation_id_reused", "操作标识已用于其他派单请求")
    return _out(row)


def _out(row) -> AssignmentOut:
    occurred_at = row.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    else:
        occurred_at = occurred_at.astimezone(UTC)
    return AssignmentOut(
        ticket_id=row.ticket_id,
        assignee_id=row.assignee_id,
        status=row.after_status,
        version=row.version,
        occurred_at=occurred_at,
    )


def assign_ticket(
    session: Session,
    actor: TicketActor,
    policy: AssignmentPolicy,
    audit: AssignmentAudit,
    ticket_id: str,
    operation_id: str,
    data: AssignmentRequest,
) -> tuple[AssignmentOut, bool]:
    if not actor.can_assign:
        raise TicketError(403, "forbidden", "无权派单")
    fingerprint = _fingerprint(data)
    try:
        existing = _event(session, ticket_id, operation_id)
        if existing is not None:
            return _replay(existing, actor, fingerprint), False

        ticket = session.execute(
            select(tickets.c.room_id).where(tickets.c.id == ticket_id)
        ).one_or_none()
        if ticket is None:
            raise TicketError(404, "ticket_not_found", "工单不存在")

        # A host adapter may call B/C over the network. Do not hold a DB
        # transaction across that call; the conditional UPDATE closes the race.
        session.rollback()
        try:
            policy.require_assignable(ticket.room_id, actor, data.assignee_id)
        except TicketError:
            raise
        except Exception as exc:
            raise TicketError(503, "assignment_policy_unavailable", "暂时无法核实派单资格") from exc
        now = datetime.now(UTC)
        changed = session.execute(
            update(tickets)
            .where(
                tickets.c.id == ticket_id,
                tickets.c.status == "REPORTED",
                tickets.c.version == data.expected_version,
            )
            .values(
                status="ASSIGNED",
                assignee_id=data.assignee_id,
                version=tickets.c.version + 1,
                updated_at=now,
            )
        )
        if changed.rowcount != 1:
            session.rollback()
            existing = _event(session, ticket_id, operation_id)
            if existing is not None:
                return _replay(existing, actor, fingerprint), False
            raise TicketError(409, "ticket_changed", "工单状态或版本已变化，请刷新后重试")

        version = data.expected_version + 1
        event_id = str(uuid4())
        session.execute(
            insert(ticket_events).values(
                id=event_id,
                ticket_id=ticket_id,
                operation_id=operation_id,
                action="assign",
                actor_id=actor.subject_id,
                assignee_id=data.assignee_id,
                request_fingerprint=fingerprint,
                before_status="REPORTED",
                after_status="ASSIGNED",
                version=version,
                occurred_at=now,
            )
        )
        try:
            audit.record_assigned(
                session,
                actor=actor,
                ticket_id=ticket_id,
                room_id=str(ticket.room_id),
                assignee_id=data.assignee_id,
                operation_id=operation_id,
                before_status="REPORTED",
                after_status="ASSIGNED",
                now=now,
            )
        except Exception as exc:
            session.rollback()
            raise TicketError(503, "audit_unavailable", "暂时无法确认派单审计") from exc
        session.commit()
        return (
            AssignmentOut(
                ticket_id=ticket_id,
                assignee_id=data.assignee_id,
                status="ASSIGNED",
                version=version,
                occurred_at=now,
            ),
            True,
        )
    except IntegrityError:
        # A concurrent request with the same operation ID may have committed.
        session.rollback()
        try:
            existing = _event(session, ticket_id, operation_id)
            if existing is not None:
                return _replay(existing, actor, fingerprint), False
        except SQLAlchemyError as exc:
            raise TicketError(503, "storage_unavailable", "暂时无法确认派单结果") from exc
        raise TicketError(503, "storage_unavailable", "暂时无法确认派单结果") from None
    except SQLAlchemyError as exc:
        session.rollback()
        raise TicketError(503, "storage_unavailable", "暂时无法保存派单") from exc
