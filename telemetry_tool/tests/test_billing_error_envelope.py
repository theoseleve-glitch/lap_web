"""Tests for standardized billing error envelope (Task 1).

Verifies that all billing/entitlement error responses contain the required
fields: code, reason_code, message, upgrade_url, required_plan, current_plan,
request_id (in meta).
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["AUTH_REQUIRED"] = True
    return app


# ── Required fields in every billing error response ──────────────────

_REQUIRED_ERROR_FIELDS = {
    "code", "reason_code", "message", "upgrade_url",
    "required_plan", "current_plan",
}
_REQUIRED_TOP_LEVEL = {"ok", "error", "meta"}
_REQUIRED_META_FIELDS = {"request_id", "version"}


def _assert_billing_envelope(data: dict, expected_code: str, expected_reason: str):
    """Assert that *data* conforms to the standardized billing error schema."""
    # Top-level keys
    for key in _REQUIRED_TOP_LEVEL:
        assert key in data, f"Missing top-level key: {key}"
    assert data["ok"] is False

    # Error section
    err = data["error"]
    for key in _REQUIRED_ERROR_FIELDS:
        assert key in err, f"Missing error field: {key}"
    assert err["code"] == expected_code
    assert err["reason_code"] == expected_reason

    # Meta section
    meta = data["meta"]
    for key in _REQUIRED_META_FIELDS:
        assert key in meta, f"Missing meta field: {key}"


# ===========================================================================
# 1. billing_error() builder
# ===========================================================================


class TestBillingErrorBuilder:
    """Direct tests for web.api_utils.billing_error()."""

    def test_plan_required_fields(self):
        app = _make_app()
        with app.test_request_context():
            from flask import g
            g.request_id = "test-req-123"

            from web.api_utils import billing_error, ReasonCode
            resp, status = billing_error(
                reason_code=ReasonCode.FEATURE_LOCKED,
                message="Comparison requires World-Class plan",
                current_plan="free",
                required_plan="world-class",
            )
            assert status == 403
            data = json.loads(resp.get_data(as_text=True))
            _assert_billing_envelope(data, "PLAN_REQUIRED", "FEATURE_LOCKED")
            assert data["error"]["current_plan"] == "free"
            assert data["error"]["required_plan"] == "world-class"
            assert data["meta"]["request_id"] == "test-req-123"

    def test_quota_exceeded_fields(self):
        app = _make_app()
        with app.test_request_context():
            from flask import g
            g.request_id = "test-req-456"

            from web.api_utils import billing_error, ErrorCode, ReasonCode
            resp, status = billing_error(
                reason_code=ReasonCode.LIMIT_EXCEEDED,
                message="Monthly reports limit reached (10/10)",
                current_plan="racer",
                error_code=ErrorCode.QUOTA_EXCEEDED,
                status=429,
                extra={"limit": 10, "used": 10, "remaining": 0, "resets_at": "2026-04-01"},
            )
            assert status == 429
            data = json.loads(resp.get_data(as_text=True))
            _assert_billing_envelope(data, "QUOTA_EXCEEDED", "LIMIT_EXCEEDED")
            assert data["error"]["limit"] == 10
            assert data["error"]["remaining"] == 0
            assert data["error"]["resets_at"] == "2026-04-01"

    def test_subscription_unpaid_fields(self):
        app = _make_app()
        with app.test_request_context():
            from flask import g
            g.request_id = "test-req-789"

            from web.api_utils import billing_error, ReasonCode
            resp, status = billing_error(
                reason_code=ReasonCode.SUBSCRIPTION_UNPAID,
                message="Payment overdue",
                current_plan="racer",
            )
            assert status == 403
            data = json.loads(resp.get_data(as_text=True))
            _assert_billing_envelope(data, "PLAN_REQUIRED", "SUBSCRIPTION_UNPAID")
            assert data["error"]["current_plan"] == "racer"

    def test_upgrade_url_defaults_from_env(self):
        app = _make_app()
        with app.test_request_context():
            from flask import g
            g.request_id = "test"

            from web.api_utils import billing_error, ReasonCode
            resp, _ = billing_error(
                reason_code=ReasonCode.FEATURE_LOCKED,
                message="Locked",
                current_plan="free",
            )
            data = json.loads(resp.get_data(as_text=True))
            # Default upgrade URL when env var not set
            assert data["error"]["upgrade_url"] == "/billing?upgrade=true"

    def test_upgrade_url_from_env_var(self):
        app = _make_app()
        with app.test_request_context():
            from flask import g
            g.request_id = "test"

            with patch.dict("os.environ", {"BILLING_UPGRADE_URL": "/pricing"}):
                from web.api_utils import billing_error, ReasonCode
                resp, _ = billing_error(
                    reason_code=ReasonCode.FEATURE_LOCKED,
                    message="Locked",
                    current_plan="free",
                )
                data = json.loads(resp.get_data(as_text=True))
                assert data["error"]["upgrade_url"] == "/pricing"

    def test_explicit_upgrade_url_overrides_env(self):
        app = _make_app()
        with app.test_request_context():
            from flask import g
            g.request_id = "test"

            with patch.dict("os.environ", {"BILLING_UPGRADE_URL": "/pricing"}):
                from web.api_utils import billing_error, ReasonCode
                resp, _ = billing_error(
                    reason_code=ReasonCode.FEATURE_LOCKED,
                    message="Locked",
                    current_plan="free",
                    upgrade_url="/billing?plan=RACER",
                )
                data = json.loads(resp.get_data(as_text=True))
                assert data["error"]["upgrade_url"] == "/billing?plan=RACER"


# ===========================================================================
# 2. _plan_required_response() uses billing_error
# ===========================================================================


class TestPlanRequiredResponse:
    """Verify _plan_required_response produces standardized envelope."""

    def test_contains_all_required_fields(self):
        app = _make_app()
        with app.test_request_context():
            from flask import g
            g.request_id = "plan-test-1"

            from auth.entitlements import _plan_required_response
            ctx = {
                "reason": "Comparison requires World-Class plan",
                "upgrade_tier": "world-class",
                "upgrade_url": "/billing?plan=WORLD-CLASS",
                "current_tier": "free",
            }
            resp, status = _plan_required_response("comparison", ctx)
            assert status == 403
            data = json.loads(resp.get_data(as_text=True))
            _assert_billing_envelope(data, "PLAN_REQUIRED", "FEATURE_LOCKED")
            assert data["error"]["required_plan"] == "world-class"
            assert data["error"]["current_plan"] == "free"
            assert data["meta"]["request_id"] == "plan-test-1"

    def test_request_id_present(self):
        app = _make_app()
        with app.test_request_context():
            from flask import g
            g.request_id = "rid-abc"

            from auth.entitlements import _plan_required_response
            resp, _ = _plan_required_response("api_access", {
                "reason": "Requires upgrade",
                "current_tier": "demo",
            })
            data = json.loads(resp.get_data(as_text=True))
            assert data["meta"]["request_id"] == "rid-abc"


# ===========================================================================
# 3. _quota_exceeded_response() uses billing_error
# ===========================================================================


class TestQuotaExceededResponse:
    """Verify _quota_exceeded_response produces standardized envelope."""

    def test_contains_all_required_fields(self):
        app = _make_app()
        with app.test_request_context():
            from flask import g
            g.request_id = "quota-test-1"

            from auth.entitlements import _quota_exceeded_response
            ctx = {
                "limit": 10,
                "used": 10,
                "remaining": 0,
                "resets_at": "2026-04-01",
                "current_tier": "racer",
            }
            resp, status = _quota_exceeded_response("reports", ctx)
            assert status == 429
            data = json.loads(resp.get_data(as_text=True))
            _assert_billing_envelope(data, "QUOTA_EXCEEDED", "LIMIT_EXCEEDED")
            assert data["error"]["limit"] == 10
            assert data["error"]["used"] == 10
            assert data["error"]["remaining"] == 0
            assert data["error"]["resets_at"] == "2026-04-01"
            assert data["meta"]["request_id"] == "quota-test-1"


# ===========================================================================
# 4. Middleware billing state blocks use billing_error
# ===========================================================================


class TestMiddlewareBillingStateEnvelope:
    """Verify middleware billing blocks produce standardized envelope."""

    def _setup_middleware_app(self):
        app = _make_app()
        from web.middleware.entitlements import entitlement_middleware
        app.before_request(entitlement_middleware)

        @app.route("/api/v1/test-endpoint", methods=["GET", "POST"])
        def test_endpoint():
            return {"ok": True}

        return app

    @patch("web.middleware.entitlements._get_conn")
    @patch("auth.entitlements._get_conn")
    @patch("auth.entitlements.get_user_subscription_status")
    def test_unpaid_blocks_write_returns_billing_envelope(self, mock_sub_status, mock_ent_conn, mock_mw_conn):
        """Unpaid users are blocked on API_WRITE (POST) but allowed on ACCESS_VIEW (GET)."""
        mock_sub_status.return_value = "unpaid"
        mock_ent_conn.return_value = MagicMock()
        mock_mw_conn.return_value = MagicMock()

        app = self._setup_middleware_app()

        @app.before_request
        def _inject_user():
            from flask import g
            g.current_user_id = 1
            g.plan_tier = "racer"
            g.workspace_id = 1

        app.before_request_funcs[None].insert(0, app.before_request_funcs[None].pop())

        with app.test_client() as client:
            # POST (API_WRITE) should be blocked
            resp = client.post("/api/v1/test-endpoint")
            assert resp.status_code == 403
            data = resp.get_json()
            _assert_billing_envelope(data, "PLAN_REQUIRED", "SUBSCRIPTION_UNPAID")
            assert data["error"]["current_plan"] == "racer"

            # GET (ACCESS_VIEW) should still be allowed per grace policy
            resp_get = client.get("/api/v1/test-endpoint")
            assert resp_get.status_code == 200

    @patch("web.middleware.entitlements._get_conn")
    @patch("auth.entitlements._get_conn")
    @patch("auth.entitlements.get_user_subscription_status")
    def test_canceled_past_grace_blocks_write(self, mock_sub_status, mock_ent_conn, mock_mw_conn):
        """Canceled past grace → effective 'unpaid', blocks writes."""
        mock_sub_status.return_value = "canceled"
        conn = MagicMock()
        from datetime import datetime, timedelta, timezone
        expired_grace = datetime.now(timezone.utc) - timedelta(days=1)
        conn.execute.return_value.fetchone.return_value = {"grace_period_end": expired_grace}
        mock_ent_conn.return_value = conn
        mock_mw_conn.return_value = conn

        app = self._setup_middleware_app()

        @app.before_request
        def _inject_user():
            from flask import g
            g.current_user_id = 1
            g.plan_tier = "racer"
            g.workspace_id = 1

        app.before_request_funcs[None].insert(0, app.before_request_funcs[None].pop())

        with app.test_client() as client:
            resp = client.post("/api/v1/test-endpoint")
            assert resp.status_code == 403
            data = resp.get_json()
            _assert_billing_envelope(data, "PLAN_REQUIRED", "SUBSCRIPTION_UNPAID")

    @patch("web.middleware.entitlements._get_conn")
    @patch("auth.entitlements._get_conn")
    @patch("auth.entitlements.get_user_subscription_status")
    def test_canceled_in_grace_blocks_compute(self, mock_sub_status, mock_ent_conn, mock_mw_conn):
        """Canceled (within grace) blocks COMPUTE actions."""
        mock_sub_status.return_value = "canceled"
        conn = MagicMock()
        from datetime import datetime, timedelta, timezone
        # Grace period NOT expired
        future_grace = datetime.now(timezone.utc) + timedelta(days=7)
        conn.execute.return_value.fetchone.return_value = {"grace_period_end": future_grace}
        mock_ent_conn.return_value = conn
        mock_mw_conn.return_value = conn

        app = _make_app()
        from web.middleware.entitlements import entitlement_middleware
        app.before_request(entitlement_middleware)

        @app.route("/analyze/sync", methods=["POST"])
        def analyze():
            return {"ok": True}

        @app.before_request
        def _inject_user():
            from flask import g
            g.current_user_id = 1
            g.plan_tier = "racer"
            g.workspace_id = 1

        app.before_request_funcs[None].insert(0, app.before_request_funcs[None].pop())

        with app.test_client() as client:
            resp = client.post("/analyze/sync")
            assert resp.status_code == 403
            data = resp.get_json()
            _assert_billing_envelope(data, "PLAN_REQUIRED", "SUBSCRIPTION_CANCELED")


# ===========================================================================
# 5. ReasonCode and ErrorCode completeness
# ===========================================================================


class TestReasonCodeCompleteness:
    """Verify all expected reason codes exist."""

    def test_all_reason_codes_defined(self):
        from web.api_utils import ReasonCode
        expected = [
            "FEATURE_LOCKED", "LIMIT_EXCEEDED", "TRIAL_ENDED",
            "PLAN_MISMATCH", "SUBSCRIPTION_UNPAID",
            "SUBSCRIPTION_CANCELED", "SUBSCRIPTION_PAUSED",
        ]
        for code in expected:
            assert hasattr(ReasonCode, code), f"Missing ReasonCode.{code}"

    def test_plan_required_in_error_code(self):
        from web.api_utils import ErrorCode
        assert hasattr(ErrorCode, "PLAN_REQUIRED")
        assert ErrorCode.PLAN_REQUIRED == "PLAN_REQUIRED"


# ===========================================================================
# 6. Grace policy matrix
# ===========================================================================


class TestGracePolicyMatrix:
    """Verify the GRACE_POLICY matrix is complete and consistent."""

    def test_all_states_defined(self):
        from web.middleware.entitlements import GRACE_POLICY
        for state in ("active", "trialing", "past_due", "canceled", "paused", "unpaid"):
            assert state in GRACE_POLICY, f"Missing state: {state}"

    def test_all_actions_defined_per_state(self):
        from web.middleware.entitlements import GRACE_POLICY
        required_actions = {"ACCESS_VIEW", "EXPORT", "COMPUTE", "UPLOAD", "API_WRITE"}
        for state, policy in GRACE_POLICY.items():
            for action in required_actions:
                assert action in policy, f"Missing action {action} in state {state}"

    def test_active_allows_everything(self):
        from web.middleware.entitlements import GRACE_POLICY
        for action, allowed in GRACE_POLICY["active"].items():
            assert allowed is True, f"active state should allow {action}"

    def test_unpaid_blocks_mutations(self):
        from web.middleware.entitlements import GRACE_POLICY
        p = GRACE_POLICY["unpaid"]
        assert p["ACCESS_VIEW"] is True
        assert p["EXPORT"] is False
        assert p["COMPUTE"] is False
        assert p["UPLOAD"] is False
        assert p["API_WRITE"] is False

    def test_canceled_allows_view_and_export(self):
        from web.middleware.entitlements import GRACE_POLICY
        p = GRACE_POLICY["canceled"]
        assert p["ACCESS_VIEW"] is True
        assert p["EXPORT"] is True
        assert p["COMPUTE"] is False

    def test_classify_action(self):
        from web.middleware.entitlements import _classify_action
        assert _classify_action("GET", "/api/v1/sessions/123") == "ACCESS_VIEW"
        assert _classify_action("POST", "/analyze/sync") == "COMPUTE"
        assert _classify_action("POST", "/api/v1/ingest/start") == "UPLOAD"
        assert _classify_action("POST", "/api/v1/exports/csv") == "EXPORT"
        assert _classify_action("POST", "/api/v1/some-endpoint") == "API_WRITE"
        assert _classify_action("DELETE", "/api/v1/sessions/1") == "API_WRITE"
