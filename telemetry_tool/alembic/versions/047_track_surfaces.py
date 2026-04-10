"""047 — aggregate track surface model.

Stores per-meter grip and geometry properties aggregated across sessions.
Each session's grip_map output is incrementally merged into this table,
building a persistent physics model of each track.
"""
from alembic import op
import sqlalchemy as sa

revision = "047"
down_revision = "046"


def upgrade():
    op.create_table(
        "track_surfaces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("track_id", sa.Text, nullable=False),
        sa.Column("distance_m", sa.Float, nullable=False),
        # Lateral grip (from grip_map.py)
        sa.Column("mu_lat_p95", sa.Float, nullable=False),
        sa.Column("mu_lat_mean", sa.Float, nullable=False),
        # Longitudinal grip (from friction_envelope.py)
        sa.Column("mu_lon_accel", sa.Float, nullable=True),
        sa.Column("mu_lon_brake", sa.Float, nullable=True),
        # Geometry
        sa.Column("elevation_m", sa.Float, nullable=True),
        sa.Column("lateral_scatter_m", sa.Float, nullable=True),
        # Provenance
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("session_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_updated", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        # Workspace isolation
        sa.Column("workspace_id", sa.Integer,
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False,
                  server_default=sa.text("current_setting('app.current_workspace_id')::integer")),
        sa.UniqueConstraint("track_id", "distance_m", "workspace_id",
                            name="uq_track_surface_bin"),
    )
    op.create_index("idx_track_surfaces_track", "track_surfaces", ["track_id"])
    op.create_index("idx_track_surfaces_workspace", "track_surfaces", ["workspace_id"])
    op.create_index("idx_track_surfaces_lookup", "track_surfaces",
                    ["track_id", "workspace_id"])

    # RLS policy
    op.execute("""
        ALTER TABLE track_surfaces ENABLE ROW LEVEL SECURITY;
        CREATE POLICY track_surfaces_tenant_isolation ON track_surfaces
            USING (workspace_id = current_setting('app.current_workspace_id')::integer)
            WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer);
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS track_surfaces_tenant_isolation ON track_surfaces")
    op.drop_table("track_surfaces")
