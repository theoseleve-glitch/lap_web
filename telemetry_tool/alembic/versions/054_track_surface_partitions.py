"""054 — Add vehicle_class and condition partitioning to track surface tables.

Prevents mixing grip data from different car types or weather conditions
in the same aggregate bins.
"""
from alembic import op
import sqlalchemy as sa

revision = "054"
down_revision = "053"


def upgrade():
    # -- track_surfaces (workspace-scoped) --
    op.add_column("track_surfaces", sa.Column("vehicle_class", sa.Text, nullable=False, server_default="car"))
    op.add_column("track_surfaces", sa.Column("condition", sa.Text, nullable=False, server_default="dry"))
    op.drop_constraint("uq_track_surface_bin", "track_surfaces", type_="unique")
    op.create_unique_constraint(
        "uq_track_surface_bin",
        "track_surfaces",
        ["track_id", "distance_m", "vehicle_class", "condition", "workspace_id"],
    )

    # -- track_surfaces_global (cross-workspace) --
    op.add_column("track_surfaces_global", sa.Column("vehicle_class", sa.Text, nullable=False, server_default="car"))
    op.add_column("track_surfaces_global", sa.Column("condition", sa.Text, nullable=False, server_default="dry"))
    op.drop_constraint("uq_track_surface_global_bin", "track_surfaces_global", type_="unique")
    op.create_unique_constraint(
        "uq_track_surface_global_bin",
        "track_surfaces_global",
        ["track_id", "distance_m", "vehicle_class", "condition"],
    )


def downgrade():
    # -- track_surfaces_global --
    op.drop_constraint("uq_track_surface_global_bin", "track_surfaces_global", type_="unique")
    op.create_unique_constraint("uq_track_surface_global_bin", "track_surfaces_global", ["track_id", "distance_m"])
    op.drop_column("track_surfaces_global", "condition")
    op.drop_column("track_surfaces_global", "vehicle_class")

    # -- track_surfaces --
    op.drop_constraint("uq_track_surface_bin", "track_surfaces", type_="unique")
    op.create_unique_constraint("uq_track_surface_bin", "track_surfaces", ["track_id", "distance_m", "workspace_id"])
    op.drop_column("track_surfaces", "condition")
    op.drop_column("track_surfaces", "vehicle_class")
