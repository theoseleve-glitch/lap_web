"""Update unique constraints to be workspace-scoped.

Revision ID: 008
Revises: 007
"""
import sqlalchemy as sa

from alembic import op

revision = "008"
down_revision = "007"


def upgrade() -> None:
    # drivers: unique driver_name per workspace
    op.drop_constraint("drivers_driver_name_key", "drivers", type_="unique")
    op.create_unique_constraint(
        "uq_drivers_workspace_name", "drivers",
        ["workspace_id", "driver_name"],
    )

    # tracks: add compound unique index for workspace-scoped track fingerprint
    # Note: track_id is the PRIMARY KEY, so we don't drop it — just add
    # a compound constraint alongside it for workspace-scoped uniqueness.
    op.create_unique_constraint(
        "uq_tracks_workspace_fingerprint", "tracks",
        ["workspace_id", "track_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_tracks_workspace_fingerprint", "tracks", type_="unique")
    # No need to restore tracks_track_id_key — it was never dropped (PK stays)

    op.drop_constraint("uq_drivers_workspace_name", "drivers", type_="unique")
    op.create_unique_constraint("drivers_driver_name_key", "drivers", ["driver_name"])
