"""Add workspace, team, and team_members tables.

Revision ID: 004
Revises: 003
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"


def upgrade() -> None:
    # Teams
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column("owner_user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("billing_plan", sa.Text, server_default="free"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # Workspaces (data isolation boundary)
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("type", sa.Text, nullable=False),  # 'personal' or 'team'
        sa.Column("owner_user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("owner_team_id", sa.Integer,
                  sa.ForeignKey("teams.id", ondelete="CASCADE")),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.CheckConstraint(
            "owner_user_id IS NOT NULL OR owner_team_id IS NOT NULL",
            name="ck_workspace_has_owner",
        ),
    )
    op.create_index("idx_workspace_user", "workspaces", ["owner_user_id"])
    op.create_index("idx_workspace_team", "workspaces", ["owner_team_id"])

    # Team members (join table with role)
    op.create_table(
        "team_members",
        sa.Column("team_id", sa.Integer,
                  sa.ForeignKey("teams.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default="member"),
        sa.Column("invited_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("accepted_at", sa.DateTime),
        sa.PrimaryKeyConstraint("team_id", "user_id"),
    )

    # Audit log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer,
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE")),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("entity_type", sa.Text),
        sa.Column("entity_id", sa.Integer),
        sa.Column("old_value", sa.Text),
        sa.Column("new_value", sa.Text),
        sa.Column("ip_address", sa.Text),
        sa.Column("request_id", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_audit_workspace", "audit_log", ["workspace_id"])
    op.create_index("idx_audit_created", "audit_log", ["created_at"])

    # Add default_workspace_id to users
    op.add_column("users", sa.Column("default_workspace_id", sa.Integer))


def downgrade() -> None:
    op.drop_column("users", "default_workspace_id")
    op.drop_table("audit_log")
    op.drop_table("team_members")
    op.drop_table("workspaces")
    op.drop_table("teams")
