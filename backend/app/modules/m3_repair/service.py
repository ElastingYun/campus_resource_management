"""Ticket behavior and persistence, independent of B/C's unpublished adapters."""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.m3_repair.contracts import RoomPolicy, TicketActor, TicketAudit, TicketError
from app.modules.m3_repair.schemas import TicketCreate, TicketOut, TicketPage
from app.modules.m3_repair.tables import tickets


def _ticket_out(row) -> TicketOut:
    created_at = row.created_at
    if created_at.tzinfo is None:
        # SQLite drops timezone information in isolated tests; all stored values
        # originate from the UTC clock. PostgreSQL preserves the offset.
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)
    return TicketOut(
        id=row.id,
        room_id=str(row.room_id),
        description=row.description,
        status=row.status,
        created_at=created_at,
    )


def _fingerprint(room_id: str, description: str) -> str:
    return hashlib.sha256((room_id + "\0" + description).encode("utf-8")).hexdigest()


def _existing(session: Session, actor: TicketActor, key: str):
    return session.execute(
        select(tickets).where(
            tickets.c.reporter_id == actor.subject_id,
            tickets.c.idempotency_key == key,
        )
    ).one_or_none()


def _replay(row, fingerprint: str) -> TicketOut:
    if row.request_fingerprint != fingerprint:
        raise TicketError(409, "idempotency_key_reused", "请求标识已用于其他报修内容")
    return _ticket_out(row)


def create_ticket(
    session: Session,
    actor: TicketActor,
    room_policy: RoomPolicy,
    audit: TicketAudit,
    data: TicketCreate,
    key: str,
) -> tuple[TicketOut, bool]:
    if not actor.can_create:
        raise TicketError(403, "forbidden", "无权提交报修")
    fingerprint = _fingerprint(data.room_id, data.description)
    try:
        existing = _existing(session, actor, key)
        if existing is not None:
            return _replay(existing, fingerprint), False

        # Do not hold a database transaction while the approved B room reader
        # performs a network request. The unique key protects a concurrent win.
        session.rollback()
        # B/C must supply a trusted policy; this call may fail closed, not guess.
        room_policy.require_reportable(int(data.room_id), actor)
        now = datetime.now(UTC)
        ticket_id = str(uuid4())
        request_id = str(uuid4())
        session.execute(
            insert(tickets).values(
                id=ticket_id,
                room_id=int(data.room_id),
                reporter_id=actor.subject_id,
                description=data.description,
                status="REPORTED",
                idempotency_key=key,
                request_fingerprint=fingerprint,
                created_at=now,
                updated_at=now,
            )
        )
        try:
            audit.record_created(
                session,
                actor=actor,
                ticket_id=ticket_id,
                room_id=data.room_id,
                request_id=request_id,
                now=now,
            )
        except Exception as exc:
            session.rollback()
            raise TicketError(503, "audit_unavailable", "暂时无法确认报修审计") from exc
        session.commit()
        return (
            TicketOut(
                id=ticket_id,
                room_id=data.room_id,
                description=data.description,
                status="REPORTED",
                created_at=now,
            ),
            True,
        )
    except IntegrityError:
        # Two concurrent requests may both miss the first read. The unique
        # constraint chooses one winner; the other returns that same result.
        session.rollback()
        try:
            existing = _existing(session, actor, key)
            if existing is not None:
                return _replay(existing, fingerprint), False
        except SQLAlchemyError as exc:
            raise TicketError(503, "storage_unavailable", "暂时无法确认报修结果") from exc
        raise TicketError(503, "storage_unavailable", "暂时无法确认报修结果") from None
    except SQLAlchemyError as exc:
        session.rollback()
        raise TicketError(503, "storage_unavailable", "暂时无法保存报修") from exc


def list_own_tickets(session: Session, actor: TicketActor, limit: int, offset: int) -> TicketPage:
    if not actor.can_read_own:
        raise TicketError(403, "forbidden", "无权查看报修记录")
    try:
        rows = session.execute(
            select(tickets)
            .where(tickets.c.reporter_id == actor.subject_id)
            .order_by(tickets.c.created_at.desc(), tickets.c.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    except SQLAlchemyError as exc:
        raise TicketError(503, "storage_unavailable", "暂时无法查询报修记录") from exc
    return TicketPage(items=[_ticket_out(row) for row in rows], limit=limit, offset=offset)


def get_own_ticket(session: Session, actor: TicketActor, ticket_id: str) -> TicketOut:
    if not actor.can_read_own:
        raise TicketError(403, "forbidden", "无权查看报修记录")
    try:
        row = session.execute(
            select(tickets).where(
                tickets.c.id == ticket_id,
                tickets.c.reporter_id == actor.subject_id,
            )
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise TicketError(503, "storage_unavailable", "暂时无法查询报修记录") from exc
    if row is None:
        raise TicketError(404, "ticket_not_found", "报修记录不存在或不可见")
    return _ticket_out(row)
