"""Test migration 080: honesty-layer columns on track_racing_lines (spec C, §5).

Two checks:
  * a structural one that runs everywhere (no PG needed) — 080 chains off the
    079 head and defines upgrade/downgrade;
  * a PG column-existence check that skips when TELEMETRY_PG_URL is unset
    (no local PG in CI), mirroring test_migration_078.

Authoritative scratch-DB apply/verify is deferred to the controller.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_pg_url = os.environ.get("TELEMETRY_PG_URL", "")
_skip_no_pg = pytest.mark.skipif(
    not _pg_url,
    reason="TELEMETRY_PG_URL not set -- skipping PostgreSQL migration test",
)

_MIGRATION = _PROJECT_ROOT / "alembic" / "versions" / "080_racing_line_honesty.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("m080", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_080_revision_chains_off_079():
    """Runs without PG: 080 is a valid revision chained onto the 079 head."""
    mod = _load_migration()
    assert mod.revision == "080_racing_line_honesty"
    assert mod.down_revision == "079_track_geometry_audit"
    assert callable(mod.upgrade) and callable(mod.downgrade)


@_skip_no_pg
def test_080_adds_honesty_columns():
    """The honesty contract columns (geometry_source, tier, provenance) exist."""
    import psycopg2  # noqa: PLC0415

    conn = psycopg2.connect(_pg_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='track_racing_lines'"
            )
            cols = {r[0] for r in cur.fetchall()}
            assert {"geometry_source", "tier", "provenance"} <= cols, \
                f"missing honesty columns; found: {cols}"
            # still a global table — no workspace_id / no RLS
            assert "workspace_id" not in cols
    finally:
        conn.close()
