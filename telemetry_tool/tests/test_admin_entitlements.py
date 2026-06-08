"""Tests for admin entitlements service.

Verifies:
- get_workspace_usage_summary returns correct aggregation
- create_override inserts row and logs audit event (hardened: allowlist, bounds, expiry)
- detect_anomalies finds overspend, stale overrides, missing plans, tier mismatches,
  long-lived/powerful overrides
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
    OVERRIDE_ALLOWLIST,
    OVERRIDE_MAX_DURATION_DAYS,
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
    # ── helpers ────────────────────────────────────────────────────────

    def _valid_expires(self, days: int = 30) -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=days)

    def _make_conn(self, override_id: int = 42) -> MagicMock:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"id": override_id}
        conn.execute.return_value = cur
        return conn

    # ── existing behaviour (updated for mandatory expires_at) ──────────

    def test_inserts_override(self):
        """A valid allowlisted override with a bounded expiry inserts successfully."""
        conn = self._make_conn(42)

        override_id = create_override(
            conn,
            override_key="analyses_per_month",
            override_value="50",
            reason="Promo code LAUNCH50",
            expires_at=self._valid_expires(30),
            user_id=1,
            created_by=99,
        )

        assert override_id == 42
        sql, params = conn.execute.call_args_list[0][0]
        assert "INSERT INTO entitlement_overrides" in sql
        assert params["key"] == "analyses_per_month"
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
                expires_at=self._valid_expires(7),
                created_by=1,
            )

    def test_workspace_level_override(self):
        """Workspace-scoped override still works when allowlisted + bounded."""
        conn = self._make_conn(7)

        override_id = create_override(
            conn,
            override_key="max_concurrent_jobs",
            override_value="5",
            reason="Enterprise deal",
            expires_at=self._valid_expires(60),
            workspace_id=10,
            created_by=99,
        )

        assert override_id == 7
        sql, params = conn.execute.call_args_list[0][0]
        assert params["ws"] == 10
        assert params["uid"] is None

    # ── new hardening tests ────────────────────────────────────────────

    def test_rejects_non_allowlisted_key(self):
        """An arbitrary key not in OVERRIDE_ALLOWLIST must be rejected."""
        conn = MagicMock()

        with pytest.raises(ValueError, match="not permitted"):
            create_override(
                conn,
                override_key="is_superuser",
                override_value="true",
                reason="test",
                expires_at=self._valid_expires(7),
                user_id=1,
                created_by=99,
            )

    def test_rejects_null_expires_at(self):
        """NULL/absent expires_at must be rejected — no forever overrides."""
        conn = MagicMock()

        with pytest.raises(ValueError, match="expires_at is required"):
            create_override(
                conn,
                override_key="analyses_per_month",
                override_value="100",
                reason="test",
                expires_at=None,
                user_id=1,
                created_by=99,
            )

    def test_rejects_over_cap_duration(self):
        """expires_at beyond OVERRIDE_MAX_DURATION_DAYS must be rejected."""
        conn = MagicMock()
        too_far = datetime.now(timezone.utc) + timedelta(days=OVERRIDE_MAX_DURATION_DAYS + 1)

        with pytest.raises(ValueError, match="maximum allowed duration"):
            create_override(
                conn,
                override_key="analyses_per_month",
                override_value="100",
                reason="test",
                expires_at=too_far,
                user_id=1,
                created_by=99,
            )

    def test_rejects_over_cap_numeric_value(self):
        """A numeric value above the defined cap must be rejected."""
        conn = MagicMock()

        with pytest.raises(ValueError, match="out of range"):
            create_override(
                conn,
                override_key="analyses_per_month",
                override_value="999999",   # far above 10_000 cap
                reason="test",
                expires_at=self._valid_expires(7),
                user_id=1,
                created_by=99,
            )

    def test_rejects_non_bool_for_bool_key(self):
        """A non-boolean JSON value for a bool key must be rejected."""
        conn = MagicMock()

        with pytest.raises(ValueError, match="boolean"):
            create_override(
                conn,
                override_key="api_access",
                override_value='"yes"',   # string, not JSON true/false
                reason="test",
                expires_at=self._valid_expires(7),
                user_id=1,
                created_by=99,
            )

    def test_valid_bounded_allowlisted_override_succeeds(self):
        """A well-formed, allowlisted, bounded override must go through."""
        conn = self._make_conn(99)

        override_id = create_override(
            conn,
            override_key="api_access",
            override_value="true",
            reason="Support credit — ticket #1234",
            expires_at=self._valid_expires(14),
            user_id=7,
            created_by=1,
        )

        assert override_id == 99

    def test_unlimited_sentinel_allowed_for_supported_keys(self):
        """Value -1 (unlimited) is accepted for keys that support it."""
        conn = self._make_conn(55)

        override_id = create_override(
            conn,
            override_key="analyses_per_month",
            override_value="-1",
            reason="World-class trial grant",
            expires_at=self._valid_expires(30),
            user_id=3,
            created_by=1,
        )

        assert override_id == 55

    def test_rejects_invalid_json_value(self):
        """A non-JSON override_value must be rejected."""
        conn = MagicMock()

        with pytest.raises(ValueError, match="valid JSON"):
            create_override(
                conn,
                override_key="analyses_per_month",
                override_value="not-json",
                reason="test",
                expires_at=self._valid_expires(7),
                user_id=1,
                created_by=99,
            )


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


class TestDetectAnomaliesLongLived:
    """Verify the long-lived / powerful-grant override anomaly check."""

    def _make_conn_with_active_overrides(self, active_overrides: list) -> MagicMock:
        """Mock a conn that returns empty for the first 4 queries, then active_overrides."""
        conn = MagicMock()
        call_count = [0]

        def mock_execute(sql, params=None):
            cur = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            # Queries 0–3 are overspend/stale/missing/mismatch → empty
            # Query 4 is the long-lived override check → return our data
            cur.fetchall.return_value = active_overrides if idx == 4 else []
            return cur

        conn.execute.side_effect = mock_execute
        return conn

    def test_flags_long_lived_override(self):
        """An override with > _ANOMALY_LONG_OVERRIDE_DAYS remaining is flagged."""
        far_future = datetime.now(timezone.utc) + timedelta(days=60)
        conn = self._make_conn_with_active_overrides([
            {
                "id": 11, "user_id": 5, "workspace_id": None,
                "override_key": "max_concurrent_jobs",
                "override_value": "10",
                "expires_at": far_future,
                "created_by": 1,
            }
        ])

        anomalies = detect_anomalies(conn)
        long_lived = [a for a in anomalies if a.anomaly_type == "long_lived_override"]
        assert len(long_lived) == 1
        assert long_lived[0].details["is_long_lived"] is True
        assert long_lived[0].user_id == 5

    def test_flags_powerful_api_access_grant(self):
        """An active api_access=true override is flagged as powerful."""
        near_future = datetime.now(timezone.utc) + timedelta(days=5)
        conn = self._make_conn_with_active_overrides([
            {
                "id": 22, "user_id": 7, "workspace_id": None,
                "override_key": "api_access",
                "override_value": "true",
                "expires_at": near_future,
                "created_by": 1,
            }
        ])

        anomalies = detect_anomalies(conn)
        long_lived = [a for a in anomalies if a.anomaly_type == "long_lived_override"]
        assert len(long_lived) == 1
        assert long_lived[0].details["is_powerful_grant"] is True

    def test_flags_unlimited_quota_grant(self):
        """analyses_per_month=-1 (unlimited) is flagged as a powerful grant."""
        near_future = datetime.now(timezone.utc) + timedelta(days=5)
        conn = self._make_conn_with_active_overrides([
            {
                "id": 33, "user_id": 9, "workspace_id": None,
                "override_key": "analyses_per_month",
                "override_value": "-1",
                "expires_at": near_future,
                "created_by": 1,
            }
        ])

        anomalies = detect_anomalies(conn)
        long_lived = [a for a in anomalies if a.anomaly_type == "long_lived_override"]
        assert len(long_lived) == 1
        assert long_lived[0].details["is_powerful_grant"] is True

    def test_short_lived_non_powerful_override_not_flagged(self):
        """A short-lived, low-privilege override should not appear in anomalies."""
        near_future = datetime.now(timezone.utc) + timedelta(days=10)
        conn = self._make_conn_with_active_overrides([
            {
                "id": 44, "user_id": 11, "workspace_id": None,
                "override_key": "max_concurrent_jobs",
                "override_value": "3",
                "expires_at": near_future,
                "created_by": 1,
            }
        ])

        anomalies = detect_anomalies(conn)
        long_lived = [a for a in anomalies if a.anomaly_type == "long_lived_override"]
        assert len(long_lived) == 0


class TestGetEffectiveEntitlements:
    def test_delegates_to_auth_module(self):
        conn = MagicMock()

        with patch("auth.entitlements.get_user_entitlements") as mock_get:
            mock_get.return_value = {"plan_tier": "racer", "reports_per_month": 10}

            result = get_effective_entitlements(conn, user_id=1, workspace_id=1)

            mock_get.assert_called_once_with(conn, 1, 1)
            assert result["plan_tier"] == "racer"
