"""Audit table for geometry-gate rejections (spec A3).

Global operational table: no workspace_id, no RLS (same rationale as 078).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "079_track_geometry_audit"
down_revision = "078_track_racing_lines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "track_geometry_audit",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("track_id", sa.Text, nullable=False),
        sa.Column("vehicle_class", sa.Text, nullable=True),
        sa.Column("condition", sa.Text, nullable=True),
        sa.Column("gate", sa.Text, nullable=False),
        sa.Column("details", JSONB, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_track_geometry_audit_track", "track_geometry_audit",
                    ["track_id", "created_at"])


def downgrade() -> None:
    op.drop_table("track_geometry_audit")
