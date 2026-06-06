"""066 — per-workspace elastic storage quota columns.

Adds storage_used_bytes (actual on-disk consumption, recomputed on upload/
delete/reconcile) and storage_allocation_bytes (the elastic allocation: 2 GiB
base, auto-grows +1 GiB at 80% — see web/storage_quota.py). Both additive +
defaulted, safe on existing rows. Chains off 065_remove_demo_tier.
"""
from alembic import op
import sqlalchemy as sa

revision = "066_workspace_storage_quota"
down_revision = "065_remove_demo_tier"
branch_labels = None
depends_on = None

_BASE_ALLOCATION = 2 * 1024 ** 3  # 2 GiB


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("storage_used_bytes", sa.BigInteger(), nullable=False,
                  server_default="0"),
    )
    op.add_column(
        "workspaces",
        sa.Column("storage_allocation_bytes", sa.BigInteger(), nullable=False,
                  server_default=str(_BASE_ALLOCATION)),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "storage_allocation_bytes")
    op.drop_column("workspaces", "storage_used_bytes")
