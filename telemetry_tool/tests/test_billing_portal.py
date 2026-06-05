"""Tests for billing status, portal, and email endpoints (Task 7).

Validates:
- GET /api/v1/billing/status returns correct billing snapshot
- Free plan user gets default status (no Stripe details)
- Paid plan user gets Stripe details when available
- POST /api/v1/billing/portal returns 400 without customer
- POST /api/v1/billing/portal returns URL with mock Stripe
- PATCH /api/v1/billing/email updates Stripe customer email
- PATCH /api/v1/billing/email returns 400 without customer
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class FakeConn:
    """Minimal fake DB connection for billing tests."""
    def __init__(self, rows_by_query=None):
        self._rows_by_query = rows_by_query or {}
        self._calls = []
        self._committed = False

    def execute(self, sql, params=None):
        self._calls.append((sql, params))
        cur = MagicMock()
        for key, rows in self._rows_by_query.items():
            if key in str(sql):
                cur.fetchone.return_value = rows[0] if rows else None
                cur.fetchall.return_value = rows
                return cur
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        return cur

    def commit(self):
        self._committed = True

    def rollback(self):
        pass


# ---------------------------------------------------------------------------
# Test billing status endpoint
# ---------------------------------------------------------------------------

class TestBillingStatus:
    def test_no_subscription_status(self):
        """No-subscription user gets default billing snapshot with no Stripe details.

        plan_tier is the zero-access 'locked' floor; subscription_status stays
        'free' (a billing-state value that is unchanged in the new model).
        """
        from web.routes.billing import billing_status

        conn = FakeConn({
            "plan_tier": [{
                "plan_tier": "locked",
                "subscription_status": "free",
                "stripe_customer_id": None,
                "stripe_subscription_id": None,
            }],
        })

        from flask import Flask
        app = Flask(__name__)
        from web.routes.billing import bp
        app.register_blueprint(bp)

        with app.test_request_context("/api/v1/billing/status"):
            from flask import g
            g.user_id = 1
            g.current_user_id = 1
            with patch("web.routes.billing._get_conn", return_value=conn):
                response, status = billing_status()
                data = response.get_json()

                assert status == 200
                assert data["ok"] is True
                assert data["data"]["plan_tier"] == "locked"
                # subscription_status 'free' is a billing state, NOT a tier — unchanged.
                assert data["data"]["subscription_status"] == "free"
                assert data["data"]["billing_cycle"] is None
                assert data["data"]["current_period_end"] is None
                assert data["data"]["payment_method"] is None

    def test_paid_plan_with_stripe_subscription(self):
        """Paid user gets Stripe details when Stripe call succeeds."""
        from web.routes.billing import billing_status

        conn = FakeConn({
            "plan_tier": [{
                "plan_tier": "racer",
                "subscription_status": "active",
                "stripe_customer_id": "cus_123",
                "stripe_subscription_id": "sub_456",
            }],
        })

        from flask import Flask
        app = Flask(__name__)
        from web.routes.billing import bp
        app.register_blueprint(bp)

        mock_sub = MagicMock()
        mock_sub.get.side_effect = lambda k, d=None: {
            "plan": {"interval": "month"},
            "current_period_end": 1740000000,
            "cancel_at_period_end": False,
            "default_payment_method": None,
        }.get(k, d)

        with app.test_request_context("/api/v1/billing/status"):
            from flask import g
            g.user_id = 1
            g.current_user_id = 1
            with patch("web.routes.billing._get_conn", return_value=conn), \
                 patch("web.routes.billing.STRIPE_SECRET_KEY", "sk_test_xxx"), \
                 patch("web.routes.billing.stripe") as mock_stripe:
                mock_stripe.Subscription.retrieve.return_value = mock_sub
                response, status = billing_status()
                data = response.get_json()

                assert status == 200
                assert data["data"]["plan_tier"] == "racer"
                assert data["data"]["subscription_status"] == "active"
                # Stripe details should be populated (at least attempted)
                mock_stripe.Subscription.retrieve.assert_called_once()


# ---------------------------------------------------------------------------
# Test billing portal endpoint
# ---------------------------------------------------------------------------

class TestBillingPortal:
    def test_portal_returns_400_without_customer(self):
        """Portal creation fails when user has no Stripe customer."""
        from web.routes.billing import billing_portal

        conn = FakeConn({
            "stripe_customer_id": [{"stripe_customer_id": None}],
        })

        from flask import Flask
        app = Flask(__name__)
        from web.routes.billing import bp
        app.register_blueprint(bp)

        with app.test_request_context(
            "/api/v1/billing/portal",
            method="POST",
            content_type="application/json",
            data=json.dumps({}),
        ):
            from flask import g
            g.user_id = 1
            g.current_user_id = 1
            with patch("web.routes.billing._get_conn", return_value=conn):
                response, status = billing_portal()
                data = response.get_json()

                assert status == 400
                assert data["ok"] is False
                assert "NO_CUSTOMER" in str(data["error"].get("details", ""))

    def test_portal_returns_url_with_stripe(self):
        """Portal creation returns URL when Stripe is configured."""
        from web.routes.billing import billing_portal

        conn = FakeConn({
            "stripe_customer_id": [{"stripe_customer_id": "cus_abc"}],
        })

        from flask import Flask
        app = Flask(__name__)
        from web.routes.billing import bp
        app.register_blueprint(bp)

        mock_session = MagicMock()
        mock_session.url = "https://billing.stripe.com/session/test"

        with app.test_request_context(
            "/api/v1/billing/portal",
            method="POST",
            content_type="application/json",
            data=json.dumps({"return_url": "https://example.com/billing"}),
        ):
            from flask import g
            g.user_id = 1
            g.current_user_id = 1
            with patch("web.routes.billing._get_conn", return_value=conn), \
                 patch("web.routes.billing.STRIPE_SECRET_KEY", "sk_test_xxx"), \
                 patch("web.routes.billing.stripe") as mock_stripe:
                mock_stripe.billing_portal.Session.create.return_value = mock_session
                response, status = billing_portal()
                data = response.get_json()

                assert status == 200
                assert data["data"]["url"] == "https://billing.stripe.com/session/test"
                mock_stripe.billing_portal.Session.create.assert_called_once()


# ---------------------------------------------------------------------------
# Test billing email endpoint
# ---------------------------------------------------------------------------

class TestBillingEmail:
    def test_email_update_requires_customer(self):
        """Email update fails without Stripe customer."""
        from web.routes.billing import billing_email

        conn = FakeConn({
            "stripe_customer_id": [{"stripe_customer_id": None}],
        })

        from flask import Flask
        app = Flask(__name__)
        from web.routes.billing import bp
        app.register_blueprint(bp)

        with app.test_request_context(
            "/api/v1/billing/email",
            method="PATCH",
            content_type="application/json",
            data=json.dumps({"email": "new@example.com"}),
        ):
            from flask import g
            g.user_id = 1
            g.current_user_id = 1
            with patch("web.routes.billing._get_conn", return_value=conn):
                response, status = billing_email()
                data = response.get_json()

                assert status == 400
                assert data["ok"] is False

    def test_email_update_success(self):
        """Email update succeeds with Stripe customer."""
        from web.routes.billing import billing_email

        conn = FakeConn({
            "stripe_customer_id": [{"stripe_customer_id": "cus_abc"}],
        })

        from flask import Flask
        app = Flask(__name__)
        from web.routes.billing import bp
        app.register_blueprint(bp)

        with app.test_request_context(
            "/api/v1/billing/email",
            method="PATCH",
            content_type="application/json",
            data=json.dumps({"email": "new@example.com"}),
        ):
            from flask import g
            g.user_id = 1
            g.current_user_id = 1
            with patch("web.routes.billing._get_conn", return_value=conn), \
                 patch("web.routes.billing.STRIPE_SECRET_KEY", "sk_test_xxx"), \
                 patch("web.routes.billing.stripe") as mock_stripe:
                response, status = billing_email()
                data = response.get_json()

                assert status == 200
                assert data["data"]["email"] == "new@example.com"
                assert data["data"]["updated"] is True
                mock_stripe.Customer.modify.assert_called_once_with(
                    "cus_abc", email="new@example.com",
                )

    def test_email_update_requires_email_field(self):
        """Email update requires email in request body."""
        from flask import Flask

        from web.routes.billing import billing_email
        app = Flask(__name__)
        from web.routes.billing import bp
        app.register_blueprint(bp)

        with app.test_request_context(
            "/api/v1/billing/email",
            method="PATCH",
            content_type="application/json",
            data=json.dumps({}),
        ):
            from flask import g
            g.user_id = 1
            g.current_user_id = 1
            with patch("web.routes.billing._get_conn", return_value=MagicMock()):
                response, status = billing_email()
                data = response.get_json()

                assert status == 400
                assert "email" in data["error"]["message"].lower()
