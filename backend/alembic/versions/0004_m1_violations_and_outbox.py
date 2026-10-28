"""M1 no-show violations and the notification outbox.

Revision ID: 0004_m1_violations_and_outbox
Revises: 0003_m1_seat_state_events
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_m1_violations_and_outbox"
down_revision = "0003_m1_seat_state_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m1_violations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("reservation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_m1_violations"),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["m1_reservations.id"], name="fk_m1_violations_reservation_id_m1_reservations"
        ),
        sa.UniqueConstraint("reservation_id", name="uq_m1_violations_reservation_id"),
    )
    op.create_index("ix_m1_violations_user", "m1_violations", ["user_id", "occurred_at"])
    op.create_table(
        "m1_notification_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("reservation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_m1_notification_outbox"),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["m1_reservations.id"],
            name="fk_m1_notification_outbox_reservation_id_m1_reservations",
        ),
        sa.UniqueConstraint("reservation_id", "kind", name="uq_m1_notification_outbox_reservation_kind"),
    )
    op.create_index(
        "ix_m1_notification_outbox_pending", "m1_notification_outbox", ["dispatched_at", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_m1_notification_outbox_pending", table_name="m1_notification_outbox")
    op.drop_table("m1_notification_outbox")
    op.drop_index("ix_m1_violations_user", table_name="m1_violations")
    op.drop_table("m1_violations")
