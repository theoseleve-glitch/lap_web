"""069 — corner_mastery: per-corner star tiers (gamification Phase 1).

first_session_id is ON DELETE SET NULL: mastery is DRIVER progress and must
survive the achieving session's deletion. workspace_id CASCADEs with the
workspace and the table is ALSO listed in CASCADE_CONFIG["workspace"] for the
GDPR purge (next task). RLS uses the canonical app.current_workspace_id GUC.
"""
from alembic import op

revision = "069_corner_mastery"
down_revision = "068_fk_child_read_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS corner_mastery (
            id              SERIAL PRIMARY KEY,
            workspace_id    INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            driver_id       INTEGER NOT NULL,
            track_id        TEXT NOT NULL,
            corner_id       INTEGER NOT NULL,
            condition       TEXT NOT NULL DEFAULT 'dry',
            tier            TEXT NOT NULL DEFAULT 'none',
            best_score      DOUBLE PRECISION NOT NULL DEFAULT 0,
            sessions_at_silver JSONB NOT NULL DEFAULT '[]',
            first_session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
            achieved_at     TIMESTAMPTZ,
            updated_at      TIMESTAMPTZ DEFAULT now(),
            UNIQUE (workspace_id, driver_id, track_id, corner_id, condition)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_corner_mastery_driver "
        "ON corner_mastery (workspace_id, driver_id, track_id)"
    )
    op.execute("ALTER TABLE corner_mastery ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE corner_mastery FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY corner_mastery_workspace_isolation ON corner_mastery
        USING (workspace_id = current_setting('app.current_workspace_id', true)::integer)
        WITH CHECK (workspace_id = current_setting('app.current_workspace_id', true)::integer)
    """)
    # Grants guarded so a dev DB without the roles still migrates (mirror 064).
    op.execute("""
        DO $$ BEGIN
            GRANT SELECT, INSERT, UPDATE, DELETE ON corner_mastery TO telemetry_app;
            GRANT USAGE, SELECT ON SEQUENCE corner_mastery_id_seq TO telemetry_app;
        EXCEPTION WHEN undefined_object THEN NULL; END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corner_mastery")
