"""072 — Session gamification idempotency flag.

Adds ``sessions.gamification_applied`` (BOOLEAN NOT NULL DEFAULT false) so the
pipeline can gate base-session XP + comeback multiplier on first-process-only
without re-awarding on reprocess.

One-time backfill caveat
────────────────────────
All existing rows land with ``gamification_applied = false`` (the column
DEFAULT).  This means already-processed historical sessions will trigger the
base-XP + comeback award ONCE on their next reprocess.  This is an accepted
trade-off: the alternative (backfilling true for every row) would silently
suppress any future deliberate re-score after a data fix.  The caveat is
documented here so operators are aware of the single extra award on first
reprocess after deploying 072.
"""
from alembic import op

revision = "072_session_gamification_applied"
down_revision = "071_phase2b_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sessions "
        "ADD COLUMN IF NOT EXISTS gamification_applied BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE sessions DROP COLUMN IF EXISTS gamification_applied"
    )
