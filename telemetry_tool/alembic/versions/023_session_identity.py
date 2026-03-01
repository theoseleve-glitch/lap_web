"""Add session identity columns.

Revision ID: 023
Revises: 022
Create Date: 2026-03-01
"""
from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("source_filename", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("source_path", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("sessions", "source_path")
    op.drop_column("sessions", "source_filename")
    op.drop_column("sessions", "display_name")
