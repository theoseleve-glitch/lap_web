"""049 -- Add allow_double_stint column to race_drivers.

Revision ID: 049
Revises: 048
Create Date: 2026-03-16
"""

import sqlalchemy as sa
from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE race_drivers ADD COLUMN IF NOT EXISTS "
        "allow_double_stint BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade():
    op.drop_column("race_drivers", "allow_double_stint")
