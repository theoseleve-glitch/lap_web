"""030 -- Billing profiles for EU/FR VAT + invoice legal fields.

Adds billing_profiles table for storing company name, address, VAT ID,
and B2C/B2B type per workspace. Synced to Stripe on update.

Revision ID: 030
Revises: 029
Create Date: 2026-03-06
"""
from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("billing_type", sa.String(10), nullable=False, server_default="b2c"),  # b2c | b2b
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("vat_id", sa.String(50), nullable=True),
        sa.Column("address_line1", sa.String(255), nullable=True),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("state_region", sa.String(100), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),  # ISO 3166-1 alpha-2
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # RLS policy
    op.execute(
        "ALTER TABLE billing_profiles ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY billing_profiles_workspace_policy ON billing_profiles "
        "USING (workspace_id = current_setting('app.workspace_id', true)::int)"
    )


def downgrade():
    op.execute("DROP POLICY IF EXISTS billing_profiles_workspace_policy ON billing_profiles")
    op.execute("ALTER TABLE billing_profiles DISABLE ROW LEVEL SECURITY")
    op.drop_table("billing_profiles")
