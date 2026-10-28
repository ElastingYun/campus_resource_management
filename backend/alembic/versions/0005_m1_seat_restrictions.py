"""M1 seat restrictions written back by M2 (approvals) and M3 (repairs).

Revision ID: 0005_m1_seat_restrictions
Revises: 0004_m1_violations_and_outbox
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_m1_seat_restrictions"
down_revision = "0004_m1_violations_and_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m1_seat_restrictions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("room_id", sa.BigInteger(), nullable=False),
        sa.Column("seat_id", sa.BigInteger(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.String(200), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.String(64), nullable=True),
        sa.Column("release_reason", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_m1_seat_restrictions"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], name="fk_m1_seat_restrictions_room_id_rooms"),
        sa.ForeignKeyConstraint(["seat_id"], ["seats.id"], name="fk_m1_seat_restrictions_seat_id_seats"),
        sa.UniqueConstraint("source_type", "source_id", name="uq_m1_seat_restrictions_source"),
        sa.CheckConstraint(
            "source_type IN ('m2_approval', 'm3_repair')", name="ck_m1_seat_restrictions_source_type"
        ),
        sa.CheckConstraint("status IN ('active', 'released')", name="ck_m1_seat_restrictions_status"),
        sa.CheckConstraint(
            "end_at IS NULL OR start_at < end_at", name="ck_m1_seat_restrictions_start_before_end"
        ),
        sa.CheckConstraint(
            "source_type <> 'm2_approval' OR end_at IS NOT NULL",
            name="ck_m1_seat_restrictions_approval_has_end",
        ),
    )
    op.create_index(
        "ix_m1_seat_restrictions_room_status", "m1_seat_restrictions", ["room_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_m1_seat_restrictions_room_status", table_name="m1_seat_restrictions")
    op.drop_table("m1_seat_restrictions")
