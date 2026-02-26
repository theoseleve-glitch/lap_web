"""Tests for workspace/tenancy schema migrations (004-008)."""
import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _load_migration(name):
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigration004:
    def test_exists(self):
        assert (_VERSIONS / "004_workspace_tables.py").exists()

    def test_revision_chain(self):
        mod = _load_migration("004_workspace_tables.py")
        assert mod.revision == "004"
        assert mod.down_revision == "003"

    def test_has_upgrade_downgrade(self):
        mod = _load_migration("004_workspace_tables.py")
        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))


class TestMigration005:
    def test_exists(self):
        assert (_VERSIONS / "005_add_workspace_id.py").exists()

    def test_revision_chain(self):
        mod = _load_migration("005_add_workspace_id.py")
        assert mod.revision == "005"
        assert mod.down_revision == "004"

    def test_tenant_tables_count(self):
        mod = _load_migration("005_add_workspace_id.py")
        assert len(mod.TENANT_TABLES) == 44

    def test_no_global_tables_included(self):
        mod = _load_migration("005_add_workspace_id.py")
        global_tables = {"schema_version", "predefined_tracks", "predefined_karts",
                         "predefined_track_coords", "users", "refresh_tokens",
                         "oauth_connections", "teams", "team_members", "workspaces", "audit_log"}
        assert not global_tables.intersection(set(mod.TENANT_TABLES))


class TestMigration006:
    def test_exists(self):
        assert (_VERSIONS / "006_backfill_workspace_id.py").exists()

    def test_revision_chain(self):
        mod = _load_migration("006_backfill_workspace_id.py")
        assert mod.revision == "006"
        assert mod.down_revision == "005"

    def test_same_tenant_tables_as_005(self):
        m005 = _load_migration("005_add_workspace_id.py")
        m006 = _load_migration("006_backfill_workspace_id.py")
        assert m006.TENANT_TABLES == m005.TENANT_TABLES


class TestMigration007:
    def test_exists(self):
        assert (_VERSIONS / "007_enable_rls.py").exists()

    def test_revision_chain(self):
        mod = _load_migration("007_enable_rls.py")
        assert mod.revision == "007"
        assert mod.down_revision == "006"

    def test_same_tenant_tables_as_005(self):
        m005 = _load_migration("005_add_workspace_id.py")
        m007 = _load_migration("007_enable_rls.py")
        assert m007.TENANT_TABLES == m005.TENANT_TABLES


class TestMigration008:
    def test_migration_008_exists(self):
        assert (_VERSIONS / "008_workspace_unique_constraints.py").exists()

    def test_revision_chain(self):
        mod = _load_migration("008_workspace_unique_constraints.py")
        assert mod.revision == "008"
        assert mod.down_revision == "007"

    def test_has_upgrade_downgrade(self):
        mod = _load_migration("008_workspace_unique_constraints.py")
        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))
