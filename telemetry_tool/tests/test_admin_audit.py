"""Tests for admin audit & security event helpers.

Validates:
- log_admin_action inserts into admin_audit_log
- log_security_event inserts into security_events
- log_stripe_webhook inserts and sanitizes payload
- _sanitize_payload removes PCI-sensitive fields
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class FakeConn:
    """Minimal fake DB connection tracking inserts."""

    def __init__(self):
        self._calls = []
        self._committed = False

    def execute(self, sql, params=None):
        self._calls.append((sql, params))
        cur = MagicMock()
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        return cur

    def commit(self):
        self._committed = True

    @property
    def last_sql(self):
        return self._calls[-1][0] if self._calls else None

    @property
    def last_params(self):
        return self._calls[-1][1] if self._calls else None


class TestLogAdminAction:
    def test_inserts_into_admin_audit_log(self):
        from admin.audit import log_admin_action

        conn = FakeConn()
        log_admin_action(
            conn,
            admin_user_id=1,
            action="user_suspended",
            target_type="user",
            target_id="42",
            reason="Abuse",
            details={"extra": "data"},
            ip_address="10.0.0.1",
            request_id="req-123",
        )

        assert len(conn._calls) == 1
        sql = conn.last_sql
        assert "admin_audit_log" in sql
        assert "INSERT" in sql.upper()
        params = conn.last_params
        assert params["admin_user_id"] == 1
        assert params["action"] == "user_suspended"
        assert params["target_type"] == "user"
        assert params["target_id"] == "42"
        assert params["reason"] == "Abuse"
        assert params["ip_address"] == "10.0.0.1"
        assert params["request_id"] == "req-123"
        assert "extra" in params["details_json"]

    def test_minimal_fields(self):
        from admin.audit import log_admin_action

        conn = FakeConn()
        log_admin_action(conn, admin_user_id=1, action="login")

        params = conn.last_params
        assert params["admin_user_id"] == 1
        assert params["action"] == "login"
        assert params["target_type"] is None
        assert params["target_id"] is None

    def test_details_serialized_as_json(self):
        from admin.audit import log_admin_action

        conn = FakeConn()
        log_admin_action(
            conn, admin_user_id=1, action="test",
            details={"key": "value", "nested": [1, 2, 3]},
        )

        details_json = conn.last_params["details_json"]
        parsed = json.loads(details_json)
        assert parsed["key"] == "value"
        assert parsed["nested"] == [1, 2, 3]


class TestLogSecurityEvent:
    def test_inserts_with_all_fields(self):
        from admin.audit import log_security_event

        conn = FakeConn()
        log_security_event(
            conn,
            event_type="login_failed",
            user_id=42,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            details={"email": "test@test.com"},
            severity="warning",
        )

        assert len(conn._calls) == 1
        sql = conn.last_sql
        assert "security_events" in sql
        params = conn.last_params
        assert params["event_type"] == "login_failed"
        assert params["user_id"] == 42
        assert params["ip_address"] == "192.168.1.1"
        assert params["user_agent"] == "Mozilla/5.0"
        assert params["severity"] == "warning"

    def test_minimal_fields_user_id_none(self):
        from admin.audit import log_security_event

        conn = FakeConn()
        log_security_event(conn, event_type="rate_limited")

        params = conn.last_params
        assert params["event_type"] == "rate_limited"
        assert params["user_id"] is None
        assert params["severity"] == "info"

    def test_default_severity_is_info(self):
        from admin.audit import log_security_event

        conn = FakeConn()
        log_security_event(conn, event_type="test_event")

        assert conn.last_params["severity"] == "info"


class TestLogStripeWebhook:
    def test_inserts_webhook_record(self):
        from admin.audit import log_stripe_webhook

        conn = FakeConn()
        payload = {"id": "evt_123", "type": "invoice.paid", "data": {"amount": 1000}}
        log_stripe_webhook(
            conn,
            stripe_event_id="evt_123",
            event_type="invoice.paid",
            payload=payload,
            signature_valid=True,
        )

        sql = conn.last_sql
        assert "stripe_webhook_log" in sql
        params = conn.last_params
        assert params["stripe_event_id"] == "evt_123"
        assert params["event_type"] == "invoice.paid"
        assert params["signature_valid"] is True
        assert params["processing_status"] == "pending"

    def test_sanitizes_payload_before_storing(self):
        from admin.audit import log_stripe_webhook

        conn = FakeConn()
        payload = {
            "id": "evt_123",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "card": {"last4": "1234", "number": "4242424242424242"},
                    "customer": "cus_abc",
                }
            },
        }
        log_stripe_webhook(
            conn, stripe_event_id="evt_123", event_type="invoice.paid",
            payload=payload, signature_valid=True,
        )

        stored = json.loads(conn.last_params["payload_json"])
        # Card data should be stripped
        assert "card" not in stored.get("data", {}).get("object", {})
        # Non-sensitive data preserved
        assert stored["id"] == "evt_123"

    def test_failed_status_with_error_message(self):
        from admin.audit import log_stripe_webhook

        conn = FakeConn()
        log_stripe_webhook(
            conn, stripe_event_id="evt_456", event_type="charge.failed",
            payload={}, signature_valid=False,
            processing_status="failed", error_message="Bad signature",
        )

        params = conn.last_params
        assert params["processing_status"] == "failed"
        assert params["error_message"] == "Bad signature"
        assert params["signature_valid"] is False


class TestSanitizePayload:
    def test_removes_card_field(self):
        from admin.audit import _sanitize_payload

        result = _sanitize_payload({
            "id": "evt_1",
            "data": {"object": {"card": {"number": "4242"}, "amount": 100}},
        })
        assert "card" not in result.get("data", {}).get("object", {})
        assert result["data"]["object"]["amount"] == 100

    def test_removes_bank_account_field(self):
        from admin.audit import _sanitize_payload

        result = _sanitize_payload({
            "data": {"object": {"bank_account": {"routing": "123"}}},
        })
        assert "bank_account" not in result.get("data", {}).get("object", {})

    def test_removes_source_field(self):
        from admin.audit import _sanitize_payload

        result = _sanitize_payload({
            "data": {"object": {"source": {"type": "card"}, "id": "ch_1"}},
        })
        assert "source" not in result.get("data", {}).get("object", {})
        assert result["data"]["object"]["id"] == "ch_1"

    def test_removes_billing_details_from_payment_method(self):
        from admin.audit import _sanitize_payload

        result = _sanitize_payload({
            "data": {
                "object": {
                    "payment_method": {
                        "billing_details": {"name": "John", "email": "j@t.com"},
                        "type": "card",
                    }
                }
            },
        })
        pm = result["data"]["object"]["payment_method"]
        assert "billing_details" not in pm
        assert pm["type"] == "card"

    def test_preserves_non_sensitive_fields(self):
        from admin.audit import _sanitize_payload

        payload = {"id": "evt_1", "type": "invoice.paid", "livemode": False}
        result = _sanitize_payload(payload)
        assert result == payload

    def test_handles_empty_payload(self):
        from admin.audit import _sanitize_payload

        assert _sanitize_payload({}) == {}

    def test_handles_missing_data_key(self):
        from admin.audit import _sanitize_payload

        result = _sanitize_payload({"id": "evt_1"})
        assert result == {"id": "evt_1"}
