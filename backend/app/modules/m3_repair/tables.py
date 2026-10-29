"""M3-owned storage; production schema is created only by Alembic migration."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)

from app.database import Base

tickets = Table(
    "m3_tickets",
    Base.metadata,
    Column("id", String(36), primary_key=True),
    # No FK to B's table until ownership and migration ordering are agreed.
    Column("room_id", BigInteger, nullable=False),
    Column("reporter_id", String(64), nullable=False),
    Column("description", String(2000), nullable=False),
    Column("status", String(32), nullable=False),
    Column("version", Integer, nullable=False, server_default="0"),
    Column("assignee_id", String(64), nullable=True),
    Column("idempotency_key", String(128), nullable=False),
    Column("request_fingerprint", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("room_id > 0", name="room_positive"),
    UniqueConstraint("reporter_id", "idempotency_key", name="uq_m3_ticket_reporter_key"),
    Index("ix_m3_tickets_reporter_created", "reporter_id", "created_at", "id"),
)

ticket_events = Table(
    "m3_ticket_events",
    Base.metadata,
    Column("id", String(36), primary_key=True),
    Column("ticket_id", String(36), ForeignKey("m3_tickets.id"), nullable=False),
    Column("operation_id", String(36), nullable=False),
    Column("action", String(32), nullable=False),
    Column("actor_id", String(64), nullable=False),
    Column("assignee_id", String(64), nullable=False),
    Column("request_fingerprint", String(64), nullable=False),
    Column("before_status", String(32), nullable=False),
    Column("after_status", String(32), nullable=False),
    Column("version", Integer, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("ticket_id", "operation_id", name="uq_m3_ticket_event_operation"),
    Index("ix_m3_ticket_events_ticket_version", "ticket_id", "version"),
)
