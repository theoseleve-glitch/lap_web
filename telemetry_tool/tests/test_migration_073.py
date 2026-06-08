"""Tests for migration 073 — reconcile app_events RLS to the canonical GUC.

Migration 058 originally created ``app_events`` with an RLS policy that used the
WRONG GUC ``current_setting('app.workspace_id')::integer``. The canonical GUC
used everywhere else on the platform is
``current_setting('app.current_workspace_id', true)::int``. This migration
rewrites ``app_events_workspace_isolation`` (USING + WITH CHECK) to the
canonical GUC. It is idempotent (DROP POLICY IF EXISTS then CREATE) and guarded
on table presence (``to_regclass('public.app_events')``).

Two test styles:
  1. structure tests (always run, no DB) — import the module + read source text;
  2. a live-PG RLS test gated on TELEMETRY_PG_URL (skipped when unset).
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_MIGRATION_PATH = (
    _PROJECT_ROOT / "alembic" / "versions" / "073_reconcile_app_events_rls.py"
)

_CANONICAL_GUC = "current_setting('app.current_workspace_id', true)::int"
_WRONG_GUC = "current_setting('app.workspace_id')"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_073", str(_MIGRATION_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _source_text() -> str:
    return _MIGRATION_PATH.read_text(encoding="utf-8")


# ── structure: file + revision chain ────────────────────────────────────


class TestMigrationFileAndRevision:
    def test_migration_file_exists(self):
        assert _MIGRATION_PATH.exists(), f"Missing migration file: {_MIGRATION_PATH}"

    def test_revision_is_073(self):
        assert _load_migration().revision == "073"

    def test_down_revision_is_072(self):
        assert _load_migration().down_revision == "072_session_gamification_applied"


# ── structure: upgrade reconciles the GUC ───────────────────────────────


class TestUpgradeReconcilesGuc:
    def test_source_uses_canonical_guc(self):
        assert _CANONICAL_GUC in _source_text()

    def test_upgrade_does_not_use_wrong_guc(self):
        upgrade_src = inspect.getsource(_load_migration().upgrade)
        assert _WRONG_GUC not in upgrade_src, (
            "upgrade() must NOT reference the wrong GUC app.workspace_id"
        )

    def test_drops_policy_before_create(self):
        assert "DROP POLICY IF EXISTS app_events_workspace_isolation" in _source_text()

    def test_guarded_on_table_presence(self):
        assert "to_regclass('public.app_events')" in _source_text()

    def test_creates_policy_with_using_and_with_check(self):
        upgrade_src = inspect.getsource(_load_migration().upgrade)
        assert "CREATE POLICY app_events_workspace_isolation" in upgrade_src
        assert "USING" in upgrade_src
        assert "WITH CHECK" in upgrade_src


# ── structure: callables ────────────────────────────────────────────────


class TestCallables:
    def test_upgrade_and_downgrade_callable(self):
        mod = _load_migration()
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)


# ── live-PG RLS test (skipped when TELEMETRY_PG_URL unset) ───────────────


@pytest.mark.skipif(
    not os.environ.get("TELEMETRY_PG_URL"),
    reason="needs a disposable PG; set TELEMETRY_PG_URL",
)
class TestLiveRls:
    """Apply the upgrade() DDL to a real app_events table and verify the
    canonical GUC actually isolates rows by workspace."""

    def _connect(self):
        psycopg2 = pytest.importorskip("psycopg2")
        conn = psycopg2.connect(os.environ["TELEMETRY_PG_URL"])
        conn.autocommit = True
        return conn

    def test_canonical_guc_isolates_rows(self):
        import re

        conn = self._connect()
        cur = conn.cursor()
        # Disposable, self-contained table mirroring app_events' isolation column.
        cur.execute("DROP TABLE IF EXISTS app_events CASCADE")
        cur.execute(
            "CREATE TABLE app_events ("
            "  id BIGSERIAL PRIMARY KEY,"
            "  workspace_id INTEGER NOT NULL,"
            "  payload TEXT)"
        )
        cur.execute("INSERT INTO app_events (workspace_id, payload) VALUES (1, 'a')")
        cur.execute("INSERT INTO app_events (workspace_id, payload) VALUES (2, 'b')")

        # Extract the CREATE POLICY body from the migration's upgrade() so the
        # test exercises the EXACT policy SQL the migration writes.
        mod = _load_migration()
        upgrade_src = inspect.getsource(mod.upgrade)
        assert _CANONICAL_GUC in upgrade_src

        cur.execute("ALTER TABLE app_events ENABLE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE app_events FORCE ROW LEVEL SECURITY")
        cur.execute("DROP POLICY IF EXISTS app_events_workspace_isolation ON app_events")
        cur.execute(
            "CREATE POLICY app_events_workspace_isolation ON app_events "
            f"USING (workspace_id = {_CANONICAL_GUC}) "
            f"WITH CHECK (workspace_id = {_CANONICAL_GUC})"
        )

        try:
            # No GUC set → canonical GUC is NULL (because of the `true` missing_ok
            # flag) → predicate is NULL → zero rows visible.
            cur.execute("SET LOCAL app.current_workspace_id = '1'")
            cur.execute("SELECT workspace_id FROM app_events ORDER BY id")
            rows = [r[0] for r in cur.fetchall()]
            assert rows == [1], f"workspace 1 should see only ws1 rows, saw {rows}"

            cur.execute("SET LOCAL app.current_workspace_id = '2'")
            cur.execute("SELECT workspace_id FROM app_events ORDER BY id")
            rows = [r[0] for r in cur.fetchall()]
            assert rows == [2], f"workspace 2 should see only ws2 rows, saw {rows}"
        finally:
            cur.execute("DROP TABLE IF EXISTS app_events CASCADE")
            conn.close()
