"""039 -- Fix score_details CHECK constraints for adaptive weighting.

Migration 036 added CHECK constraints capping sub-scores at 25, but
the scoring system uses adaptive weights that normalize sub-scores to
sum to 100.  When categories like robustness are suppressed (e.g. for
practice sessions), the remaining categories scale above 25.

This migration replaces the <= 25 constraints with <= 100 (matching
the total score ceiling).  In qualifying mode, pace alone can reach
~59 after normalization, so the per-category cap must match TOTAL_MAX.

Revision ID: 039
Revises: 038
Create Date: 2026-03-11
"""
from sqlalchemy import text

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None

_OLD_CONSTRAINTS = [
    ("score_details", "chk_score_details_pace"),
    ("score_details", "chk_score_details_consistency"),
    ("score_details", "chk_score_details_execution"),
    ("score_details", "chk_score_details_robustness"),
]

_NEW_CONSTRAINTS = [
    (
        "score_details",
        "chk_score_details_pace",
        "pace_score IS NULL OR (pace_score >= 0 AND pace_score <= 100)",
    ),
    (
        "score_details",
        "chk_score_details_consistency",
        "consistency_score IS NULL OR (consistency_score >= 0 AND consistency_score <= 100)",
    ),
    (
        "score_details",
        "chk_score_details_execution",
        "execution_score IS NULL OR (execution_score >= 0 AND execution_score <= 100)",
    ),
    (
        "score_details",
        "chk_score_details_robustness",
        "robustness_score IS NULL OR (robustness_score >= 0 AND robustness_score <= 100)",
    ),
]


def upgrade():
    # Drop the old overly-restrictive constraints
    for table, name in _OLD_CONSTRAINTS:
        op.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))

    # Add widened constraints
    for table, name, expr in _NEW_CONSTRAINTS:
        op.execute(
            text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr}) NOT VALID")
        )


def downgrade():
    # Restore original constraints from migration 036
    for table, name, _ in _NEW_CONSTRAINTS:
        op.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))

    _ORIGINAL = [
        ("score_details", "chk_score_details_pace",
         "pace_score IS NULL OR (pace_score >= 0 AND pace_score <= 25)"),
        ("score_details", "chk_score_details_consistency",
         "consistency_score IS NULL OR (consistency_score >= 0 AND consistency_score <= 25)"),
        ("score_details", "chk_score_details_execution",
         "execution_score IS NULL OR (execution_score >= 0 AND execution_score <= 25)"),
        ("score_details", "chk_score_details_robustness",
         "robustness_score IS NULL OR (robustness_score >= 0 AND robustness_score <= 25)"),
    ]
    for table, name, expr in _ORIGINAL:
        op.execute(
            text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr}) NOT VALID")
        )
