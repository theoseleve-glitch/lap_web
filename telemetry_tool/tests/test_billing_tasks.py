"""Tests for Stripe reconciliation Celery task."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _mock_conn():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


def _user_row(user_id, sub_id, sub_status, plan_tier="racer"):
    return {
        "id": user_id,
        "stripe_subscription_id": sub_id,
        "subscription_status": sub_status,
        "plan_tier": plan_tier,
    }


class TestReconcileStripe:
    @patch("tasks.billing_tasks.get_pg_connection")
    @patch("tasks.billing_tasks.stripe")
    def test_heals_mismatch(self, mock_stripe, mock_db):
        """Reconciliation fixes local state when it differs from Stripe."""
        conn = _mock_conn()
        mock_db.return_value = conn

        # First execute().fetchall() returns user list;
        # subsequent execute().fetchone() returns user lookup for transition_subscription;
        # remaining calls are UPDATE/INSERT statements.
        users_result = MagicMock()
        users_result.fetchall.return_value = [
            _user_row(1, "sub_abc", "active"),
        ]
        user_lookup = MagicMock()
        user_lookup.fetchone.return_value = {
            "email": "test@x.com",
            "subscription_status": "active",
            "plan_tier": "racer",
        }
        default_result = MagicMock()
        default_result.fetchone.return_value = None
        default_result.fetchall.return_value = []

        conn.execute.side_effect = [
            users_result,    # SELECT users with stripe subs
            user_lookup,     # SELECT user in transition_subscription
            default_result,  # INSERT audit_log
            default_result,  # UPDATE users SET plan_tier/status
            default_result,  # extra safety
        ]
        mock_stripe.Subscription.retrieve.return_value = MagicMock(status="canceled")

        from tasks.billing_tasks import _reconcile_stripe_impl
        result = _reconcile_stripe_impl()

        assert result["healed"] == 1
        assert result["checked"] == 1

    @patch("tasks.billing_tasks.get_pg_connection")
    @patch("tasks.billing_tasks.stripe")
    def test_no_mismatch_no_update(self, mock_stripe, mock_db):
        """Reconciliation does not UPDATE when local matches Stripe."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            _user_row(1, "sub_abc", "active"),
        ]
        mock_stripe.Subscription.retrieve.return_value = MagicMock(status="active")

        from tasks.billing_tasks import _reconcile_stripe_impl
        result = _reconcile_stripe_impl()

        assert result["healed"] == 0
        assert result["checked"] == 1

    @patch("tasks.billing_tasks.get_pg_connection")
    @patch("tasks.billing_tasks.stripe")
    def test_resource_missing_still_cancels(self, mock_stripe, mock_db):
        """FIX 4: a definitive 'no such subscription' from Stripe (InvalidRequestError
        with code='resource_missing') is still treated as cancelled — this is the
        one case the narrowed except must preserve, not silently swallow.
        """
        conn = _mock_conn()
        mock_db.return_value = conn

        users_result = MagicMock()
        users_result.fetchall.return_value = [
            _user_row(1, "sub_gone", "active"),
        ]
        user_lookup = MagicMock()
        user_lookup.fetchone.return_value = {
            "email": "test@x.com",
            "subscription_status": "active",
            "plan_tier": "racer",
        }
        default_result = MagicMock()
        default_result.fetchone.return_value = None
        default_result.fetchall.return_value = []

        conn.execute.side_effect = [
            users_result,    # SELECT users with stripe subs
            user_lookup,     # SELECT user in transition_subscription
            default_result,  # INSERT audit_log
            default_result,  # UPDATE users
            default_result,  # extra safety
        ]

        # Give the mocked stripe module a real exception subclass (mirrors the
        # SignatureVerificationError-as-Exception trick in test_billing_webhook.py)
        # so `except stripe.error.InvalidRequestError` in the source binds to it.
        class _FakeInvalidRequestError(Exception):
            def __init__(self, message, code=None, http_status=None):
                super().__init__(message)
                self.code = code
                self.http_status = http_status

        mock_stripe.error = MagicMock()
        mock_stripe.error.InvalidRequestError = _FakeInvalidRequestError
        mock_stripe.Subscription.retrieve.side_effect = _FakeInvalidRequestError(
            "No such subscription: 'sub_gone'", code="resource_missing",
        )

        from tasks.billing_tasks import _reconcile_stripe_impl
        result = _reconcile_stripe_impl()

        assert result["healed"] == 1
        assert result["errors"] == 0

    @patch("tasks.billing_tasks.get_pg_connection")
    @patch("tasks.billing_tasks.stripe")
    def test_transient_stripe_error_skips_without_cancelling(self, mock_stripe, mock_db):
        """FIX 4: a transient Stripe error (timeout/5xx/rate-limit/rotated key)
        must NOT be treated as 'subscription cancelled'. The old blanket
        `except Exception: ... canceled` would mass-cancel (and email) the
        entire subscriber base on a single bad Stripe API call — the user
        must instead be skipped for this run and counted as an error.
        """
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            _user_row(1, "sub_transient", "active"),
        ]

        mock_stripe.error = MagicMock()
        mock_stripe.error.InvalidRequestError = type(
            "InvalidRequestError", (Exception,), {},
        )
        mock_stripe.error.APIConnectionError = type(
            "APIConnectionError", (Exception,), {},
        )
        mock_stripe.Subscription.retrieve.side_effect = mock_stripe.error.APIConnectionError(
            "Connection timed out",
        )

        from tasks.billing_tasks import _reconcile_stripe_impl
        result = _reconcile_stripe_impl()

        assert result["healed"] == 0
        assert result["errors"] == 1
        assert result["checked"] == 1
        # Only the initial SELECT of subscribers happened — no UPDATE/transition
        # was attempted for the skipped user.
        assert conn.execute.call_count == 1

    @patch("tasks.billing_tasks.get_pg_connection")
    @patch("tasks.billing_tasks.stripe")
    def test_empty_subscribers(self, mock_stripe, mock_db):
        """Reconciliation handles zero subscribers gracefully."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = []

        from tasks.billing_tasks import _reconcile_stripe_impl
        result = _reconcile_stripe_impl()

        assert result["healed"] == 0
        assert result["checked"] == 0


class TestBeatSchedule:
    def test_beat_schedule_has_reconcile(self):
        """Celery beat schedule includes reconcile-stripe."""
        from celery_app import celery
        schedule = celery.conf.beat_schedule
        assert "reconcile-stripe" in schedule
        assert schedule["reconcile-stripe"]["task"] == "tasks.billing_tasks.reconcile_stripe"
        assert schedule["reconcile-stripe"]["schedule"] == 3600

    def test_beat_schedule_has_purge(self):
        """Celery beat schedule includes purge-deleted-accounts."""
        from celery_app import celery
        schedule = celery.conf.beat_schedule
        assert "purge-deleted-accounts" in schedule

    def test_beat_schedule_has_export_cleanup(self):
        """Celery beat schedule includes cleanup-expired-exports."""
        from celery_app import celery
        schedule = celery.conf.beat_schedule
        assert "cleanup-expired-exports" in schedule

    def test_beat_schedule_has_reconcile_pending_entitlements(self):
        """FIX 3: Celery beat schedule sweeps stripe_pending_entitlements."""
        from celery_app import celery
        schedule = celery.conf.beat_schedule
        assert "reconcile-pending-entitlements" in schedule
        assert (
            schedule["reconcile-pending-entitlements"]["task"]
            == "tasks.billing_tasks.reconcile_pending_entitlements"
        )


# ===========================================================================
# FIX 3 — reconcile_pending_entitlements: sweep orphaned paying customers
# ===========================================================================


def _pending_row(row_id, email, plan_tier="world-class",
                  customer_id="cus_pending", subscription_id="sub_pending"):
    return {
        "id": row_id,
        "stripe_customer_id": customer_id,
        "stripe_subscription_id": subscription_id,
        "customer_email": email,
        "plan_tier": plan_tier,
    }


class TestReconcilePendingEntitlements:
    """FIX 3: stripe_pending_entitlements is written on an unmatched checkout
    but nothing ever read it back — orphaned paying customers stayed locked
    forever. This task closes that loop.
    """

    @patch("tasks.billing_tasks.return_pg_connection")
    @patch("tasks.billing_tasks.get_maint_connection")
    @patch("tasks.billing_tasks.transition_subscription")
    def test_matching_email_links_user_and_marks_reconciled(
        self, mock_transition, mock_get_maint, mock_return_conn,
    ):
        """A pending row whose email matches a user (case-insensitively) gets
        that user's Stripe IDs attached and the row marked reconciled_at.
        """
        conn = _mock_conn()
        mock_get_maint.return_value = conn
        mock_transition.return_value = True

        pending_result = MagicMock()
        pending_result.fetchall.return_value = [
            _pending_row(1, "Alex.Martin@gmail.com"),
        ]
        user_match = MagicMock()
        user_match.fetchone.return_value = {"id": 42}
        default_result = MagicMock()
        default_result.fetchone.return_value = None
        default_result.fetchall.return_value = []

        conn.execute.side_effect = [
            pending_result,   # SELECT stripe_pending_entitlements WHERE reconciled_at IS NULL
            user_match,       # SELECT id FROM users WHERE LOWER(email) = LOWER(...)
            default_result,   # UPDATE users SET stripe_customer_id/stripe_subscription_id
            default_result,   # UPDATE stripe_pending_entitlements SET reconciled_at
        ]

        from tasks.billing_tasks import _reconcile_pending_entitlements_impl
        result = _reconcile_pending_entitlements_impl()

        assert result == {"checked": 1, "linked": 1, "unmatched": 0, "errors": 0}
        mock_transition.assert_called_once()
        args, kwargs = mock_transition.call_args
        assert args[1] == 42  # user id resolved from the pending row's email
        assert args[2] == "active"
        assert kwargs.get("plan_tier") == "world-class"

        # The row must be marked reconciled — find the UPDATE ... reconciled_at call.
        reconciled_calls = [
            c for c in conn.execute.call_args_list
            if "reconciled_at" in str(c[0][0])
        ]
        assert reconciled_calls, "Expected an UPDATE ... SET reconciled_at call"

        # The email match itself must be case-insensitive.
        email_match_sql = str(conn.execute.call_args_list[1][0][0])
        assert "LOWER(email)" in email_match_sql

        mock_return_conn.assert_called_once_with(conn)

    @patch("tasks.billing_tasks.return_pg_connection")
    @patch("tasks.billing_tasks.get_maint_connection")
    @patch("tasks.billing_tasks.transition_subscription")
    def test_no_matching_user_leaves_row_untouched(
        self, mock_transition, mock_get_maint, mock_return_conn,
    ):
        """A pending row with no matching user is left alone (reconciled_at
        stays NULL) so a later signup can still be swept and linked.
        """
        conn = _mock_conn()
        mock_get_maint.return_value = conn

        pending_result = MagicMock()
        pending_result.fetchall.return_value = [
            _pending_row(2, "ghost@example.com"),
        ]
        no_user_match = MagicMock()
        no_user_match.fetchone.return_value = None

        conn.execute.side_effect = [
            pending_result,   # SELECT stripe_pending_entitlements WHERE reconciled_at IS NULL
            no_user_match,    # SELECT id FROM users WHERE LOWER(email) = LOWER(...) -> miss
        ]

        from tasks.billing_tasks import _reconcile_pending_entitlements_impl
        result = _reconcile_pending_entitlements_impl()

        assert result == {"checked": 1, "linked": 0, "unmatched": 1, "errors": 0}
        mock_transition.assert_not_called()
        # No UPDATE of any kind should have been issued for the unmatched row.
        assert conn.execute.call_count == 2

    @patch("tasks.billing_tasks.return_pg_connection")
    @patch("tasks.billing_tasks.get_maint_connection")
    def test_empty_pending_table(self, mock_get_maint, mock_return_conn):
        """No unreconciled rows → no-op, zeroed counters."""
        conn = _mock_conn()
        mock_get_maint.return_value = conn
        conn.execute.return_value.fetchall.return_value = []

        from tasks.billing_tasks import _reconcile_pending_entitlements_impl
        result = _reconcile_pending_entitlements_impl()

        assert result == {"checked": 0, "linked": 0, "unmatched": 0, "errors": 0}

    @patch("tasks.billing_tasks.return_pg_connection")
    @patch("tasks.billing_tasks.get_maint_connection")
    @patch("tasks.billing_tasks.transition_subscription")
    def test_one_bad_row_does_not_abort_the_sweep(
        self, mock_transition, mock_get_maint, mock_return_conn,
    ):
        """A per-row exception (e.g. a DB hiccup) must not abort the whole
        sweep — it is counted as an error and the sweep continues.
        """
        conn = _mock_conn()
        mock_get_maint.return_value = conn

        pending_result = MagicMock()
        pending_result.fetchall.return_value = [
            _pending_row(3, "broken@example.com"),
        ]
        conn.execute.side_effect = [
            pending_result,               # SELECT stripe_pending_entitlements
            RuntimeError("DB exploded"),  # SELECT users -> raises
        ]

        from tasks.billing_tasks import _reconcile_pending_entitlements_impl
        result = _reconcile_pending_entitlements_impl()

        assert result["checked"] == 1
        assert result["errors"] == 1
        assert result["linked"] == 0
        mock_transition.assert_not_called()
