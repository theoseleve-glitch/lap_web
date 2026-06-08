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


# ===========================================================================
# A3 — Webhook reliability: retry on handler error
# ===========================================================================

class TestWebhookReliability:
    """A3: handler exception → non-2xx + Redis dedup key cleared so Stripe retries."""

    def _make_stripe_event(self, event_type="invoice.paid", event_id="evt_reliability_1"):
        return {
            "type": event_type,
            "id": event_id,
            "created": 1700000000,
            "data": {"object": {"customer": "cus_rel_test"}},
        }

    def _build_app(self):
        import flask
        app = flask.Flask(__name__)
        app.config["TESTING"] = True
        from web.routes.billing import bp
        app.register_blueprint(bp)
        return app

    @patch("web.routes.billing.STRIPE_SECRET_KEY", "sk_test_fake")
    @patch("web.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_fake")
    @patch("web.routes.billing._redis_event_is_seen", return_value=False)
    @patch("web.routes.billing._redis_event_clear")
    @patch("web.routes.billing._redis_event_mark_seen")
    @patch("web.routes.billing._get_conn")
    @patch("web.routes.billing.stripe")
    def test_handler_exception_returns_non_2xx_and_clears_redis(
        self, mock_stripe, mock_get_conn, mock_mark_seen, mock_clear, mock_is_seen
    ):
        """When a handler raises, the response must be non-2xx and Redis key cleared."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn
        conn.execute.return_value.fetchone.return_value = None  # no DB dedup hit

        event = self._make_stripe_event()
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.error = MagicMock()
        mock_stripe.error.SignatureVerificationError = Exception

        with patch("web.routes.billing._handle_payment_succeeded",
                   side_effect=RuntimeError("DB exploded")):
            app = self._build_app()
            with app.test_client() as client:
                resp = client.post(
                    "/api/v1/billing/webhook",
                    data=json.dumps(event),
                    content_type="application/json",
                    headers={"Stripe-Signature": "t=1,v1=sig"},
                )

        assert resp.status_code >= 500, (
            f"Expected 5xx on handler error, got {resp.status_code}"
        )
        mock_clear.assert_called_once_with("evt_reliability_1")
        mock_mark_seen.assert_not_called()

    @patch("web.routes.billing.STRIPE_SECRET_KEY", "sk_test_fake")
    @patch("web.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_fake")
    @patch("web.routes.billing._redis_event_is_seen", return_value=False)
    @patch("web.routes.billing._redis_event_clear")
    @patch("web.routes.billing._redis_event_mark_seen")
    @patch("web.routes.billing._get_conn")
    @patch("web.routes.billing.stripe")
    def test_successful_event_returns_200_and_marks_seen(
        self, mock_stripe, mock_get_conn, mock_mark_seen, mock_clear, mock_is_seen
    ):
        """Successful handler → 200 + Redis key marked seen (deduped on replay)."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn
        conn.execute.return_value.fetchone.return_value = None

        event = self._make_stripe_event(event_id="evt_success_1")
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.error = MagicMock()
        mock_stripe.error.SignatureVerificationError = Exception

        with patch("web.routes.billing._handle_payment_succeeded", return_value=None):
            app = self._build_app()
            with app.test_client() as client:
                resp = client.post(
                    "/api/v1/billing/webhook",
                    data=json.dumps(event),
                    content_type="application/json",
                    headers={"Stripe-Signature": "t=1,v1=sig"},
                )

        assert resp.status_code == 200
        mock_mark_seen.assert_called_once_with("evt_success_1")
        mock_clear.assert_not_called()

    @patch("web.routes.billing.STRIPE_SECRET_KEY", "sk_test_fake")
    @patch("web.routes.billing.STRIPE_WEBHOOK_SECRET", "whsec_fake")
    @patch("web.routes.billing._redis_event_is_seen", return_value=True)
    @patch("web.routes.billing._get_conn")
    @patch("web.routes.billing.stripe")
    def test_replay_of_successful_event_is_noop_200(
        self, mock_stripe, mock_get_conn, mock_is_seen
    ):
        """Replayed event that was already processed → 200 (skipped) without re-processing."""
        conn = _mock_conn()
        mock_get_conn.return_value = conn

        event = self._make_stripe_event(event_id="evt_replay_1")
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.error = MagicMock()
        mock_stripe.error.SignatureVerificationError = Exception

        with patch("web.routes.billing._handle_payment_succeeded") as mock_handler:
            app = self._build_app()
            with app.test_client() as client:
                resp = client.post(
                    "/api/v1/billing/webhook",
                    data=json.dumps(event),
                    content_type="application/json",
                    headers={"Stripe-Signature": "t=1,v1=sig"},
                )

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("skipped") is True
        mock_handler.assert_not_called()


# ===========================================================================
# A4 — Customer matching by stripe_customer_id
# ===========================================================================

class TestCheckoutCustomerMatching:
    """A4: user matched by stripe_customer_id when email differs."""

    def test_checkout_matched_by_stripe_customer_id_when_email_differs(self):
        """If email has no match but stripe_customer_id does, user is resolved."""
        from web.routes.billing import _handle_checkout_completed

        with patch("web.routes.billing._get_conn") as mock_conn_fn, \
             patch("web.routes.billing.audit_log"), \
             patch("billing.state_machine.transition_subscription", return_value=True) as mock_transition:

            conn = _mock_conn()
            mock_conn_fn.return_value = conn

            # Simulate: metadata has no user_id, client_reference_id absent,
            # stripe_customer_id lookup finds the user, email lookup would miss.
            call_results = iter([
                # 1. metadata user_id lookup → miss (no client_reference_id / meta uid)
                # (skipped — no uid_hint)
                # 2. stripe_customer_id lookup → HIT
                MagicMock(**{"fetchone.return_value": {"id": 77, "email": "old@example.com"}}),
                # 3. UPDATE users SET stripe_customer_id + stripe_subscription_id
                MagicMock(**{"fetchone.return_value": None}),
                # 4. transition_subscription inner SELECT
                MagicMock(**{"fetchone.return_value": None}),
            ])
            conn.execute.side_effect = lambda sql, params=None: next(call_results)

            session = {
                "id": "cs_test_cid_match",
                "customer_email": "new@example.com",  # email that has NO user row
                "customer": "cus_existing_123",
                "subscription": "sub_abc",
                "metadata": {"plan_tier": "world-class"},
            }
            _handle_checkout_completed(session)

        mock_transition.assert_called_once()
        args = mock_transition.call_args
        assert args[0][2] == "active"
        assert args[1]["plan_tier"] == "world-class"

    def test_unmatched_checkout_records_pending_entitlement(self):
        """When no user row found at all, a pending entitlement is stored."""
        from web.routes.billing import _handle_checkout_completed

        with patch("web.routes.billing._get_conn") as mock_conn_fn, \
             patch("web.routes.billing.audit_log"), \
             patch("billing.state_machine.transition_subscription") as mock_transition:

            conn = _mock_conn()
            mock_conn_fn.return_value = conn
            # All lookups return None → no user found
            conn.execute.return_value.fetchone.return_value = None

            session = {
                "id": "cs_nomatch_1",
                "customer_email": "ghost@example.com",
                "customer": "cus_ghost_999",
                "subscription": "sub_ghost",
                "metadata": {"plan_tier": "world-class"},
            }
            with patch("web.routes.billing.logger") as mock_logger:
                _handle_checkout_completed(session)

            # Must NOT attempt to transition (no user)
            mock_transition.assert_not_called()
            # Must emit a loud error
            mock_logger.error.assert_called()
            # Must attempt to insert a pending entitlement
            insert_calls = [str(c) for c in conn.execute.call_args_list]
            assert any("stripe_pending_entitlements" in s for s in insert_calls)


# ===========================================================================
# B4 — Strict price→tier: unmapped → locked, never paid
# ===========================================================================

class TestStrictPriceTier:
    """B4: unmapped Stripe price resolves to 'locked', never a paid tier."""

    def test_unmapped_price_resolves_to_locked_not_paid(self):
        """_resolve_tier_from_checkout with unknown price → 'locked'."""
        from web.routes.billing import _resolve_tier_from_checkout
        session = {
            "id": "cs_unmapped",
            "metadata": {},  # no plan_tier hint
            "line_items": {
                "data": [{"price": {"id": "price_unknown_coupon_xyz"}}]
            },
        }
        tier = _resolve_tier_from_checkout(session)
        assert tier == "locked", f"Expected 'locked', got '{tier}'"

    def test_unmapped_price_emits_alert(self):
        """An unmapped price triggers logger.error."""
        from web.routes.billing import _resolve_tier_from_checkout
        session = {"id": "cs_alert", "metadata": {}}
        with patch("web.routes.billing.logger") as mock_logger:
            _resolve_tier_from_checkout(session)
        mock_logger.error.assert_called()

    def test_subscription_created_unmapped_price_resolves_to_locked(self):
        """_handle_subscription_created with unknown price → plan_tier='locked'."""
        from web.routes.billing import _handle_subscription_created

        with patch("web.routes.billing._get_conn") as mock_conn_fn, \
             patch("web.routes.billing.audit_log"), \
             patch("billing.state_machine.transition_subscription", return_value=True) as mock_transition:

            conn = _mock_conn()
            mock_conn_fn.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"id": 42}

            subscription = {
                "id": "sub_unmapped",
                "customer": "cus_xyz",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_not_in_allowlist"}}]},
            }
            with patch("web.routes.billing.logger") as mock_logger:
                _handle_subscription_created(subscription)

            mock_transition.assert_called_once()
            _, kwargs = mock_transition.call_args
            assert kwargs.get("plan_tier") == "locked", (
                f"Expected plan_tier='locked', got '{kwargs.get('plan_tier')}'"
            )
            # Must emit a loud alert
            mock_logger.error.assert_called()
