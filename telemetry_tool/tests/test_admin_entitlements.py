"""Tests for admin entitlements service.

Verifies:
- get_workspace_usage_summary returns correct aggregation
- create_override inserts row and logs audit event
- detect_anomalies finds overspend, stale overrides, missing plans, tier mismatches
- refresh_user_tier updates tier when needed
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from admin.entitlements import (
    Anomaly,
    create_override,
    detect_anomalies,
    get_effective_entitlements,
    get_workspace_usage_summary,
    refresh_user_tier,
)


class TestGetWorkspaceUsageSummary:
    def test_returns_usage_by_event_type(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"event_type": "reports", "total": 5},
            {"event_type": "uploads", "total": 3},
        ]
        conn.execute.return_value = cur

        result = get_workspace_usage_summary(conn, workspace_id=1, period="2026-02")

        assert result == {"reports": 5, "uploads": 3}
        sql, params = conn.execute.call_args[0]
        assert params["ws"] == 1
        assert params["ps"] == "2026-02-01"

    def test_defaults_to_current_month(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn.execute.return_value = cur

        result = get_workspace_usage_summary(conn, workspace_id=1)

        assert result == {}
        sql, params = conn.execute.call_args[0]
        now = datetime.now(timezone.utc)
        assert params["ps"] == f"{now.strftime('%Y-%m')}-01"

    def test_empty_usage(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        conn.execute.return_value = cur

        result = get_workspace_usage_summary(conn, workspace_id=99, period="2025-01")
        assert result == {}


class TestCreateOverride:
    def test_inserts_override(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 42}
        conn.execute.return_value = cur

        override_id = create_override(
            conn,
            override_key="reports_per_month",
            override_value="50",
            reason="Promo code LAUNCH50",
            user_id=1,
            created_by=99,
        )

        assert override_id == 42
        sql, params = conn.execute.call_args_list[0][0]
        assert "INSERT INTO entitlement_overrides" in sql
        assert params["key"] == "reports_per_month"
        assert params["val"] == "50"
        assert params["uid"] == 1
        assert params["by"] == 99

    def test_requires_user_or_workspace(self):
        conn = MagicMock()

        with pytest.raises(ValueError, match="At least one"):
            create_override(
                conn,
                override_key="api_access",
                override_value="true",
                reason="test",
                created_by=1,
            )

    def test_workspace_level_override(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 7}
        conn.execute.return_value = cur

        override_id = create_override(
            conn,
            override_key="max_concurrent_jobs",
            override_value="5",
            reason="Enterprise deal",
            workspace_id=10,
            created_by=99,
        )

        assert override_id == 7
        sql, params = conn.execute.call_args_list[0][0]
        assert params["ws"] == 10
        assert params["uid"] is None


class TestRefreshUserTier:
    def test_no_subscription_sets_locked(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {
            "plan_tier": "racer",
            "stripe_subscription_id": None,
        }
        conn.execute.return_value = cur

        result = refresh_user_tier(conn, user_id=1, admin_user_id=99)

        assert result["old_tier"] == "racer"
        # No subscription → the zero-access locked floor (no free tier).
        assert result["new_tier"] == "locked"
        assert result["changed"] is True

    def test_user_not_found(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn.execute.return_value = cur

        result = refresh_user_tier(conn, user_id=999, admin_user_id=99)
        assert result == {"error": "user_not_found"}

    def test_with_subscription_keeps_tier(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {
            "plan_tier": "world-class",
            "stripe_subscription_id": "sub_test_123",
        }
        conn.execute.return_value = cur

        result = refresh_user_tier(conn, user_id=1, admin_user_id=99)

        assert result["old_tier"] == "world-class"
        assert result["new_tier"] == "world-class"
        assert result["changed"] is False


class TestDetectAnomalies:
    def _make_conn(self, queries_results: dict):
        """Create a mock conn that returns different results per query pattern."""
        conn = MagicMock()
        call_count = [0]

        def mock_execute(sql, params=None):
            cur = MagicMock()
            key = call_count[0]
            call_count[0] += 1

            if key < len(list(queries_results.values())):
                cur.fetchall.return_value = list(queries_results.values())[key]
            else:
                cur.fetchall.return_value = []
            return cur

        conn.execute.side_effect = mock_execute
        return conn

    def test_detects_overspend(self):
        conn = self._make_conn({
            "overspend": [
                {"workspace_id": 1, "event_type": "reports", "total": 15,
                 "plan_tier": "racer", "user_id": 42},
            ],
            "stale": [],
            "missing": [],
            "mismatch": [],
        })

        anomalies = detect_anomalies(conn)

        overspend = [a for a in anomalies if a.anomaly_type == "overspend"]
        assert len(overspend) == 1
        assert overspend[0].user_id == 42
        assert overspend[0].details["total"] == 15

    def test_detects_stale_overrides(self):
        conn = self._make_conn({
            "overspend": [],
            "stale": [
                {"id": 5, "user_id": 10, "workspace_id": None,
                 "override_key": "api_access",
                 "expires_at": datetime(2025, 1, 1, tzinfo=timezone.utc)},
            ],
            "missing": [],
            "mismatch": [],
        })

        anomalies = detect_anomalies(conn)

        stale = [a for a in anomalies if a.anomaly_type == "stale_override"]
        assert len(stale) == 1
        assert stale[0].details["override_id"] == 5

    def test_detects_tier_mismatch(self):
        conn = self._make_conn({
            "overspend": [],
            "stale": [],
            "missing": [],
            "mismatch": [
                {"id": 3, "email": "paid@test.com",
                 "plan_tier": "locked", "subscription_status": "active"},
            ],
        })

        anomalies = detect_anomalies(conn)

        mismatches = [a for a in anomalies if a.anomaly_type == "tier_mismatch"]
        assert len(mismatches) == 1
        assert mismatches[0].severity == "error"
        assert mismatches[0].details["email"] == "paid@test.com"

    def test_no_anomalies(self):
        conn = self._make_conn({
            "overspend": [],
            "stale": [],
            "missing": [],
            "mismatch": [],
        })

        anomalies = detect_anomalies(conn)
        assert anomalies == []

    def test_handles_db_errors_gracefully(self):
        conn = MagicMock()
        conn.execute.side_effect = Exception("DB connection lost")

        # Should not raise — each check catches its own errors
        anomalies = detect_anomalies(conn)
        assert anomalies == []


class TestGetEffectiveEntitlements:
    def test_delegates_to_auth_module(self):
        conn = MagicMock()

        with patch("auth.entitlements.get_user_entitlements") as mock_get:
            mock_get.return_value = {"plan_tier": "racer", "reports_per_month": 10}

            result = get_effective_entitlements(conn, user_id=1, workspace_id=1)

            mock_get.assert_called_once_with(conn, 1, 1)
            assert result["plan_tier"] == "racer"
