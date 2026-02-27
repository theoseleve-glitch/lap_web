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
        conn.execute.return_value.fetchall.return_value = [
            _user_row(1, "sub_abc", "active"),
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
    def test_handles_deleted_subscription(self, mock_stripe, mock_db):
        """Reconciliation handles subscription not found in Stripe."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            _user_row(1, "sub_gone", "active"),
        ]
        mock_stripe.Subscription.retrieve.side_effect = Exception("No such subscription")

        from tasks.billing_tasks import _reconcile_stripe_impl
        result = _reconcile_stripe_impl()

        assert result["healed"] == 1

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
