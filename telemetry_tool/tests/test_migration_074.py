"""Tests for migration 074 — marketing_events (anonymous, GLOBAL, no RLS).

``marketing_events`` records anonymous front-of-funnel events. It is GLOBAL (no
workspace/tenant column) and therefore carries NO Row-Level Security. It must
NOT capture identifying fields (user_id / ip_address / user_agent). The table is
partitioned by range on ``created_at`` with a composite PK ``(id, created_at)``
(Postgres requires the partition key in the PK), with monthly partitions seeded
for 2026-06 / 2026-07 / 2026-08.

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

_MIGRATION_PATH = _PROJECT_ROOT / "alembic" / "versions" / "074_marketing_events.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_074", str(_MIGRATION_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _source_text() -> str:
    return _MIGRATION_PATH.read_text(encoding="utf-8")


class TestMigrationFileAndRevision:
    def test_migration_file_exists(self):
        assert _MIGRATION_PATH.exists(), f"Missing migration file: {_MIGRATION_PATH}"

    def test_revision_is_074(self):
        assert _load_migration().revision == "074"

    def test_down_revision_is_073(self):
        assert _load_migration().down_revision == "073"


class TestUpgradeSchema:
    def test_creates_table_idempotently(self):
        assert "CREATE TABLE IF NOT EXISTS marketing_events" in _source_text()

    def test_partitioned_by_range_on_created_at(self):
        assert "PARTITION BY RANGE (created_at)" in _source_text()

    def test_composite_primary_key(self):
        assert "PRIMARY KEY (id, created_at)" in _source_text()

    def test_three_monthly_partitions_present(self):
        src = _source_text()
        for part in (
            "marketing_events_2026_06",
            "marketing_events_2026_07",
            "marketing_events_2026_08",
        ):
            assert part in src, f"Missing partition {part!r}"

    def test_index_present(self):
        assert "ix_marketing_events_type_ts" in _source_text()

    def test_no_identifying_columns(self):
        upgrade_src = inspect.getsource(_load_migration().upgrade)
        for forbidden in ("user_id", "ip_address", "user_agent"):
            assert forbidden not in upgrade_src, (
                f"marketing_events must NOT capture {forbidden!r} (anonymous, GDPR)"
            )

    def test_no_row_level_security(self):
        upgrade_src = inspect.getsource(_load_migration().upgrade)
        assert "ROW LEVEL SECURITY" not in upgrade_src, (
            "marketing_events is GLOBAL — it must not enable RLS"
        )


class TestDowngrade:
    def test_downgrade_drops_table(self):
        downgrade_src = inspect.getsource(_load_migration().downgrade)
        assert "DROP TABLE IF EXISTS marketing_events" in downgrade_src

    def test_upgrade_and_downgrade_callable(self):
        mod = _load_migration()
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)
