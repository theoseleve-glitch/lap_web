"""085 -- grip anchor columns on corner_metrics.

Phase 1 of driving-pattern-recognition. Stores an honestly-labelled
"% of available grip used" alongside the legacy grip_utilization column,
which is deliberately left untouched (see the Phase 1 plan).

``grip_anchor_tier`` holds one of exactly four values (``grip_anchor.TIERS``):
``session_envelope_ellipse_fitted``, ``session_envelope_ellipse_default_p2``,
``driver_best_session``, ``refused``. The two ``session_envelope_*`` tiers are
deliberately NOT called "physics": their baseline is a per-speed-bin p95 of
|a_lat| computed from the SAME session's own laps, so the number is relative to
what that driver did on that day, never an absolute claim about the car's
limit. Anything rendering these columns must say so.

``grip_anchor_pct`` is NOT capped at 100: the baseline is a p95 percentile, so
exceeding it is expected and is the most diagnostic value available. Measured
on real kart telemetry the median is 101.51%.

DEPLOY ORDER MATTERS. ``db/queries.py``'s INSERT names these four columns
unconditionally, so code that ships before this revision is applied loses the
ENTIRE corner_metrics write for every session (all three writers swallow the
error). See ``docs/runbooks/grip-anchor-085-deploy.md``.
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
