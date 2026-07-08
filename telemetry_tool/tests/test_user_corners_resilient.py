"""_fetch_user_corners must degrade gracefully on a missing table.

User-defined corners are an optional override. On a fresh DB whose schema is
created only at persist time, step 10h queried user_corners before it existed
and the raw SELECT raised OperationalError, degrading the pipeline. A missing
table means "no overrides" -> None, not a failure.
"""
import sqlite3

from pipeline.orchestrator import _fetch_user_corners


def test_missing_table_returns_none_not_raise():
    conn = sqlite3.connect(":memory:")  # no user_corners table
    assert _fetch_user_corners(conn, "sess-1") is None


def test_none_conn_returns_none():
    assert _fetch_user_corners(None, "sess-1") is None


def test_empty_table_returns_empty_list():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_corners (session_id TEXT, corner_index INTEGER, "
        "s_entry REAL, s_apex REAL, s_exit REAL, lat_entry REAL, lon_entry REAL, "
        "lat_apex REAL, lon_apex REAL, lat_exit REAL, lon_exit REAL);"
    )
    conn.commit()
    assert _fetch_user_corners(conn, "sess-1") == []


def test_returns_rows_when_present():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_corners (session_id TEXT, corner_index INTEGER, "
        "s_entry REAL, s_apex REAL, s_exit REAL, lat_entry REAL, lon_entry REAL, "
        "lat_apex REAL, lon_apex REAL, lat_exit REAL, lon_exit REAL);"
    )
    conn.execute(
        "INSERT INTO user_corners VALUES ('sess-1', 1, 10, 20, 30, 0, 0, 0, 0, 0, 0);"
    )
    conn.commit()
    rows = _fetch_user_corners(conn, "sess-1")
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0]["corner_index"] == 1 and rows[0]["s_apex"] == 20
