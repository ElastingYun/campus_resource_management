"""M1 seat state event trail recording the source of every availability change.

Revision ID: 0003_m1_seat_state_events
Revises: 0002_m1_reservations
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_m1_seat_state_events"
down_revision = "0002_m1_reservations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m1_seat_state_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("room_id", sa.BigInteger(), nullable=False),
        sa.Column("seat_id", sa.BigInteger(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_m1_seat_state_events"),
        sa.CheckConstraint(
            "source_type IN ('m1_reservation', 'm2_approval', 'm3_repair')",
            name="ck_m1_seat_state_events_source_type",
        ),
    )
    op.create_index(
        "ix_m1_seat_state_events_room_time", "m1_seat_state_events", ["room_id", "occurred_at"]
    )
    op.create_index(
        "ix_m1_seat_state_events_source", "m1_seat_state_events", ["source_type", "source_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_m1_seat_state_events_source", table_name="m1_seat_state_events")
    op.drop_index("ix_m1_seat_state_events_room_time", table_name="m1_seat_state_events")
    op.drop_table("m1_seat_state_events")
