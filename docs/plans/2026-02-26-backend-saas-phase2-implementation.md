# Backend SaaS Phase 2 — Tenancy + RBAC Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add multi-tenant workspace isolation with Row-Level Security and role-based access control, so every data row belongs to exactly one workspace and users can only see their own data.

**Architecture:** Create workspaces (personal + team), add `workspace_id` to all 44 data tables via Alembic migrations, enable PostgreSQL RLS with `SET LOCAL` per request, and add RBAC decorators. Existing INSERT queries auto-fill workspace_id via column DEFAULT; SELECTs/UPDATEs are auto-filtered by RLS. Legacy mode (`AUTH_REQUIRED=0`) uses a default workspace.

**Tech Stack:** PostgreSQL 16 (RLS policies), psycopg2, Alembic, Flask middleware

**Design doc:** `docs/plans/2026-02-26-backend-saas-overhaul-design.md` §2 (Data Model & Tenancy), §3 (RBAC)

**Depends on:** Phase 1 complete (branch `feat/backend-saas-phase1`)

---

## PR 6: Workspace + Team Model with RLS (Tasks 1–7)

### Task 1: Create teams, workspaces, team_members tables (Migration 004)

**Files:**
- Create: `telemetry_tool/alembic/versions/004_workspace_tables.py`
- Test: `telemetry_tool/tests/test_workspace_schema.py`

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_workspace_schema.py`:
```python
"""Tests for workspace schema (migration 004)."""
import importlib.util
from pathlib import Path

import pytest

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


class TestMigration004:
    def _load(self):
        spec = importlib.util.spec_from_file_location(
            "m004", _VERSIONS / "004_workspace_tables.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_migration_004_exists(self):
        assert (_VERSIONS / "004_workspace_tables.py").exists()

    def test_revision_chain(self):
        mod = self._load()
        assert mod.revision == "004"
        assert mod.down_revision == "003"

    def test_has_upgrade_downgrade(self):
        mod = self._load()
        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_workspace_schema.py -v`
Expected: FAIL (file does not exist)

**Step 3: Write migration 004**

Create `telemetry_tool/alembic/versions/004_workspace_tables.py`:
```python
"""Add workspace, team, and team_members tables.

Revision ID: 004
Revises: 003
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"


def upgrade() -> None:
    # Teams
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column("owner_user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("billing_plan", sa.Text, server_default="free"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # Workspaces (data isolation boundary)
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("type", sa.Text, nullable=False),  # 'personal' or 'team'
        sa.Column("owner_user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("owner_team_id", sa.Integer,
                  sa.ForeignKey("teams.id", ondelete="CASCADE")),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.CheckConstraint(
            "owner_user_id IS NOT NULL OR owner_team_id IS NOT NULL",
            name="ck_workspace_has_owner",
        ),
    )
    op.create_index("idx_workspace_user", "workspaces", ["owner_user_id"])
    op.create_index("idx_workspace_team", "workspaces", ["owner_team_id"])

    # Team members (join table with role)
    op.create_table(
        "team_members",
        sa.Column("team_id", sa.Integer,
                  sa.ForeignKey("teams.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default="member"),
        sa.Column("invited_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("accepted_at", sa.DateTime),
        sa.PrimaryKeyConstraint("team_id", "user_id"),
    )

    # Audit log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer,
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE")),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("entity_type", sa.Text),
        sa.Column("entity_id", sa.Integer),
        sa.Column("old_value", sa.Text),  # JSONB in practice via PG
        sa.Column("new_value", sa.Text),
        sa.Column("ip_address", sa.Text),
        sa.Column("request_id", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_audit_workspace", "audit_log", ["workspace_id"])
    op.create_index("idx_audit_created", "audit_log", ["created_at"])

    # Add default_workspace_id to users (their personal workspace)
    op.add_column("users", sa.Column("default_workspace_id", sa.Integer))


def downgrade() -> None:
    op.drop_column("users", "default_workspace_id")
    op.drop_table("audit_log")
    op.drop_table("team_members")
    op.drop_table("workspaces")
    op.drop_table("teams")
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_workspace_schema.py -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add telemetry_tool/alembic/versions/004_workspace_tables.py \
       telemetry_tool/tests/test_workspace_schema.py
git commit -m "feat(tenancy): add workspace, team, team_members tables (migration 004)"
```

---

### Task 2: Add workspace_id to all data tables (Migration 005)

**Files:**
- Create: `telemetry_tool/alembic/versions/005_add_workspace_id.py`
- Modify: `telemetry_tool/tests/test_workspace_schema.py`

This is the largest single migration. It adds `workspace_id INTEGER` (nullable initially) to all 44 data tables, plus indexes. The column is nullable here so the migration can run on existing data. Task 3 backfills and makes it NOT NULL.

**Tables receiving workspace_id** (44 total — everything except `schema_version`, `predefined_tracks`, `predefined_karts`, `predefined_track_coords`, `users`, `refresh_tokens`, `oauth_connections`, `teams`, `team_members`, `workspaces`, `audit_log`):

```
tracks, drivers, sessions, laps, gps_traces, score_details, condition_phases,
weekends, weekend_sessions, track_records, condition_markers,
driver_profiles, driver_progression, driving_style_features,
theoretical_data, reference_lines, session_sectors,
data_health, session_tags, corner_metrics, corner_best_practices,
track_key_corners, session_weather, vehicle_setups, what_if_scenarios,
session_annotations, development_plans, plan_drill_sessions, driver_badges,
custom_dashboards, export_templates, stint_analysis, ingestion_jobs,
karts, track_sectors, race_configs, race_drivers, race_stints,
race_pit_stops, race_windows, race_messages, race_neutralizations,
race_rivals, race_rival_events
```

**Step 1: Add tests**

Append to `telemetry_tool/tests/test_workspace_schema.py`:
```python
class TestMigration005:
    def _load(self):
        spec = importlib.util.spec_from_file_location(
            "m005", _VERSIONS / "005_add_workspace_id.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_migration_005_exists(self):
        assert (_VERSIONS / "005_add_workspace_id.py").exists()

    def test_revision_chain(self):
        mod = self._load()
        assert mod.revision == "005"
        assert mod.down_revision == "004"

    def test_tables_count(self):
        """005 should add workspace_id to exactly 44 tables."""
        mod = self._load()
        assert len(mod.TENANT_TABLES) == 44
```

**Step 2: Write migration 005**

Create `telemetry_tool/alembic/versions/005_add_workspace_id.py`:
```python
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

# All tables that get workspace_id (44 total).
# Global tables excluded: schema_version, predefined_tracks, predefined_karts,
# predefined_track_coords. Auth tables excluded: users, refresh_tokens,
# oauth_connections, teams, team_members, workspaces, audit_log.
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
        op.add_column(
            table,
            sa.Column("workspace_id", sa.Integer, nullable=True),
        )
        op.create_index(f"idx_{table}_workspace", table, ["workspace_id"])


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.drop_index(f"idx_{table}_workspace", table_name=table)
        op.drop_column(table, "workspace_id")
```

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_workspace_schema.py -v`
Expected: 6 PASS

**Step 4: Commit**

```bash
git add telemetry_tool/alembic/versions/005_add_workspace_id.py \
       telemetry_tool/tests/test_workspace_schema.py
git commit -m "feat(tenancy): add workspace_id (nullable) to all 44 data tables (migration 005)"
```

---

### Task 3: Backfill workspace_id + make NOT NULL (Migration 006)

**Files:**
- Create: `telemetry_tool/alembic/versions/006_backfill_workspace_id.py`
- Modify: `telemetry_tool/tests/test_workspace_schema.py`

This migration creates a "default" workspace for the system, assigns all existing data to it, makes workspace_id NOT NULL, adds FK constraints, and sets a DEFAULT expression so new INSERTs auto-fill workspace_id from the PostgreSQL session variable `app.current_workspace_id`.

**Step 1: Add test**

```python
class TestMigration006:
    def _load(self):
        spec = importlib.util.spec_from_file_location(
            "m006", _VERSIONS / "006_backfill_workspace_id.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_revision_chain(self):
        mod = self._load()
        assert mod.revision == "006"
        assert mod.down_revision == "005"
```

**Step 2: Write migration 006**

Create `telemetry_tool/alembic/versions/006_backfill_workspace_id.py`:
```python
"""Backfill workspace_id on all data tables, make NOT NULL, add FK + DEFAULT.

Creates a system default workspace (type='personal', display_name='Default').
All existing rows get this workspace's ID. Column becomes NOT NULL with a
DEFAULT that reads from current_setting('app.current_workspace_id'), so
existing INSERT queries don't need modification.

Revision ID: 006
Revises: 005
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"

# Same list as 005.
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

    # 1. Create the default workspace (for existing data + legacy mode).
    #    Find first user to be owner, or NULL if no users yet.
    result = conn.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1"))
    first_user = result.scalar()

    conn.execute(sa.text(
        "INSERT INTO workspaces (type, owner_user_id, display_name) "
        "VALUES ('personal', :uid, 'Default Workspace')"
    ), {"uid": first_user})

    result = conn.execute(sa.text(
        "SELECT id FROM workspaces WHERE display_name = 'Default Workspace' "
        "ORDER BY id LIMIT 1"
    ))
    default_ws_id = result.scalar()

    # 2. Backfill all existing rows.
    for table in TENANT_TABLES:
        conn.execute(sa.text(
            f'UPDATE "{table}" SET workspace_id = :ws WHERE workspace_id IS NULL'
        ), {"ws": default_ws_id})

    # 3. Make NOT NULL + FK + DEFAULT.
    for table in TENANT_TABLES:
        op.alter_column(table, "workspace_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_workspace",
            table, "workspaces",
            ["workspace_id"], ["id"],
            ondelete="CASCADE",
        )
        # DEFAULT reads workspace_id from the PG session variable.
        # This means existing INSERT queries auto-fill workspace_id.
        op.alter_column(
            table, "workspace_id",
            server_default=sa.text(
                "current_setting('app.current_workspace_id')::integer"
            ),
        )

    # 4. Set default_workspace_id for first user.
    if first_user and default_ws_id:
        conn.execute(sa.text(
            "UPDATE users SET default_workspace_id = :ws WHERE id = :uid"
        ), {"ws": default_ws_id, "uid": first_user})


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.alter_column(table, "workspace_id", server_default=None)
        op.drop_constraint(f"fk_{table}_workspace", table, type_="foreignkey")
        op.alter_column(table, "workspace_id", nullable=True)
    # Don't delete the default workspace — data may reference it.
```

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_workspace_schema.py -v`
Expected: 7 PASS (new test for 006 chain)

**Step 4: Commit**

```bash
git add telemetry_tool/alembic/versions/006_backfill_workspace_id.py \
       telemetry_tool/tests/test_workspace_schema.py
git commit -m "feat(tenancy): backfill workspace_id, add NOT NULL + FK + DEFAULT (migration 006)"
```

---

### Task 4: Enable RLS on all tenant-scoped tables (Migration 007)

**Files:**
- Create: `telemetry_tool/alembic/versions/007_enable_rls.py`
- Modify: `telemetry_tool/tests/test_workspace_schema.py`

**Step 1: Add test**

```python
class TestMigration007:
    def _load(self):
        spec = importlib.util.spec_from_file_location(
            "m007", _VERSIONS / "007_enable_rls.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_revision_chain(self):
        mod = self._load()
        assert mod.revision == "007"
        assert mod.down_revision == "006"

    def test_same_tenant_tables(self):
        """007 should use the same TENANT_TABLES list as 005."""
        m005 = importlib.util.module_from_spec(
            importlib.util.spec_from_file_location(
                "m005", _VERSIONS / "005_add_workspace_id.py"
            )
        )
        importlib.util.spec_from_file_location(
            "m005", _VERSIONS / "005_add_workspace_id.py"
        ).loader.exec_module(m005)
        mod = self._load()
        assert mod.TENANT_TABLES == m005.TENANT_TABLES
```

**Step 2: Write migration 007**

Create `telemetry_tool/alembic/versions/007_enable_rls.py`:
```python
"""Enable Row-Level Security on all tenant-scoped tables.

Each table gets:
1. ALTER TABLE ... ENABLE ROW LEVEL SECURITY;
2. A policy that filters by workspace_id = current_setting('app.current_workspace_id')

The app user (non-superuser) sees only rows matching the current workspace.
Superusers bypass RLS (for migrations and admin tasks).

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
        conn.execute(sa.text(
            f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'
        ))
        conn.execute(sa.text(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f"USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
            f"WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    for table in reversed(TENANT_TABLES):
        conn.execute(sa.text(
            f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"'
        ))
        conn.execute(sa.text(
            f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'
        ))
```

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_workspace_schema.py -v`
Expected: 9 PASS

**Step 4: Commit**

```bash
git add telemetry_tool/alembic/versions/007_enable_rls.py \
       telemetry_tool/tests/test_workspace_schema.py
git commit -m "feat(tenancy): enable RLS on all 44 data tables (migration 007)"
```

---

### Task 5: Workspace service — CRUD + auto-create on registration

**Files:**
- Create: `telemetry_tool/auth/workspace.py`
- Modify: `telemetry_tool/auth/service.py` (register_user creates personal workspace)
- Test: `telemetry_tool/tests/test_workspace_service.py`

**Step 1: Write tests**

Create `telemetry_tool/tests/test_workspace_service.py`:
```python
"""Tests for workspace service (no PG required — mocked DB)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestCreatePersonalWorkspace:
    def test_creates_workspace_and_returns_id(self):
        from auth.workspace import create_personal_workspace

        conn = MagicMock()
        call_count = [0]

        def execute_side_effect(sql, params=None):
            cur = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:  # INSERT workspace RETURNING id
                cur.fetchone.return_value = {"id": 10}
            elif call_count[0] == 2:  # UPDATE users.default_workspace_id
                pass
            return cur

        conn.execute.side_effect = execute_side_effect

        ws_id = create_personal_workspace(conn, user_id=42, display_name="Alice")
        assert ws_id == 10
        assert call_count[0] == 2  # INSERT + UPDATE
        conn.commit.assert_called()

    def test_display_name_defaults_to_personal(self):
        from auth.workspace import create_personal_workspace

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 1}
        conn.execute.return_value = cur

        create_personal_workspace(conn, user_id=1)
        # Check the SQL included "Personal Workspace" as default name
        call_args = conn.execute.call_args_list[0]
        assert "Personal Workspace" in str(call_args)


class TestGetUserWorkspaces:
    def test_returns_personal_and_team_workspaces(self):
        from auth.workspace import get_user_workspaces

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"id": 1, "type": "personal", "display_name": "My Workspace"},
            {"id": 2, "type": "team", "display_name": "Team Alpha"},
        ]
        conn.execute.return_value = cur

        result = get_user_workspaces(conn, user_id=42)
        assert len(result) == 2
        assert result[0]["type"] == "personal"
        assert result[1]["type"] == "team"


class TestSetWorkspaceContext:
    def test_sets_pg_session_variable(self):
        from auth.workspace import set_workspace_context

        conn = MagicMock()
        set_workspace_context(conn, workspace_id=42)
        conn.execute.assert_called_once()
        sql_arg = str(conn.execute.call_args[0][0])
        assert "app.current_workspace_id" in sql_arg
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_workspace_service.py -v`
Expected: FAIL (auth.workspace does not exist)

**Step 3: Implement workspace service**

Create `telemetry_tool/auth/workspace.py`:
```python
"""Workspace management — create, list, set context."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def create_personal_workspace(
    conn, user_id: int, display_name: str = "Personal Workspace"
) -> int:
    """Create a personal workspace for a user and set it as their default.

    Returns the new workspace ID.
    """
    cur = conn.execute(
        "INSERT INTO workspaces (type, owner_user_id, display_name) "
        "VALUES (%(type)s, %(uid)s, %(name)s) RETURNING id",
        {"type": "personal", "uid": user_id, "name": display_name},
    )
    ws_id = cur.fetchone()["id"]

    conn.execute(
        "UPDATE users SET default_workspace_id = %(ws)s WHERE id = %(uid)s",
        {"ws": ws_id, "uid": user_id},
    )
    conn.commit()
    return ws_id


def create_team_workspace(conn, team_id: int, display_name: str) -> int:
    """Create a workspace for a team. Returns the new workspace ID."""
    cur = conn.execute(
        "INSERT INTO workspaces (type, owner_team_id, display_name) "
        "VALUES (%(type)s, %(tid)s, %(name)s) RETURNING id",
        {"type": "team", "tid": team_id, "name": display_name},
    )
    ws_id = cur.fetchone()["id"]
    conn.commit()
    return ws_id


def get_user_workspaces(conn, user_id: int) -> list[dict]:
    """Return all workspaces a user can access (personal + team memberships)."""
    cur = conn.execute(
        "SELECT w.id, w.type, w.display_name, w.owner_user_id, w.owner_team_id "
        "FROM workspaces w "
        "LEFT JOIN team_members tm ON w.owner_team_id = tm.team_id "
        "WHERE w.owner_user_id = %(uid)s "
        "   OR tm.user_id = %(uid)s "
        "ORDER BY w.type, w.display_name",
        {"uid": user_id},
    )
    return [dict(row) for row in cur.fetchall()]


def get_default_workspace_id(conn, user_id: int) -> int | None:
    """Return the user's default workspace ID."""
    cur = conn.execute(
        "SELECT default_workspace_id FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    )
    row = cur.fetchone()
    return row["default_workspace_id"] if row else None


def set_workspace_context(conn, workspace_id: int) -> None:
    """Set the PostgreSQL session variable for RLS.

    Must be called at the start of each request, before any tenant-scoped
    queries.  Uses SET LOCAL so the setting is scoped to the current
    transaction only.
    """
    conn.execute(
        "SET LOCAL app.current_workspace_id = %(ws)s",
        {"ws": str(workspace_id)},
    )
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_workspace_service.py -v`
Expected: 4 PASS

**Step 5: Update register_user to create personal workspace**

Modify `telemetry_tool/auth/service.py` — add after `conn.commit()` in `register_user()`:
```python
    # Auto-create personal workspace for the new user.
    from auth.workspace import create_personal_workspace
    create_personal_workspace(conn, user_id=row["id"],
                              display_name=f"{display_name}'s Workspace")
```

**Step 6: Run full test suite**

Run: `pytest telemetry_tool/tests/ -v --tb=short`
Expected: All tests PASS (existing + new)

**Step 7: Commit**

```bash
git add telemetry_tool/auth/workspace.py \
       telemetry_tool/auth/service.py \
       telemetry_tool/tests/test_workspace_service.py
git commit -m "feat(tenancy): workspace service + auto-create on registration"
```

---

### Task 6: Team service — CRUD + member management

**Files:**
- Create: `telemetry_tool/auth/teams.py`
- Test: `telemetry_tool/tests/test_team_service.py`

**Step 1: Write tests**

Create `telemetry_tool/tests/test_team_service.py`:
```python
"""Tests for team service (no PG required — mocked DB)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.service import AuthError


class TestCreateTeam:
    def test_creates_team_and_workspace(self):
        from auth.teams import create_team

        conn = MagicMock()
        call_count = [0]

        def execute_side_effect(sql, params=None):
            cur = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:  # INSERT team RETURNING id
                cur.fetchone.return_value = {"id": 5}
            elif call_count[0] == 2:  # INSERT team_members (owner)
                pass
            elif call_count[0] == 3:  # INSERT workspace RETURNING id
                cur.fetchone.return_value = {"id": 20}
            return cur

        conn.execute.side_effect = execute_side_effect

        result = create_team(conn, owner_id=1, name="Alpha Racing", slug="alpha-racing")
        assert result["team_id"] == 5
        assert result["workspace_id"] == 20
        conn.commit.assert_called()

    def test_slug_must_be_unique(self):
        from auth.teams import create_team

        conn = MagicMock()
        conn.execute.side_effect = Exception("duplicate key value violates unique constraint")

        with pytest.raises(AuthError) as exc_info:
            create_team(conn, owner_id=1, name="Dup", slug="dup-slug")
        assert exc_info.value.code == "CONFLICT"


class TestAddMember:
    def test_adds_member_with_role(self):
        from auth.teams import add_member

        conn = MagicMock()
        add_member(conn, team_id=5, user_id=10, role="member")
        conn.execute.assert_called_once()
        conn.commit.assert_called()

    def test_rejects_invalid_role(self):
        from auth.teams import add_member

        conn = MagicMock()
        with pytest.raises(AuthError, match="Invalid role"):
            add_member(conn, team_id=5, user_id=10, role="superadmin")


class TestChangeMemberRole:
    def test_changes_role(self):
        from auth.teams import change_member_role

        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 1
        conn.execute.return_value = cur

        change_member_role(conn, team_id=5, user_id=10, new_role="admin")
        conn.commit.assert_called()


class TestRemoveMember:
    def test_removes_member(self):
        from auth.teams import remove_member

        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 1
        conn.execute.return_value = cur

        remove_member(conn, team_id=5, user_id=10)
        conn.commit.assert_called()

    def test_cannot_remove_owner(self):
        from auth.teams import remove_member

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"role": "owner"}
        conn.execute.return_value = cur

        with pytest.raises(AuthError, match="Cannot remove team owner"):
            remove_member(conn, team_id=5, user_id=1)
```

**Step 2: Run to verify failure**

Run: `pytest telemetry_tool/tests/test_team_service.py -v`
Expected: FAIL (auth.teams does not exist)

**Step 3: Implement team service**

Create `telemetry_tool/auth/teams.py`:
```python
"""Team management — create team, manage members, roles."""
from __future__ import annotations

import logging
from auth.service import AuthError

logger = logging.getLogger(__name__)

VALID_ROLES = {"owner", "admin", "member", "viewer"}


def create_team(conn, owner_id: int, name: str, slug: str) -> dict:
    """Create a team with the given owner.

    The owner is automatically added as a member with role='owner'.
    A team workspace is also created.

    Returns dict with team_id and workspace_id.
    """
    try:
        cur = conn.execute(
            "INSERT INTO teams (name, slug, owner_user_id) "
            "VALUES (%(name)s, %(slug)s, %(owner)s) RETURNING id",
            {"name": name, "slug": slug, "owner": owner_id},
        )
        team_id = cur.fetchone()["id"]

        # Owner is always a member
        conn.execute(
            "INSERT INTO team_members (team_id, user_id, role, accepted_at) "
            "VALUES (%(tid)s, %(uid)s, 'owner', NOW())",
            {"tid": team_id, "uid": owner_id},
        )

        # Create team workspace
        from auth.workspace import create_team_workspace
        ws_id = create_team_workspace(conn, team_id=team_id, display_name=name)

        conn.commit()
        return {"team_id": team_id, "workspace_id": ws_id}
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise AuthError("Team slug already taken", "CONFLICT")
        raise


def add_member(conn, team_id: int, user_id: int, role: str = "member") -> None:
    """Add a user to a team with the given role."""
    if role not in VALID_ROLES:
        raise AuthError(f"Invalid role: {role}", "VALIDATION_ERROR")

    conn.execute(
        "INSERT INTO team_members (team_id, user_id, role) "
        "VALUES (%(tid)s, %(uid)s, %(role)s) "
        "ON CONFLICT (team_id, user_id) DO NOTHING",
        {"tid": team_id, "uid": user_id, "role": role},
    )
    conn.commit()


def change_member_role(conn, team_id: int, user_id: int, new_role: str) -> None:
    """Change a team member's role."""
    if new_role not in VALID_ROLES:
        raise AuthError(f"Invalid role: {new_role}", "VALIDATION_ERROR")

    cur = conn.execute(
        "UPDATE team_members SET role = %(role)s "
        "WHERE team_id = %(tid)s AND user_id = %(uid)s",
        {"role": new_role, "tid": team_id, "uid": user_id},
    )
    if cur.rowcount == 0:
        raise AuthError("Member not found", "NOT_FOUND")
    conn.commit()


def remove_member(conn, team_id: int, user_id: int) -> None:
    """Remove a user from a team. Cannot remove the owner."""
    cur = conn.execute(
        "SELECT role FROM team_members WHERE team_id = %(tid)s AND user_id = %(uid)s",
        {"tid": team_id, "uid": user_id},
    )
    row = cur.fetchone()
    if row and row["role"] == "owner":
        raise AuthError("Cannot remove team owner", "FORBIDDEN")

    cur = conn.execute(
        "DELETE FROM team_members WHERE team_id = %(tid)s AND user_id = %(uid)s",
        {"tid": team_id, "uid": user_id},
    )
    if cur.rowcount == 0:
        raise AuthError("Member not found", "NOT_FOUND")
    conn.commit()


def get_team_members(conn, team_id: int) -> list[dict]:
    """Return all members of a team with their roles."""
    cur = conn.execute(
        "SELECT u.id, u.email, u.display_name, tm.role, tm.accepted_at "
        "FROM team_members tm "
        "JOIN users u ON u.id = tm.user_id "
        "WHERE tm.team_id = %(tid)s "
        "ORDER BY tm.role, u.display_name",
        {"tid": team_id},
    )
    return [dict(row) for row in cur.fetchall()]


def get_user_role_in_team(conn, team_id: int, user_id: int) -> str | None:
    """Return the user's role in a team, or None if not a member."""
    cur = conn.execute(
        "SELECT role FROM team_members WHERE team_id = %(tid)s AND user_id = %(uid)s",
        {"tid": team_id, "uid": user_id},
    )
    row = cur.fetchone()
    return row["role"] if row else None
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_team_service.py -v`
Expected: 6 PASS

**Step 5: Run full suite**

Run: `pytest telemetry_tool/tests/ --tb=short`
Expected: All pass

**Step 6: Commit**

```bash
git add telemetry_tool/auth/teams.py telemetry_tool/tests/test_team_service.py
git commit -m "feat(tenancy): team service — CRUD + member management"
```

---

### Task 7: Tenant middleware — resolve workspace, SET LOCAL

**Files:**
- Create: `telemetry_tool/web/middleware/tenant.py`
- Modify: `telemetry_tool/web/app.py` (register tenant middleware)
- Test: `telemetry_tool/tests/test_tenant_middleware.py`

**Step 1: Write tests**

Create `telemetry_tool/tests/test_tenant_middleware.py`:
```python
"""Tests for tenant middleware (no PG required — mocked)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestTenantMiddleware:
    def test_sets_workspace_from_header(self):
        """X-Workspace-Id header sets g.workspace_id."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        with app.test_request_context(
            "/api/v1/sessions",
            headers={"X-Workspace-Id": "42"},
        ):
            g.current_user_id = 1
            with patch("web.middleware.tenant._verify_workspace_access", return_value=True), \
                 patch("web.middleware.tenant._set_rls_context"):
                tenant_middleware()
                assert g.workspace_id == 42

    def test_falls_back_to_default_workspace(self):
        """Without header, uses user's default workspace."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        with app.test_request_context("/api/v1/sessions"):
            g.current_user_id = 1
            with patch("web.middleware.tenant.get_default_workspace_id", return_value=99), \
                 patch("web.middleware.tenant._set_rls_context"):
                tenant_middleware()
                assert g.workspace_id == 99

    def test_skips_non_api_routes(self):
        """Non-/api/v1/ routes don't need workspace resolution."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        with app.test_request_context("/static/main.css"):
            result = tenant_middleware()
            assert result is None
            assert not hasattr(g, "workspace_id")

    def test_legacy_mode_uses_default_workspace(self):
        """When AUTH_REQUIRED=False, use default workspace for all requests."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = False
        app.config["USE_PG"] = True
        app.config["DEFAULT_WORKSPACE_ID"] = 1

        with app.test_request_context("/api/v1/sessions"):
            with patch("web.middleware.tenant._set_rls_context"):
                tenant_middleware()
                assert g.workspace_id == 1

    def test_returns_403_when_no_workspace_access(self):
        """Returns 403 if user doesn't have access to requested workspace."""
        from web.middleware.tenant import tenant_middleware
        from flask import Flask, g

        app = Flask(__name__)
        app.config["AUTH_REQUIRED"] = True
        app.config["USE_PG"] = True

        with app.test_request_context(
            "/api/v1/sessions",
            headers={"X-Workspace-Id": "999"},
        ):
            g.current_user_id = 1
            with patch("web.middleware.tenant._verify_workspace_access", return_value=False):
                result = tenant_middleware()
                assert result is not None  # Returns error response
```

**Step 2: Run to verify failure**

Run: `pytest telemetry_tool/tests/test_tenant_middleware.py -v`
Expected: FAIL (module not found)

**Step 3: Implement tenant middleware**

Create `telemetry_tool/web/middleware/tenant.py`:
```python
"""Tenant middleware — resolves workspace_id and sets RLS context."""
from flask import request, g, current_app, jsonify

from auth.workspace import get_default_workspace_id


def tenant_middleware():
    """Before-request hook: resolve workspace and set RLS context.

    When AUTH_REQUIRED is False (legacy mode), uses DEFAULT_WORKSPACE_ID
    for all requests.  Otherwise resolves from X-Workspace-Id header or
    user's default workspace.
    """
    if not current_app.config.get("USE_PG"):
        return  # SQLite mode — no tenancy

    # Only apply to API routes
    if not request.path.startswith("/api/v1/"):
        return

    # Legacy mode: use system default workspace
    if not current_app.config.get("AUTH_REQUIRED"):
        g.workspace_id = current_app.config.get("DEFAULT_WORKSPACE_ID", 1)
        _set_rls_context(g.workspace_id)
        return

    # Auth mode: resolve workspace for authenticated user
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return  # Auth middleware will handle the 401

    # Check for explicit workspace header
    ws_header = request.headers.get("X-Workspace-Id")
    if ws_header:
        try:
            workspace_id = int(ws_header)
        except (ValueError, TypeError):
            return jsonify({
                "ok": False,
                "error": {"code": "VALIDATION_ERROR",
                          "message": "Invalid X-Workspace-Id header"},
                "meta": {},
            }), 400

        if not _verify_workspace_access(user_id, workspace_id):
            return jsonify({
                "ok": False,
                "error": {"code": "FORBIDDEN",
                          "message": "No access to this workspace"},
                "meta": {},
            }), 403

        g.workspace_id = workspace_id
    else:
        # Fall back to user's default workspace
        from web.db import get_db_connection
        conn = get_db_connection()
        default_ws = get_default_workspace_id(conn, user_id)
        if default_ws is None:
            return jsonify({
                "ok": False,
                "error": {"code": "NOT_FOUND",
                          "message": "No default workspace. Create one first."},
                "meta": {},
            }), 404
        g.workspace_id = default_ws

    _set_rls_context(g.workspace_id)


def _verify_workspace_access(user_id: int, workspace_id: int) -> bool:
    """Check if user has access to the given workspace."""
    from web.db import get_db_connection
    conn = get_db_connection()
    cur = conn.execute(
        "SELECT 1 FROM workspaces w "
        "LEFT JOIN team_members tm ON w.owner_team_id = tm.team_id "
        "WHERE w.id = %(ws)s AND (w.owner_user_id = %(uid)s OR tm.user_id = %(uid)s) "
        "LIMIT 1",
        {"ws": workspace_id, "uid": user_id},
    )
    return cur.fetchone() is not None


def _set_rls_context(workspace_id: int) -> None:
    """Set the PostgreSQL session variable for RLS filtering."""
    from web.db import get_db_connection
    from auth.workspace import set_workspace_context
    conn = get_db_connection()
    set_workspace_context(conn, workspace_id)
```

**Step 4: Register in app factory**

In `telemetry_tool/web/app.py`, add after the auth middleware registration (inside the `if cfg.USE_PG:` block):
```python
            from .middleware.tenant import tenant_middleware
            app.before_request(tenant_middleware)
            logger.debug("Registered tenant middleware")
```

**Step 5: Run tests**

Run: `pytest telemetry_tool/tests/test_tenant_middleware.py -v`
Expected: 5 PASS

**Step 6: Run full suite**

Run: `pytest telemetry_tool/tests/ --tb=short`
Expected: All pass

**Step 7: Commit**

```bash
git add telemetry_tool/web/middleware/tenant.py \
       telemetry_tool/web/app.py \
       telemetry_tool/tests/test_tenant_middleware.py
git commit -m "feat(tenancy): tenant middleware — workspace resolution + RLS context"
```

---

## PR 8: RBAC Permission Checks (Tasks 8–11)

### Task 8: RBAC service — permission checking + decorators

**Files:**
- Create: `telemetry_tool/auth/rbac.py`
- Test: `telemetry_tool/tests/test_rbac.py`

**Step 1: Write tests**

Create `telemetry_tool/tests/test_rbac.py`:
```python
"""Tests for RBAC permission system (no PG required)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestRoleHierarchy:
    def test_owner_has_all_permissions(self):
        from auth.rbac import has_permission
        assert has_permission("owner", "delete_workspace")
        assert has_permission("owner", "upload_csv")
        assert has_permission("owner", "view_sessions")

    def test_admin_cannot_delete_workspace(self):
        from auth.rbac import has_permission
        assert not has_permission("admin", "delete_workspace")
        assert has_permission("admin", "manage_members")
        assert has_permission("admin", "upload_csv")

    def test_member_limited(self):
        from auth.rbac import has_permission
        assert has_permission("member", "upload_csv")
        assert has_permission("member", "view_sessions")
        assert not has_permission("member", "manage_members")
        assert not has_permission("member", "delete_sessions")

    def test_viewer_read_only(self):
        from auth.rbac import has_permission
        assert has_permission("viewer", "view_sessions")
        assert not has_permission("viewer", "upload_csv")
        assert not has_permission("viewer", "delete_sessions")


class TestRequireRoleDecorator:
    def test_allows_sufficient_role(self):
        from auth.rbac import require_role

        app = Flask(__name__)
        app.config["USE_PG"] = True

        @require_role("member")
        def test_view():
            return "ok"

        with app.test_request_context("/api/v1/test"):
            g.current_user_id = 1
            g.workspace_id = 10
            g.workspace_role = "admin"  # admin >= member
            result = test_view()
            assert result == "ok"

    def test_rejects_insufficient_role(self):
        from auth.rbac import require_role

        app = Flask(__name__)
        app.config["USE_PG"] = True

        @require_role("admin")
        def test_view():
            return "ok"

        with app.test_request_context("/api/v1/test"):
            g.current_user_id = 1
            g.workspace_id = 10
            g.workspace_role = "viewer"
            result, status = test_view()
            assert status == 403
```

**Step 2: Run to verify failure**

Run: `pytest telemetry_tool/tests/test_rbac.py -v`
Expected: FAIL

**Step 3: Implement RBAC service**

Create `telemetry_tool/auth/rbac.py`:
```python
"""Role-based access control — permission matrix + decorators."""
from __future__ import annotations

from functools import wraps

from flask import g, jsonify

# Role hierarchy: higher index = more permissions.
ROLE_LEVELS = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}

# Permission matrix: minimum role required for each action.
PERMISSIONS = {
    # Viewing
    "view_sessions": "viewer",
    "view_tracks": "viewer",
    "view_drivers": "viewer",
    "view_analytics": "viewer",

    # Creating / uploading
    "upload_csv": "member",
    "create_annotations": "member",
    "create_race_strategy": "member",
    "manage_own_drivers": "member",

    # Editing others' data
    "edit_any_session": "admin",
    "delete_sessions": "admin",
    "delete_tracks": "admin",

    # Team management
    "manage_members": "admin",
    "invite_members": "admin",
    "change_roles": "admin",

    # Destructive / billing
    "delete_workspace": "owner",
    "billing": "owner",
    "gdpr_export": "owner",
}


def has_permission(role: str, action: str) -> bool:
    """Check if a role has permission for a given action."""
    required_role = PERMISSIONS.get(action)
    if required_role is None:
        return False  # Unknown action — deny by default
    return ROLE_LEVELS.get(role, -1) >= ROLE_LEVELS.get(required_role, 999)


def require_role(minimum_role: str):
    """Decorator: endpoint requires at least the given role in the current workspace.

    Expects ``g.workspace_role`` to be set by the tenant middleware.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user_role = getattr(g, "workspace_role", None)
            if user_role is None:
                return jsonify({
                    "ok": False,
                    "error": {"code": "FORBIDDEN", "message": "No workspace role"},
                    "meta": {},
                }), 403

            if ROLE_LEVELS.get(user_role, -1) < ROLE_LEVELS.get(minimum_role, 999):
                return jsonify({
                    "ok": False,
                    "error": {"code": "FORBIDDEN",
                              "message": f"Requires {minimum_role} role or higher"},
                    "meta": {},
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


def require_permission(action: str):
    """Decorator: endpoint requires a specific permission."""
    min_role = PERMISSIONS.get(action, "owner")
    return require_role(min_role)
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_rbac.py -v`
Expected: 6 PASS

**Step 5: Commit**

```bash
git add telemetry_tool/auth/rbac.py telemetry_tool/tests/test_rbac.py
git commit -m "feat(rbac): permission matrix + require_role/require_permission decorators"
```

---

### Task 9: Add workspace_role resolution to tenant middleware

**Files:**
- Modify: `telemetry_tool/web/middleware/tenant.py`
- Modify: `telemetry_tool/tests/test_tenant_middleware.py`

**Step 1: Add test**

Add to `test_tenant_middleware.py`:
```python
class TestWorkspaceRoleResolution:
    def test_personal_workspace_owner_gets_owner_role(self):
        """Owner of personal workspace gets 'owner' role."""
        from web.middleware.tenant import _resolve_workspace_role
        from flask import Flask, g

        app = Flask(__name__)
        with app.test_request_context():
            conn = MagicMock()
            # Workspace owned by user
            cur = MagicMock()
            cur.fetchone.return_value = {"type": "personal", "owner_user_id": 1, "owner_team_id": None}
            conn.execute.return_value = cur

            role = _resolve_workspace_role(conn, user_id=1, workspace_id=10)
            assert role == "owner"

    def test_team_member_gets_team_role(self):
        """Team member gets their role from team_members."""
        from web.middleware.tenant import _resolve_workspace_role
        from flask import Flask, g

        app = Flask(__name__)
        with app.test_request_context():
            conn = MagicMock()
            call_count = [0]

            def execute_side(sql, params=None):
                cur = MagicMock()
                call_count[0] += 1
                if call_count[0] == 1:  # workspace lookup
                    cur.fetchone.return_value = {"type": "team", "owner_user_id": None, "owner_team_id": 5}
                elif call_count[0] == 2:  # team_members role
                    cur.fetchone.return_value = {"role": "admin"}
                return cur

            conn.execute.side_effect = execute_side
            role = _resolve_workspace_role(conn, user_id=10, workspace_id=20)
            assert role == "admin"
```

**Step 2: Add role resolution to tenant middleware**

Add to `telemetry_tool/web/middleware/tenant.py`:
```python
def _resolve_workspace_role(conn, user_id: int, workspace_id: int) -> str | None:
    """Determine the user's role in a workspace.

    Personal workspace owner → 'owner'.
    Team workspace → look up role in team_members.
    """
    cur = conn.execute(
        "SELECT type, owner_user_id, owner_team_id FROM workspaces WHERE id = %(ws)s",
        {"ws": workspace_id},
    )
    ws = cur.fetchone()
    if ws is None:
        return None

    if ws["type"] == "personal":
        return "owner" if ws["owner_user_id"] == user_id else None

    # Team workspace — look up team membership
    cur = conn.execute(
        "SELECT role FROM team_members WHERE team_id = %(tid)s AND user_id = %(uid)s",
        {"tid": ws["owner_team_id"], "uid": user_id},
    )
    row = cur.fetchone()
    return row["role"] if row else None
```

And in the `tenant_middleware()` function, add after setting `g.workspace_id`:
```python
    # Resolve role
    from web.db import get_db_connection
    conn = get_db_connection()
    g.workspace_role = _resolve_workspace_role(conn, user_id, g.workspace_id)
```

For legacy mode, set: `g.workspace_role = "owner"` (full access).

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_tenant_middleware.py -v`
Expected: 7 PASS (5 existing + 2 new)

**Step 4: Commit**

```bash
git add telemetry_tool/web/middleware/tenant.py \
       telemetry_tool/tests/test_tenant_middleware.py
git commit -m "feat(rbac): workspace role resolution in tenant middleware"
```

---

### Task 10: Workspace + team API routes

**Files:**
- Create: `telemetry_tool/web/routes/workspaces.py`
- Create: `telemetry_tool/web/routes/teams.py`
- Modify: `telemetry_tool/web/app.py` (register blueprints)

**Step 1: Implement workspace routes**

Create `telemetry_tool/web/routes/workspaces.py`:
```python
"""Workspace management API routes."""
import logging
from flask import Blueprint, request, jsonify, g
from auth.rbac import require_role

logger = logging.getLogger(__name__)

bp = Blueprint("workspaces", __name__, url_prefix="/api/v1/workspaces")


def _json_response(data=None, error=None, status=200):
    if error:
        return jsonify({"ok": False, "error": error, "meta": {}}), status
    return jsonify({"ok": True, "data": data, "meta": {}}), status


def _get_conn():
    from flask import current_app
    if not current_app.config.get("USE_PG"):
        raise RuntimeError("Workspace routes require PostgreSQL (USE_PG=1)")
    from web.db import get_db_connection
    return get_db_connection()


@bp.route("", methods=["GET"])
def list_workspaces():
    """List all workspaces the current user can access."""
    from auth.workspace import get_user_workspaces
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return _json_response(error={"code": "UNAUTHORIZED", "message": "Auth required"}, status=401)

    conn = _get_conn()
    workspaces = get_user_workspaces(conn, user_id)
    return _json_response(data={"workspaces": workspaces})


@bp.route("/current", methods=["GET"])
def current_workspace():
    """Return the current workspace context."""
    ws_id = getattr(g, "workspace_id", None)
    ws_role = getattr(g, "workspace_role", None)
    return _json_response(data={
        "workspace_id": ws_id,
        "role": ws_role,
    })
```

**Step 2: Implement team routes**

Create `telemetry_tool/web/routes/teams.py`:
```python
"""Team management API routes."""
import logging
import re
from flask import Blueprint, request, jsonify, g
from auth.rbac import require_role
from auth.service import AuthError

logger = logging.getLogger(__name__)

bp = Blueprint("teams", __name__, url_prefix="/api/v1/teams")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


def _json_response(data=None, error=None, status=200):
    if error:
        return jsonify({"ok": False, "error": error, "meta": {}}), status
    return jsonify({"ok": True, "data": data, "meta": {}}), status


def _get_conn():
    from flask import current_app
    if not current_app.config.get("USE_PG"):
        raise RuntimeError("Team routes require PostgreSQL (USE_PG=1)")
    from web.db import get_db_connection
    return get_db_connection()


@bp.route("", methods=["POST"])
def create_team():
    """Create a new team. Requires authenticated user."""
    from auth.teams import create_team as svc_create_team
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return _json_response(error={"code": "UNAUTHORIZED", "message": "Auth required"}, status=401)

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    slug = (body.get("slug") or "").strip().lower()

    if not name:
        return _json_response(error={"code": "VALIDATION_ERROR", "message": "Team name required"}, status=400)
    if not slug or not _SLUG_RE.match(slug):
        return _json_response(
            error={"code": "VALIDATION_ERROR",
                   "message": "Slug must be 3-50 lowercase alphanumeric characters with hyphens"},
            status=400,
        )

    conn = _get_conn()
    try:
        result = svc_create_team(conn, owner_id=user_id, name=name, slug=slug)
        return _json_response(data=result, status=201)
    except AuthError as e:
        status_code = 409 if e.code == "CONFLICT" else 400
        return _json_response(error={"code": e.code, "message": str(e)}, status=status_code)
    except Exception:
        logger.exception("Team creation failed")
        return _json_response(error={"code": "INTERNAL_ERROR", "message": "Team creation failed"}, status=500)


@bp.route("/<int:team_id>/members", methods=["GET"])
@require_role("viewer")
def list_members(team_id):
    """List members of a team."""
    from auth.teams import get_team_members
    conn = _get_conn()
    members = get_team_members(conn, team_id)
    return _json_response(data={"members": members})


@bp.route("/<int:team_id>/members", methods=["POST"])
@require_role("admin")
def invite_member(team_id):
    """Add a member to a team."""
    from auth.teams import add_member
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    role = body.get("role", "member")

    if not user_id:
        return _json_response(error={"code": "VALIDATION_ERROR", "message": "user_id required"}, status=400)

    conn = _get_conn()
    try:
        add_member(conn, team_id=team_id, user_id=user_id, role=role)
        return _json_response(data={"message": "Member added"}, status=201)
    except AuthError as e:
        return _json_response(error={"code": e.code, "message": str(e)}, status=400)


@bp.route("/<int:team_id>/members/<int:user_id>", methods=["DELETE"])
@require_role("admin")
def remove_team_member(team_id, user_id):
    """Remove a member from a team."""
    from auth.teams import remove_member
    conn = _get_conn()
    try:
        remove_member(conn, team_id=team_id, user_id=user_id)
        return _json_response(data={"message": "Member removed"})
    except AuthError as e:
        code = 403 if e.code == "FORBIDDEN" else 404
        return _json_response(error={"code": e.code, "message": str(e)}, status=code)
```

**Step 3: Register in app factory**

Add to `telemetry_tool/web/app.py` inside the `if cfg.USE_PG:` block:
```python
            from .routes.workspaces import bp as workspaces_bp
            from .routes.teams import bp as teams_bp
            app.register_blueprint(workspaces_bp)
            app.register_blueprint(teams_bp)
            logger.debug("Registered workspace and team blueprints")
```

**Step 4: Run full test suite**

Run: `pytest telemetry_tool/tests/ --tb=short`
Expected: All pass

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/workspaces.py \
       telemetry_tool/web/routes/teams.py \
       telemetry_tool/web/app.py
git commit -m "feat(api): workspace and team management routes"
```

---

### Task 11: Update unique constraints for workspace scoping

**Files:**
- Create: `telemetry_tool/alembic/versions/008_workspace_unique_constraints.py`
- Modify: `telemetry_tool/tests/test_workspace_schema.py`

The design specifies that certain uniqueness constraints must be scoped to workspace:
- `UNIQUE(workspace_id, driver_name)` on `drivers`
- `UNIQUE(workspace_id, track_id)` on `tracks` (track_id is the fingerprint)

**Step 1: Write migration**

```python
"""Update unique constraints to be workspace-scoped.

Revision ID: 008
Revises: 007
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"


def upgrade() -> None:
    # drivers: unique driver_name per workspace
    op.drop_constraint("drivers_driver_name_key", "drivers", type_="unique")
    op.create_unique_constraint(
        "uq_drivers_workspace_name", "drivers",
        ["workspace_id", "driver_name"],
    )

    # tracks: unique track_id (fingerprint) per workspace
    op.drop_constraint("tracks_track_id_key", "tracks", type_="unique")
    op.create_unique_constraint(
        "uq_tracks_workspace_fingerprint", "tracks",
        ["workspace_id", "track_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_tracks_workspace_fingerprint", "tracks", type_="unique")
    op.create_unique_constraint("tracks_track_id_key", "tracks", ["track_id"])

    op.drop_constraint("uq_drivers_workspace_name", "drivers", type_="unique")
    op.create_unique_constraint("drivers_driver_name_key", "drivers", ["driver_name"])
```

**Step 2: Add test, run, commit**

```bash
git add telemetry_tool/alembic/versions/008_workspace_unique_constraints.py \
       telemetry_tool/tests/test_workspace_schema.py
git commit -m "feat(tenancy): workspace-scoped unique constraints for drivers and tracks"
```

---

## Verification Checklist (Phase 2 Complete)

After all tasks are implemented, verify:

- [ ] `alembic upgrade head` runs 004→005→006→007→008 without error
- [ ] Default workspace created with all existing data assigned to it
- [ ] `USE_PG=1 AUTH_REQUIRED=0` — legacy mode: all data visible, default workspace used
- [ ] `USE_PG=1 AUTH_REQUIRED=1` — workspace scoped: only own data visible via RLS
- [ ] `X-Workspace-Id` header switches workspace context
- [ ] Personal workspace auto-created on user registration
- [ ] Team creation creates team + workspace + owner membership
- [ ] RBAC decorators enforce role hierarchy: owner > admin > member > viewer
- [ ] `USE_PG=0` — app works identically (SQLite, no tenancy)
- [ ] All existing tests pass
- [ ] All new tenancy/RBAC tests pass
