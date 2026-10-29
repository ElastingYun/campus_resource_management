"""Create E-owned repair tickets without coupling to unpublished B/C tables."""

import sqlalchemy as sa

from alembic import op

revision = "e02_m3_tickets"
down_revision = "0006_m1_seat_restrictions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m3_tickets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("room_id", sa.BigInteger(), nullable=False),
        sa.Column("reporter_id", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("room_id > 0", name="ck_m3_tickets_room_positive"),
        sa.UniqueConstraint("reporter_id", "idempotency_key", name="uq_m3_ticket_reporter_key"),
    )
    op.create_index(
        "ix_m3_tickets_reporter_created",
        "m3_tickets",
        ["reporter_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_m3_tickets_reporter_created", table_name="m3_tickets")
    op.drop_table("m3_tickets")
