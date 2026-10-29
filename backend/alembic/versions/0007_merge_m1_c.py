"""Join the existing M1 and C migration branches without rewriting history."""

revision = "0007_merge_m1_c"
down_revision = ("0006_m1_seat_restrictions", "0002_c_identity_approval")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
