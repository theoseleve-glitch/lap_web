"""Test migration 078: track_racing_lines global table.

Skips automatically when TELEMETRY_PG_URL is not set (no local PG in CI).
Authoritative scratch-DB apply/verify is deferred to the controller.

Adapted from the repo's test_db_connection.py pattern — pg_conn fixture and
pytest.mark.pg do NOT exist in this codebase, so we use a local skipif mark
and connect directly via psycopg2 in the test body.
"""
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


@_skip_no_pg
def test_078_creates_global_racing_lines_table():
    """Assert table columns, no workspace_id, and RLS disabled."""
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
            assert {
                "track_id", "vehicle_class", "condition", "line_kind",
                "points", "status", "computed_at",
            } <= cols, f"Missing expected columns; found: {cols}"
            # global table — must NOT have workspace_id or RLS
            assert "workspace_id" not in cols, \
                "workspace_id must not exist on global table"
            cur.execute(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE relname='track_racing_lines'"
            )
            row = cur.fetchone()
            assert row is not None, "track_racing_lines not found in pg_class"
            assert row[0] is False, "RLS must be disabled on global table"
    finally:
        conn.close()
