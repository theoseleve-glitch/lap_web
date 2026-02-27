"""Tests for Stripe webhook deduplication and event handling."""
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _mock_conn():
    """Return a mock PG connection with fetchone/fetchall defaults."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


class TestWebhookDedup:
    """Stripe webhook deduplication tests."""

    def test_duplicate_event_is_skipped(self):
        """Second delivery of same event ID returns True (already processed)."""
        conn = _mock_conn()
        # Simulate event already in DB
        conn.execute.return_value.fetchone.return_value = {"id": 1}

        from web.routes.billing import _is_event_processed
        assert _is_event_processed(conn, "evt_123") is True

    def test_new_event_is_not_skipped(self):
        """First delivery of event ID returns False (not processed)."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None

        from web.routes.billing import _is_event_processed
        assert _is_event_processed(conn, "evt_456") is False

    def test_record_event_inserts_row(self):
        """_record_event inserts a row into stripe_events."""
        conn = _mock_conn()

        from web.routes.billing import _record_event
        _record_event(conn, "evt_789", "checkout.session.completed", "abc123")

        # Verify INSERT was executed
        calls = [str(c) for c in conn.execute.call_args_list]
        assert any("stripe_events" in s for s in calls)


class TestSubscriptionUpdateFetchesStripe:
    """Verify subscription.updated fetches current state from Stripe API."""

    @patch("web.routes.billing._get_conn")
    @patch("web.routes.billing.stripe")
    def test_fetches_current_status_from_stripe(self, mock_stripe, mock_get_conn):
        """_handle_subscription_updated calls Stripe API for current status."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn
        mock_stripe.Subscription.retrieve.return_value = MagicMock(
            status="canceled",
        )

        from web.routes.billing import _handle_subscription_updated

        sub_data = {
            "id": "sub_123",
            "customer": "cus_abc",
            "status": "active",  # Event says active but Stripe says canceled
            "items": {"data": []},
        }
        _handle_subscription_updated(sub_data)

        # Should have called Stripe API
        mock_stripe.Subscription.retrieve.assert_called_once_with("sub_123")
