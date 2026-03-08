"""028 – rollup tables for driver and track aggregate stats

Revision ID: 028
Revises: 027
Create Date: 2026-03-02
"""
from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS driver_stats_rollup (
            workspace_id  INTEGER NOT NULL REFERENCES workspaces(id),
            driver_id     INTEGER NOT NULL REFERENCES drivers(driver_id),
            session_count INTEGER NOT NULL DEFAULT 0,
            total_laps    INTEGER NOT NULL DEFAULT 0,
            best_time_s   DOUBLE PRECISION,
            avg_score     DOUBLE PRECISION,
            avg_consistency DOUBLE PRECISION,
            last_session_date DATE,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workspace_id, driver_id)
        )
    """))
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS track_stats_rollup (
            workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
            track_id        TEXT NOT NULL REFERENCES tracks(track_id),
            session_count   INTEGER NOT NULL DEFAULT 0,
            best_time_s     DOUBLE PRECISION,
            avg_score       DOUBLE PRECISION,
            last_session_date DATE,
            unique_drivers  INTEGER NOT NULL DEFAULT 0,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workspace_id, track_id)
        )
    """))

    # RLS policies
    op.execute(sa.text("ALTER TABLE driver_stats_rollup ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        "CREATE POLICY driver_stats_rollup_workspace ON driver_stats_rollup "
        "USING (workspace_id = current_setting('app.current_workspace_id')::int)"
    ))
    op.execute(sa.text("ALTER TABLE track_stats_rollup ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        "CREATE POLICY track_stats_rollup_workspace ON track_stats_rollup "
        "USING (workspace_id = current_setting('app.current_workspace_id')::int)"
    ))

    # Indexes
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_driver_rollup_ws "
        "ON driver_stats_rollup (workspace_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_track_rollup_ws "
        "ON track_stats_rollup (workspace_id)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS track_stats_rollup CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS driver_stats_rollup CASCADE"))
