"""Add workspace_id column to all tenant-scoped data tables.

This migration adds workspace_id as NULLABLE. Migration 006 will
backfill existing data and make it NOT NULL.

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"

TENANT_TABLES = [
    "tracks", "drivers", "sessions", "laps", "gps_traces",
    "score_details", "condition_phases",
    "weekends", "weekend_sessions", "track_records", "condition_markers",
    "driver_profiles", "driver_progression", "driving_style_features",
    "theoretical_data", "reference_lines", "session_sectors",
    "data_health", "session_tags",
    "corner_metrics", "corner_best_practices", "track_key_corners",
    "session_weather",
    "vehicle_setups", "what_if_scenarios",
    "session_annotations", "development_plans", "plan_drill_sessions",
    "driver_badges", "custom_dashboards", "export_templates",
    "stint_analysis", "ingestion_jobs",
    "karts", "track_sectors",
    "race_configs", "race_drivers", "race_stints", "race_pit_stops",
    "race_windows", "race_messages",
    "race_neutralizations", "race_rivals", "race_rival_events",
]


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.add_column(table, sa.Column("workspace_id", sa.Integer, nullable=True))
        op.create_index(f"idx_{table}_workspace", table, ["workspace_id"])


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.drop_index(f"idx_{table}_workspace", table_name=table)
        op.drop_column(table, "workspace_id")
