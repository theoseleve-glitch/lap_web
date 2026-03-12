"""Fix RLS policies using wrong GUC setting name.

Migrations 017 (session_weather_laps), 026 (exports), 030 (billing_profiles),
and 041 (driver_xp, achievements, drill_executions) created RLS policies
referencing ``app.workspace_id`` instead of the canonical
``app.current_workspace_id`` that the middleware actually sets.

This caused all rows in those 5 tables to be invisible through RLS.

Revision ID: 044
Revises: 043
Create Date: 2026-03-12
"""
import sqlalchemy as sa

from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None

# (table, policy_name, original_setting_expr)
_BROKEN_POLICIES = [
    ("session_weather_laps", "session_weather_laps_workspace_isolation",
     "current_setting('app.workspace_id', true)"),
    ("exports", "exports_workspace_isolation",
     "current_setting('app.workspace_id')::integer"),
    ("billing_profiles", "billing_profiles_workspace_policy",
     "current_setting('app.workspace_id', true)::int"),
    ("driver_xp", "driver_xp_workspace",
     "current_setting('app.workspace_id')::int"),
    ("achievements", "achievements_workspace",
     "current_setting('app.workspace_id')::int"),
    ("drill_executions", "drill_exec_workspace",
     "current_setting('app.workspace_id')::int"),
]

_CORRECT_EXPR_INT = "current_setting('app.current_workspace_id')::integer"
_CORRECT_EXPR_TEXT = "current_setting('app.current_workspace_id')"

# Tables where workspace_id is TEXT, not INTEGER
_TEXT_WS_TABLES = {"session_weather_laps"}


def upgrade() -> None:
    for table, policy, _ in _BROKEN_POLICIES:
        expr = _CORRECT_EXPR_TEXT if table in _TEXT_WS_TABLES else _CORRECT_EXPR_INT
        op.execute(sa.text(
            f"DROP POLICY IF EXISTS {policy} ON {table}"
        ))
        op.execute(sa.text(
            f"CREATE POLICY {policy} ON {table} "
            f"USING (workspace_id = {expr})"
        ))


def downgrade() -> None:
    for table, policy, original_expr in _BROKEN_POLICIES:
        op.execute(sa.text(
            f"DROP POLICY IF EXISTS {policy} ON {table}"
        ))
        op.execute(sa.text(
            f"CREATE POLICY {policy} ON {table} "
            f"USING (workspace_id = {original_expr})"
        ))
