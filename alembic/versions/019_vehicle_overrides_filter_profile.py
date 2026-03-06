"""Add vehicle override and filter profile columns to sessions table.

Stores user-provided vehicle parameter overrides (mass, power, drag model)
and the resolved filter profile name/version used during analysis.

Idempotent: checks column existence before adding.

Revision ID: 019
Revises: 018
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """Check if a column already exists (idempotent migrations)."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _has_column("sessions", "override_mass_kg"):
        op.add_column("sessions", sa.Column("override_mass_kg", sa.Float(), nullable=True))
    if not _has_column("sessions", "override_power_kw"):
        op.add_column("sessions", sa.Column("override_power_kw", sa.Float(), nullable=True))
    if not _has_column("sessions", "override_drag_model"):
        op.add_column("sessions", sa.Column("override_drag_model", sa.String(32), nullable=True))
    if not _has_column("sessions", "filter_profile_name"):
        op.add_column("sessions", sa.Column("filter_profile_name", sa.String(64), nullable=True))
    if not _has_column("sessions", "filter_profile_version"):
        op.add_column("sessions", sa.Column("filter_profile_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    for col in ("filter_profile_version", "filter_profile_name",
                "override_drag_model", "override_power_kw", "override_mass_kg"):
        if _has_column("sessions", col):
            op.drop_column("sessions", col)
