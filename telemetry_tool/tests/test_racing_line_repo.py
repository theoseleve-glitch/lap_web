"""Test racing_line_repo CRUD over track_racing_lines (migration 078).

Skips automatically when TELEMETRY_PG_URL is not set — no local PG in dev.
Authoritative upsert/read/status integration test against a scratch DB is
run by the controller.  Local job: module imports cleanly, test collects and
skips without errors.

Adapted from the ``_skip_no_pg`` pattern in ``test_migration_078.py`` and
``test_db_connection.py`` — direct psycopg2, no pg_conn fixture (the fixture
and ``pytest.mark.pg`` do not exist in this codebase).
"""
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.track_surface.racing_line_repo import (  # noqa: E402
    get_racing_lines,
    set_racing_line_status,
    upsert_racing_line,
)

_pg_url = os.environ.get("TELEMETRY_PG_URL", "")
_skip_no_pg = pytest.mark.skipif(
    not _pg_url,
    reason="TELEMETRY_PG_URL not set -- skipping PostgreSQL racing_line_repo test",
)

# Unlikely to collide with production data
_TEST_TRACK_ID = "T1_rl_repo_test"

_DTO = {
    "points": [{"d": 0.0, "n": 0.1, "v": 30.0}],
    "condition": "dry",
    "solver_meta": {
        "status": "solved",
        "solve_time_s": 1.0,
        "lap_time_s": 88.0,
    },
}


def _make_pg_conn():
    """Raw psycopg2 connection with RealDictCursor for dict-keyed row access."""
    import psycopg2  # noqa: PLC0415
    import psycopg2.extras  # noqa: PLC0415

    conn = psycopg2.connect(_pg_url)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


@_skip_no_pg
def test_upsert_is_idempotent_and_readback_parses_points():
    """Upsert twice → exactly one row; points decoded to list; status transition works."""
    conn = _make_pg_conn()
    try:
        # Clean any pre-existing rows from a prior failed run
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM track_racing_lines WHERE track_id = %s",
                (_TEST_TRACK_ID,),
            )
        conn.commit()

        # Idempotency: call upsert twice, expect one row
        for _ in range(2):
            upsert_racing_line(
                conn, _TEST_TRACK_ID, "generic", "dry", _DTO,
                solver_version="v1",
                grip_snapshot_hash="h1",
                n_laps_used=12,
            )
        conn.commit()

        rows = get_racing_lines(conn, _TEST_TRACK_ID, "generic")
        assert len(rows) == 1, f"Expected 1 row after idempotent upsert, got {len(rows)}"
        assert rows[0]["condition"] == "dry"
        assert isinstance(rows[0]["points"], list), (
            f"points must be a list, got {type(rows[0]['points'])}"
        )
        assert rows[0]["points"][0] == {"d": 0.0, "n": 0.1, "v": 30.0}, (
            f"Unexpected points value: {rows[0]['points']}"
        )
        assert rows[0]["status"] == "ok"

        # Status transition: mark failed
        set_racing_line_status(
            conn, _TEST_TRACK_ID, "generic", "dry", "failed", reason="timeout"
        )
        conn.commit()

        rows2 = get_racing_lines(conn, _TEST_TRACK_ID, "generic")
        assert rows2[0]["status"] == "failed", (
            f"Expected status 'failed', got {rows2[0]['status']!r}"
        )

    finally:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM track_racing_lines WHERE track_id = %s",
                    (_TEST_TRACK_ID,),
                )
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()


@_skip_no_pg
def test_set_status_inserts_placeholder_when_no_row_exists():
    """set_racing_line_status inserts a placeholder row when none exists yet."""
    conn = _make_pg_conn()
    try:
        # Ensure clean slate
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM track_racing_lines WHERE track_id = %s",
                (_TEST_TRACK_ID,),
            )
        conn.commit()

        # Insert via status call only (no prior upsert_racing_line)
        set_racing_line_status(
            conn, _TEST_TRACK_ID, "generic", "dry", "pending"
        )
        conn.commit()

        rows = get_racing_lines(conn, _TEST_TRACK_ID, "generic")
        assert len(rows) == 1, (
            f"Expected placeholder row, got {len(rows)} rows"
        )
        assert rows[0]["status"] == "pending"
        # Placeholder has empty points list
        assert rows[0]["points"] == [], (
            f"Expected empty points list for placeholder, got {rows[0]['points']}"
        )

    finally:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM track_racing_lines WHERE track_id = %s",
                    (_TEST_TRACK_ID,),
                )
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()


# --- Honesty-column wiring (spec C, Task 2) — verified WITHOUT PG via a
#     capturing fake connection that records the SQL + params. -----------------
import json as _json  # noqa: E402


class _CapturingCursor:
    def __init__(self, sink):
        self._sink = sink

    def execute(self, sql, params=None):
        self._sink.append((sql, params))

    def close(self):
        pass


class _CapturingConn:
    def __init__(self):
        self.calls = []

    def cursor(self, *a, **k):
        return _CapturingCursor(self.calls)


def test_upsert_writes_honesty_columns_no_pg():
    conn = _CapturingConn()
    upsert_racing_line(
        conn, "T", "generic", "dry", _DTO,
        solver_version="v1", grip_snapshot_hash="h", n_laps_used=5,
        geometry_source="gt_anchored_native", tier="optimal_line",
        provenance={"laps_used": 5},
    )
    sql, params = conn.calls[-1]
    assert "geometry_source" in sql and "tier" in sql and "provenance" in sql
    assert params["geometry_source"] == "gt_anchored_native"
    assert params["tier"] == "optimal_line"
    assert _json.loads(params["provenance"]) == {"laps_used": 5}


def test_upsert_provenance_none_is_null_no_pg():
    conn = _CapturingConn()
    upsert_racing_line(
        conn, "T", "generic", "dry", _DTO,
        solver_version="v1", grip_snapshot_hash="h", n_laps_used=0,
    )
    _, params = conn.calls[-1]
    assert params["provenance"] is None
    assert params["tier"] is None
    assert params["geometry_source"] is None


def test_set_status_persists_reason_as_provenance_no_pg():
    conn = _CapturingConn()
    set_racing_line_status(
        conn, "T", "generic", "dry", "failed",
        reason="solver_infeasible", tier="refused",
    )
    sql, params = conn.calls[-1]
    assert "provenance" in sql and "tier" in sql
    assert params["tier"] == "refused"
    assert _json.loads(params["provenance"]) == {"reason": "solver_infeasible"}
