"""027 – composite indexes for workspace-scoped queries

Revision ID: 027
Revises: 026
Create Date: 2026-03-02
"""
import sqlalchemy as sa

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_sessions_ws_date "
        "ON sessions (workspace_id, session_date DESC)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_sessions_ws_driver "
        "ON sessions (workspace_id, driver_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_sessions_ws_track "
        "ON sessions (workspace_id, track_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_laps_session_lap "
        "ON laps (session_id, lap_number)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_gps_session_lap "
        "ON gps_traces (session_id, lap_number)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS idx_sessions_ws_date"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_sessions_ws_driver"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_sessions_ws_track"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_laps_session_lap"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_gps_session_lap"))
