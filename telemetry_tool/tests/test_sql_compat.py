"""Tests for the SQL compatibility layer (Task 6).

All tests run without a live PostgreSQL instance -- they exercise
pure string translation logic gated by the ``USE_PG`` env var.
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on path (mirrors conftest.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.sql_compat import translate_params


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _enable_pg(monkeypatch):
    """By default all tests run in PG mode; individual tests override."""
    monkeypatch.setenv("USE_PG", "1")


# ------------------------------------------------------------------
# 1. Named parameters
# ------------------------------------------------------------------

def test_named_params():
    """:session_id -> %(session_id)s"""
    sql = "SELECT * FROM sessions WHERE session_id = :session_id;"
    result = translate_params(sql)
    assert "%(session_id)s" in result
    assert ":session_id" not in result


def test_named_params_multiple():
    """Multiple named params in the same query."""
    sql = (
        "SELECT * FROM laps "
        "WHERE session_id = :session_id AND lap_number = :lap_number;"
    )
    result = translate_params(sql)
    assert "%(session_id)s" in result
    assert "%(lap_number)s" in result
    assert ":session_id" not in result
    assert ":lap_number" not in result


# ------------------------------------------------------------------
# 2. Positional parameters
# ------------------------------------------------------------------

def test_positional_params():
    """? -> %s"""
    sql = "INSERT INTO laps (session_id, lap_number) VALUES (?, ?);"
    result = translate_params(sql)
    assert result.count("%s") == 2
    assert "?" not in result


# ------------------------------------------------------------------
# 3. No parameters (passthrough)
# ------------------------------------------------------------------

def test_no_params():
    """Plain SQL with no params passes through unchanged (except whitespace)."""
    sql = "SELECT COUNT(*) FROM sessions;"
    result = translate_params(sql)
    assert result == sql


# ------------------------------------------------------------------
# 4. INSERT OR IGNORE
# ------------------------------------------------------------------

def test_insert_or_ignore():
    """INSERT OR IGNORE -> INSERT INTO ... ON CONFLICT DO NOTHING."""
    sql = (
        "INSERT OR IGNORE INTO drivers (driver_name) "
        "VALUES (:driver_name);"
    )
    result = translate_params(sql)
    assert "INSERT INTO" in result
    assert "OR IGNORE" not in result
    assert "ON CONFLICT DO NOTHING" in result
    # Named param should also be translated
    assert "%(driver_name)s" in result


# ------------------------------------------------------------------
# 5. INSERT OR REPLACE
# ------------------------------------------------------------------

def test_insert_or_replace():
    """INSERT OR REPLACE strips OR REPLACE, warns (requires manual conversion)."""
    sql = (
        "INSERT OR REPLACE INTO laps "
        "(session_id, lap_number, lap_time_s) "
        "VALUES (:session_id, :lap_number, :lap_time_s);"
    )
    result = translate_params(sql)
    assert "INSERT INTO" in result
    assert "OR REPLACE" not in result
    # No ON CONFLICT generated — requires manual conversion with conflict target
    assert "ON CONFLICT" not in result


# ------------------------------------------------------------------
# 6. LIKE patterns preserved
# ------------------------------------------------------------------

def test_does_not_mangle_like():
    """LIKE '%test%' must not be confused with %s params."""
    sql = "SELECT * FROM sessions WHERE csv_filename LIKE '%test%';"
    result = translate_params(sql)
    assert "'%test%'" in result


def test_like_with_named_param():
    """LIKE pattern + named param: both translated correctly."""
    sql = (
        "SELECT * FROM sessions "
        "WHERE csv_filename LIKE '%test%' AND driver_id = :driver_id;"
    )
    result = translate_params(sql)
    assert "'%test%'" in result
    assert "%(driver_id)s" in result


# ------------------------------------------------------------------
# 7. PostgreSQL :: type-casts preserved
# ------------------------------------------------------------------

def test_does_not_mangle_typecast():
    """::text must not be confused with :name params."""
    sql = "SELECT session_id::text FROM sessions WHERE session_id = :session_id;"
    result = translate_params(sql)
    assert "::text" in result
    assert "%(session_id)s" in result


def test_typecast_int():
    """::int should be preserved."""
    sql = "SELECT total_score::int FROM sessions;"
    result = translate_params(sql)
    assert "::int" in result


# ------------------------------------------------------------------
# 8. Passthrough when SQLite mode
# ------------------------------------------------------------------

def test_passthrough_when_sqlite(monkeypatch):
    """When USE_PG=0, translate_params returns SQL unchanged."""
    monkeypatch.setenv("USE_PG", "0")
    sql = "SELECT * FROM sessions WHERE session_id = :session_id;"
    result = translate_params(sql)
    assert result == sql
    assert ":session_id" in result  # NOT translated


def test_passthrough_when_unset(monkeypatch):
    """When USE_PG is absent, translate_params returns SQL unchanged."""
    monkeypatch.delenv("USE_PG", raising=False)
    sql = "INSERT OR IGNORE INTO drivers (driver_name) VALUES (:driver_name);"
    result = translate_params(sql)
    assert result == sql  # No translation


# ------------------------------------------------------------------
# 9. Edge cases
# ------------------------------------------------------------------

def test_multiple_statements():
    """Named params across multiple semicolon-separated statements."""
    sql = (
        "SELECT * FROM sessions WHERE session_id = :sid; "
        "SELECT * FROM laps WHERE session_id = :sid;"
    )
    result = translate_params(sql)
    assert result.count("%(sid)s") == 2


def test_real_query_from_codebase():
    """Translate a real query from queries.py (INSERT_SESSION)."""
    sql = (
        "INSERT OR REPLACE INTO sessions (\n"
        "    session_id, csv_filename, driver_id\n"
        ") VALUES (\n"
        "    :session_id, :csv_filename, :driver_id\n"
        ");"
    )
    result = translate_params(sql)
    assert "OR REPLACE" not in result
    # Params still translated even though ON CONFLICT not auto-generated
    assert "%(session_id)s" in result
    assert "%(csv_filename)s" in result
    assert "%(driver_id)s" in result
