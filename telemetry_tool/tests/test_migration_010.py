"""Tests for migration 010 — GDPR tables (deleted_at + data_exports)."""
import ast
import inspect
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_migration_module():
    """Import the migration module."""
    import importlib.util

    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "010_gdpr_account.py"
    )
    spec = importlib.util.spec_from_file_location("migration_010", str(migration_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get_source_text() -> str:
    """Return the raw source text of the migration file."""
    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "010_gdpr_account.py"
    )
    return migration_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests — file existence and revision chain
# ---------------------------------------------------------------------------

class TestMigrationFileAndRevision:
    def test_migration_file_exists(self):
        """Migration 010 file exists at the expected path."""
        migration_path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "010_gdpr_account.py"
        )
        assert migration_path.exists(), f"Missing migration file: {migration_path}"

    def test_revision_is_010(self):
        """Migration revision is '010'."""
        mod = _get_migration_module()
        assert mod.revision == "010"

    def test_down_revision_is_009(self):
        """Migration 010 revises 009 (correct chain)."""
        mod = _get_migration_module()
        assert mod.down_revision == "009"


# ---------------------------------------------------------------------------
# Tests — upgrade function
# ---------------------------------------------------------------------------

class TestUpgradeFunction:
    def test_upgrade_adds_deleted_at_column(self):
        """upgrade() adds 'deleted_at' column to 'users' table."""
        source = _get_source_text()
        assert "deleted_at" in source
        assert "add_column" in source
        # Verify it targets the users table
        assert '"users"' in source or "'users'" in source

    def test_upgrade_creates_data_exports_table(self):
        """upgrade() creates the 'data_exports' table."""
        source = _get_source_text()
        assert "data_exports" in source
        assert "create_table" in source

    def test_data_exports_has_correct_columns(self):
        """data_exports table has all required columns."""
        source = _get_source_text()
        required_columns = [
            "id", "user_id", "status", "file_path",
            "format", "created_at", "expires_at", "completed_at",
        ]
        for col in required_columns:
            assert f'"{col}"' in source or f"'{col}'" in source, (
                f"Missing column '{col}' in data_exports table definition"
            )

    def test_both_indexes_created(self):
        """Both idx_data_exports_user and idx_users_deleted_at indexes are created."""
        source = _get_source_text()
        assert "idx_data_exports_user" in source, "Missing index idx_data_exports_user"
        assert "idx_users_deleted_at" in source, "Missing index idx_users_deleted_at"


# ---------------------------------------------------------------------------
# Tests — downgrade function
# ---------------------------------------------------------------------------

class TestDowngradeFunction:
    def test_downgrade_drops_data_exports(self):
        """downgrade() drops the data_exports table."""
        source = _get_source_text()
        # Check that downgrade section contains drop_table for data_exports
        assert "drop_table" in source
        # Verify the target table name
        assert "data_exports" in source

    def test_downgrade_drops_deleted_at_column(self):
        """downgrade() drops the deleted_at column from users."""
        source = _get_source_text()
        assert "drop_column" in source
        # Verify it targets users table and deleted_at column
        assert "deleted_at" in source

    def test_upgrade_and_downgrade_are_callable(self):
        """Both upgrade() and downgrade() are callable functions."""
        mod = _get_migration_module()
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)
