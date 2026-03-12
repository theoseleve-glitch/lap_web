"""Add workspace_members table and backfill from existing data.

Multiple modules (invites, GDPR tasks, leaderboard, billing, admin)
reference a ``workspace_members`` table that was never created.
Membership was previously inferred through workspace→team→team_members
joins, but the code expects a direct workspace_id→user_id mapping.

Revision ID: 045
Revises: 044
Create Date: 2026-03-12
"""
import sqlalchemy as sa

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.Integer,
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
    )
    op.create_index(
        "idx_workspace_members_user", "workspace_members", ["user_id"],
    )

    # Backfill: personal workspace owners
    op.execute(sa.text(
        "INSERT INTO workspace_members (workspace_id, user_id, role) "
        "SELECT id, owner_user_id, 'owner' "
        "FROM workspaces "
        "WHERE type = 'personal' AND owner_user_id IS NOT NULL "
        "ON CONFLICT (workspace_id, user_id) DO NOTHING"
    ))

    # Backfill: team workspace members (via workspaces → teams → team_members)
    op.execute(sa.text(
        "INSERT INTO workspace_members (workspace_id, user_id, role) "
        "SELECT w.id, tm.user_id, tm.role "
        "FROM workspaces w "
        "JOIN team_members tm ON w.owner_team_id = tm.team_id "
        "WHERE w.type = 'team' AND w.owner_team_id IS NOT NULL "
        "ON CONFLICT (workspace_id, user_id) DO NOTHING"
    ))

    # RLS policy
    op.execute(sa.text(
        "ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY"
    ))
    op.execute(sa.text(
        "CREATE POLICY workspace_members_workspace_isolation "
        "ON workspace_members "
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer)"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "DROP POLICY IF EXISTS workspace_members_workspace_isolation "
        "ON workspace_members"
    ))
    op.drop_table("workspace_members")
