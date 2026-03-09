"""Add kart session and maintenance tables — kart_sessions, kart_maintenance.

Extends the existing karts table (from migration 001) with session-level
kart assignment tracking and a maintenance log for tracking engine hours,
tyre changes, and other service events.

NOTE: karts already exists from 001_initial_schema; this migration only
creates the two new companion tables.

Revision ID: 012
Revises: 011
Create Date: 2026-02-27
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "012"
down_revision = "011"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # kart_sessions — links a kart to a telemetry session, recording
    # which physical kart was used for each session (rental number,
    # fleet assignment, etc.).
    # ------------------------------------------------------------------
    op.create_table(
        "kart_sessions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "kart_id",
            sa.Integer,
            sa.ForeignKey("karts.kart_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kart_number", sa.Text),  # fleet/rental number used that day
        sa.Column("tyre_compound", sa.Text),  # compound fitted at session start
        sa.Column("tyre_age_laps", sa.Integer),  # laps already on tyres at start
        sa.Column("fuel_level_pct", sa.Float),  # estimated fuel % at start
        sa.Column("ballast_kg", sa.Float),
        sa.Column("front_pressure_psi", sa.Float),
        sa.Column("rear_pressure_psi", sa.Float),
        sa.Column("sprocket_front", sa.Integer),
        sa.Column("sprocket_rear", sa.Integer),
        sa.Column("setup_notes", sa.Text),
        sa.Column("performance_notes", sa.Text),
        sa.Column("rating", sa.Integer),  # 1-5 subjective kart feel
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "kart_id", "session_id", name="uq_kart_sessions_kart_session"
        ),
    )
    op.create_index("ix_kart_sessions_kart_id", "kart_sessions", ["kart_id"])
    op.create_index("ix_kart_sessions_session_id", "kart_sessions", ["session_id"])

    # ------------------------------------------------------------------
    # kart_maintenance — service and maintenance log for karts.
    # Tracks engine hours, tyre swaps, chain/sprocket replacements,
    # crash repairs, etc.
    # ------------------------------------------------------------------
    op.create_table(
        "kart_maintenance",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "kart_id",
            sa.Integer,
            sa.ForeignKey("karts.kart_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("maintenance_type", sa.Text, nullable=False),  # engine_service, tyre_change, chain, crash_repair, general
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("performed_by", sa.Text),
        sa.Column("engine_hours_at", sa.Float),  # engine hour meter reading at service
        sa.Column("odometer_km", sa.Float),  # total distance at service
        sa.Column("cost", sa.Float),  # cost of parts/service
        sa.Column("currency", sa.Text, server_default="EUR"),
        sa.Column("parts_json", JSONB),  # list of {part_name, part_number, qty, cost}
        sa.Column("next_service_hours", sa.Float),  # target hours for next service
        sa.Column("next_service_date", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_kart_maintenance_kart_id", "kart_maintenance", ["kart_id"])
    op.create_index(
        "ix_kart_maintenance_type", "kart_maintenance", ["maintenance_type"]
    )
    op.create_index(
        "ix_kart_maintenance_performed_at", "kart_maintenance", ["performed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_kart_maintenance_performed_at", "kart_maintenance")
    op.drop_index("ix_kart_maintenance_type", "kart_maintenance")
    op.drop_index("ix_kart_maintenance_kart_id", "kart_maintenance")
    op.drop_table("kart_maintenance")
    op.drop_index("ix_kart_sessions_session_id", "kart_sessions")
    op.drop_index("ix_kart_sessions_kart_id", "kart_sessions")
    op.drop_table("kart_sessions")
