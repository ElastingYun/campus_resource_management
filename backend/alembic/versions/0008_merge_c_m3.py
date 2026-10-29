"""Join the existing C and M3 migration heads without rewriting history."""

revision = "0008_merge_c_m3"
down_revision = ("0007_merge_m1_c", "e03_m3_assignment")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
