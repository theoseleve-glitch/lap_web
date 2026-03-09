"""Add race strategy tables — race_strategies, race_alerts, race_compound_models.

Extends the existing race management schema (race_configs, race_stints, etc.
from migration 001) with higher-level strategy planning, real-time alert
tracking, and tyre-compound performance modelling for endurance races.

NOTE: race_stints already exists from 001_initial_schema; this migration
only creates the three new tables.

Revision ID: 011
Revises: 010
Create Date: 2026-02-27
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "011"
down_revision = "010"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # race_strategies — high-level strategy plans tied to a race config.
    # A single race may have multiple candidate strategies (e.g. "2-stop
    # aggressive", "3-stop conservative") that the team evaluates.
    # ------------------------------------------------------------------
    op.create_table(
        "race_strategies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("strategy_name", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("total_stints", sa.Integer, nullable=False),
        sa.Column("total_pit_stops", sa.Integer, nullable=False),
        sa.Column("estimated_race_time_s", sa.Float),
        sa.Column("estimated_fuel_kg", sa.Float),
        sa.Column("target_lap_time_s", sa.Float),
        sa.Column("stint_plan_json", JSONB),  # ordered list of {driver, laps, compound, fuel}
        sa.Column("pit_windows_json", JSONB),  # optimal pit windows per stop
        sa.Column("weather_scenario", sa.Text),  # dry / wet / mixed
        sa.Column("risk_level", sa.Text, server_default="medium"),  # low / medium / high
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_race_strategies_race_id", "race_strategies", ["race_id"])

    # ------------------------------------------------------------------
    # race_alerts — real-time alerts generated during a live race
    # (tyre degradation warning, fuel low, weather change, etc.).
    # ------------------------------------------------------------------
    op.create_table(
        "race_alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "strategy_id",
            sa.Integer,
            sa.ForeignKey("race_strategies.id", ondelete="SET NULL"),
        ),
        sa.Column("alert_type", sa.Text, nullable=False),  # fuel_low, tyre_deg, weather, pit_window, pace_drop, penalty
        sa.Column("severity", sa.Text, nullable=False, server_default="info"),  # info / warning / critical
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("message", sa.Text),
        sa.Column("race_time_s", sa.Integer),  # elapsed race time when alert fired
        sa.Column("lap_number", sa.Integer),
        sa.Column("driver_name", sa.Text),
        sa.Column("payload_json", JSONB),  # arbitrary context data
        sa.Column(
            "acknowledged",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("acknowledged_by", sa.Text),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_race_alerts_race_id", "race_alerts", ["race_id"])
    op.create_index("ix_race_alerts_type", "race_alerts", ["alert_type"])
    op.create_index("ix_race_alerts_severity", "race_alerts", ["severity"])

    # ------------------------------------------------------------------
    # race_compound_models — tyre/fuel compound degradation models used
    # to predict stint lengths and optimal pit windows.
    # ------------------------------------------------------------------
    op.create_table(
        "race_compound_models",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("compound_name", sa.Text, nullable=False),  # e.g. "soft", "medium", "hard", "wet"
        sa.Column("compound_code", sa.Text),  # short code like S/M/H/W
        sa.Column("expected_life_laps", sa.Integer),
        sa.Column("peak_grip_lap", sa.Integer),  # lap where grip is highest
        sa.Column("deg_rate_per_lap_s", sa.Float),  # seconds of pace lost per lap
        sa.Column("cliff_lap", sa.Integer),  # lap at which performance drops sharply
        sa.Column("cliff_severity_pct", sa.Float),
        sa.Column("optimal_temp_min_c", sa.Float),
        sa.Column("optimal_temp_max_c", sa.Float),
        sa.Column("warm_up_laps", sa.Integer, server_default="1"),
        sa.Column("fuel_effect_s_per_kg", sa.Float),  # lap time delta per kg of fuel
        sa.Column("deg_curve_json", JSONB),  # detailed per-lap degradation curve
        sa.Column("source", sa.Text),  # how model was built: "manual", "historical", "live_fit"
        sa.Column("sample_sessions", sa.Integer),  # number of sessions used to build model
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "race_id", "compound_name", name="uq_race_compound_models_race_compound"
        ),
    )
    op.create_index(
        "ix_race_compound_models_race_id", "race_compound_models", ["race_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_race_compound_models_race_id", "race_compound_models")
    op.drop_table("race_compound_models")
    op.drop_index("ix_race_alerts_severity", "race_alerts")
    op.drop_index("ix_race_alerts_type", "race_alerts")
    op.drop_index("ix_race_alerts_race_id", "race_alerts")
    op.drop_table("race_alerts")
    op.drop_index("ix_race_strategies_race_id", "race_strategies")
    op.drop_table("race_strategies")
