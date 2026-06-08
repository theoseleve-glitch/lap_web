"""Tests for migration 076 — telemetry_maint role (NOSUPERUSER BYPASSRLS).

The admin/analytics surface reads cross-tenant aggregates via a role that
bypasses RLS. ``telemetry_maint`` ALREADY EXISTS on prod, so CREATE ROLE must be
guarded (a bare CREATE ROLE on an existing role aborts the migration
transaction); the role is ensured via ``ALTER ROLE`` otherwise. Because the role
BYPASSes RLS, it is granted **SELECT only** — any write grant would let the admin
mutate any tenant's rows. Downgrade revokes the grants but does NOT drop the role
(it predates this migration).

Structure tests only (no DB).
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_MIGRATION_PATH = (
    _PROJECT_ROOT / "alembic" / "versions" / "076_telemetry_maint_role.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_076", str(_MIGRATION_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _source_text() -> str:
    return _MIGRATION_PATH.read_text(encoding="utf-8")


class TestMigrationFileAndRevision:
    def test_migration_file_exists(self):
        assert _MIGRATION_PATH.exists(), f"Missing migration file: {_MIGRATION_PATH}"

    def test_revision_is_076(self):
        assert _load_migration().revision == "076"

    def test_down_revision_is_075(self):
        assert _load_migration().down_revision == "075"


class TestRoleDefinition:
    def test_mentions_role_with_attributes(self):
        src = _source_text()
        assert "telemetry_maint" in src
        assert "NOSUPERUSER" in src
        assert "BYPASSRLS" in src

    def test_create_role_is_guarded_on_pg_roles(self):
        upgrade_src = inspect.getsource(_load_migration().upgrade)
        assert "FROM pg_roles" in upgrade_src
        assert "rolname" in upgrade_src
        # Guard precedes CREATE ROLE so a bare CREATE never aborts the txn.
        assert "IF NOT EXISTS" in upgrade_src
        assert "CREATE ROLE telemetry_maint" in upgrade_src


class TestGrants:
    def test_grants_select_on_both_tables(self):
        src = _source_text()
        assert "GRANT SELECT ON app_events TO telemetry_maint" in src
        assert "GRANT SELECT ON marketing_events TO telemetry_maint" in src

    def test_no_write_grants_in_upgrade(self):
        upgrade_src = inspect.getsource(_load_migration().upgrade)
        for forbidden in ("GRANT INSERT", "GRANT UPDATE", "GRANT DELETE"):
            assert forbidden not in upgrade_src, (
                f"BYPASSRLS role must be read-only — found {forbidden!r}"
            )


class TestDowngrade:
    def test_downgrade_revokes_but_does_not_drop_role(self):
        downgrade_src = inspect.getsource(_load_migration().downgrade)
        assert "REVOKE" in downgrade_src
        assert "DROP ROLE" not in downgrade_src, (
            "telemetry_maint predates this migration — downgrade must NOT drop it"
        )

    def test_upgrade_and_downgrade_callable(self):
        mod = _load_migration()
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)
