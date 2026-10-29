"""Add M3 assignment versioning and operation history on top of E-02."""

import sqlalchemy as sa

from alembic import op

revision = "e03_m3_assignment"
down_revision = "e02_m3_tickets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "m3_tickets", sa.Column("version", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("m3_tickets", sa.Column("assignee_id", sa.String(length=64), nullable=True))
    op.create_table(
        "m3_ticket_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "ticket_id", sa.String(length=36), sa.ForeignKey("m3_tickets.id"), nullable=False
        ),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("assignee_id", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("before_status", sa.String(length=32), nullable=False),
        sa.Column("after_status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ticket_id", "operation_id", name="uq_m3_ticket_event_operation"),
    )
    op.create_index(
        "ix_m3_ticket_events_ticket_version", "m3_ticket_events", ["ticket_id", "version"]
    )


def downgrade() -> None:
    op.drop_index("ix_m3_ticket_events_ticket_version", table_name="m3_ticket_events")
    op.drop_table("m3_ticket_events")
    op.drop_column("m3_tickets", "assignee_id")
    op.drop_column("m3_tickets", "version")
