"""055 — Create track_surface_snapshots table for grip evolution tracking.

Stores point-in-time snapshots of the aggregate grip profile so we can
track how grip evolves across sessions, days, and weather changes.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "055"
down_revision = "054"


def upgrade():
    op.create_table(
        "track_surface_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("track_id", sa.Text, nullable=False),
        sa.Column("vehicle_class", sa.Text, nullable=False, server_default="car"),
        sa.Column("condition", sa.Text, nullable=False, server_default="dry"),
        sa.Column("session_count", sa.Integer, nullable=False),
        sa.Column(
            "snapshot_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("grip_profile", JSONB, nullable=False),
        sa.Column("session_id", sa.Text, nullable=True),
        sa.Column(
            "workspace_id",
            sa.Integer,
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text("current_setting('app.current_workspace_id')::integer"),
        ),
    )

    op.create_index(
        "idx_snapshots_track",
        "track_surface_snapshots",
        ["track_id", "vehicle_class", "condition"],
    )
    op.create_index(
        "idx_snapshots_workspace",
        "track_surface_snapshots",
        ["workspace_id"],
    )

    # RLS
    op.execute("ALTER TABLE track_surface_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY snapshots_tenant ON track_surface_snapshots "
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
    )


def downgrade():
    op.execute("DROP POLICY IF EXISTS snapshots_tenant ON track_surface_snapshots")
    op.drop_index("idx_snapshots_workspace", table_name="track_surface_snapshots")
    op.drop_index("idx_snapshots_track", table_name="track_surface_snapshots")
    op.drop_table("track_surface_snapshots")
