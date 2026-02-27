"""Tests for the usage tracking service.

Uses MagicMock connections -- no real database required.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.usage import (
    get_current_period,
    get_usage_count,
    increment_usage,
    get_usage_snapshot,
)


# ── Tests: get_current_period ──────────────────────────────────────────

class TestCurrentPeriod:
    def test_returns_yyyy_mm_format(self):
        period = get_current_period()
        assert len(period) == 7
        assert period[4] == "-"

    def test_returns_current_month(self):
        now = datetime.now(timezone.utc)
        expected = f"{now.year}-{now.month:02d}"
        assert get_current_period() == expected

    def test_month_is_zero_padded(self):
        period = get_current_period()
        month_part = period.split("-")[1]
        assert len(month_part) == 2


# ── Tests: get_usage_count ─────────────────────────────────────────────

class TestGetUsageCount:
    def test_returns_zero_when_no_row(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        count = get_usage_count(conn, workspace_id=1, metric="reports")
        assert count == 0

    def test_returns_count_from_row(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"count": 7}
        count = get_usage_count(conn, workspace_id=1, metric="reports")
        assert count == 7

    def test_uses_default_period_when_none(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        get_usage_count(conn, workspace_id=1, metric="reports")
        # Verify the SQL was called with current period
        call_args = conn.execute.call_args
        params = call_args[0][1]
        assert params["p"] == get_current_period()

    def test_uses_explicit_period(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"count": 3}
        count = get_usage_count(conn, workspace_id=1, metric="reports", period="2025-12")
        assert count == 3
        call_args = conn.execute.call_args
        params = call_args[0][1]
        assert params["p"] == "2025-12"

    def test_queries_correct_table(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        get_usage_count(conn, workspace_id=42, metric="uploads")
        sql_arg = conn.execute.call_args[0][0]
        assert "usage_counters" in sql_arg
        params = conn.execute.call_args[0][1]
        assert params["ws"] == 42
        assert params["m"] == "uploads"


# ── Tests: increment_usage ─────────────────────────────────────────────

class TestIncrementUsage:
    def test_calls_upsert(self):
        conn = MagicMock()
        # First call is the INSERT/upsert, second is the SELECT in get_usage_count
        conn.execute.return_value.fetchone.return_value = {"count": 1}
        increment_usage(conn, workspace_id=1, metric="reports")
        # At least one execute call for the upsert
        assert conn.execute.call_count >= 1
        first_sql = conn.execute.call_args_list[0][0][0]
        assert "INSERT INTO" in first_sql
        assert "usage_counters" in first_sql
        assert "ON CONFLICT" in first_sql

    def test_does_not_commit_mid_request(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"count": 1}
        increment_usage(conn, workspace_id=1, metric="uploads")
        conn.commit.assert_not_called()

    def test_default_amount_is_one(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"count": 1}
        increment_usage(conn, workspace_id=1, metric="reports")
        params = conn.execute.call_args_list[0][0][1]
        assert params["amt"] == 1

    def test_custom_amount(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"count": 5}
        increment_usage(conn, workspace_id=1, metric="reports", amount=5)
        params = conn.execute.call_args_list[0][0][1]
        assert params["amt"] == 5

    def test_returns_new_count(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"count": 8}
        result = increment_usage(conn, workspace_id=1, metric="reports")
        assert result == 8


# ── Tests: get_usage_snapshot ──────────────────────────────────────────

class TestUsageSnapshot:
    def test_returns_all_tracked_metrics(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        snapshot = get_usage_snapshot(conn, workspace_id=1, plan="racer")
        assert "reports" in snapshot
        assert "uploads" in snapshot

    def test_racer_limits(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        snapshot = get_usage_snapshot(conn, workspace_id=1, plan="racer")
        assert snapshot["reports"]["limit"] == 10
        assert snapshot["reports"]["used"] == 0
        assert snapshot["reports"]["remaining"] == 10
        assert snapshot["uploads"]["limit"] == 10

    def test_free_limits(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        snapshot = get_usage_snapshot(conn, workspace_id=1, plan="free")
        assert snapshot["reports"]["limit"] == 1
        assert snapshot["uploads"]["limit"] == 1

    def test_world_class_unlimited(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        snapshot = get_usage_snapshot(conn, workspace_id=1, plan="world_class")
        assert snapshot["reports"]["limit"] == -1
        assert snapshot["reports"]["remaining"] == -1
        assert snapshot["uploads"]["limit"] == -1

    def test_includes_reset_date(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        snapshot = get_usage_snapshot(conn, workspace_id=1, plan="racer")
        resets = snapshot["reports"]["resets"]
        # Should be YYYY-MM-DD format, first of next month
        parts = resets.split("-")
        assert len(parts) == 3
        assert parts[2] == "01"

    def test_with_existing_usage(self):
        conn = MagicMock()
        # Return count=7 for every get_usage_count call
        conn.execute.return_value.fetchone.return_value = {"count": 7}
        snapshot = get_usage_snapshot(conn, workspace_id=1, plan="racer")
        assert snapshot["reports"]["used"] == 7
        assert snapshot["reports"]["remaining"] == 3  # 10 - 7

    def test_unknown_plan_falls_back_to_free(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        snapshot = get_usage_snapshot(conn, workspace_id=1, plan="nonexistent")
        assert snapshot["reports"]["limit"] == 1  # free plan default
