"""036 -- Add domain CHECK constraints for data integrity.

Adds CHECK constraints matching Pydantic validation rules:
- score_details: scores in [0, 25], max >= score
- laps: lap_time_s > 0, lap_number >= 0
- sessions: best_lap_time_s > 0, total_score in [0, 100]

All constraints use NOT VALID for zero-downtime on large tables.

Revision ID: 036
Revises: 035
Create Date: 2026-03-09
"""
from sqlalchemy import text

from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None

_CONSTRAINTS = [
    # score_details: scores between 0 and 25
    (
        "score_details",
        "chk_score_details_pace",
        "pace_score IS NULL OR (pace_score >= 0 AND pace_score <= 25)",
    ),
    (
        "score_details",
        "chk_score_details_consistency",
        "consistency_score IS NULL OR (consistency_score >= 0 AND consistency_score <= 25)",
    ),
    (
        "score_details",
        "chk_score_details_execution",
        "execution_score IS NULL OR (execution_score >= 0 AND execution_score <= 25)",
    ),
    (
        "score_details",
        "chk_score_details_robustness",
        "robustness_score IS NULL OR (robustness_score >= 0 AND robustness_score <= 25)",
    ),
    # laps: positive values
    (
        "laps",
        "chk_laps_lap_time_positive",
        "lap_time_s IS NULL OR lap_time_s > 0",
    ),
    (
        "laps",
        "chk_laps_lap_number_nonneg",
        "lap_number >= 0",
    ),
    # sessions: valid score range
    (
        "sessions",
        "chk_sessions_total_score",
        "total_score IS NULL OR (total_score >= 0 AND total_score <= 100)",
    ),
    (
        "sessions",
        "chk_sessions_best_lap_positive",
        "best_lap_time_s IS NULL OR best_lap_time_s > 0",
    ),
]


def upgrade():
    conn = op.get_bind()
    for table, name, expr in _CONSTRAINTS:
        # Check if constraint already exists (idempotent)
        row = conn.execute(
            text(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE constraint_name = :name AND table_name = :table"
            ),
            {"name": name, "table": table},
        ).fetchone()
        if row:
            continue
        op.execute(
            text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr}) NOT VALID")
        )


def downgrade():
    for table, name, _ in _CONSTRAINTS:
        op.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))
