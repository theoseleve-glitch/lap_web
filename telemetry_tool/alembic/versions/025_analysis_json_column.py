"""Add analysis_json column to sessions table.

This column stores supplementary analysis data (sector analysis,
corner coaching, theoretical lap, etc.) as a JSON blob. It existed
in the SQLite schema (db/schema.py) but was never added to
PostgreSQL via migration.

Revision ID: 025
Revises: 022
Create Date: 2026-03-01
"""
from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("analysis_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "analysis_json")
