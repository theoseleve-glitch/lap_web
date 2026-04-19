"""052 — global track surface aggregate (cross-workspace).

Same schema as track_surfaces but without workspace_id or RLS.
Aggregates grip data across all workspaces for richer models.
"""
from alembic import op
import sqlalchemy as sa

revision = "052"
down_revision = "051"


def upgrade():
    op.create_table(
        "track_surfaces_global",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("track_id", sa.Text, nullable=False),
        sa.Column("distance_m", sa.Float, nullable=False),
        sa.Column("mu_lat_p95", sa.Float, nullable=False),
        sa.Column("mu_lat_mean", sa.Float, nullable=False),
        sa.Column("mu_lon_accel", sa.Float, nullable=True),
        sa.Column("mu_lon_brake", sa.Float, nullable=True),
        sa.Column("elevation_m", sa.Float, nullable=True),
        sa.Column("lateral_scatter_m", sa.Float, nullable=True),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("session_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_updated", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("track_id", "distance_m",
                            name="uq_track_surface_global_bin"),
    )
    op.create_index("idx_track_surfaces_global_track", "track_surfaces_global", ["track_id"])


def downgrade():
    op.drop_table("track_surfaces_global")
