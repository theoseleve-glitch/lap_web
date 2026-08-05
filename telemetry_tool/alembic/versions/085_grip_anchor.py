"""085 -- grip anchor columns on corner_metrics.

Phase 1 of driving-pattern-recognition. Stores an honestly-labelled
"% of available grip used" alongside the legacy grip_utilization column,
which is deliberately left untouched (see the Phase 1 plan).

grip_anchor_pct is NOT capped at 100: the friction envelope is a percentile,
so exceeding it is expected and is the most diagnostic value available.
"""
from alembic import op
import sqlalchemy as sa

revision = "085_grip_anchor"
down_revision = "084_merge_chain_ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("corner_metrics", sa.Column("grip_anchor_tier", sa.Text(), nullable=True))
    op.add_column("corner_metrics", sa.Column("grip_anchor_reason", sa.Text(), nullable=True))
    op.add_column("corner_metrics", sa.Column("grip_anchor_pct", sa.Float(), nullable=True))
    op.add_column("corner_metrics", sa.Column("grip_anchor_baseline_g", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("corner_metrics", "grip_anchor_baseline_g")
    op.drop_column("corner_metrics", "grip_anchor_pct")
    op.drop_column("corner_metrics", "grip_anchor_reason")
    op.drop_column("corner_metrics", "grip_anchor_tier")
