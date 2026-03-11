"""041 -- Corner progression tracking for coaching V3.

Stores per-corner metrics across sessions for trend detection
and multi-session coaching insights.

Revision ID: 041
Revises: 040
Create Date: 2026-03-11
"""
from sqlalchemy import text

from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS corner_progression (
            id              SERIAL PRIMARY KEY,
            workspace_id    INTEGER NOT NULL DEFAULT current_setting('app.current_workspace_id')::integer,
            driver_id       INTEGER NOT NULL,
            track_id        INTEGER NOT NULL,
            session_id      INTEGER NOT NULL,
            session_date    DATE NOT NULL,
            corner_id       INTEGER NOT NULL,
            apex_speed_mps      REAL,
            entry_speed_mps     REAL,
            exit_speed_mps      REAL,
            braking_point_m     REAL,
            time_loss_s         REAL,
            grip_utilisation_pct REAL,
            trail_brake_score   REAL,
            primary_cause       TEXT,
            theoretical_apex_mps  REAL,
            theoretical_entry_mps REAL,
            theoretical_exit_mps  REAL,
            created_at      TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
    """))

    # Indexes for trend queries
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_corner_prog_lookup
        ON corner_progression (driver_id, track_id, corner_id, session_date)
    """))

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_corner_prog_unique
        ON corner_progression (workspace_id, driver_id, track_id, session_id, corner_id)
    """))

    # RLS
    conn.execute(text(
        'ALTER TABLE corner_progression ENABLE ROW LEVEL SECURITY'
    ))
    conn.execute(text("""
        CREATE POLICY corner_progression_tenant_isolation
        ON corner_progression
        USING (workspace_id = current_setting('app.current_workspace_id')::integer)
        WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP POLICY IF EXISTS corner_progression_tenant_isolation ON corner_progression"))
    conn.execute(text("DROP TABLE IF EXISTS corner_progression"))
