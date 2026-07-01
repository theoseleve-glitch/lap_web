"""078 — track_racing_lines: global (RLS-free) store of computed optimal lines.

Same rationale as track_surfaces_global (052): derived from aggregate grip, so
no workspace_id / no RLS; k-anonymity is applied at READ time (Lane 3) via the
grip snapshot's contributor count. Chains off the live head 077.
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "078_track_racing_lines"
down_revision = "077_stripe_pending_entitlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "track_racing_lines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("track_id", sa.Text, nullable=False),
        sa.Column("vehicle_class", sa.Text, nullable=False, server_default="generic"),
        sa.Column("condition", sa.Text, nullable=False),           # dry|wet
        sa.Column("line_kind", sa.Text, nullable=False, server_default="optimal"),
        sa.Column("points", JSONB, nullable=True),                 # [{d,n,v}]
        sa.Column("solver_version", sa.Text, nullable=True),
        sa.Column("grip_snapshot_hash", sa.Text, nullable=True),
        sa.Column("n_laps_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("lap_time_s", sa.Float, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),  # ok|failed|pending
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("track_id", "vehicle_class", "condition", "line_kind",
                            name="uq_track_racing_line"),
    )
    op.create_index("idx_track_racing_lines_track", "track_racing_lines", ["track_id"])


def downgrade() -> None:
    op.drop_index("idx_track_racing_lines_track", table_name="track_racing_lines")
    op.drop_table("track_racing_lines")
