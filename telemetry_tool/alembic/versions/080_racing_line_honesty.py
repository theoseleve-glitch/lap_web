"""080 — racing-line honesty layer: tier + provenance on track_racing_lines (spec C, §5).

Adds the honesty contract columns to the global racing-lines table (078):
  geometry_source : how the solved boundary was obtained
                    (gt_anchored_native | predicted | default) — mirrors
                    TrackSurface.boundary_source.
  tier            : optimal_line | speed_profile_only | refused — the trust
                    level a consumer may render. A ``speed_profile_only`` must
                    NEVER be drawn as a racing line (spec §5).
  provenance      : jsonb audit — laps_used, grip_confidence_summary, geometry
                    gates version, solver name/version, validation results,
                    warm-start source.

Global table, no workspace_id / no RLS (same rationale as 078). Chains off the
079 head. Existing rows get NULLs (nullable, like solver_version); the tier
decision in compute_racing_lines backfills on the next solve.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "080_racing_line_honesty"
down_revision = "079_track_geometry_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("track_racing_lines",
                  sa.Column("geometry_source", sa.Text, nullable=True))
    op.add_column("track_racing_lines",
                  sa.Column("tier", sa.Text, nullable=True))
    op.add_column("track_racing_lines",
                  sa.Column("provenance", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("track_racing_lines", "provenance")
    op.drop_column("track_racing_lines", "tier")
    op.drop_column("track_racing_lines", "geometry_source")
