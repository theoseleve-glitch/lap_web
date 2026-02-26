"""Update unique constraints to be workspace-scoped.

Revision ID: 008
Revises: 007
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"


def upgrade() -> None:
    # drivers: unique driver_name per workspace
    op.drop_constraint("drivers_driver_name_key", "drivers", type_="unique")
    op.create_unique_constraint(
        "uq_drivers_workspace_name", "drivers",
        ["workspace_id", "driver_name"],
    )

    # tracks: unique track_id (fingerprint) per workspace
    op.drop_constraint("tracks_track_id_key", "tracks", type_="unique")
    op.create_unique_constraint(
        "uq_tracks_workspace_fingerprint", "tracks",
        ["workspace_id", "track_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_tracks_workspace_fingerprint", "tracks", type_="unique")
    op.create_unique_constraint("tracks_track_id_key", "tracks", ["track_id"])

    op.drop_constraint("uq_drivers_workspace_name", "drivers", type_="unique")
    op.create_unique_constraint("drivers_driver_name_key", "drivers", ["driver_name"])
