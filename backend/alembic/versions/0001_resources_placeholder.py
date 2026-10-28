"""Provisional rooms and seats master data (owner: B, written by A for M1).

Revision ID: 0001_resources_placeholder
Revises:
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_resources_placeholder"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("access_scope", sa.String(16), nullable=False),
        sa.Column("department_id", sa.String(64), nullable=True),
        sa.Column("open_time", sa.Time(), nullable=False),
        sa.Column("close_time", sa.Time(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_rooms"),
        sa.UniqueConstraint("code", name="uq_rooms_code"),
        sa.CheckConstraint("access_scope IN ('campus', 'department')", name="ck_rooms_access_scope"),
        sa.CheckConstraint(
            "access_scope = 'campus' OR department_id IS NOT NULL",
            name="ck_rooms_department_scope_has_id",
        ),
        sa.CheckConstraint("open_time < close_time", name="ck_rooms_open_before_close"),
    )
    op.create_table(
        "seats",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("room_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("outlet_type", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_seats"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], name="fk_seats_room_id_rooms"),
        sa.UniqueConstraint("room_id", "code", name="uq_seats_room_id_code"),
        sa.CheckConstraint("outlet_type IN ('none', 'fixed', 'rail')", name="ck_seats_outlet_type"),
    )
    op.create_index("ix_seats_room_id", "seats", ["room_id"])


def downgrade() -> None:
    op.drop_index("ix_seats_room_id", table_name="seats")
    op.drop_table("seats")
    op.drop_table("rooms")
