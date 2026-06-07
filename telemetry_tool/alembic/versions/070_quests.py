"""070 — quests: machine-verifiable per-driver quests (gamification Phase 2a)."""
from alembic import op

revision = "070_quests"
down_revision = "069_complete_rls_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS quests (
            id              SERIAL PRIMARY KEY,
            workspace_id    INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            driver_id       INTEGER NOT NULL,
            spec            JSONB NOT NULL,
            metric          TEXT NOT NULL,
            comparator      TEXT NOT NULL,
            target          DOUBLE PRECISION NOT NULL,
            baseline        DOUBLE PRECISION,
            human_text      TEXT NOT NULL,
            xp              INTEGER NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'active',
            focused         BOOLEAN NOT NULL DEFAULT false,
            source_session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ DEFAULT now(),
            completed_at    TIMESTAMPTZ,
            expires_at      TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_quests_driver_status "
        "ON quests (workspace_id, driver_id, status)"
    )
    op.execute("ALTER TABLE quests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE quests FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY quests_workspace_isolation ON quests
        USING (workspace_id = current_setting('app.current_workspace_id', true)::integer)
        WITH CHECK (workspace_id = current_setting('app.current_workspace_id', true)::integer)
    """)
    # Grants guarded so a dev DB without the roles still migrates (mirror 069_corner_mastery).
    op.execute("""
        DO $$ BEGIN
            GRANT SELECT, INSERT, UPDATE, DELETE ON quests TO telemetry_app;
            GRANT USAGE, SELECT ON SEQUENCE quests_id_seq TO telemetry_app;
        EXCEPTION WHEN undefined_object THEN NULL; END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS quests")
