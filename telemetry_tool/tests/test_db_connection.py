"""Tests for the database connection abstraction (Task 5).

Verifies:
* SQLite remains the default when USE_PG is not set.
* PostgreSQL routing activates when USE_PG=1.
* PG connections return dict-accessible rows.
"""

import os
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

# Ensure project root is on path (mirrors conftest.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ------------------------------------------------------------------
# 1. SQLite default (always runnable)
# ------------------------------------------------------------------

def test_sqlite_default(monkeypatch):
    """Without USE_PG, get_db_connection() returns a sqlite3 connection."""
    monkeypatch.delenv("USE_PG", raising=False)

    from web.db import get_db_connection

    conn = get_db_connection(db_path=Path(":memory:"))
    try:
        assert isinstance(conn, sqlite3.Connection)
        # Verify row factory is set
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_sqlite_default_explicit_zero(monkeypatch):
    """USE_PG=0 is equivalent to unset -- still returns SQLite."""
    monkeypatch.setenv("USE_PG", "0")

    from web.db import get_db_connection

    conn = get_db_connection(db_path=Path(":memory:"))
    try:
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()


# ------------------------------------------------------------------
# 2. PostgreSQL routing (requires a live PG or gets skipped)
# ------------------------------------------------------------------

_pg_url = os.environ.get("TELEMETRY_PG_URL", "")
_skip_no_pg = pytest.mark.skipif(
    not _pg_url,
    reason="TELEMETRY_PG_URL not set -- no PostgreSQL available",
)


@_skip_no_pg
def test_pg_when_flag_on(monkeypatch):
    """With USE_PG=1, get_pg_connection() returns a psycopg2 connection."""
    monkeypatch.setenv("USE_PG", "1")

    # Import inside the test so the flag is already set.
    from web.db_pg import close_pool, get_pg_connection, return_pg_connection

    conn = get_pg_connection()
    try:
        import psycopg2.extensions
        assert isinstance(conn, psycopg2.extensions.connection)
    finally:
        return_pg_connection(conn)
        close_pool()


@_skip_no_pg
def test_pg_returns_dict_rows(monkeypatch):
    """PG connections use RealDictCursor -- rows are dict-accessible."""
    monkeypatch.setenv("USE_PG", "1")

    from web.db_pg import close_pool, get_pg_connection, return_pg_connection

    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 AS value")
        row = cur.fetchone()
        # RealDictCursor returns RealDictRow which supports dict access.
        assert row["value"] == 1
        cur.close()
    finally:
        return_pg_connection(conn)
        close_pool()


# ------------------------------------------------------------------
# 3. Routing integration (mocked -- no real PG needed)
# ------------------------------------------------------------------

def test_get_db_connection_routes_to_pg(monkeypatch):
    """get_db_connection() delegates to get_pg_connection when USE_PG=1."""
    monkeypatch.setenv("USE_PG", "1")

    sentinel = object()

    with mock.patch("web.db_pg.get_pg_connection", return_value=sentinel) as m:
        from web.db import get_db_connection
        result = get_db_connection()
        m.assert_called_once()
        assert result is sentinel
