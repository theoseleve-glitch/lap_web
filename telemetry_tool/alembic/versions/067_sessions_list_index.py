"""067 — composite index for the workspace session list.

The default session list filters ``deleted_at IS NULL``, is workspace-scoped
(RLS), and orders by ``session_date DESC``. Without a matching composite index
this degrades to a filtered scan + sort that worsens as a workspace accumulates
sessions — the "power user with hundreds of sessions times out" risk. The index
lets the planner satisfy filter + tenant-scope + ordering directly.

Additive + idempotent (CREATE INDEX IF NOT EXISTS), safe on existing data.
Chains off 066_workspace_storage_quota.
"""
from alembic import op

revision = "067_sessions_list_index"
down_revision = "066_workspace_storage_quota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_ws_active_date "
        "ON sessions (workspace_id, deleted_at, session_date DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sessions_ws_active_date")
