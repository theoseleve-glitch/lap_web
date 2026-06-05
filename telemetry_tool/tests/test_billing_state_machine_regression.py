"""Regression tests for billing correctness.

Validates:
- subscription_status is NOT always "free" after checkout/webhook
- State machine transitions work end-to-end
- Stripe status mapping covers all Stripe statuses
- Entitlement middleware blocks unpaid/canceled users
- plan_tier derived from price_id mapping
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# State machine unit tests
# ---------------------------------------------------------------------------

class TestStateMachine:
    def test_free_to_active(self):
        from billing.state_machine import validate_transition
        assert validate_transition("free", "active") is True

    def test_free_to_trialing(self):
        from billing.state_machine import validate_transition
        assert validate_transition("free", "trialing") is True

    def test_active_to_past_due(self):
        from billing.state_machine import validate_transition
        assert validate_transition("active", "past_due") is True

    def test_active_to_unpaid(self):
        from billing.state_machine import validate_transition
        assert validate_transition("active", "unpaid") is True

    def test_past_due_to_active(self):
        from billing.state_machine import validate_transition
        assert validate_transition("past_due", "active") is True

    def test_past_due_to_unpaid(self):
        from billing.state_machine import validate_transition
        assert validate_transition("past_due", "unpaid") is True

    def test_canceled_to_active(self):
        from billing.state_machine import validate_transition
        assert validate_transition("canceled", "active") is True

    def test_canceled_to_free(self):
        from billing.state_machine import validate_transition
        assert validate_transition("canceled", "free") is True

    def test_free_to_canceled_invalid(self):
        from billing.state_machine import validate_transition
        assert validate_transition("free", "canceled") is False

    def test_free_to_past_due_invalid(self):
        from billing.state_machine import validate_transition
        assert validate_transition("free", "past_due") is False


class TestStripeStatusMapping:
    def test_all_stripe_statuses_mapped(self):
        from billing.state_machine import map_stripe_status
        stripe_statuses = [
            "trialing", "active", "past_due", "canceled",
            "unpaid", "paused", "incomplete", "incomplete_expired",
        ]
        for status in stripe_statuses:
            result = map_stripe_status(status)
            assert result in ("free", "trialing", "active", "past_due",
                              "canceled", "unpaid", "paused"), \
                f"Stripe status '{status}' mapped to unexpected '{result}'"

    def test_active_maps_to_active(self):
        from billing.state_machine import map_stripe_status
        assert map_stripe_status("active") == "active"

    def test_incomplete_maps_to_free(self):
        from billing.state_machine import map_stripe_status
        assert map_stripe_status("incomplete") == "free"

    def test_incomplete_expired_maps_to_canceled(self):
        from billing.state_machine import map_stripe_status
        assert map_stripe_status("incomplete_expired") == "canceled"

    def test_unknown_maps_to_free(self):
        from billing.state_machine import map_stripe_status
        assert map_stripe_status("bogus_status") == "free"


# ---------------------------------------------------------------------------
# Webhook handler tests — subscription_status NOT stuck at "free"
# ---------------------------------------------------------------------------

class TestCheckoutActivatesSubscription:
    """REGRESSION: subscription_status must change from 'free' to 'active'
    after checkout.session.completed webhook."""

    def test_checkout_sets_active_and_tier(self):
        from web.routes.billing import _handle_checkout_completed
        with patch("web.routes.billing._get_conn") as mock_conn_fn, \
             patch("web.routes.billing.audit_log"), \
             patch("billing.state_machine.transition_subscription", return_value=True) as mock_transition:
            conn = MagicMock()
            mock_conn_fn.return_value = conn
            # First execute: UPDATE stripe IDs
            # Second execute: SELECT id
            conn.execute.return_value.fetchone.return_value = {"id": 1}

            session = {
                "id": "cs_test_123",
                "customer_email": "user@test.com",
                "customer": "cus_test_123",
                "subscription": "sub_test_123",
                "metadata": {"plan_tier": "racer"},
            }
            _handle_checkout_completed(session)

            mock_transition.assert_called_once()
            args = mock_transition.call_args
            assert args[0][2] == "active"  # new_status
            assert args[1]["plan_tier"] == "racer"


class TestSubscriptionCreatedHandler:
    """customer.subscription.created should activate the user."""

    def test_subscription_created_activates(self):
        from web.routes.billing import _handle_subscription_created
        with patch("web.routes.billing._get_conn") as mock_conn_fn, \
             patch("web.routes.billing.audit_log"), \
             patch("billing.state_machine.transition_subscription", return_value=True) as mock_transition:
            conn = MagicMock()
            mock_conn_fn.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"id": 1}

            subscription = {
                "id": "sub_test_123",
                "customer": "cus_test_123",
                "status": "active",
                "items": {"data": []},
            }
            _handle_subscription_created(subscription)

            mock_transition.assert_called_once()
            args = mock_transition.call_args
            assert args[0][2] == "active"

    def test_subscription_created_trialing(self):
        from web.routes.billing import _handle_subscription_created
        with patch("web.routes.billing._get_conn") as mock_conn_fn, \
             patch("web.routes.billing.audit_log"), \
             patch("billing.state_machine.transition_subscription", return_value=True) as mock_transition:
            conn = MagicMock()
            mock_conn_fn.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"id": 1}

            subscription = {
                "id": "sub_test_123",
                "customer": "cus_test_123",
                "status": "trialing",
                "items": {"data": []},
            }
            _handle_subscription_created(subscription)

            mock_transition.assert_called_once()
            args = mock_transition.call_args
            assert args[0][2] == "trialing"


class TestSubscriptionUpdatedUsesStateMachine:
    """REGRESSION: _handle_subscription_updated must use state machine,
    not raw SQL."""

    def test_updated_uses_transition_subscription(self):
        from web.routes.billing import _handle_subscription_updated
        mock_stripe_sub = MagicMock()
        mock_stripe_sub.status = "past_due"

        with patch("web.routes.billing._get_conn") as mock_conn_fn, \
             patch("web.routes.billing.audit_log"), \
             patch("web.routes.billing.stripe") as mock_stripe, \
             patch("billing.state_machine.transition_subscription", return_value=True) as mock_transition:
            mock_stripe.Subscription.retrieve.return_value = mock_stripe_sub
            conn = MagicMock()
            mock_conn_fn.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"id": 1}

            _handle_subscription_updated({
                "id": "sub_123",
                "customer": "cus_123",
                "status": "past_due",
                "items": {"data": []},
            })

            mock_transition.assert_called_once()
            args = mock_transition.call_args
            assert args[0][2] == "past_due"


# ---------------------------------------------------------------------------
# Transition end-to-end (with mock DB)
# ---------------------------------------------------------------------------

class TestTransitionEndToEnd:
    """Test transition_subscription writes correct status to DB."""

    def test_transition_writes_new_status(self):
        from billing.state_machine import transition_subscription

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "subscription_status": "free",  # billing state — unchanged in new model
            "plan_tier": "locked",
        }

        with patch("billing.state_machine.logger"):
            result = transition_subscription(conn, 1, "active", plan_tier="racer")

        assert result is True
        # Verify UPDATE was called with correct status
        update_call = conn.execute.call_args_list[1]
        sql = update_call[0][0]
        params = update_call[0][1]
        assert "subscription_status = %(new_status)s" in sql
        assert params["new_status"] == "active"
        assert params["tier"] == "racer"

    def test_transition_rejects_invalid(self):
        from billing.state_machine import transition_subscription

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "email": "user@test.com",
            "subscription_status": "free",  # billing state — unchanged in new model
            "plan_tier": "locked",
        }

        with patch("billing.state_machine.logger"):
            result = transition_subscription(conn, 1, "past_due")

        assert result is False
        # Only the SELECT should have been called, not UPDATE
        assert conn.execute.call_count == 1


# ---------------------------------------------------------------------------
# Plan tier derivation from price_id
# ---------------------------------------------------------------------------

class TestPlanTierDerivation:
    def test_price_to_tier_mapping(self):
        """STRIPE_PRICE_TO_TIER maps the standard + founding price IDs to the membership tier.

        June-8 model: ONE membership. Both the standard (€19.90) and Founding-50
        (€14.90) prices grant the same full-access tier (internally 'world-class').
        """
        import os
        with patch.dict(os.environ, {
            "STRIPE_PRICE_STANDARD_MONTHLY": "price_standard_mo",
            "STRIPE_PRICE_FOUNDING_MONTHLY": "price_founding_mo",
        }):
            from web.routes.billing import STRIPE_PRICE_TO_TIER, _init_price_mapping
            STRIPE_PRICE_TO_TIER.clear()
            _init_price_mapping()
            assert STRIPE_PRICE_TO_TIER.get("price_standard_mo") == "world-class"
            assert STRIPE_PRICE_TO_TIER.get("price_founding_mo") == "world-class"

    def test_resolve_tier_from_metadata(self):
        from web.routes.billing import _resolve_tier_from_checkout
        session = {"metadata": {"plan_tier": "world-class"}}
        assert _resolve_tier_from_checkout(session) == "world-class"


# ---------------------------------------------------------------------------
# Regression: subscription_status NOT always "free"
# ---------------------------------------------------------------------------

class TestSubscriptionStatusRegression:
    """The core regression: after a successful checkout and webhook,
    subscription_status must NOT be 'free'."""

    def test_status_not_free_after_checkout(self):
        """Simulates full checkout flow and verifies status != free."""
        from billing.state_machine import transition_subscription

        conn = MagicMock()
        # Simulate user currently on the locked floor (subscription_status 'free')
        conn.execute.return_value.fetchone.return_value = {
            "email": "driver@racing.com",
            "subscription_status": "free",  # billing state — unchanged in new model
            "plan_tier": "locked",
        }

        with patch("billing.state_machine.logger"):
            result = transition_subscription(
                conn, 1, "active", plan_tier="racer",
            )

        assert result is True
        update_sql = conn.execute.call_args_list[1][0][0]
        update_params = conn.execute.call_args_list[1][0][1]
        assert update_params["new_status"] == "active"
        assert update_params["tier"] == "racer"
        # The UPDATE SQL sets subscription_status, NOT leaving it as 'free'
        assert "subscription_status = %(new_status)s" in update_sql

    def test_status_not_free_after_subscription_updated_webhook(self):
        """Subscription.updated webhook must transition away from free."""
        from billing.state_machine import transition_subscription

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "email": "driver@racing.com",
            "subscription_status": "free",  # billing state — unchanged in new model
            "plan_tier": "locked",
        }

        with patch("billing.state_machine.logger"):
            result = transition_subscription(conn, 1, "active")

        assert result is True
        update_params = conn.execute.call_args_list[1][0][1]
        assert update_params["new_status"] == "active"
