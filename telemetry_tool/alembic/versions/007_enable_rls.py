"""Enable Row-Level Security on all tenant-scoped tables.

Revision ID: 007
Revises: 006
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"

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
    conn = op.get_bind()
    for table in TENANT_TABLES:
        conn.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        conn.execute(sa.text(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f"USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
            f"WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    for table in reversed(TENANT_TABLES):
        conn.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"'))
        conn.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
