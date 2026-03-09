"""Initial PostgreSQL schema — all tables from SQLite schema v24.

Translates every table across phases 1-17 of the existing SQLite schema
into PostgreSQL DDL with proper types (JSONB, TIMESTAMP, etc.), foreign
key actions (CASCADE / SET NULL), and indexes for common query patterns.

Revision ID: 001
Revises: None
Create Date: 2026-02-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==================================================================
    # Phase 1: Core tables
    # ==================================================================

    op.create_table(
        "schema_version",
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("description", sa.Text),
    )

    op.create_table(
        "drivers",
        sa.Column("driver_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("driver_name", sa.Text, nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("notes", sa.Text),
    )

    # tracks references sessions for dry/wet ref — created as bare TEXT
    # initially; FK constraints added after sessions table exists.
    op.create_table(
        "tracks",
        sa.Column("track_id", sa.Text, primary_key=True),
        sa.Column("track_name", sa.Text, nullable=False),
        sa.Column("lap_length_m", sa.Float, nullable=False),
        sa.Column("bbox_lat_min", sa.Float),
        sa.Column("bbox_lat_max", sa.Float),
        sa.Column("bbox_lon_min", sa.Float),
        sa.Column("bbox_lon_max", sa.Float),
        sa.Column("start_lat", sa.Float),
        sa.Column("start_lon", sa.Float),
        sa.Column("sample_count", sa.Integer),
        sa.Column("lap_count", sa.Integer),
        sa.Column("has_joker", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("joker_distance_delta_m", sa.Float),
        sa.Column("joker_time_delta_s", sa.Float),
        sa.Column("dry_ref_session_id", sa.Text),
        sa.Column("wet_ref_session_id", sa.Text),
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

    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Text, primary_key=True),
        sa.Column("csv_filename", sa.Text, nullable=False),
        sa.Column(
            "driver_id",
            sa.Integer,
            sa.ForeignKey("drivers.driver_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "track_id",
            sa.Text,
            sa.ForeignKey("tracks.track_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_type", sa.Text, nullable=False, server_default="practice"
        ),
        sa.Column("track_state", sa.Text, nullable=False, server_default="dry"),
        sa.Column("session_date", sa.Text, nullable=False),
        sa.Column("n_laps", sa.Integer),
        sa.Column("best_lap_time_s", sa.Float),
        sa.Column("mean_lap_time_s", sa.Float),
        sa.Column("total_score", sa.Float),
        sa.Column("grade", sa.Text),
        sa.Column("weather_json", JSONB),
        sa.Column("notes", sa.Text),
        sa.Column("html_report_path", sa.Text),
        sa.Column("simulation_method", sa.Text),
        sa.Column("joker_lap_number", sa.Integer),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Now add deferred FKs from tracks -> sessions
    op.create_foreign_key(
        "fk_tracks_dry_ref_session",
        "tracks",
        "sessions",
        ["dry_ref_session_id"],
        ["session_id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tracks_wet_ref_session",
        "tracks",
        "sessions",
        ["wet_ref_session_id"],
        ["session_id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "laps",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lap_number", sa.Integer, nullable=False),
        sa.Column("lap_time_s", sa.Float),
        sa.Column("speed_mean_mps", sa.Float),
        sa.Column("speed_max_mps", sa.Float),
        sa.Column("braking_max_mps2", sa.Float),
        sa.Column("accel_max_mps2", sa.Float),
        sa.Column("line_length_m", sa.Float),
        sa.Column("is_valid", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_best", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("phase_id", sa.Integer),
        sa.Column("invalid_reason", sa.Text),
        sa.Column("is_joker", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("session_id", "lap_number", name="uq_laps_session_lap"),
    )

    op.create_table(
        "gps_traces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lap_number", sa.Integer, nullable=False),
        sa.Column("latitudes_json", JSONB, nullable=False),
        sa.Column("longitudes_json", JSONB, nullable=False),
        sa.Column("distances_json", JSONB, nullable=False),
        sa.Column("speeds_json", JSONB, nullable=False),
        sa.Column("accel_lat_json", JSONB),
        sa.Column("accel_long_json", JSONB),
        sa.UniqueConstraint(
            "session_id", "lap_number", name="uq_gps_traces_session_lap"
        ),
    )

    op.create_table(
        "score_details",
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("pace_score", sa.Float),
        sa.Column("pace_max", sa.Float),
        sa.Column("consistency_score", sa.Float),
        sa.Column("consistency_max", sa.Float),
        sa.Column("execution_score", sa.Float),
        sa.Column("execution_max", sa.Float),
        sa.Column("robustness_score", sa.Float),
        sa.Column("robustness_max", sa.Float),
        sa.Column("strengths_json", JSONB),
        sa.Column("weaknesses_json", JSONB),
        sa.Column("adaptation_score", sa.Float),
    )

    op.create_table(
        "condition_phases",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase_id", sa.Integer, nullable=False),
        sa.Column("lap_start", sa.Integer, nullable=False),
        sa.Column("lap_end", sa.Integer, nullable=False),
        sa.Column("label", sa.Text),
        sa.Column("confidence", sa.Float),
        sa.Column("median_pace_s", sa.Float),
        sa.UniqueConstraint(
            "session_id", "phase_id", name="uq_condition_phases_session_phase"
        ),
    )

    # ==================================================================
    # Phase 2: Weekends, track records, condition markers
    # ==================================================================

    op.create_table(
        "weekends",
        sa.Column("weekend_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text),
        sa.Column(
            "track_id",
            sa.Text,
            sa.ForeignKey("tracks.track_id", ondelete="SET NULL"),
        ),
        sa.Column("start_date", sa.Text),
        sa.Column("end_date", sa.Text),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "weekend_sessions",
        sa.Column(
            "weekend_id",
            sa.Integer,
            sa.ForeignKey("weekends.weekend_id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("session_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "track_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "track_id",
            sa.Text,
            sa.ForeignKey("tracks.track_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("record_time_s", sa.Float, nullable=False),
        sa.Column("record_holder", sa.Text),
        sa.Column("record_date", sa.Text),
        sa.Column("vehicle_class", sa.Text),
        sa.Column("source", sa.Text),
        sa.UniqueConstraint(
            "track_id", "vehicle_class", name="uq_track_records_track_class"
        ),
    )

    op.create_table(
        "condition_markers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lap_number", sa.Integer, nullable=False),
        sa.Column("new_state", sa.Text, nullable=False),
        sa.Column("notes", sa.Text),
        sa.UniqueConstraint(
            "session_id", "lap_number", name="uq_condition_markers_session_lap"
        ),
    )

    # ==================================================================
    # Phase 3: Driver profiles, progression, driving style
    # ==================================================================

    op.create_table(
        "driver_profiles",
        sa.Column(
            "driver_id",
            sa.Integer,
            sa.ForeignKey("drivers.driver_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("weight_kg", sa.Float),
        sa.Column("kart_class", sa.Text),
        sa.Column("experience_level", sa.Text),
        sa.Column("goals", sa.Text),
        sa.Column("preferred_tracks", sa.Text),
        sa.Column("custom_notes", sa.Text),
        sa.Column("email", sa.Text),
        sa.Column("phone", sa.Text),
        sa.Column("id_code", sa.Text),
        sa.Column("pace_delta_mean_s", sa.Float),
        sa.Column("consistency_rating", sa.Float),
        sa.Column("aggression_index", sa.Float),
        sa.Column("smoothness_index", sa.Float),
        sa.Column("improvement_trend", sa.Text),
        sa.Column("total_sessions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_laps", sa.Integer, nullable=False, server_default="0"),
        sa.Column("best_ever_time_s", sa.Float),
        sa.Column("best_ever_track_id", sa.Text),
        sa.Column("wet_skill_proxy", sa.Float),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "driver_progression",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "driver_id",
            sa.Integer,
            sa.ForeignKey("drivers.driver_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_date", sa.Text),
        sa.Column("track_id", sa.Text),
        sa.Column("pace_delta_s", sa.Float),
        sa.Column("consistency_cv_pct", sa.Float),
        sa.Column("aggression_index", sa.Float),
        sa.Column("smoothness_index", sa.Float),
        sa.Column("total_score", sa.Float),
        sa.Column("n_laps", sa.Integer),
        sa.UniqueConstraint(
            "driver_id", "session_id", name="uq_driver_progression_driver_session"
        ),
    )

    op.create_table(
        "driving_style_features",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "driver_id",
            sa.Integer,
            sa.ForeignKey("drivers.driver_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trail_braking_depth", sa.Float),
        sa.Column("brake_point_consistency", sa.Float),
        sa.Column("brake_pressure_buildup_rate", sa.Float),
        sa.Column("apex_speed_ratio", sa.Float),
        sa.Column("turn_in_aggressiveness", sa.Float),
        sa.Column("throttle_onset_delay_m", sa.Float),
        sa.Column("exit_acceleration_efficiency", sa.Float),
        sa.Column("line_variation_index", sa.Float),
        sa.Column("early_vs_late_stint_pace", sa.Float),
        sa.Column("smoothness_composite", sa.Float),
        sa.Column("style_label", sa.Text),
        sa.Column("style_confidence", sa.Float),
        sa.Column("strengths_json", JSONB),
        sa.Column("weaknesses_json", JSONB),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "driver_id", "session_id", name="uq_driving_style_driver_session"
        ),
    )

    # ==================================================================
    # Phase 4: Theoretical data, reference lines
    # ==================================================================

    op.create_table(
        "theoretical_data",
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("theoretical_time_s", sa.Float),
        sa.Column("actual_best_time_s", sa.Float),
        sa.Column("gap_pct", sa.Float),
        sa.Column("simulation_method", sa.Text),
        sa.Column("speed_profile_json", JSONB),
        sa.Column("distance_json", JSONB),
        sa.Column("metrics_json", JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "reference_lines",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("latitudes_json", JSONB, nullable=False),
        sa.Column("longitudes_json", JSONB, nullable=False),
        sa.Column("distances_json", JSONB, nullable=False),
        sa.Column("speeds_json", JSONB),
    )

    # ==================================================================
    # Phase 5: Visualization — sector decomposition
    # ==================================================================

    op.create_table(
        "session_sectors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sector_index", sa.Integer, nullable=False),
        sa.Column("distance_m", sa.Float, nullable=False),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("label", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "session_id", "sector_index", name="uq_session_sectors_session_sector"
        ),
    )

    # ==================================================================
    # Phase 6: Data health, session tags
    # ==================================================================

    op.create_table(
        "data_health",
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("gps_quality", sa.Float),
        sa.Column("accel_quality", sa.Float),
        sa.Column("channel_count", sa.Integer),
        sa.Column("missing_channels", sa.Text),
        sa.Column("data_gaps", sa.Integer),
        sa.Column("total_samples", sa.Integer),
        sa.Column("overall_score", sa.Float),
        sa.Column("report_json", JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "session_tags",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float),
        sa.Column("source", sa.Text, nullable=False, server_default="auto"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "session_id", "tag", name="uq_session_tags_session_tag"
        ),
    )

    # ==================================================================
    # Phase 7: Corner metrics, best practices, key corners
    # ==================================================================

    op.create_table(
        "corner_metrics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lap_number", sa.Integer, nullable=False),
        sa.Column("corner_id", sa.Integer, nullable=False),
        sa.Column("brake_point_m", sa.Float),
        sa.Column("brake_intensity", sa.Float),
        sa.Column("entry_speed_mps", sa.Float),
        sa.Column("apex_speed_mps", sa.Float),
        sa.Column("exit_speed_mps", sa.Float),
        sa.Column("throttle_onset_m", sa.Float),
        sa.Column("exit_accel_mps2", sa.Float),
        sa.Column("grip_utilization", sa.Float),
        sa.Column("time_loss_ms", sa.Float),
        sa.Column("coaching_hint", sa.Text),
        sa.UniqueConstraint(
            "session_id",
            "lap_number",
            "corner_id",
            name="uq_corner_metrics_session_lap_corner",
        ),
    )

    op.create_table(
        "corner_best_practices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "track_id",
            sa.Text,
            sa.ForeignKey("tracks.track_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("corner_id", sa.Integer, nullable=False),
        sa.Column("best_entry_mps", sa.Float),
        sa.Column("best_apex_mps", sa.Float),
        sa.Column("best_exit_mps", sa.Float),
        sa.Column("best_brake_m", sa.Float),
        sa.Column("best_throttle_onset_m", sa.Float),
        sa.Column("best_time_s", sa.Float),
        sa.Column("sample_count", sa.Integer, server_default="0"),
        sa.Column("source_sessions", sa.Text),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "track_id", "corner_id", name="uq_corner_best_practices_track_corner"
        ),
    )

    op.create_table(
        "track_key_corners",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "track_id",
            sa.Text,
            sa.ForeignKey("tracks.track_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("corner_id", sa.Integer, nullable=False),
        sa.Column("label", sa.Text),
        sa.Column("lat", sa.Float),
        sa.Column("lon", sa.Float),
        sa.Column("dist_m", sa.Float),
        sa.UniqueConstraint(
            "track_id", "corner_id", name="uq_track_key_corners_track_corner"
        ),
    )

    # ==================================================================
    # Phase 8: Session weather
    # ==================================================================

    op.create_table(
        "session_weather",
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("air_temp_c", sa.Float),
        sa.Column("track_temp_c", sa.Float),
        sa.Column("humidity_pct", sa.Float),
        sa.Column("wind_speed_mps", sa.Float),
        sa.Column("wind_dir_deg", sa.Float),
        sa.Column("pressure_hpa", sa.Float),
        sa.Column("weather_source", sa.Text),
        sa.Column("recorded_at", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ==================================================================
    # Phase 9: Vehicle setups, what-if scenarios
    # ==================================================================

    op.create_table(
        "vehicle_setups",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "driver_id",
            sa.Integer,
            sa.ForeignKey("drivers.driver_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("setup_name", sa.Text),
        sa.Column("front_pressure", sa.Float),
        sa.Column("rear_pressure", sa.Float),
        sa.Column("front_camber", sa.Float),
        sa.Column("rear_camber", sa.Float),
        sa.Column("ride_height_mm", sa.Float),
        sa.Column("spring_rate", sa.Float),
        sa.Column("weight_kg", sa.Float),
        sa.Column("fuel_load_kg", sa.Float),
        sa.Column("gear_ratios_json", JSONB),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "what_if_scenarios",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scenario_name", sa.Text),
        sa.Column("adjustments_json", JSONB),
        sa.Column("predicted_time_s", sa.Float),
        sa.Column("baseline_time_s", sa.Float),
        sa.Column("delta_s", sa.Float),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # ==================================================================
    # Phase 10: Annotations, dev plans, badges, dashboards, exports
    # ==================================================================

    op.create_table(
        "session_annotations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lap_number", sa.Integer),
        sa.Column("distance_m", sa.Float),
        sa.Column(
            "annotation_type", sa.Text, nullable=False, server_default="note"
        ),
        sa.Column("title", sa.Text),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("tags_json", JSONB),
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

    op.create_table(
        "development_plans",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "driver_id",
            sa.Integer,
            sa.ForeignKey("drivers.driver_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_name", sa.Text, nullable=False),
        sa.Column("template_id", sa.Text),
        sa.Column("level", sa.Text, nullable=False, server_default="intermediate"),
        sa.Column("weeks_json", JSONB, nullable=False),
        sa.Column("progress_json", JSONB),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("completed_at", sa.Text),
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

    op.create_table(
        "plan_drill_sessions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "plan_id",
            sa.Integer,
            sa.ForeignKey("development_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_index", sa.Integer, nullable=False),
        sa.Column("drill_index", sa.Integer, nullable=False),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "plan_id",
            "week_index",
            "drill_index",
            "session_id",
            name="uq_plan_drill_sessions_plan_week_drill_session",
        ),
    )

    op.create_table(
        "driver_badges",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "driver_id",
            sa.Integer,
            sa.ForeignKey("drivers.driver_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("badge_type", sa.Text, nullable=False),
        sa.Column("badge_name", sa.Text, nullable=False),
        sa.Column("badge_level", sa.Text),
        sa.Column("metadata_json", JSONB),
        sa.Column(
            "earned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "plan_id",
            sa.Integer,
            sa.ForeignKey("development_plans.id", ondelete="SET NULL"),
        ),
    )

    op.create_table(
        "custom_dashboards",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("driver_id", sa.Integer),
        sa.Column("dashboard_name", sa.Text, nullable=False),
        sa.Column("layout_json", JSONB, nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.text("false")),
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

    op.create_table(
        "export_templates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("template_name", sa.Text, nullable=False, unique=True),
        sa.Column("sections_json", JSONB, nullable=False),
        sa.Column("format", sa.Text, nullable=False, server_default="pdf"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ==================================================================
    # Phase 11: Stint analysis
    # ==================================================================

    op.create_table(
        "stint_analysis",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stint_number", sa.Integer, nullable=False),
        sa.Column("lap_start", sa.Integer, nullable=False),
        sa.Column("lap_end", sa.Integer, nullable=False),
        sa.Column("lap_count", sa.Integer, nullable=False),
        sa.Column("best_lap", sa.Integer),
        sa.Column("best_time_s", sa.Float),
        sa.Column("mean_time_s", sa.Float),
        sa.Column("median_time_s", sa.Float),
        sa.Column("std_time_s", sa.Float),
        sa.Column("cv_pct", sa.Float),
        sa.Column("pace_fade_pct", sa.Float),
        sa.Column("tyre_cliff_lap", sa.Integer),
        sa.Column("tyre_cliff_severity_pct", sa.Float),
        sa.Column("pace_trend_slope", sa.Float),
        sa.Column("coaching_hint", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "session_id", "stint_number", name="uq_stint_analysis_session_stint"
        ),
    )

    # ==================================================================
    # Phase 12: Streaming ingestion pipeline
    # ==================================================================

    op.create_table(
        "ingestion_jobs",
        sa.Column("job_id", sa.Text, primary_key=True),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("sha256", sa.Text),
        sa.Column("sha256_partial", sa.Text, nullable=False),
        sa.Column("encoding", sa.Text),
        sa.Column("delimiter", sa.Text),
        sa.Column("header_idx", sa.Integer),
        sa.Column("n_rows_total", sa.Integer),
        sa.Column("n_rows_loaded", sa.Integer, server_default="0"),
        sa.Column("n_chunks", sa.Integer, server_default="0"),
        sa.Column("cache_dir", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("elapsed_s", sa.Float),
        sa.Column("peak_rss_mb", sa.Float),
        sa.Column("throughput_mb_s", sa.Float),
    )

    # ==================================================================
    # Phase 13: Predefined catalogs, karts, track sectors
    # ==================================================================

    op.create_table(
        "predefined_tracks",
        sa.Column(
            "predefined_track_id", sa.Integer, primary_key=True, autoincrement=True
        ),
        sa.Column("country", sa.Text),
        sa.Column("track_name", sa.Text),
        sa.Column("city", sa.Text),
        sa.Column("region", sa.Text),
        sa.Column("layout_name", sa.Text),
        sa.Column("layout_length_m", sa.Float),
        sa.Column("direction", sa.Text),
        sa.Column("rental_available", sa.Boolean, server_default=sa.text("false")),
        sa.Column("owner_available", sa.Boolean, server_default=sa.text("false")),
        sa.Column("outdoor", sa.Boolean, server_default=sa.text("true")),
        sa.Column("data_quality", sa.Text),
        sa.Column("source_url", sa.Text),
    )

    op.create_table(
        "predefined_karts",
        sa.Column(
            "predefined_kart_id", sa.Integer, primary_key=True, autoincrement=True
        ),
        sa.Column("segment", sa.Text),
        sa.Column("manufacturer", sa.Text),
        sa.Column("model", sa.Text),
        sa.Column("model_year_start", sa.Integer),
        sa.Column("use_or_championship", sa.Text),
        sa.Column("engine", sa.Text),
        sa.Column("power_hp", sa.Float),
        sa.Column("engine_type", sa.Text),
        sa.Column("kart_weight_kg", sa.Float),
        sa.Column("top_speed_kmh", sa.Float),
        sa.Column("zero_to_100_s", sa.Float),
        sa.Column("power_to_weight", sa.Float),
        sa.Column("braking_g_est", sa.Float),
        sa.Column("lateral_g_est", sa.Float),
        sa.Column("weight_source", sa.Text),
    )

    op.create_table(
        "karts",
        sa.Column("kart_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "predefined_kart_id",
            sa.Integer,
            sa.ForeignKey("predefined_karts.predefined_kart_id", ondelete="SET NULL"),
        ),
        sa.Column("kart_name", sa.Text, nullable=False),
        sa.Column("manufacturer", sa.Text),
        sa.Column("model", sa.Text),
        sa.Column("engine", sa.Text),
        sa.Column("power_hp", sa.Float),
        sa.Column("kart_weight_kg", sa.Float),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "track_sectors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "track_id",
            sa.Text,
            sa.ForeignKey("tracks.track_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sector_index", sa.Integer, nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("distance_m", sa.Float),
        sa.Column("label", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "track_id", "sector_index", name="uq_track_sectors_track_sector"
        ),
    )

    # ==================================================================
    # Phase 14: Meteo geocoding cache
    # ==================================================================

    op.create_table(
        "predefined_track_coords",
        sa.Column("track_name", sa.Text, primary_key=True),
        sa.Column("city", sa.Text),
        sa.Column("country", sa.Text, server_default="FR"),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column(
            "geocoded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ==================================================================
    # Phase 15: Race strategy (endurance race management)
    # ==================================================================

    op.create_table(
        "race_configs",
        sa.Column("race_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_name", sa.Text, nullable=False),
        sa.Column("track_name", sa.Text),
        sa.Column("team_name", sa.Text),
        sa.Column("race_duration_s", sa.Integer, nullable=False),
        sa.Column("reference_weight_kg", sa.Float),
        sa.Column("desired_stints", sa.Integer, nullable=False, server_default="4"),
        sa.Column("fuel_autonomy_s", sa.Integer),
        sa.Column("min_pit_stop_s", sa.Integer, nullable=False, server_default="60"),
        sa.Column("pit_speed_kmh", sa.Float),
        sa.Column("pit_open_s", sa.Integer),
        sa.Column("pit_close_s", sa.Integer),
        sa.Column("empty_kart_kg", sa.Float),
        sa.Column("full_tank_kg", sa.Float),
        sa.Column("min_total_kart_kg", sa.Float),
        sa.Column(
            "weigh_on_pit_exit", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column("qualifying_duration_s", sa.Integer),
        sa.Column(
            "refuel_after_quali", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "mandatory_driver_change",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "refueling_allowed", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column("quick_pit_stop_s", sa.Integer),
        sa.Column("race_start_ts", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
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

    op.create_table(
        "race_drivers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("driver_name", sa.Text, nullable=False),
        sa.Column("driver_order", sa.Integer, nullable=False),
        sa.Column("min_stint_s", sa.Integer),
        sa.Column("max_stint_s", sa.Integer),
        sa.Column("min_cumulative_s", sa.Integer),
        sa.Column("max_cumulative_s", sa.Integer),
        sa.Column("min_rest_s", sa.Integer, nullable=False, server_default="0"),
        sa.Column("weight_kg", sa.Float),
        sa.Column("com_channel", sa.Text),
        sa.Column("color_hex", sa.Text),
    )

    op.create_table(
        "race_stints",
        sa.Column("stint_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stint_order", sa.Integer, nullable=False),
        sa.Column(
            "driver_id",
            sa.Integer,
            sa.ForeignKey("race_drivers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("planned_start_s", sa.Integer),
        sa.Column("planned_end_s", sa.Integer),
        sa.Column("planned_duration_s", sa.Integer),
        sa.Column("actual_start_s", sa.Integer),
        sa.Column("actual_end_s", sa.Integer),
        sa.Column("actual_duration_s", sa.Integer),
        sa.Column("fuel_at_start", sa.Float),
        sa.Column("fuel_at_end", sa.Float),
        sa.Column("ballast_kg", sa.Float),
        sa.Column("ballast_base_kg", sa.Float),
        sa.Column("ballast_fuel_offset_kg", sa.Float),
        sa.Column("fuel_burn_rate_kgs", sa.Float),
        sa.Column("notes", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="planned"),
    )

    op.create_table(
        "race_pit_stops",
        sa.Column("pit_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stint_id",
            sa.Integer,
            sa.ForeignKey("race_stints.stint_id", ondelete="SET NULL"),
        ),
        sa.Column("planned_at_s", sa.Integer),
        sa.Column("actual_at_s", sa.Integer),
        sa.Column("duration_s", sa.Integer),
        sa.Column("driver_change", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("refueled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("fuel_added_kg", sa.Float),
        sa.Column("ballast_changed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text),
        sa.Column("pit_type", sa.Text, nullable=False, server_default="full"),
    )

    op.create_table(
        "race_windows",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("window_type", sa.Text, nullable=False),
        sa.Column("label", sa.Text),
        sa.Column("start_s", sa.Integer, nullable=False),
        sa.Column("end_s", sa.Integer, nullable=False),
        sa.Column("refuel_allowed", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "driver_change_allowed", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column("window_order", sa.Integer, nullable=False, server_default="1"),
    )

    # ==================================================================
    # Phase 16: TeamTalk — race messages
    # ==================================================================

    op.create_table(
        "race_messages",
        sa.Column("msg_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("category", sa.Text, server_default="general"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # ==================================================================
    # Phase 17: Live Race Intelligence — neutralizations, rivals
    # ==================================================================

    op.create_table(
        "race_neutralizations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_s", sa.Integer, nullable=False),
        sa.Column("end_s", sa.Integer),
        sa.Column("reason", sa.Text, nullable=False, server_default="safety_car"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "race_rivals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("team_name", sa.Text, nullable=False),
        sa.Column("car_number", sa.Text, nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "race_rival_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer,
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rival_id",
            sa.Integer,
            sa.ForeignKey("race_rivals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("at_s", sa.Integer, nullable=False),
        sa.Column("detail", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ==================================================================
    # Indexes for common query patterns
    # ==================================================================

    # Sessions — lookups by driver, track, date
    op.create_index("ix_sessions_driver_id", "sessions", ["driver_id"])
    op.create_index("ix_sessions_track_id", "sessions", ["track_id"])
    op.create_index("ix_sessions_session_date", "sessions", ["session_date"])

    # Laps — lookups by session
    op.create_index("ix_laps_session_id", "laps", ["session_id"])

    # GPS traces — lookups by session
    op.create_index("ix_gps_traces_session_id", "gps_traces", ["session_id"])

    # Corner metrics — lookups by session and by corner
    op.create_index("ix_corner_metrics_session_id", "corner_metrics", ["session_id"])

    # Driver progression — lookups by driver
    op.create_index(
        "ix_driver_progression_driver_id", "driver_progression", ["driver_id"]
    )

    # Driving style features — lookups by driver
    op.create_index(
        "ix_driving_style_features_driver_id",
        "driving_style_features",
        ["driver_id"],
    )

    # Session tags — tag lookup
    op.create_index("ix_session_tags_session_id", "session_tags", ["session_id"])
    op.create_index("ix_session_tags_tag", "session_tags", ["tag"])

    # Session annotations — session lookup
    op.create_index(
        "ix_session_annotations_session_id", "session_annotations", ["session_id"]
    )

    # Weekend sessions — lookup by weekend
    op.create_index(
        "ix_weekend_sessions_weekend_id", "weekend_sessions", ["weekend_id"]
    )

    # Stint analysis — session lookup
    op.create_index("ix_stint_analysis_session_id", "stint_analysis", ["session_id"])

    # Race tables — race_id lookups
    op.create_index("ix_race_drivers_race_id", "race_drivers", ["race_id"])
    op.create_index("ix_race_stints_race_id", "race_stints", ["race_id"])
    op.create_index("ix_race_pit_stops_race_id", "race_pit_stops", ["race_id"])
    op.create_index("ix_race_windows_race_id", "race_windows", ["race_id"])
    op.create_index("ix_race_messages_race_id", "race_messages", ["race_id"])
    op.create_index(
        "ix_race_neutralizations_race_id", "race_neutralizations", ["race_id"]
    )
    op.create_index("ix_race_rivals_race_id", "race_rivals", ["race_id"])
    op.create_index(
        "ix_race_rival_events_race_id", "race_rival_events", ["race_id"]
    )
    op.create_index(
        "ix_race_rival_events_rival_id", "race_rival_events", ["rival_id"]
    )

    # Development plans — driver lookup
    op.create_index(
        "ix_development_plans_driver_id", "development_plans", ["driver_id"]
    )

    # Driver badges — driver lookup
    op.create_index("ix_driver_badges_driver_id", "driver_badges", ["driver_id"])

    # Ingestion jobs — status lookup
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])

    # Condition phases — session lookup
    op.create_index(
        "ix_condition_phases_session_id", "condition_phases", ["session_id"]
    )

    # Condition markers — session lookup
    op.create_index(
        "ix_condition_markers_session_id", "condition_markers", ["session_id"]
    )

    # Track records — track lookup
    op.create_index("ix_track_records_track_id", "track_records", ["track_id"])

    # Corner best practices — track lookup
    op.create_index(
        "ix_corner_best_practices_track_id", "corner_best_practices", ["track_id"]
    )

    # Track key corners — track lookup
    op.create_index(
        "ix_track_key_corners_track_id", "track_key_corners", ["track_id"]
    )

    # Track sectors — track lookup
    op.create_index("ix_track_sectors_track_id", "track_sectors", ["track_id"])

    # Vehicle setups — driver lookup
    op.create_index("ix_vehicle_setups_driver_id", "vehicle_setups", ["driver_id"])

    # What-if scenarios — session lookup
    op.create_index(
        "ix_what_if_scenarios_session_id", "what_if_scenarios", ["session_id"]
    )

    # Plan drill sessions — plan lookup
    op.create_index(
        "ix_plan_drill_sessions_plan_id", "plan_drill_sessions", ["plan_id"]
    )

    # Session sectors — session lookup
    op.create_index(
        "ix_session_sectors_session_id", "session_sectors", ["session_id"]
    )


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""

    # Phase 17 (depends on race_configs, race_rivals)
    op.drop_table("race_rival_events")
    op.drop_table("race_rivals")
    op.drop_table("race_neutralizations")

    # Phase 16 (depends on race_configs)
    op.drop_table("race_messages")

    # Phase 15 (race strategy — children first)
    op.drop_table("race_windows")
    op.drop_table("race_pit_stops")
    op.drop_table("race_stints")
    op.drop_table("race_drivers")
    op.drop_table("race_configs")

    # Phase 14
    op.drop_table("predefined_track_coords")

    # Phase 13
    op.drop_table("track_sectors")
    op.drop_table("karts")
    op.drop_table("predefined_karts")
    op.drop_table("predefined_tracks")

    # Phase 12
    op.drop_table("ingestion_jobs")

    # Phase 11
    op.drop_table("stint_analysis")

    # Phase 10 (children first)
    op.drop_table("export_templates")
    op.drop_table("custom_dashboards")
    op.drop_table("driver_badges")
    op.drop_table("plan_drill_sessions")
    op.drop_table("development_plans")
    op.drop_table("session_annotations")

    # Phase 9
    op.drop_table("what_if_scenarios")
    op.drop_table("vehicle_setups")

    # Phase 8
    op.drop_table("session_weather")

    # Phase 7
    op.drop_table("track_key_corners")
    op.drop_table("corner_best_practices")
    op.drop_table("corner_metrics")

    # Phase 6
    op.drop_table("session_tags")
    op.drop_table("data_health")

    # Phase 5
    op.drop_table("session_sectors")

    # Phase 4
    op.drop_table("reference_lines")
    op.drop_table("theoretical_data")

    # Phase 3
    op.drop_table("driving_style_features")
    op.drop_table("driver_progression")
    op.drop_table("driver_profiles")

    # Phase 2
    op.drop_table("condition_markers")
    op.drop_table("track_records")
    op.drop_table("weekend_sessions")
    op.drop_table("weekends")

    # Phase 1 (must drop FKs from tracks before dropping sessions)
    op.drop_table("condition_phases")
    op.drop_table("score_details")
    op.drop_table("gps_traces")
    op.drop_table("laps")

    # Drop deferred FKs from tracks -> sessions before dropping sessions
    op.drop_constraint("fk_tracks_dry_ref_session", "tracks", type_="foreignkey")
    op.drop_constraint("fk_tracks_wet_ref_session", "tracks", type_="foreignkey")

    op.drop_table("sessions")
    op.drop_table("tracks")
    op.drop_table("drivers")
    op.drop_table("schema_version")
