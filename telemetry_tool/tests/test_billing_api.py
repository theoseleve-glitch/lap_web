"""Tests for PROMPT 2B — billing API endpoints, webhook enhancements, subscription state transitions.

Validates:
- Billing subscription endpoint returns correct structure
- Usage endpoint aggregates from usage_monthly
- Portal URL generation
- Webhook handles trial_will_end, subscription.paused, payment recovery emails
- Entitlement state transitions (active/trialing/past_due/canceled/paused)
- Billing email templates
"""
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Test billing webhook handlers
# ---------------------------------------------------------------------------

class TestWebhookHandlers:
    def test_handle_subscription_paused(self):
        """Subscription pause transitions to 'paused' via state machine."""
        from web.routes.billing import _handle_subscription_paused
        with patch("web.routes.billing._get_conn") as mock_conn, \
             patch("billing.state_machine.transition_subscription", return_value=True) as mock_transition:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"id": 42}
            _handle_subscription_paused({"customer": "cus_123"})
            mock_transition.assert_called_once()
            call_kwargs = mock_transition.call_args
            assert call_kwargs[0][2] == "paused"  # new_status

    def test_handle_trial_will_end(self):
        """Trial ending sends email notification."""
        from web.routes.billing import _handle_trial_will_end
        with patch("web.routes.billing._get_conn") as mock_conn, \
             patch("web.routes.billing._send_billing_email") as mock_email:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"email": "user@test.com"}
            _handle_trial_will_end({"customer": "cus_123"})
            mock_email.assert_called_once_with("user@test.com", "trial_ending")

    def test_handle_payment_failed_sends_email(self):
        """Payment failure transitions to 'past_due' via state machine."""
        from web.routes.billing import _handle_payment_failed
        with patch("web.routes.billing._get_conn") as mock_conn, \
             patch("web.routes.billing.audit_log"), \
             patch("billing.state_machine.transition_subscription", return_value=True) as mock_transition:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"id": 42}
            _handle_payment_failed({"customer": "cus_123"})
            mock_transition.assert_called_once()
            call_kwargs = mock_transition.call_args
            assert call_kwargs[0][2] == "past_due"  # new_status

    def test_handle_subscription_deleted_sends_email(self):
        """Cancellation transitions to 'canceled' via state machine."""
        from web.routes.billing import _handle_subscription_deleted
        with patch("web.routes.billing._get_conn") as mock_conn, \
             patch("web.routes.billing.audit_log"), \
             patch("billing.state_machine.transition_subscription", return_value=True) as mock_transition:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"id": 42}
            _handle_subscription_deleted({"customer": "cus_123", "id": "sub_123"})
            mock_transition.assert_called_once()
            call_kwargs = mock_transition.call_args
            assert call_kwargs[0][2] == "canceled"  # new_status

    def test_handle_payment_succeeded_recovery(self):
        """Payment success from past_due transitions to 'active' via state machine."""
        from web.routes.billing import _handle_payment_succeeded
        with patch("web.routes.billing._get_conn") as mock_conn, \
             patch("billing.state_machine.transition_subscription", return_value=True) as mock_transition:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchone.return_value = {
                "id": 42,
                "subscription_status": "past_due",
            }
            _handle_payment_succeeded({"customer": "cus_123"})
            mock_transition.assert_called_once()
            call_kwargs = mock_transition.call_args
            assert call_kwargs[0][2] == "active"  # new_status


# ---------------------------------------------------------------------------
# Test billing email templates
# ---------------------------------------------------------------------------

class TestBillingEmails:
    def test_trial_ending_template(self):
        """Trial ending email includes 'View Plans' CTA."""
        from web.routes.billing import _send_billing_email
        with patch("auth.email._send") as mock_send:
            mock_send.return_value = True
            _send_billing_email("user@test.com", "trial_ending")
            mock_send.assert_called_once()
            _, subject, html = mock_send.call_args[0]
            assert "trial" in subject.lower()
            assert "View Plans" in html

    def test_payment_failed_template(self):
        """Payment failed email includes 'Update Payment Method' CTA."""
        from web.routes.billing import _send_billing_email
        with patch("auth.email._send") as mock_send:
            mock_send.return_value = True
            _send_billing_email("user@test.com", "payment_failed")
            mock_send.assert_called_once()
            _, subject, html = mock_send.call_args[0]
            assert "failed" in subject.lower()
            assert "Update Payment Method" in html

    def test_subscription_canceled_template(self):
        """Cancellation email includes feature loss info."""
        from web.routes.billing import _send_billing_email
        with patch("auth.email._send") as mock_send:
            mock_send.return_value = True
            _send_billing_email("user@test.com", "subscription_canceled")
            mock_send.assert_called_once()
            _, subject, html = mock_send.call_args[0]
            assert "canceled" in subject.lower()
            assert "Resubscribe" in html

    def test_payment_recovered_template(self):
        """Recovery email confirms active status."""
        from web.routes.billing import _send_billing_email
        with patch("auth.email._send") as mock_send:
            mock_send.return_value = True
            _send_billing_email("user@test.com", "payment_recovered")
            mock_send.assert_called_once()
            _, subject, html = mock_send.call_args[0]
            assert "active" in subject.lower() or "successful" in subject.lower()
            assert "Go to Dashboard" in html

    def test_unknown_event_type(self):
        """Unknown event type logs warning but doesn't crash."""
        from web.routes.billing import _send_billing_email
        with patch("auth.email._send") as mock_send:
            _send_billing_email("user@test.com", "nonexistent_event")
            mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Test entitlement state transitions
# ---------------------------------------------------------------------------

class TestEntitlementStateTransitions:
    def _make_entitlements(self, sub_status, plan_tier="racer"):
        """Helper to build entitlements dict with given status."""
        from auth.entitlements import get_user_entitlements
        conn = MagicMock()
        # User query
        conn.execute.return_value.fetchone.side_effect = [
            {"plan_tier": plan_tier},                # get_user_plan_tier
            {"subscription_status": sub_status},     # get_user_subscription_status
            {                                         # get_plan_definitions
                "reports_per_month": 10,
                "max_upload_size_mb": 500,
                "telemetry_retention_days": 90,
                "api_access": False,
                "comparison_enabled": False,
                "coaching_plans_enabled": True,
                "visualization_enabled": True,
                "race_strategy_limit": "full",
                "live_monitoring": True,
                "export_formats": '["csv","pdf"]',
                "max_concurrent_jobs": 2,
                "rate_multiplier": 2.0,
            },
        ]
        conn.execute.return_value.fetchall.return_value = []  # overrides + usage
        return get_user_entitlements(conn, 1, 1)

    def test_active_full_access(self):
        """Active subscription gets full plan entitlements."""
        ents = self._make_entitlements("active")
        assert ents["analyses_per_month"] == 10
        assert "_paused" not in ents

    def test_trialing_full_access(self):
        """Trialing subscription gets full plan entitlements."""
        ents = self._make_entitlements("trialing")
        assert ents["analyses_per_month"] == 10
        assert "_paused" not in ents

    def test_past_due_flagged(self):
        """Past due subscription gets full access but is flagged."""
        ents = self._make_entitlements("past_due")
        assert ents.get("_past_due") is True
        assert ents["analyses_per_month"] == 10

    def test_canceled_flagged(self):
        """Canceled subscription is flagged for grace period handling."""
        ents = self._make_entitlements("canceled")
        assert ents.get("_cancel_pending") is True

    def test_paused_blocks_reports(self):
        """Paused subscription blocks new reports via the locked floor.

        The entitlement engine no longer sets ``_paused`` directly; instead it
        sets ``_locked_by_status = 'paused'`` and zeros out the quota.  The
        important invariant — that a paused user CANNOT run new analyses — is
        preserved: analyses_per_month and analyses_remaining must both be 0.
        """
        ents = self._make_entitlements("paused")
        # Block is enforced via the locked-floor mechanism, not the old _paused flag.
        assert ents.get("_locked_by_status") == "paused", (
            f"Expected _locked_by_status='paused', got: {ents}"
        )
        assert ents["analyses_per_month"] == 0
        assert ents["analyses_remaining"] == 0


# ---------------------------------------------------------------------------
# Test billing API blueprint registration
# ---------------------------------------------------------------------------

class TestBillingBlueprintRegistration:
    def test_api_v1_billing_blueprint_registered(self):
        """The api_v1_billing blueprint should be registered in app.py."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "app", str(_PROJECT_ROOT / "web" / "app.py"),
        )
        source = Path(_PROJECT_ROOT / "web" / "app.py").read_text()
        assert "api_v1_billing" in source

    def test_billing_endpoints_exist(self):
        """Key endpoint functions should exist in the module."""
        from web.routes.api_v1_billing import (
            create_portal,
            get_invoices,
            get_subscription,
            get_usage,
        )
        assert callable(get_subscription)
        assert callable(get_invoices)
        assert callable(get_usage)
        assert callable(create_portal)


# ---------------------------------------------------------------------------
# Test usage entitlements integration
# ---------------------------------------------------------------------------

class TestUsageEntitlements:
    def test_reports_remaining_calculation(self):
        """Reports remaining = limit - used."""
        from auth.entitlements import get_user_entitlements
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [
            {"plan_tier": "racer"},
            {"subscription_status": "active"},
            {
                "reports_per_month": 10,
                "max_upload_size_mb": 500,
                "telemetry_retention_days": 90,
                "api_access": False,
                "comparison_enabled": False,
                "coaching_plans_enabled": True,
                "visualization_enabled": True,
                "race_strategy_limit": "full",
                "live_monitoring": True,
                "export_formats": '["csv","pdf"]',
                "max_concurrent_jobs": 2,
                "rate_multiplier": 2.0,
            },
        ]
        conn.execute.return_value.fetchall.side_effect = [
            [],  # overrides
            [],  # workspace overrides
            [{"event_type": "analyses", "total": 7}],  # usage
        ]
        ents = get_user_entitlements(conn, 1, 1)
        assert ents["analyses_used"] == 7
        assert ents["analyses_remaining"] == 3


# ---------------------------------------------------------------------------
# Regression tests: /checkout route collision fix
#
# Prior to the fix, billing_bp (billing.py) was registered BEFORE
# api_v1_billing_bp (api_v1_billing.py) in app.py, and both blueprints used
# url_prefix="/api/v1/billing".  Flask/Werkzeug therefore routed
# POST /api/v1/billing/checkout to the OLD auth-required handler in billing.py,
# which immediately returned 403 "Authentication required" for guest callers.
# The Founding-50 handler in api_v1_billing.py was unreachable dead code.
#
# Fix applied: billing.py's handler was moved to POST /checkout/upgrade so the
# two blueprints no longer collide.  These tests assert:
#   (a) The URL map assigns POST /api/v1/billing/checkout to the founding-aware
#       view function (create_checkout, not create_checkout_session).
#   (b) A guest request (no JWT) to POST /api/v1/billing/checkout does NOT
#       receive 403 "Authentication required" — it reaches the founding handler
#       and gets back either a checkout_url (200) or a clean config-missing
#       error (503), never the auth guard.
# ---------------------------------------------------------------------------

def _build_test_app():
    """Build a minimal Flask app that mirrors the production blueprint
    registration order from app.py (billing_bp first, then api_v1_billing_bp).
    """
    from flask import Flask
    from web.routes.billing import bp as billing_bp
    from web.routes.api_v1_billing import bp as api_v1_billing_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    # Register in the same order as production to prove the collision is gone.
    app.register_blueprint(billing_bp)
    app.register_blueprint(api_v1_billing_bp)
    return app


class TestCheckoutRouteCollision:
    """Regression suite for the /checkout blueprint collision (feat/founding-50-offer)."""

    def test_checkout_url_maps_to_founding_handler(self):
        """app.url_map must route POST /api/v1/billing/checkout to create_checkout
        (the founding-aware handler in api_v1_billing.py), not
        create_checkout_session (the old auth-required handler in billing.py).
        """
        app = _build_test_app()
        # Resolve the view function name for the POST checkout rule.
        adapter = app.url_map.bind("localhost")
        endpoint, _ = adapter.match("/api/v1/billing/checkout", method="POST")
        # Flask endpoint format is "<blueprint_name>.<view_function_name>"
        assert endpoint == "api_v1_billing.create_checkout", (
            f"Expected 'api_v1_billing.create_checkout', got '{endpoint}'. "
            "The billing.py /checkout handler is still shadowing the founding handler."
        )

    def test_guest_checkout_does_not_return_403(self):
        """A guest POST to /api/v1/billing/checkout must NOT return 403.

        The founding handler returns 503 when Stripe env vars are absent (no
        STRIPE_SECRET_KEY / price IDs configured in test env).  That is the
        correct behaviour — 'payments not configured' — not 'auth required'.
        Any 2xx or 5xx other than 403 proves the founding handler is reached.
        """
        app = _build_test_app()
        # Patch the module-level STRIPE_SECRET_KEY so _get_stripe() returns None
        # → the founding handler hits the "Payments are not configured" 503 path.
        # We deliberately do NOT mock Stripe or the DB; we only need to confirm
        # we are NOT hitting the auth guard (403).
        with patch("web.routes.api_v1_billing.STRIPE_SECRET_KEY", ""):
            with app.test_client() as client:
                resp = client.post(
                    "/api/v1/billing/checkout",
                    json={"email": "guest@example.com"},
                    content_type="application/json",
                )
        assert resp.status_code != 403, (
            f"Got 403 — the old billing.py auth-guard handler is still being "
            f"served at /api/v1/billing/checkout (collision not fixed)."
        )
        # Must be the founding handler's "not configured" response, not an
        # unexpected crash — accept any non-403 status as proof of routing fix.
        assert resp.status_code in (200, 400, 502, 503), (
            f"Unexpected status {resp.status_code}; expected 503 (unconfigured Stripe)."
        )

    def test_upgrade_route_exists_and_requires_auth(self):
        """The old in-app upgrade handler must still be reachable at the NEW
        path /checkout/upgrade, and must still enforce auth (returns 403 for
        unauthenticated callers) — confirming it was moved, not deleted.
        """
        app = _build_test_app()
        with app.test_client() as client:
            resp = client.post(
                "/api/v1/billing/checkout/upgrade",
                json={"plan": "world-class", "billing_cycle": "monthly"},
                content_type="application/json",
            )
        # The upgrade handler checks current_user_id and returns 403 when absent.
        assert resp.status_code == 403, (
            f"Expected 403 (auth required) at /checkout/upgrade, got {resp.status_code}. "
            "The upgrade handler may have been removed rather than moved."
        )
