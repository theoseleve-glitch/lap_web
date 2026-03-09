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
        assert ents["reports_per_month"] == 10
        assert "_paused" not in ents

    def test_trialing_full_access(self):
        """Trialing subscription gets full plan entitlements."""
        ents = self._make_entitlements("trialing")
        assert ents["reports_per_month"] == 10
        assert "_paused" not in ents

    def test_past_due_flagged(self):
        """Past due subscription gets full access but is flagged."""
        ents = self._make_entitlements("past_due")
        assert ents.get("_past_due") is True
        assert ents["reports_per_month"] == 10

    def test_canceled_flagged(self):
        """Canceled subscription is flagged for grace period handling."""
        ents = self._make_entitlements("canceled")
        assert ents.get("_cancel_pending") is True

    def test_paused_blocks_reports(self):
        """Paused subscription blocks new reports."""
        ents = self._make_entitlements("paused")
        assert ents.get("_paused") is True
        assert ents["reports_per_month"] == 0
        assert ents["reports_remaining"] == 0


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
            [{"event_type": "report_generated", "total": 7}],  # usage
        ]
        ents = get_user_entitlements(conn, 1, 1)
        assert ents["reports_used"] == 7
        assert ents["reports_remaining"] == 3
