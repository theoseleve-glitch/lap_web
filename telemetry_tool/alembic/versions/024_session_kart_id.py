"""Add kart_id to sessions table.

Revision ID: 024
Revises: 023
Create Date: 2026-03-01
"""
from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("kart_id", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("sessions", "kart_id")
