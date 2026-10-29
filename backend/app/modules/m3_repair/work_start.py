"""E-owned work-start transition, guarded by a trusted M1 confirmation port."""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.m3_repair.contracts import (
    RestrictionConfirmation,
    TicketActor,
    TicketError,
    WorkStartAudit,
)
from app.modules.m3_repair.schemas import WorkStartOut, WorkStartRequest
from app.modules.m3_repair.tables import ticket_events, tickets


def _fingerprint(data: WorkStartRequest) -> str:
    return hashlib.sha256(f"start\0{data.expected_version}".encode()).hexdigest()


def _event(session: Session, ticket_id: str, operation_id: str):
    return session.execute(
        select(ticket_events).where(
            ticket_events.c.ticket_id == ticket_id,
            ticket_events.c.operation_id == operation_id,
        )
    ).one_or_none()


def _replay(row, actor: TicketActor, fingerprint: str) -> WorkStartOut:
    if (
        row.action != "start"
        or row.actor_id != actor.subject_id
        or row.assignee_id != actor.subject_id
        or row.request_fingerprint != fingerprint
    ):
        raise TicketError(409, "operation_id_reused", "操作标识已用于其他工单操作")
    occurred_at = row.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    else:
        occurred_at = occurred_at.astimezone(UTC)
    return WorkStartOut(
        ticket_id=row.ticket_id,
        assignee_id=row.assignee_id,
        status=row.after_status,
        version=row.version,
        occurred_at=occurred_at,
    )


def start_work(
    session: Session,
    actor: TicketActor,
    restriction: RestrictionConfirmation,
    audit: WorkStartAudit,
    ticket_id: str,
    operation_id: str,
    data: WorkStartRequest,
) -> tuple[WorkStartOut, bool]:
    if not actor.can_start_repair:
        raise TicketError(403, "forbidden", "无权开始维修")
    fingerprint = _fingerprint(data)
    try:
        existing = _event(session, ticket_id, operation_id)
        if existing is not None:
            return _replay(existing, actor, fingerprint), False

        ticket = session.execute(
            select(
                tickets.c.room_id, tickets.c.assignee_id, tickets.c.status, tickets.c.version
            ).where(tickets.c.id == ticket_id)
        ).one_or_none()
        if ticket is None:
            raise TicketError(404, "ticket_not_found", "工单不存在")
        if ticket.assignee_id != actor.subject_id:
            raise TicketError(403, "not_assignee", "只有被指派的维修人可以开工")
        if ticket.status != "ASSIGNED" or ticket.version != data.expected_version:
            raise TicketError(409, "ticket_changed", "工单状态或版本已变化，请刷新后重试")

        # The M1 reader may make a network request. Release the read transaction
        # first, then use a conditional update to close the race after it returns.
        session.rollback()
        try:
            restriction.require_active(ticket_id, ticket.room_id)
        except TicketError:
            raise
        except Exception as exc:
            raise TicketError(503, "restriction_unconfirmed", "暂时无法确认教室已下架") from exc

        now = datetime.now(UTC)
        changed = session.execute(
            update(tickets)
            .where(
                tickets.c.id == ticket_id,
                tickets.c.status == "ASSIGNED",
                tickets.c.version == data.expected_version,
                tickets.c.assignee_id == actor.subject_id,
            )
            .values(status="REPAIRING", version=tickets.c.version + 1, updated_at=now)
        )
        if changed.rowcount != 1:
            session.rollback()
            existing = _event(session, ticket_id, operation_id)
            if existing is not None:
                return _replay(existing, actor, fingerprint), False
            raise TicketError(409, "ticket_changed", "工单状态或版本已变化，请刷新后重试")

        version = data.expected_version + 1
        session.execute(
            insert(ticket_events).values(
                id=str(uuid4()),
                ticket_id=ticket_id,
                operation_id=operation_id,
                action="start",
                actor_id=actor.subject_id,
                assignee_id=actor.subject_id,
                request_fingerprint=fingerprint,
                before_status="ASSIGNED",
                after_status="REPAIRING",
                version=version,
                occurred_at=now,
            )
        )
        try:
            audit.record_started(
                session,
                actor=actor,
                ticket_id=ticket_id,
                room_id=str(ticket.room_id),
                operation_id=operation_id,
                before_status="ASSIGNED",
                after_status="REPAIRING",
                now=now,
            )
        except Exception as exc:
            session.rollback()
            raise TicketError(503, "audit_unavailable", "暂时无法确认开工审计") from exc
        session.commit()
        return (
            WorkStartOut(
                ticket_id=ticket_id,
                assignee_id=actor.subject_id,
                status="REPAIRING",
                version=version,
                occurred_at=now,
            ),
            True,
        )
    except IntegrityError:
        session.rollback()
        try:
            existing = _event(session, ticket_id, operation_id)
            if existing is not None:
                return _replay(existing, actor, fingerprint), False
        except SQLAlchemyError as exc:
            raise TicketError(503, "storage_unavailable", "暂时无法确认开工结果") from exc
        raise TicketError(503, "storage_unavailable", "暂时无法确认开工结果") from None
    except SQLAlchemyError as exc:
        session.rollback()
        raise TicketError(503, "storage_unavailable", "暂时无法保存开工") from exc
