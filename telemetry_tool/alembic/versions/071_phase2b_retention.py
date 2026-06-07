"""071 — Phase 2b retention: driver_xp.pit_passes + weekly_recap table."""
from alembic import op

revision = "071_phase2b_retention"
down_revision = "070_quests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE driver_xp ADD COLUMN IF NOT EXISTS pit_passes INTEGER NOT NULL DEFAULT 0")
    op.execute("""
        CREATE TABLE IF NOT EXISTS weekly_recap (
            id            SERIAL PRIMARY KEY,
            workspace_id  INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            driver_id     INTEGER NOT NULL,
            iso_week      TEXT NOT NULL,
            payload       JSONB NOT NULL,
            emailed       BOOLEAN NOT NULL DEFAULT false,
            created_at    TIMESTAMPTZ DEFAULT now(),
            UNIQUE (workspace_id, driver_id, iso_week)
        )
    """)
    op.execute("ALTER TABLE weekly_recap ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE weekly_recap FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY weekly_recap_workspace_isolation ON weekly_recap
        USING (workspace_id = current_setting('app.current_workspace_id', true)::integer)
        WITH CHECK (workspace_id = current_setting('app.current_workspace_id', true)::integer)
    """)
    # Grants guarded so a dev DB without the roles still migrates (mirror 070_quests).
    op.execute("""
        DO $$ BEGIN
            GRANT SELECT, INSERT, UPDATE, DELETE ON weekly_recap TO telemetry_app;
            GRANT USAGE, SELECT ON SEQUENCE weekly_recap_id_seq TO telemetry_app;
        EXCEPTION WHEN undefined_object THEN NULL; END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS weekly_recap")
    op.execute("ALTER TABLE driver_xp DROP COLUMN IF EXISTS pit_passes")
