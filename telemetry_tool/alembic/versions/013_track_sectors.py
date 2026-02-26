"""Add sector_times table for per-lap sector timing data.

Extends the existing track_sectors table (from migration 001, which defines
sector boundary markers on a track) with per-lap sector split times. This
enables sector-level performance analysis, identifying which sectors a
driver gains or loses time in across laps and sessions.

NOTE: track_sectors already exists from 001_initial_schema; this migration
only creates the new sector_times table.

Revision ID: 013
Revises: 012
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # sector_times — per-lap timing for each sector boundary defined
    # in track_sectors.  One row per (session, lap, sector) triple.
    # ------------------------------------------------------------------
    op.create_table(
        "sector_times",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lap_number", sa.Integer, nullable=False),
        sa.Column(
            "sector_id",
            sa.Integer,
            sa.ForeignKey("track_sectors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sector_index", sa.Integer, nullable=False),  # denormalized for fast queries
        sa.Column("sector_time_s", sa.Float, nullable=False),  # time to traverse this sector
        sa.Column("cumulative_time_s", sa.Float),  # cumulative from sector 1 through this sector
        sa.Column("speed_entry_mps", sa.Float),  # speed at sector entry
        sa.Column("speed_exit_mps", sa.Float),  # speed at sector exit
        sa.Column("speed_min_mps", sa.Float),  # min speed within sector
        sa.Column("speed_max_mps", sa.Float),  # max speed within sector
        sa.Column("speed_mean_mps", sa.Float),  # average speed within sector
        sa.Column("delta_to_best_s", sa.Float),  # delta vs session-best sector time
        sa.Column("delta_to_theoretical_s", sa.Float),  # delta vs theoretical best
        sa.Column("is_personal_best", sa.Boolean, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "session_id",
            "lap_number",
            "sector_index",
            name="uq_sector_times_session_lap_sector",
        ),
    )
    op.create_index("ix_sector_times_session_id", "sector_times", ["session_id"])
    op.create_index("ix_sector_times_sector_id", "sector_times", ["sector_id"])
    op.create_index(
        "ix_sector_times_session_lap",
        "sector_times",
        ["session_id", "lap_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_sector_times_session_lap", "sector_times")
    op.drop_index("ix_sector_times_sector_id", "sector_times")
    op.drop_index("ix_sector_times_session_id", "sector_times")
    op.drop_table("sector_times")
