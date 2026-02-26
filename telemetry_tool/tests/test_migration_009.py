"""Tests for Alembic migration 009 — Celery pipeline columns, batch_jobs table."""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_migration():
    """Import migration 009 as a module."""
    migration_path = _PROJECT_ROOT / "alembic" / "versions" / "009_celery_pipeline.py"
    spec = importlib.util.spec_from_file_location("migration_009", migration_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigrationMetadata:
    """Verify module-level revision identifiers."""

    def test_revision_is_009(self):
        mod = _load_migration()
        assert mod.revision == "009"

    def test_down_revision_is_008(self):
        mod = _load_migration()
        assert mod.down_revision == "008"


class TestUpgradeFunction:
    """Verify upgrade() exists and contains expected schema changes."""

    def test_upgrade_is_callable(self):
        mod = _load_migration()
        assert callable(mod.upgrade)

    def test_upgrade_contains_all_ingestion_jobs_columns(self):
        mod = _load_migration()
        source = inspect.getsource(mod.upgrade)
        expected_columns = [
            "celery_task_id",
            "processing_version",
            "stage_name",
            "stage_index",
            "stage_total",
            "progress_pct",
            "error_class",
            "pause_reason",
            "updated_at",
        ]
        for col in expected_columns:
            assert col in source, f"Missing column {col!r} in upgrade()"

    def test_upgrade_creates_batch_jobs_table(self):
        mod = _load_migration()
        source = inspect.getsource(mod.upgrade)
        assert "batch_jobs" in source

    def test_upgrade_adds_sessions_processing_version(self):
        mod = _load_migration()
        source = inspect.getsource(mod.upgrade)
        assert "sessions" in source
        assert "processing_version" in source


class TestDowngradeFunction:
    """Verify downgrade() exists and is callable."""

    def test_downgrade_is_callable(self):
        mod = _load_migration()
        assert callable(mod.downgrade)

    def test_downgrade_drops_batch_jobs(self):
        mod = _load_migration()
        source = inspect.getsource(mod.downgrade)
        assert "batch_jobs" in source

    def test_downgrade_drops_added_columns(self):
        mod = _load_migration()
        source = inspect.getsource(mod.downgrade)
        expected_drops = [
            "celery_task_id",
            "processing_version",
            "stage_name",
            "stage_index",
            "stage_total",
            "progress_pct",
            "error_class",
            "pause_reason",
            "updated_at",
        ]
        for col in expected_drops:
            assert col in source, f"Missing drop for column {col!r} in downgrade()"
