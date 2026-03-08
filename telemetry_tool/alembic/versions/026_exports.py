"""exports table for async export jobs

Revision ID: 026
Revises: 025
Create Date: 2026-03-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("file_path", sa.Text),
        sa.Column("file_size", sa.BigInteger),
        sa.Column("filters", JSONB),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    # RLS policy for workspace isolation
    op.execute(sa.text("""
        ALTER TABLE exports ENABLE ROW LEVEL SECURITY;
        CREATE POLICY exports_workspace_isolation ON exports
            USING (workspace_id = current_setting('app.workspace_id')::integer);
    """))
    op.create_index("ix_exports_workspace_user", "exports", ["workspace_id", "user_id"])


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS exports_workspace_isolation ON exports"))
    op.drop_index("ix_exports_workspace_user")
    op.drop_table("exports")
