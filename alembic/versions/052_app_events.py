"""Create partitioned app_events table for frontend engagement tracking.

Stores page views, chart interactions, and other frontend events scoped
to a workspace. Uses RANGE partitioning on created_at for efficient
time-based queries and retention management. RLS enforces workspace
isolation using the same app.workspace_id pattern as all other tables.

Revision ID: 052
Revises: 051
"""
from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade():
    # -- Step 1: Create partitioned parent table --
    op.execute(
        """
        CREATE TABLE app_events (
            id          BIGSERIAL,
            workspace_id INTEGER NOT NULL,
            user_id      INTEGER NOT NULL,
            event_type   TEXT NOT NULL,
            properties   JSONB NOT NULL DEFAULT '{}',
            path         TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
        """
    )

    # -- Step 2: Create initial monthly partitions --
    op.execute(
        """
        CREATE TABLE app_events_2026_04
            PARTITION OF app_events
            FOR VALUES FROM ('2026-04-01') TO ('2026-05-01')
        """
    )
    op.execute(
        """
        CREATE TABLE app_events_2026_05
            PARTITION OF app_events
            FOR VALUES FROM ('2026-05-01') TO ('2026-06-01')
        """
    )

    # -- Step 3: Create indexes on the parent (propagate to partitions) --
    op.execute(
        """
        CREATE INDEX ix_app_events_ws_type_ts
            ON app_events (workspace_id, event_type, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_app_events_user_ts
            ON app_events (user_id, created_at)
        """
    )

    # -- Step 4: Enable RLS and create workspace isolation policy --
    op.execute("ALTER TABLE app_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY app_events_workspace_isolation ON app_events
        USING (workspace_id = current_setting('app.workspace_id')::integer)
        WITH CHECK (workspace_id = current_setting('app.workspace_id')::integer)
        """
    )


def downgrade():
    op.execute(
        "DROP POLICY IF EXISTS app_events_workspace_isolation ON app_events"
    )
    op.execute("ALTER TABLE app_events DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS app_events CASCADE")
