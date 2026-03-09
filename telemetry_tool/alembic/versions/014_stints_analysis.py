"""Add stint_laps and tyre_degradation tables for detailed stint analysis.

Extends the existing stint_analysis table (from migration 001, which stores
aggregate stint statistics) with per-lap breakdown within stints and a
dedicated tyre degradation tracking table for modelling grip loss over time.

NOTE: stint_analysis already exists from 001_initial_schema; this migration
only creates the two new companion tables.

Revision ID: 014
Revises: 013
Create Date: 2026-02-27
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "014"
down_revision = "013"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # stint_laps — per-lap data within each stint, linking back to the
    # parent stint_analysis row.  Enables lap-by-lap pace fade charts,
    # fuel-corrected pace analysis, and tyre-life correlation.
    # ------------------------------------------------------------------
    op.create_table(
        "stint_laps",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "stint_id",
            sa.Integer,
            sa.ForeignKey("stint_analysis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lap_number", sa.Integer, nullable=False),
        sa.Column("lap_time_s", sa.Float, nullable=False),
        sa.Column("position_in_stint", sa.Integer, nullable=False),  # 1-based position within stint
        sa.Column("delta_to_stint_best_s", sa.Float),  # delta vs best lap in this stint
        sa.Column("delta_to_session_best_s", sa.Float),  # delta vs overall session best
        sa.Column("fuel_corrected_time_s", sa.Float),  # lap time after fuel weight correction
        sa.Column("tyre_age_laps", sa.Integer),  # total laps on current tyre set
        sa.Column("estimated_grip_pct", sa.Float),  # estimated grip level 0-100
        sa.Column("pace_trend_label", sa.Text),  # improving / stable / degrading
        sa.Column("is_outlier", sa.Boolean, server_default=sa.text("false")),
        sa.Column("outlier_reason", sa.Text),  # traffic, off-track, yellow_flag, etc.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "stint_id", "lap_number", name="uq_stint_laps_stint_lap"
        ),
    )
    op.create_index("ix_stint_laps_stint_id", "stint_laps", ["stint_id"])
    op.create_index("ix_stint_laps_session_id", "stint_laps", ["session_id"])

    # ------------------------------------------------------------------
    # tyre_degradation — per-session or per-stint degradation model,
    # tracking how tyre performance evolves over a stint/session.
    # Used for predicting tyre cliff, optimal pit stop timing, and
    # compound selection.
    # ------------------------------------------------------------------
    op.create_table(
        "tyre_degradation",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stint_id",
            sa.Integer,
            sa.ForeignKey("stint_analysis.id", ondelete="SET NULL"),
        ),
        sa.Column("compound", sa.Text),  # tyre compound name: soft/medium/hard/wet
        sa.Column("start_lap", sa.Integer, nullable=False),
        sa.Column("end_lap", sa.Integer, nullable=False),
        sa.Column("total_laps", sa.Integer, nullable=False),
        sa.Column("deg_rate_s_per_lap", sa.Float),  # linear degradation rate
        sa.Column("deg_rate_r_squared", sa.Float),  # fit quality of linear model
        sa.Column("quadratic_coeff", sa.Float),  # quadratic term for non-linear deg
        sa.Column("cliff_detected", sa.Boolean, server_default=sa.text("false")),
        sa.Column("cliff_lap", sa.Integer),  # lap number where cliff occurs
        sa.Column("cliff_severity_pct", sa.Float),  # % pace drop at cliff
        sa.Column("peak_grip_lap", sa.Integer),  # best grip after warm-up
        sa.Column("warm_up_laps", sa.Integer),  # laps to reach operating temperature
        sa.Column("initial_pace_s", sa.Float),  # pace at tyre peak grip
        sa.Column("final_pace_s", sa.Float),  # pace at end of stint
        sa.Column("total_deg_s", sa.Float),  # total seconds lost to degradation
        sa.Column("track_temp_c", sa.Float),  # track temperature during stint
        sa.Column("air_temp_c", sa.Float),  # air temperature during stint
        sa.Column("deg_curve_json", JSONB),  # per-lap [lap, time, grip_pct] array
        sa.Column("model_type", sa.Text, server_default="linear"),  # linear / quadratic / piecewise
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_tyre_degradation_session_id", "tyre_degradation", ["session_id"]
    )
    op.create_index("ix_tyre_degradation_stint_id", "tyre_degradation", ["stint_id"])
    op.create_index(
        "ix_tyre_degradation_compound", "tyre_degradation", ["compound"]
    )


def downgrade() -> None:
    op.drop_index("ix_tyre_degradation_compound", "tyre_degradation")
    op.drop_index("ix_tyre_degradation_stint_id", "tyre_degradation")
    op.drop_index("ix_tyre_degradation_session_id", "tyre_degradation")
    op.drop_table("tyre_degradation")
    op.drop_index("ix_stint_laps_session_id", "stint_laps")
    op.drop_index("ix_stint_laps_stint_id", "stint_laps")
    op.drop_table("stint_laps")
