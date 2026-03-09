"""Tests for Stripe webhook logging to stripe_webhook_log.

Verifies:
- Webhook is logged with pending status after signature verification
- Status updated to processed after successful handling
- Status updated to failed on exception
- Sanitize payload strips PCI fields
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestWebhookLogging:
    def _make_app(self):
        from flask import Flask

        app = Flask(__name__)
        app.config["TESTING"] = True
        return app

    def _build_stripe_mock(self, event_type="checkout.session.completed"):
        """Create a mock stripe module with construct_event returning a valid event."""
        mock_stripe = MagicMock()
        mock_stripe.error = type("error", (), {
            "SignatureVerificationError": type(
                "SignatureVerificationError", (Exception,), {}
            ),
        })()
        mock_stripe.Webhook.construct_event.return_value = {
            "id": "evt_test_123",
            "type": event_type,
            "created": 1709100000,
            "data": {
                "object": {
                    "id": "cs_test_456",
                    "customer": "cus_test_789",
                    "customer_email": "user@test.com",
                    "subscription": "sub_test_abc",
                },
            },
        }
        return mock_stripe

    def test_webhook_logged_as_pending(self):
        """After signature verification, webhook is logged with pending status."""
        app = self._make_app()
        mock_stripe = self._build_stripe_mock()
        conn = MagicMock()
        conn.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))

        import importlib

        import web.routes.billing as billing_mod
        importlib.reload(billing_mod)

        with patch.object(billing_mod, "stripe", mock_stripe):
            with patch.object(billing_mod, "STRIPE_SECRET_KEY", "sk_test"):
                with patch.object(billing_mod, "STRIPE_WEBHOOK_SECRET", "whsec_test"):
                    with patch.object(billing_mod, "_get_conn", return_value=conn):
                        with patch.object(billing_mod, "_redis_event_check", return_value=False):
                            with patch.object(billing_mod, "_is_event_processed", return_value=False):
                                with patch.object(billing_mod, "_check_event_ordering", return_value=True):
                                    with patch("admin.audit.log_stripe_webhook") as mock_log_wh:
                                        with app.test_request_context(
                                            "/api/v1/billing/webhook",
                                            method="POST",
                                            data=b'{"test": true}',
                                            headers={"Stripe-Signature": "valid"},
                                        ):
                                            with patch.object(billing_mod, "_handle_checkout_completed"):
                                                billing_mod.stripe_webhook()

                                            mock_log_wh.assert_called_once()
                                            args, kwargs = mock_log_wh.call_args
                                            assert args[1] == "evt_test_123"
                                            assert args[2] == "checkout.session.completed"
                                            assert kwargs["signature_valid"] is True
                                            assert kwargs["processing_status"] == "pending"

    def test_webhook_status_updated_to_processed(self):
        """After successful processing, webhook status is updated."""
        app = self._make_app()
        mock_stripe = self._build_stripe_mock()
        conn = MagicMock()
        conn.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))

        import importlib

        import web.routes.billing as billing_mod
        importlib.reload(billing_mod)

        with patch.object(billing_mod, "stripe", mock_stripe):
            with patch.object(billing_mod, "STRIPE_SECRET_KEY", "sk_test"):
                with patch.object(billing_mod, "STRIPE_WEBHOOK_SECRET", "whsec_test"):
                    with patch.object(billing_mod, "_get_conn", return_value=conn):
                        with patch.object(billing_mod, "_redis_event_check", return_value=False):
                            with patch.object(billing_mod, "_is_event_processed", return_value=False):
                                with patch.object(billing_mod, "_check_event_ordering", return_value=True):
                                    with patch.object(billing_mod, "_update_webhook_status") as mock_update:
                                        with app.test_request_context(
                                            "/api/v1/billing/webhook",
                                            method="POST",
                                            data=b'{}',
                                            headers={"Stripe-Signature": "valid"},
                                        ):
                                            with patch.object(billing_mod, "_handle_checkout_completed"):
                                                billing_mod.stripe_webhook()

                                            mock_update.assert_called_with(
                                                conn, "evt_test_123", "processed"
                                            )

    def test_webhook_status_updated_to_failed_on_error(self):
        """On processing error, webhook status is set to failed."""
        app = self._make_app()
        mock_stripe = self._build_stripe_mock()
        conn = MagicMock()
        conn.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))

        import importlib

        import web.routes.billing as billing_mod
        importlib.reload(billing_mod)

        with patch.object(billing_mod, "stripe", mock_stripe):
            with patch.object(billing_mod, "STRIPE_SECRET_KEY", "sk_test"):
                with patch.object(billing_mod, "STRIPE_WEBHOOK_SECRET", "whsec_test"):
                    with patch.object(billing_mod, "_get_conn", return_value=conn):
                        with patch.object(billing_mod, "_redis_event_check", return_value=False):
                            with patch.object(billing_mod, "_is_event_processed", return_value=False):
                                with patch.object(billing_mod, "_check_event_ordering", return_value=True):
                                    with patch.object(billing_mod, "_update_webhook_status") as mock_update:
                                        with app.test_request_context(
                                            "/api/v1/billing/webhook",
                                            method="POST",
                                            data=b'{}',
                                            headers={"Stripe-Signature": "valid"},
                                        ):
                                            with patch.object(billing_mod, "_handle_checkout_completed",
                                                              side_effect=ValueError("bad data")):
                                                billing_mod.stripe_webhook()

                                            mock_update.assert_called_with(
                                                conn, "evt_test_123", "failed", "bad data"
                                            )


class TestSanitizePayload:
    def test_strips_card_data(self):
        from admin.audit import _sanitize_payload

        payload = {
            "id": "pi_123",
            "data": {
                "object": {
                    "id": "ch_123",
                    "card": {"last4": "4242", "brand": "visa"},
                    "amount": 2000,
                    "bank_account": {"routing_number": "110000000"},
                    "source": {"object": "card", "last4": "1234"},
                },
            },
        }
        result = _sanitize_payload(payload)

        # Sensitive fields removed
        obj = result["data"]["object"]
        assert "card" not in obj
        assert "bank_account" not in obj
        assert "source" not in obj
        # Safe fields preserved
        assert obj["amount"] == 2000
        # Original not mutated
        assert "card" in payload["data"]["object"]

    def test_strips_payment_method_billing_details(self):
        from admin.audit import _sanitize_payload

        payload = {
            "data": {
                "object": {
                    "payment_method": {
                        "type": "card",
                        "billing_details": {"address": "123 Main St"},
                    },
                },
            },
        }
        result = _sanitize_payload(payload)
        pm = result["data"]["object"]["payment_method"]
        assert "billing_details" not in pm
        assert pm["type"] == "card"

    def test_handles_missing_data(self):
        from admin.audit import _sanitize_payload

        result = _sanitize_payload({"amount": 100})
        assert result == {"amount": 100}

    def test_handles_none(self):
        from admin.audit import _sanitize_payload

        result = _sanitize_payload({})
        assert result == {}
