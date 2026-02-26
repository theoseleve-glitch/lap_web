"""Backfill workspace_id on all data tables, make NOT NULL, add FK + DEFAULT.

Creates a system default workspace. All existing rows get this workspace's ID.
Column becomes NOT NULL with a DEFAULT that reads from
current_setting('app.current_workspace_id'), so existing INSERT queries
auto-fill workspace_id.

Revision ID: 006
Revises: 005
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"

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

    # 1. Create the default workspace
    result = conn.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1"))
    first_user = result.scalar()

    if first_user is None:
        # Fresh database with no users — create a system workspace.
        # Temporarily drop the CHECK constraint so we can insert with
        # NULL owner (no users exist yet).  Re-add it afterwards.
        conn.execute(sa.text(
            "ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS ck_workspace_has_owner"
        ))
        conn.execute(sa.text(
            "INSERT INTO workspaces (type, display_name) "
            "VALUES ('personal', 'Default Workspace')"
        ))
        conn.execute(sa.text(
            "ALTER TABLE workspaces ADD CONSTRAINT ck_workspace_has_owner "
            "CHECK (owner_user_id IS NOT NULL OR owner_team_id IS NOT NULL) NOT VALID"
        ))
    else:
        conn.execute(sa.text(
            "INSERT INTO workspaces (type, owner_user_id, display_name) "
            "VALUES ('personal', :uid, 'Default Workspace')"
        ), {"uid": first_user})

    result = conn.execute(sa.text(
        "SELECT id FROM workspaces WHERE display_name = 'Default Workspace' "
        "ORDER BY id LIMIT 1"
    ))
    default_ws_id = result.scalar()

    # 2. Backfill all existing rows
    for table in TENANT_TABLES:
        conn.execute(sa.text(
            f'UPDATE "{table}" SET workspace_id = :ws WHERE workspace_id IS NULL'
        ), {"ws": default_ws_id})

    # 3. Make NOT NULL + FK + DEFAULT
    for table in TENANT_TABLES:
        op.alter_column(table, "workspace_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_workspace", table, "workspaces",
            ["workspace_id"], ["id"], ondelete="CASCADE",
        )
        op.alter_column(
            table, "workspace_id",
            server_default=sa.text("current_setting('app.current_workspace_id')::integer"),
        )

    # 4. Set default_workspace_id for first user
    if first_user and default_ws_id:
        conn.execute(sa.text(
            "UPDATE users SET default_workspace_id = :ws WHERE id = :uid"
        ), {"ws": default_ws_id, "uid": first_user})


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.alter_column(table, "workspace_id", server_default=None)
        op.drop_constraint(f"fk_{table}_workspace", table, type_="foreignkey")
        op.alter_column(table, "workspace_id", nullable=True)
