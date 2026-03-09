"""034 -- Force RLS on table owners.

By default, PostgreSQL row-level security policies do not apply to the
table owner.  Since the application connects as the table owner (the
``telemetry`` role), RLS was silently bypassed in production.

``ALTER TABLE ... FORCE ROW LEVEL SECURITY`` makes the policies apply
even to the owner, closing the privilege escalation gap identified in
audit item #1093.

Revision ID: 034
Revises: 033
Create Date: 2026-03-09
"""
from sqlalchemy import text

from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None

# All tables that have RLS enabled across migrations 007, 017, 019, 021, 026, 028, 030
RLS_TABLES = [
    # From 007
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
    # From 017
    "session_weather_laps",
    # From 021
    "support_tickets", "usage_counters",
    # From 026
    "exports",
    # From 028
    "driver_stats_rollup", "track_stats_rollup",
    # From 030
    "billing_profiles",
]


def upgrade() -> None:
    conn = op.get_bind()
    for table in RLS_TABLES:
        # FORCE makes RLS apply even to the table owner role
        conn.execute(text(f'ALTER TABLE IF EXISTS "{table}" FORCE ROW LEVEL SECURITY'))


def downgrade() -> None:
    conn = op.get_bind()
    for table in reversed(RLS_TABLES):
        conn.execute(text(f'ALTER TABLE IF EXISTS "{table}" NO FORCE ROW LEVEL SECURITY'))
