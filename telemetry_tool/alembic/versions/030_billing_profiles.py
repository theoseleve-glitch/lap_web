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
    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_profiles (
            id SERIAL PRIMARY KEY,
            workspace_id INTEGER NOT NULL UNIQUE REFERENCES workspaces(id) ON DELETE CASCADE,
            billing_type VARCHAR(10) NOT NULL DEFAULT 'b2c',
            company_name VARCHAR(255),
            vat_id VARCHAR(50),
            address_line1 VARCHAR(255),
            address_line2 VARCHAR(255),
            city VARCHAR(100),
            postal_code VARCHAR(20),
            state_region VARCHAR(100),
            country_code VARCHAR(2),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # RLS policy (idempotent)
    op.execute(
        "ALTER TABLE billing_profiles ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS billing_profiles_workspace_policy ON billing_profiles"
    )
    op.execute(
        "CREATE POLICY billing_profiles_workspace_policy ON billing_profiles "
        "USING (workspace_id = current_setting('app.workspace_id', true)::int)"
    )


def downgrade():
    op.execute("DROP POLICY IF EXISTS billing_profiles_workspace_policy ON billing_profiles")
    op.execute("ALTER TABLE billing_profiles DISABLE ROW LEVEL SECURITY")
    op.drop_table("billing_profiles")
