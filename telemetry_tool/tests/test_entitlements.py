"""Tests for entitlement resolution, feature gating, and quota enforcement.

Tests use a mock PG connection (dict-based cursor) to avoid requiring
a real PostgreSQL database — same pattern as test_rbac.py.
"""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from flask import Flask, g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── Helpers ──────────────────────────────────────────────────────────

def _make_plan_row(tier="demo", **overrides):
    """Build a plan_definitions row dict."""
    defaults = {
        "tier": tier,
        "display_name": tier.title(),
        "reports_per_month": 1 if tier == "demo" else (10 if tier == "racer" else None),
        "max_upload_size_mb": {"demo": 500, "racer": 2000, "world-class": 5000, "b2b": 10000}.get(tier, 500),
        "telemetry_retention_days": {"demo": 30, "racer": 90, "world-class": 365, "b2b": None}.get(tier),
        "api_access": tier in ("world-class", "b2b"),
        "comparison_enabled": tier in ("racer", "world-class", "b2b"),
        "coaching_plans_enabled": tier in ("racer", "world-class", "b2b"),
        "visualization_enabled": tier in ("racer", "world-class", "b2b"),
        "race_strategy_limit": "4h_basic" if tier == "demo" else ("24h_complex" if tier == "racer" else "unlimited"),
        "live_monitoring": tier in ("racer", "world-class", "b2b"),
        "export_formats": '["csv"]' if tier == "demo" else '["pdf","csv"]',
        "max_concurrent_jobs": {"demo": 1, "racer": 2, "world-class": 5, "b2b": 10}.get(tier, 1),
        "rate_multiplier": {"demo": 1.0, "racer": 2.0, "world-class": 5.0, "b2b": 10.0}.get(tier, 1.0),
    }
    defaults.update(overrides)
    return defaults


class _FakeCursor:
    """Minimal cursor mock returning pre-set rows."""
    def __init__(self, rows):
        self._rows = rows
        self._pos = 0

    def fetchone(self):
        if self._pos < len(self._rows):
            row = self._rows[self._pos]
            self._pos += 1
            return row
        return None

    def fetchall(self):
        return self._rows


def _mock_conn(execute_side_effects):
    """Build a mock connection that returns different results per query.

    execute_side_effects: list of lists-of-dicts.
    Each call to conn.execute() pops the next entry.
    """
    conn = MagicMock()
    cursors = [_FakeCursor(rows) for rows in execute_side_effects]
    conn.execute = MagicMock(side_effect=cursors)
    return conn


# ── Tests: get_user_plan_tier ────────────────────────────────────────

class TestGetUserPlanTier:
    def test_returns_plan_tier(self):
        from auth.entitlements import get_user_plan_tier
        conn = _mock_conn([[{"plan_tier": "racer"}]])
        assert get_user_plan_tier(conn, 1) == "racer"

    def test_returns_locked_for_missing_user(self):
        from auth.entitlements import get_user_plan_tier
        conn = _mock_conn([[]])  # no rows
        # Missing user fails CLOSED to the zero-access 'locked' floor.
        assert get_user_plan_tier(conn, 999) == "locked"

    def test_returns_locked_for_null_tier(self):
        from auth.entitlements import get_user_plan_tier
        conn = _mock_conn([[{"plan_tier": None}]])
        # Null plan_tier fails CLOSED to the zero-access 'locked' floor.
        assert get_user_plan_tier(conn, 1) == "locked"


# ── Tests: get_plan_definitions ──────────────────────────────────────

class TestGetPlanDefinitions:
    def test_returns_plan_row(self):
        from auth.entitlements import get_plan_definitions
        plan = _make_plan_row("racer")
        conn = _mock_conn([[plan]])
        result = get_plan_definitions(conn, "racer")
        assert result["tier"] == "racer"
        assert result["reports_per_month"] == 10
        assert result["api_access"] is False

    def test_returns_none_for_unknown_tier(self):
        from auth.entitlements import get_plan_definitions
        conn = _mock_conn([[]])
        assert get_plan_definitions(conn, "nonexistent") is None


# ── Tests: get_user_entitlements ─────────────────────────────────────

class TestGetUserEntitlements:
    def test_demo_tier_entitlements(self):
        """demo tier with 'free' subscription_status → locked floor (B3 fix).

        PRE-FIX: demo + free returned 1 analysis (fail-open gap: subscription
        status was not enforced as a hard gate alongside plan_tier).
        POST-FIX: 'free' is not in the allowed-status set → locked floor (0).
        The plan_tier and subscription_status keys are kept for display.
        """
        from auth.entitlements import get_user_entitlements
        conn = _mock_conn([
            [{"plan_tier": "demo"}],                # get_user_plan_tier
            [{"subscription_status": "free"}],       # get_user_subscription_status
            [_make_plan_row("demo")],                # get_plan_definitions
            [],                                      # user-level overrides
            [],                                      # workspace-level overrides
            [],                                      # usage_monthly
        ])
        ents = get_user_entitlements(conn, 1, workspace_id=1)

        assert ents["plan_tier"] == "demo"
        assert ents["subscription_status"] == "free"
        # B3: 'free' status → locked floor (zero grants)
        assert ents["analyses_per_month"] == 0
        assert ents["analyses_remaining"] == 0
        assert ents["api_access"] is False
        assert ents["comparison_enabled"] is False
        assert ents["visualization_enabled"] is False
        assert ents.get("_locked_by_status") == "free"
        assert ents["max_concurrent_jobs"] == 1

    def test_worldclass_has_all_features(self):
        from auth.entitlements import get_user_entitlements
        conn = _mock_conn([
            [{"plan_tier": "world-class"}],
            [{"subscription_status": "active"}],
            [_make_plan_row("world-class")],
            [],  # overrides user
            [],  # overrides ws
            [],  # usage
        ])
        ents = get_user_entitlements(conn, 1, workspace_id=1)

        assert ents["plan_tier"] == "world-class"
        assert ents["analyses_per_month"] == -1  # unlimited
        assert ents["analyses_remaining"] is None
        assert ents["api_access"] is True
        assert ents["comparison_enabled"] is True
        assert ents["visualization_enabled"] is True
        assert ents["race_strategy_limit"] == "unlimited"
        assert ents["max_concurrent_jobs"] == 5

    def test_override_increases_quota(self):
        """Overrides on an active subscription are respected (B3 fix scope).

        With subscription_status='active', a support override to 5 analyses
        is honoured.  The B3 locked-floor only fires for disallowed statuses.
        """
        from auth.entitlements import get_user_entitlements
        conn = _mock_conn([
            [{"plan_tier": "demo"}],
            [{"subscription_status": "active"}],   # active → not locked
            [_make_plan_row("demo")],
            [{"override_key": "analyses_per_month",
              "override_value": json.dumps({"value": 5})}],  # user override
            [],  # ws overrides
            [],  # usage
        ])
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == 5

    def test_expired_override_ignored(self):
        """Expired overrides should not be returned by _get_active_overrides.

        With an active subscription, expired overrides are filtered by the DB
        query (WHERE expires_at > now()), so the plan default is used.
        Using active subscription to isolate override behaviour from B3 locking.
        """
        from auth.entitlements import get_user_entitlements

        # The query has WHERE expires_at > now(), so expired rows won't be returned
        conn = _mock_conn([
            [{"plan_tier": "racer"}],
            [{"subscription_status": "active"}],   # active → not locked
            [_make_plan_row("racer")],
            [],  # no active overrides (expired ones filtered by query)
            [],  # ws overrides
            [],  # usage
        ])
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == 10  # default racer (no override)

    def test_usage_counted_correctly(self):
        from auth.entitlements import get_user_entitlements
        conn = _mock_conn([
            [{"plan_tier": "racer"}],
            [{"subscription_status": "active"}],
            [_make_plan_row("racer")],
            [],  # overrides user
            [],  # overrides ws
            [{"event_type": "analyses", "total": 7}],  # usage
        ])
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == 10
        assert ents["analyses_used"] == 7
        assert ents["analyses_remaining"] == 3

    def test_paused_subscription_forces_locked_floor(self):
        """paused subscription is now treated as a disallowed status (B3 fix).

        PRE-FIX: paused set _paused=True but left most entitlements in place.
        POST-FIX: 'paused' is not in the allowed-status set → locked floor.
        The middleware's GRACE_POLICY already blocked COMPUTE/EXPORT/UPLOAD for
        paused, so this aligns the entitlement layer with that policy.
        """
        from auth.entitlements import get_user_entitlements
        conn = _mock_conn([
            [{"plan_tier": "racer"}],
            [{"subscription_status": "paused"}],
            [_make_plan_row("racer")],
            [], [], [],
        ])
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == 0
        assert ents.get("_locked_by_status") == "paused"


# ── Tests: authorize_feature ─────────────────────────────────────────

class TestAuthorizeFeature:
    def _setup_conn(self, tier="demo"):
        return _mock_conn([
            [{"plan_tier": tier}],
            [{"subscription_status": "active"}],
            [_make_plan_row(tier)],
            [], [], [],
        ])

    def test_demo_denied_comparison(self):
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("demo")
            allowed, ctx = authorize_feature(conn, 1, "comparison")
            assert allowed is False
            assert ctx["upgrade_tier"] == "racer"

    def test_worldclass_allowed_comparison(self):
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("world-class")
            allowed, ctx = authorize_feature(conn, 1, "comparison")
            assert allowed is True

    def test_demo_denied_api_access(self):
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("demo")
            allowed, ctx = authorize_feature(conn, 1, "api_access")
            assert allowed is False
            assert ctx["upgrade_tier"] == "world-class"

    def test_racer_allowed_visualization(self):
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("racer")
            allowed, ctx = authorize_feature(conn, 1, "visualization")
            assert allowed is True

    def test_demo_denied_visualization(self):
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("demo")
            allowed, ctx = authorize_feature(conn, 1, "visualization")
            assert allowed is False
            assert ctx["upgrade_tier"] == "racer"

    def test_demo_has_limited_race_strategy(self):
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("demo")
            allowed, ctx = authorize_feature(conn, 1, "race_strategy_full")
            assert allowed is False
            assert ctx["upgrade_tier"] == "world-class"

    def test_racer_has_limited_race_strategy_full(self):
        """Racer has 24h complex but NOT unlimited — race_strategy_full requires world-class."""
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("racer")
            allowed, ctx = authorize_feature(conn, 1, "race_strategy_full")
            assert allowed is False
            assert ctx["upgrade_tier"] == "world-class"

    def test_worldclass_has_full_race_strategy(self):
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("world-class")
            allowed, ctx = authorize_feature(conn, 1, "race_strategy_full")
            assert allowed is True

    def test_demo_denied_export_pdf(self):
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("demo")
            allowed, ctx = authorize_feature(conn, 1, "export_pdf")
            assert allowed is False
            assert ctx["upgrade_tier"] == "racer"

    def test_racer_allowed_export_pdf(self):
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("racer")
            allowed, ctx = authorize_feature(conn, 1, "export_pdf")
            assert allowed is True

    def test_unknown_feature_denied(self):
        """Unknown (unmapped) features must fail CLOSED — B1 fix.

        PRE-FIX behaviour: `authorize_feature` returned True for any feature
        not in _BOOLEAN_FEATURES or the explicit checks (fail-open gap).
        POST-FIX: unmapped features return False so new feature keys cannot
        accidentally grant access before they are wired into the entitlement map.
        """
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("demo")
            allowed, ctx = authorize_feature(conn, 1, "some_future_feature")
            assert allowed is False, "Unknown feature must be DENIED (fail-closed)"
            assert "reason" in ctx


# ── Tests: check_quota ───────────────────────────────────────────────

class TestCheckQuota:
    def test_demo_quota_allows_first_analysis(self):
        from auth.entitlements import check_quota
        conn = _mock_conn([
            [{"plan_tier": "demo"}],
            [{"subscription_status": "active"}],
            [_make_plan_row("demo")],
            [], [], [],  # overrides + usage (0 used)
        ])
        allowed, ctx = check_quota(conn, 1, 1, "analyses", cost=1)
        assert allowed is True
        assert ctx["remaining"] == 0  # 1 limit - 0 used - 1 cost = 0 remaining after
        assert ctx["limit"] == 1

    def test_demo_quota_blocks_second_analysis(self):
        from auth.entitlements import check_quota
        conn = _mock_conn([
            [{"plan_tier": "demo"}],
            [{"subscription_status": "active"}],
            [_make_plan_row("demo")],
            [], [],
            [{"event_type": "analyses", "total": 1}],  # 1 already used
        ])
        allowed, ctx = check_quota(conn, 1, 1, "analyses", cost=1)
        assert allowed is False
        assert ctx["remaining"] == 0
        assert ctx["used"] == 1

    def test_worldclass_unlimited(self):
        from auth.entitlements import check_quota
        conn = _mock_conn([
            [{"plan_tier": "world-class"}],
            [{"subscription_status": "active"}],
            [_make_plan_row("world-class")],
            [], [], [],
        ])
        allowed, ctx = check_quota(conn, 1, 1, "analyses", cost=1)
        assert allowed is True
        assert ctx["remaining"] is None
        assert ctx["limit"] is None

    def test_racer_under_quota(self):
        from auth.entitlements import check_quota
        conn = _mock_conn([
            [{"plan_tier": "racer"}],
            [{"subscription_status": "active"}],
            [_make_plan_row("racer")],
            [], [],
            [{"event_type": "analyses", "total": 5}],
        ])
        allowed, ctx = check_quota(conn, 1, 1, "analyses", cost=1)
        assert allowed is True
        assert ctx["remaining"] == 4  # 10 - 5 - 1 = 4
        assert ctx["limit"] == 10

    def test_unknown_meter_always_allowed(self):
        from auth.entitlements import check_quota
        conn = _mock_conn([
            [{"plan_tier": "demo"}],
            [{"subscription_status": "active"}],
            [_make_plan_row("demo")],
            [], [], [],
        ])
        allowed, ctx = check_quota(conn, 1, 1, "unknown_meter", cost=1)
        assert allowed is True

    def test_resets_at_is_first_of_next_month(self):
        from auth.entitlements import check_quota
        conn = _mock_conn([
            [{"plan_tier": "demo"}],
            [{"subscription_status": "active"}],
            [_make_plan_row("demo")],
            [], [],
            [{"event_type": "analyses", "total": 1}],
        ])
        allowed, ctx = check_quota(conn, 1, 1, "analyses", cost=1)
        # Should have a resets_at date
        resets = date.fromisoformat(ctx["resets_at"])
        assert resets.day == 1
        assert resets > date.today()


# ── Tests: record_usage ──────────────────────────────────────────────

class TestRecordUsage:
    def test_inserts_event_and_upserts_monthly(self):
        from auth.entitlements import record_usage
        conn = MagicMock()
        record_usage(conn, user_id=1, workspace_id=1,
                     event_type="analyses", cost=1,
                     metadata={"session_id": "s1"})
        # Should have 4 execute calls: INSERT usage_events + UPSERT usage_monthly
        # + UPSERT usage_counters + SELECT usage_counters (from increment_usage)
        assert conn.execute.call_count == 4

        # First call: INSERT INTO usage_events
        first_call = conn.execute.call_args_list[0]
        assert "usage_events" in first_call[0][0]

        # Second call: INSERT ... ON CONFLICT ... usage_monthly
        second_call = conn.execute.call_args_list[1]
        assert "usage_monthly" in second_call[0][0]
        assert "ON CONFLICT" in second_call[0][0]

        # Third call: UPSERT usage_counters
        third_call = conn.execute.call_args_list[2]
        assert "usage_counters" in third_call[0][0]

    def test_null_metadata_works(self):
        from auth.entitlements import record_usage
        conn = MagicMock()
        record_usage(conn, user_id=1, workspace_id=1,
                     event_type="csv_uploaded")
        assert conn.execute.call_count == 4


# ── Tests: log_audit_event ───────────────────────────────────────────

class TestLogAuditEvent:
    def test_inserts_audit_row(self):
        from auth.entitlements import log_audit_event
        app = Flask(__name__)
        with app.test_request_context():
            g.current_user_id = 42
            g.workspace_id = 1
            conn = MagicMock()
            log_audit_event(conn, "plan_changed",
                            details={"from": "demo", "to": "racer"})
            assert conn.execute.call_count == 1
            call_sql = conn.execute.call_args[0][0]
            assert "audit_log" in call_sql

    def test_explicit_user_id_overrides_g(self):
        from auth.entitlements import log_audit_event
        app = Flask(__name__)
        with app.test_request_context():
            g.current_user_id = 42
            conn = MagicMock()
            log_audit_event(conn, "test", user_id=99)
            params = conn.execute.call_args[0][1]
            assert params["uid"] == 99


# ── Tests: require_feature decorator ─────────────────────────────────

class TestRequireFeatureDecorator:
    def test_allows_authorized_feature(self):
        from auth.entitlements import require_feature
        app = Flask(__name__)
        app.config["USE_PG"] = True

        @app.route("/test")
        @require_feature("visualization")
        def test_route():
            return {"ok": True}

        with app.test_request_context():
            # Mock the connection and entitlements check
            g.current_user_id = 1
            with patch("auth.entitlements.authorize_feature", return_value=(True, {"current_tier": "racer"})):
                with patch("auth.entitlements._get_conn"):
                    resp = test_route()
                    assert resp == {"ok": True}

    def test_blocks_unauthorized_feature(self):
        from auth.entitlements import require_feature
        app = Flask(__name__)
        app.config["USE_PG"] = True

        @app.route("/test")
        @require_feature("comparison")
        def test_route():
            return {"ok": True}

        with app.test_request_context():
            g.current_user_id = 1
            ctx = {"reason": "comparison requires racer plan or higher", "upgrade_tier": "racer",
                   "upgrade_url": "/billing?plan=RACER", "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    resp, status = test_route()
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"
                    assert data["error"]["required_plan"] == "racer"

    def test_requires_auth(self):
        from auth.entitlements import require_feature
        app = Flask(__name__)
        app.config["USE_PG"] = True

        @app.route("/test")
        @require_feature("api_access")
        def test_route():
            return {"ok": True}

        with app.test_request_context():
            g.current_user_id = None  # not authenticated
            resp, status = test_route()
            assert status == 401


# ── Tests: require_quota decorator ───────────────────────────────────

class TestRequireQuotaDecorator:
    def test_allows_under_quota(self):
        from auth.entitlements import require_quota
        app = Flask(__name__)
        app.config["USE_PG"] = True

        @app.route("/test")
        @require_quota("analyses", cost=1)
        def test_route():
            return {"ok": True}

        with app.test_request_context():
            g.current_user_id = 1
            g.workspace_id = 1
            with patch("auth.entitlements.check_quota",
                       return_value=(True, {"remaining": 5, "limit": 10, "used": 5, "resets_at": "2026-04-01"})):
                with patch("auth.entitlements._get_conn"):
                    resp = test_route()
                    assert resp == {"ok": True}

    def test_blocks_over_quota(self):
        from auth.entitlements import require_quota
        app = Flask(__name__)
        app.config["USE_PG"] = True

        @app.route("/test")
        @require_quota("analyses", cost=1)
        def test_route():
            return {"ok": True}

        with app.test_request_context():
            g.current_user_id = 1
            g.workspace_id = 1
            ctx = {"remaining": 0, "limit": 10, "used": 10, "resets_at": "2026-04-01"}
            with patch("auth.entitlements.check_quota", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    resp, status = test_route()
                    data = resp.get_json()
                    assert status == 429
                    assert data["error"]["code"] == "QUOTA_EXCEEDED"
                    assert data["error"]["limit"] == 10
                    assert data["error"]["remaining"] == 0


# ── Tests: Stripe price → tier mapping ───────────────────────────────

class TestStripePriceMapping:
    def test_resolve_from_metadata(self):
        from web.routes.billing import _resolve_tier_from_checkout
        session = {"metadata": {"plan_tier": "world-class"}}
        assert _resolve_tier_from_checkout(session) == "world-class"

    def test_resolve_ignores_invalid_metadata(self):
        from web.routes.billing import _resolve_tier_from_checkout
        session = {"metadata": {"plan_tier": "invalid_tier"}}
        # Invalid/unmapped metadata must resolve to 'locked', never a paid default (B4).
        tier = _resolve_tier_from_checkout(session)
        assert tier == "locked"  # strict fail-closed: unmapped → locked

    def test_resolve_from_line_items(self):
        from web.routes.billing import STRIPE_PRICE_TO_TIER, _resolve_tier_from_checkout

        # Temporarily add a test price mapping
        STRIPE_PRICE_TO_TIER["price_test_123"] = "world-class"
        try:
            session = {
                "metadata": {},
                "line_items": {
                    "data": [{"price": {"id": "price_test_123"}}]
                },
            }
            assert _resolve_tier_from_checkout(session) == "world-class"
        finally:
            del STRIPE_PRICE_TO_TIER["price_test_123"]


# ── Tests: Feature gating matrix (comprehensive) ────────────────────

class TestFeatureGatingMatrix:
    """Verify every tier×feature combination matches pricing.ts."""

    FEATURES_BY_TIER = {
        "demo": {
            "api_access": False,
            "comparison": False,
            "coaching_plans": False,
            "visualization": False,
            "live_monitoring": False,
            "export_pdf": False,
            "race_strategy_full": False,
            "gamification": False,
        },
        "racer": {
            "api_access": False,
            "comparison": True,
            "coaching_plans": True,
            "visualization": True,
            "live_monitoring": True,
            "export_pdf": True,
            "race_strategy_full": False,  # racer has 24h_complex, not unlimited
            "gamification": True,
        },
        "world-class": {
            "api_access": True,
            "comparison": True,
            "coaching_plans": True,
            "visualization": True,
            "live_monitoring": True,
            "export_pdf": True,
            "race_strategy_full": True,
            "gamification": True,
        },
    }

    @pytest.mark.parametrize("tier", ["demo", "racer", "world-class"])
    @pytest.mark.parametrize("feature", [
        "api_access", "comparison", "coaching_plans", "visualization",
        "live_monitoring", "export_pdf", "race_strategy_full", "gamification",
    ])
    def test_feature_gating(self, tier, feature):
        from auth.entitlements import authorize_feature
        expected = self.FEATURES_BY_TIER[tier][feature]

        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = _mock_conn([
                [{"plan_tier": tier}],
                [{"subscription_status": "active"}],
                [_make_plan_row(tier)],
                [], [], [],
            ])
            allowed, ctx = authorize_feature(conn, 1, feature)
            assert allowed is expected, (
                f"tier={tier} feature={feature}: expected {expected}, got {allowed}"
            )


# ── Tests: Pure-Python PLAN_ENTITLEMENTS ───────────────────────────────

class TestPlanEntitlements:
    """Tests for the static PLAN_ENTITLEMENTS dict and helpers."""

    def test_free_alias_is_locked_zero_analyses(self):
        from auth.entitlements import get_plan_entitlements
        # 'free' is now a fail-closed alias to 'locked' — ZERO analyses.
        ent = get_plan_entitlements("free")
        assert ent["analyses_per_month"] == 0

    def test_racer_plan_has_ten_analyses(self):
        from auth.entitlements import get_plan_entitlements
        ent = get_plan_entitlements("racer")
        assert ent["analyses_per_month"] == 10

    def test_world_class_has_unlimited_analyses(self):
        from auth.entitlements import get_plan_entitlements
        ent = get_plan_entitlements("world_class")
        assert ent["analyses_per_month"] == -1

    def test_unknown_plan_falls_back_to_locked(self):
        from auth.entitlements import get_plan_entitlements
        # Unknown tiers fail CLOSED to 'locked' (== the 'free' alias).
        ent = get_plan_entitlements("nonexistent")
        assert ent == get_plan_entitlements("locked")
        assert ent == get_plan_entitlements("free")
        assert ent["analyses_per_month"] == 0

    def test_all_plans_have_required_keys(self):
        from auth.entitlements import KNOWN_PLANS, PLAN_ENTITLEMENTS
        required = {
            "analyses_per_month", "raw_retention_days",
            "report_retention", "comparison_progress", "coaching_drills",
            "viz_workspace", "strategy_dashboard", "live_pace", "pit_planning",
            "pdf_reports", "api_access", "track_management", "max_workspace_members",
        }
        for plan in KNOWN_PLANS:
            ent = PLAN_ENTITLEMENTS[plan]
            assert required.issubset(ent.keys()), f"{plan} missing keys: {required - ent.keys()}"

    def test_demo_and_free_both_alias_locked(self):
        from auth.entitlements import get_plan_entitlements
        # demo and free are now BOTH fail-closed aliases to 'locked' (zero).
        assert get_plan_entitlements("demo") == get_plan_entitlements("free")
        assert get_plan_entitlements("demo") == get_plan_entitlements("locked")
        assert get_plan_entitlements("demo")["analyses_per_month"] == 0

    def test_free_plan_boolean_features_disabled(self):
        from auth.entitlements import get_plan_entitlements
        ent = get_plan_entitlements("free")
        assert ent["coaching_drills"] is False
        assert ent["viz_workspace"] is False
        assert ent["live_pace"] is False
        assert ent["pit_planning"] is False
        assert ent["pdf_reports"] is False
        assert ent["api_access"] is False
        assert ent["comparison_progress"] is False

    def test_racer_plan_features(self):
        from auth.entitlements import get_plan_entitlements
        ent = get_plan_entitlements("racer")
        assert ent["coaching_drills"] is True
        assert ent["viz_workspace"] is True
        assert ent["live_pace"] is True
        assert ent["api_access"] is False
        assert ent["comparison_progress"] is True
        assert ent["strategy_dashboard"] == "24h_complex"

    def test_world_class_all_features_enabled(self):
        from auth.entitlements import get_plan_entitlements
        ent = get_plan_entitlements("world_class")
        assert ent["coaching_drills"] is True
        assert ent["viz_workspace"] is True
        assert ent["api_access"] is True
        assert ent["comparison_progress"] is True
        assert ent["max_workspace_members"] == 5


class TestCheckUsageLimit:
    """Tests for check_usage_limit (pure Python, no DB)."""

    def test_under_limit_allowed(self):
        from auth.entitlements import check_usage_limit
        ok, info = check_usage_limit(plan="racer", metric="analyses", current_count=5)
        assert ok is True
        assert info["limit"] == 10
        assert info["used"] == 5
        assert info["remaining"] == 5

    def test_at_limit_blocked(self):
        from auth.entitlements import check_usage_limit
        ok, info = check_usage_limit(plan="racer", metric="analyses", current_count=10)
        assert ok is False
        assert info["remaining"] == 0

    def test_over_limit_blocked(self):
        from auth.entitlements import check_usage_limit
        ok, info = check_usage_limit(plan="racer", metric="analyses", current_count=15)
        assert ok is False

    def test_unlimited_always_allowed(self):
        from auth.entitlements import check_usage_limit
        ok, info = check_usage_limit(plan="world_class", metric="analyses", current_count=99999)
        assert ok is True
        assert info["remaining"] == -1  # unlimited sentinel

    def test_free_plan_zero_analyses(self):
        from auth.entitlements import check_usage_limit
        # 'free' aliases 'locked' — ZERO analyses, blocked even at count 0.
        ok, info = check_usage_limit(plan="free", metric="analyses", current_count=0)
        assert ok is False
        assert info["limit"] == 0
        ok, _ = check_usage_limit(plan="free", metric="analyses", current_count=1)
        assert ok is False

    def test_unknown_metric_defaults_blocked(self):
        from auth.entitlements import check_usage_limit
        ok, info = check_usage_limit(plan="racer", metric="unknown_thing", current_count=0)
        assert ok is False
        assert info["limit"] == 0

    def test_locked_floor_zero_remaining_at_zero_count(self):
        from auth.entitlements import check_usage_limit
        # locked/free floor: limit 0 → no remaining, blocked at any count.
        ok, info = check_usage_limit(plan="free", metric="analyses", current_count=0)
        assert ok is False
        assert info["limit"] == 0
        assert info["remaining"] == 0

    def test_demo_alias_works_in_limit_check(self):
        from auth.entitlements import check_usage_limit
        # 'demo' aliases 'locked' — ZERO limit (no free report).
        ok, info = check_usage_limit(plan="demo", metric="analyses", current_count=0)
        assert ok is False
        assert info["limit"] == 0


class TestDeviceSyncEntitlements:
    """Tests for device_sync, auto_analyze_on_sync, max_linked_devices."""

    def test_device_sync_entitlement_demo(self):
        from auth.entitlements import get_plan_entitlements
        ents = get_plan_entitlements("demo")
        assert ents["device_sync"] is False
        assert ents["auto_analyze_on_sync"] is False
        assert ents["max_linked_devices"] == 0

    def test_device_sync_entitlement_racer(self):
        from auth.entitlements import get_plan_entitlements
        ents = get_plan_entitlements("racer")
        assert ents["device_sync"] is True
        assert ents["auto_analyze_on_sync"] is False
        assert ents["max_linked_devices"] == 2

    def test_device_sync_entitlement_world_class(self):
        from auth.entitlements import get_plan_entitlements
        ents = get_plan_entitlements("world_class")
        assert ents["device_sync"] is True
        assert ents["auto_analyze_on_sync"] is True
        assert ents["max_linked_devices"] == 3

    def test_device_sync_alias_consistency(self):
        """world-class alias must see the same keys as world_class."""
        from auth.entitlements import get_plan_entitlements
        wc = get_plan_entitlements("world_class")
        wc_alias = get_plan_entitlements("world-class")
        assert wc["device_sync"] == wc_alias["device_sync"]
        assert wc["auto_analyze_on_sync"] == wc_alias["auto_analyze_on_sync"]


# ── Security fix tests (B1 / B3 / B8 / B9) ──────────────────────────────────
# Each class covers one fix and contains a regression guard for the "good"
# world-class+active path to ensure we haven't over-locked paying users.

class TestB1UnknownFeatureFailClosed:
    """Fix B1: authorize_feature() must DENY unknown/unmapped features."""

    def _setup_conn(self, tier="locked", status="free"):
        return _mock_conn([
            [{"plan_tier": tier}],
            [{"subscription_status": status}],
            [_make_plan_row(tier)],
            [], [], [],
        ])

    def test_unknown_feature_is_denied(self):
        """(a) Unmapped feature → denied, not allowed."""
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("racer", "active")
            allowed, ctx = authorize_feature(conn, 1, "nonexistent_feature_xyz")
            assert allowed is False, "Unknown feature must be denied (B1)"
            assert "reason" in ctx

    def test_exports_feature_denied_for_locked(self):
        """(a) 'exports' feature key (middleware alias) is denied for locked tier."""
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("locked", "free")
            # locked plan has no PDF in export_formats → denied
            allowed, ctx = authorize_feature(conn, 1, "exports")
            assert allowed is False, "'exports' must be denied for locked tier"
            assert ctx.get("upgrade_tier") == "racer"

    def test_exports_feature_allowed_for_racer(self):
        """'exports' feature key is granted for Racer+ (has pdf in export_formats)."""
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            conn = self._setup_conn("racer", "active")
            allowed, ctx = authorize_feature(conn, 1, "exports")
            assert allowed is True, "'exports' must be allowed for racer tier"

    def test_world_class_active_not_over_locked_by_b1(self):
        """(b) Regression guard: world-class + active → known features still granted."""
        from auth.entitlements import authorize_feature
        app = Flask(__name__)
        with app.test_request_context():
            g.workspace_id = 1
            for feature in ("api_access", "comparison", "visualization", "export_pdf"):
                conn = self._setup_conn("world-class", "active")
                allowed, ctx = authorize_feature(conn, 1, feature)
                assert allowed is True, (
                    f"B1 regression: world-class+active must keep {feature} granted"
                )


class TestB3PaidTierRequiresActiveStatus:
    """Fix B3: get_user_entitlements() requires paid tier AND active status.

    Previously, a user with plan_tier='world-class' but subscription_status='unpaid'
    would receive full world-class entitlements (fail-open gap).  After this fix,
    any status not in {active, trialing, past_due, canceled} forces the locked floor.
    """

    def _make_conn(self, tier, status, usage=0):
        return _mock_conn([
            [{"plan_tier": tier}],
            [{"subscription_status": status}],
            [_make_plan_row(tier)],
            [], [],  # overrides
            [{"event_type": "analyses", "total": usage}] if usage else [],
        ])

    def test_world_class_active_keeps_full_access(self):
        """(b) world-class + active → unlimited analyses, premium features on."""
        from auth.entitlements import get_user_entitlements
        conn = self._make_conn("world-class", "active")
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["plan_tier"] == "world-class"
        assert ents["subscription_status"] == "active"
        assert ents["analyses_per_month"] == -1, "world-class+active must be unlimited"
        assert ents["api_access"] is True
        assert ents["comparison_enabled"] is True
        assert ents.get("_locked_by_status") is None, "Must NOT be locked for active status"

    def test_world_class_trialing_keeps_full_access(self):
        """(b) world-class + trialing → full access (trial is allowed)."""
        from auth.entitlements import get_user_entitlements
        conn = self._make_conn("world-class", "trialing")
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == -1
        assert ents.get("_locked_by_status") is None

    def test_world_class_past_due_keeps_full_access(self):
        """(b) world-class + past_due → full access with grace flag."""
        from auth.entitlements import get_user_entitlements
        conn = self._make_conn("world-class", "past_due")
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == -1
        assert ents.get("_past_due") is True
        assert ents.get("_locked_by_status") is None

    def test_world_class_canceled_keeps_grace_access(self):
        """(b) world-class + canceled → grace period features kept, cancel flag set."""
        from auth.entitlements import get_user_entitlements
        conn = self._make_conn("world-class", "canceled")
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == -1
        assert ents.get("_cancel_pending") is True
        assert ents.get("_locked_by_status") is None

    def test_world_class_unpaid_forced_to_locked_floor(self):
        """(c) world-class + unpaid → zero entitlements (locked floor)."""
        from auth.entitlements import get_user_entitlements
        conn = self._make_conn("world-class", "unpaid")
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        # plan_tier + subscription_status preserved for display
        assert ents["plan_tier"] == "world-class"
        assert ents["subscription_status"] == "unpaid"
        # But grants are zeroed
        assert ents["analyses_per_month"] == 0, "unpaid → 0 analyses"
        assert ents["analyses_remaining"] == 0
        assert ents["api_access"] is False
        assert ents["comparison_enabled"] is False
        assert ents.get("_locked_by_status") == "unpaid"

    def test_world_class_free_status_forced_to_locked_floor(self):
        """(c) world-class + free status → zero entitlements."""
        from auth.entitlements import get_user_entitlements
        conn = self._make_conn("world-class", "free")
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == 0
        assert ents["api_access"] is False
        assert ents.get("_locked_by_status") == "free"

    def test_world_class_expired_forced_to_locked_floor(self):
        """(c) world-class + expired → zero entitlements."""
        from auth.entitlements import get_user_entitlements
        conn = self._make_conn("world-class", "expired")
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == 0
        assert ents.get("_locked_by_status") == "expired"

    def test_world_class_incomplete_forced_to_locked_floor(self):
        """(c) world-class + incomplete → zero entitlements."""
        from auth.entitlements import get_user_entitlements
        conn = self._make_conn("world-class", "incomplete")
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == 0
        assert ents.get("_locked_by_status") == "incomplete"

    def test_racer_active_keeps_10_analyses(self):
        """(b) Regression guard: racer + active must keep 10 analyses per month."""
        from auth.entitlements import get_user_entitlements
        conn = self._make_conn("racer", "active")
        ents = get_user_entitlements(conn, 1, workspace_id=1)
        assert ents["analyses_per_month"] == 10
        assert ents.get("_locked_by_status") is None


class TestB8NullPlanLimitFailClosed:
    """Fix B8: NULL/None plan_definitions limit must coalesce to the tier floor,
    never to unlimited.  Only -1 means unlimited.
    """

    def test_null_limit_in_check_quota_denied(self):
        """(d) NULL plan limit → denied (0), not unlimited."""
        from auth.entitlements import check_quota
        # Simulate world-class plan with NULL reports_per_month in DB
        # (plan row has None → should coalesce to py tier floor, which is -1
        # for world-class, but test with a racer having NULL to ensure denial
        # when py default is also finite).
        # We test with a plan row that has None for reports_per_month, and
        # the py_defaults for 'racer' give 10 — so it should use 10, not unlimited.
        conn = _mock_conn([
            [{"plan_tier": "racer"}],
            [{"subscription_status": "active"}],
            [_make_plan_row("racer", reports_per_month=None)],  # NULL in DB
            [], [],
            [],  # usage: 0
        ])
        allowed, ctx = check_quota(conn, 1, 1, "analyses", cost=1)
        # With NULL DB limit, py default for racer = 10 → should be allowed at 0 used
        assert allowed is True
        assert ctx["limit"] == 10  # coalesced to tier floor, not None/unlimited

    def test_null_limit_explicit_none_in_check_quota_uses_floor(self):
        """(d) NULL plan limit with locked tier → 0 (deny at 0 used)."""
        from auth.entitlements import check_quota
        # locked tier has analyses_per_month=0 as its floor
        conn = _mock_conn([
            [{"plan_tier": "locked"}],
            [{"subscription_status": "free"}],
            [_make_plan_row("locked", reports_per_month=None)],
            [], [],
            [],
        ])
        allowed, ctx = check_quota(conn, 1, 1, "analyses", cost=1)
        assert allowed is False, "NULL limit + locked tier → 0 → deny"
        assert ctx["limit"] == 0

    def test_minus_one_limit_is_unlimited(self):
        """(d) -1 plan limit → unlimited (explicitly allowed)."""
        from auth.entitlements import check_quota
        conn = _mock_conn([
            [{"plan_tier": "world-class"}],
            [{"subscription_status": "active"}],
            [_make_plan_row("world-class", reports_per_month=-1)],
            [], [], [],
        ])
        allowed, ctx = check_quota(conn, 1, 1, "analyses", cost=1)
        assert allowed is True
        assert ctx["remaining"] is None  # unlimited sentinel
        assert ctx["limit"] is None

    def test_null_limit_in_check_and_record_quota_uses_floor(self):
        """(d) NULL in plan_definitions for check_and_record_quota → tier floor."""
        from auth.entitlements import check_and_record_quota
        # racer with NULL in plan row → py default = 10
        plan_row = _make_plan_row("racer", reports_per_month=None)
        conn = _mock_conn([
            [{"plan_tier": "racer"}],          # get_user_plan_tier
            [plan_row],                         # get_plan_definitions
            # SELECT FOR UPDATE (usage_monthly) — 0 used
            [],
        ])
        # Patch record_usage to avoid further DB calls
        from unittest.mock import patch
        with patch("auth.entitlements.record_usage"):
            allowed, ctx = check_and_record_quota(conn, 1, 1, "analyses", cost=1)
        assert allowed is True
        assert ctx["limit"] == 10  # tier floor for racer

    def test_minus_one_in_check_and_record_quota_is_unlimited(self):
        """(d) -1 in plan_definitions → unlimited, usage recorded."""
        from auth.entitlements import check_and_record_quota
        plan_row = _make_plan_row("world-class", reports_per_month=-1)
        conn = _mock_conn([
            [{"plan_tier": "world-class"}],
            [plan_row],
        ])
        from unittest.mock import patch
        with patch("auth.entitlements.record_usage") as mock_record:
            allowed, ctx = check_and_record_quota(conn, 1, 1, "analyses", cost=1)
        assert allowed is True
        assert ctx["remaining"] is None
        mock_record.assert_called_once()


class TestB9MissingIdentityLockedFloor:
    """Fix B9: entitlement_snapshot() must fail CLOSED when user or workspace
    is unresolved — never inherit workspace-1 entitlements.
    """

    def test_missing_user_returns_locked_snapshot(self):
        """(e) user_id=None → locked floor snapshot returned."""
        from web.middleware.entitlements import entitlement_snapshot
        app = Flask(__name__)
        app.config["USE_PG"] = True
        with app.test_request_context():
            from flask import g
            g.current_user_id = None
            g.workspace_id = 1  # workspace present but user absent
            snapshot = entitlement_snapshot()
            assert snapshot["plan_tier"] == "locked"
            assert snapshot["analyses_per_month"] == 0
            assert snapshot["api_access"] is False
            assert snapshot.get("_locked_by_missing_identity") is True

    def test_missing_workspace_returns_locked_snapshot(self):
        """(e) workspace_id=None → locked floor snapshot returned."""
        from web.middleware.entitlements import entitlement_snapshot
        app = Flask(__name__)
        app.config["USE_PG"] = True
        with app.test_request_context():
            from flask import g
            g.current_user_id = 42
            g.workspace_id = None
            snapshot = entitlement_snapshot()
            assert snapshot["plan_tier"] == "locked"
            assert snapshot["analyses_per_month"] == 0
            assert snapshot.get("_locked_by_missing_identity") is True

    def test_missing_both_returns_locked_snapshot(self):
        """(e) Both user_id and workspace_id None → locked floor."""
        from web.middleware.entitlements import entitlement_snapshot
        app = Flask(__name__)
        app.config["USE_PG"] = True
        with app.test_request_context():
            from flask import g
            g.current_user_id = None
            g.workspace_id = None
            snapshot = entitlement_snapshot()
            assert snapshot["plan_tier"] == "locked"
            assert snapshot["api_access"] is False

    def test_resolved_identity_does_not_lock(self):
        """(e) Regression guard: resolved user + workspace → DB lookup attempted."""
        from web.middleware.entitlements import entitlement_snapshot
        from unittest.mock import MagicMock, patch
        app = Flask(__name__)
        app.config["USE_PG"] = True
        with app.test_request_context():
            from flask import g
            g.current_user_id = 1
            g.workspace_id = 1
            fake_snap = {"plan_tier": "world-class", "analyses_per_month": -1}
            with patch("web.middleware.entitlements.get_user_entitlements",
                       return_value=fake_snap):
                # Simulate cache miss → falls through to DB
                with patch("web.middleware.entitlements._get_conn",
                           return_value=MagicMock()):
                    # cached_entitlements raises → falls back to get_user_entitlements
                    with patch("web.entitlement_cache.cached_entitlements",
                               side_effect=Exception("cache miss")):
                        snapshot = entitlement_snapshot()
            assert snapshot["plan_tier"] == "world-class"
            assert snapshot.get("_locked_by_missing_identity") is None
