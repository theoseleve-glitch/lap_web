"""Tests for migration 075 — user_consent.

Per-user consent record (analytics / marketing booleans) keyed 1:1 to
``users(id)``. Used by the consent gate before any behavioral event is emitted.
Idempotent CREATE; downgrade drops the table.

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

_MIGRATION_PATH = _PROJECT_ROOT / "alembic" / "versions" / "075_user_consent.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_075", str(_MIGRATION_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _source_text() -> str:
    return _MIGRATION_PATH.read_text(encoding="utf-8")


class TestMigrationFileAndRevision:
    def test_migration_file_exists(self):
        assert _MIGRATION_PATH.exists(), f"Missing migration file: {_MIGRATION_PATH}"

    def test_revision_is_075(self):
        assert _load_migration().revision == "075"

    def test_down_revision_is_074(self):
        assert _load_migration().down_revision == "074"


class TestUpgradeSchema:
    def test_creates_table_idempotently(self):
        assert "CREATE TABLE IF NOT EXISTS user_consent" in _source_text()

    def test_user_id_primary_key_references_users(self):
        src = _source_text()
        assert "user_id INTEGER PRIMARY KEY" in src
        assert "REFERENCES users(id)" in src

    def test_has_all_columns(self):
        src = _source_text()
        for col in ("analytics", "marketing", "version", "updated_at"):
            assert col in src, f"Missing column {col!r}"

    def test_consent_booleans_default_false(self):
        src = _source_text()
        assert "analytics BOOLEAN NOT NULL DEFAULT false" in src
        assert "marketing BOOLEAN NOT NULL DEFAULT false" in src

    def test_version_is_not_null(self):
        assert "version INTEGER NOT NULL" in _source_text()


class TestDowngrade:
    def test_downgrade_drops_table(self):
        downgrade_src = inspect.getsource(_load_migration().downgrade)
        assert "DROP TABLE IF EXISTS user_consent" in downgrade_src

    def test_upgrade_and_downgrade_callable(self):
        mod = _load_migration()
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)
