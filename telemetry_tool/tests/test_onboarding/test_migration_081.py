"""Test migration 081: track_onboarding_requests (track onboarding loop, Task 3).

Two checks, mirroring test_migration_080.py / test_migration_073.py:
  * a structural one that runs everywhere (no PG needed) -- 081 chains off the
    080 head, defines upgrade/downgrade, and its DDL references the expected
    table/index names and the partial-unique dedup predicate;
  * a PG table/index-existence check that skips when TELEMETRY_PG_URL is
    unset (no local PG in CI).

Authoritative scratch-DB apply/verify is deferred to the controller.
"""
import importlib.util
import inspect
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_pg_url = os.environ.get("TELEMETRY_PG_URL", "")
_skip_no_pg = pytest.mark.skipif(
    not _pg_url,
    reason="TELEMETRY_PG_URL not set -- skipping PostgreSQL migration test",
)

_MIGRATION = (
    _PROJECT_ROOT / "alembic" / "versions" / "081_track_onboarding_requests.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m081", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_file_exists():
    assert _MIGRATION.exists(), f"Missing migration file: {_MIGRATION}"


def test_081_revision_chains_off_080():
    """Runs without PG: 081 is a valid revision chained onto the 080 head."""
    mod = _load_migration()
    assert mod.revision == "081_track_onboarding_requests"
    assert mod.down_revision == "080_racing_line_honesty"
    assert mod.branch_labels is None
    assert mod.depends_on is None
    assert callable(mod.upgrade) and callable(mod.downgrade)


def test_081_no_other_migration_claims_080_as_parent():
    """Single-head guard: 081 must be the ONLY file chaining off 080."""
    versions_dir = _MIGRATION.parent
    claimants = [
        p for p in versions_dir.glob("*.py")
        if p.name != _MIGRATION.name
        and 'down_revision = "080_racing_line_honesty"' in p.read_text(encoding="utf-8")
    ]
    assert claimants == [], f"080 has multiple children (broken alembic head): {claimants}"


def test_081_creates_table_with_expected_columns():
    upgrade_src = inspect.getsource(_load_migration().upgrade)
    assert '"track_onboarding_requests"' in upgrade_src
    for col in (
        '"id"', '"track_key"', '"track_label"', '"fingerprint"', '"status"',
        '"bbox"', '"first_session_ref"', '"session_refs"', '"session_count"',
        '"draft_status"', '"draft_path"', '"token_jti"', '"error"',
        '"created_at"', '"updated_at"', '"emailed_at"', '"blessed_at"',
    ):
        assert col in upgrade_src, f"missing column {col} in upgrade()"


def test_081_partial_unique_index_on_open_requests():
    upgrade_src = inspect.getsource(_load_migration().upgrade)
    assert "ux_onboarding_open" in upgrade_src
    assert "status <> 'blessed'" in upgrade_src


def test_081_status_created_index():
    upgrade_src = inspect.getsource(_load_migration().upgrade)
    assert "ix_onboarding_status_created" in upgrade_src


def test_081_is_a_global_table_no_workspace_id():
    """No workspace_id column, no RLS wiring -- intentional per the module docstring."""
    upgrade_src = inspect.getsource(_load_migration().upgrade)
    assert "workspace_id" not in upgrade_src
    assert "ROW LEVEL SECURITY" not in upgrade_src


def test_081_downgrade_drops_table_and_indexes():
    downgrade_src = inspect.getsource(_load_migration().downgrade)
    assert "track_onboarding_requests" in downgrade_src
    assert "ux_onboarding_open" in downgrade_src
    assert "ix_onboarding_status_created" in downgrade_src


@_skip_no_pg
def test_081_table_and_indexes_exist_in_pg():
    import psycopg2  # noqa: PLC0415

    conn = psycopg2.connect(_pg_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='track_onboarding_requests'"
            )
            cols = {r[0] for r in cur.fetchall()}
            expected = {
                "id", "track_key", "track_label", "fingerprint", "status",
                "bbox", "first_session_ref", "session_refs", "session_count",
                "draft_status", "draft_path", "token_jti", "error",
                "created_at", "updated_at", "emailed_at", "blessed_at",
            }
            assert expected <= cols, f"missing columns; found: {cols}"
            assert "workspace_id" not in cols

            cur.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename='track_onboarding_requests'"
            )
            idx = {r[0] for r in cur.fetchall()}
            assert {"ux_onboarding_open", "ix_onboarding_status_created"} <= idx
    finally:
        conn.close()
