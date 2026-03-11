"""041 – gamification tables (driver_xp, achievements, drill_executions).

Adds XP/leveling, achievement tracking, and drill execution linking
for the development plans gamification system.
"""
from alembic import op

revision = "041"
down_revision = "040"


def upgrade():
    # ── driver_xp ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE driver_xp (
            id              SERIAL PRIMARY KEY,
            workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
            driver_id       INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
            total_xp        INTEGER NOT NULL DEFAULT 0,
            level           INTEGER NOT NULL DEFAULT 0,
            current_streak  INTEGER NOT NULL DEFAULT 0,
            longest_streak  INTEGER NOT NULL DEFAULT 0,
            last_session_date DATE,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, driver_id)
        );
    """)
    op.execute("CREATE INDEX ix_driver_xp_driver ON driver_xp (driver_id);")
    op.execute("ALTER TABLE driver_xp ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY driver_xp_workspace ON driver_xp
            USING (workspace_id = current_setting('app.workspace_id')::int);
    """)

    # ── achievements ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE achievements (
            id              SERIAL PRIMARY KEY,
            workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
            driver_id       INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
            achievement_key VARCHAR(64) NOT NULL,
            unlocked_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            session_id      INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
            UNIQUE (workspace_id, driver_id, achievement_key)
        );
    """)
    op.execute(
        "CREATE INDEX ix_achievements_driver ON achievements (driver_id, achievement_key);"
    )
    op.execute("ALTER TABLE achievements ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY achievements_workspace ON achievements
            USING (workspace_id = current_setting('app.workspace_id')::int);
    """)

    # ── drill_executions ───────────────────────────────────────
    op.execute("""
        CREATE TABLE drill_executions (
            id              SERIAL PRIMARY KEY,
            workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
            driver_id       INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
            plan_id         INTEGER NOT NULL REFERENCES development_plans(id) ON DELETE CASCADE,
            week_number     INTEGER NOT NULL,
            drill_index     INTEGER NOT NULL,
            session_id      INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
            status          VARCHAR(16) NOT NULL DEFAULT 'attempted'
                            CHECK (status IN ('attempted', 'completed', 'skipped')),
            notes           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, plan_id, week_number, drill_index, session_id)
        );
    """)
    op.execute("CREATE INDEX ix_drill_exec_plan ON drill_executions (plan_id);")
    op.execute("ALTER TABLE drill_executions ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY drill_exec_workspace ON drill_executions
            USING (workspace_id = current_setting('app.workspace_id')::int);
    """)

    # ── extend dev_plans ───────────────────────────────────────
    op.execute(
        "ALTER TABLE development_plans ADD COLUMN xp_earned INTEGER NOT NULL DEFAULT 0;"
    )


def downgrade():
    op.execute("ALTER TABLE development_plans DROP COLUMN IF EXISTS xp_earned;")
    op.execute("DROP TABLE IF EXISTS drill_executions CASCADE;")
    op.execute("DROP TABLE IF EXISTS achievements CASCADE;")
    op.execute("DROP TABLE IF EXISTS driver_xp CASCADE;")
