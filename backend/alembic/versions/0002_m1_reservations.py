"""M1 reservations with a no-double-booking exclusion constraint, and M1 settings.

Revision ID: 0002_m1_reservations
Revises: 0001_resources_placeholder
Create Date: 2026-10-27
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_m1_reservations"
down_revision = "0001_resources_placeholder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # btree_gist lets one GiST exclusion constraint mix "=" on seat_id with "&&"
    # on time ranges. It is a trusted extension, so the database owner may create it.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "m1_reservations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("seat_id", sa.BigInteger(), nullable=False),
        sa.Column("room_id", sa.BigInteger(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_m1_reservations"),
        sa.ForeignKeyConstraint(["seat_id"], ["seats.id"], name="fk_m1_reservations_seat_id_seats"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], name="fk_m1_reservations_room_id_rooms"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_m1_reservations_user_idem"),
        sa.CheckConstraint(
            "status IN ('booked', 'checked_in', 'cancelled', 'no_show')",
            name="ck_m1_reservations_status",
        ),
        sa.CheckConstraint("start_at < end_at", name="ck_m1_reservations_start_before_end"),
    )
    op.create_index("ix_m1_reservations_user_start", "m1_reservations", ["user_id", "start_at"])
    op.create_index("ix_m1_reservations_status_start", "m1_reservations", ["status", "start_at"])
    # Final guard against double booking: concurrent inserts that pass the
    # application check still cannot both commit an overlapping active interval.
    op.execute(
        """
        ALTER TABLE m1_reservations
        ADD CONSTRAINT ex_m1_reservations_seat_overlap
        EXCLUDE USING gist (seat_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)
        WHERE (status IN ('booked', 'checked_in'))
        """
    )
    op.create_table(
        "m1_settings",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("key", name="pk_m1_settings"),
    )


def downgrade() -> None:
    op.drop_table("m1_settings")
    op.drop_index("ix_m1_reservations_status_start", table_name="m1_reservations")
    op.drop_index("ix_m1_reservations_user_start", table_name="m1_reservations")
    op.drop_table("m1_reservations")
    # btree_gist is left installed: other modules may rely on it.
