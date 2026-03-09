"""Tests for billing reliability features: idempotency, retry, cache, dead-letter."""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_conn():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


def _mock_redis():
    r = MagicMock()
    r.get.return_value = None
    r.set.return_value = True
    r.delete.return_value = True
    r.pipeline.return_value = r
    r.execute.return_value = []
    return r


# ===========================================================================
# 1. Entitlement cache
# ===========================================================================


class TestEntitlementCache:
    """Tests for web.entitlement_cache module."""

    @patch("web.entitlement_cache._get_redis")
    @patch("web.entitlement_cache._fetch_from_db")
    def test_cache_hit_returns_cached(self, mock_db, mock_redis_fn):
        """Cache hit returns JSON from Redis without hitting DB."""
        r = _mock_redis()
        mock_redis_fn.return_value = r
        cached_data = {"plan_tier": "racer", "features": ["comparison"]}
        r.get.return_value = json.dumps(cached_data)

        from web.entitlement_cache import cached_entitlements
        result = cached_entitlements(42, 1)

        assert result == cached_data
        mock_db.assert_not_called()

    @patch("web.entitlement_cache._get_redis")
    @patch("web.entitlement_cache._fetch_from_db")
    def test_cache_miss_fetches_db_and_caches(self, mock_db, mock_redis_fn):
        """Cache miss fetches from DB and stores in Redis."""
        r = _mock_redis()
        mock_redis_fn.return_value = r
        r.get.return_value = None
        db_data = {"plan_tier": "world-class"}
        mock_db.return_value = db_data

        from web.entitlement_cache import cached_entitlements
        result = cached_entitlements(42, 1)

        assert result == db_data
        r.set.assert_called()  # Should cache the result
        mock_db.assert_called_once_with(42, 1)

    @patch("web.entitlement_cache._get_redis")
    def test_invalidate_deletes_key(self, mock_redis_fn):
        """invalidate_entitlements deletes the cache key."""
        r = _mock_redis()
        mock_redis_fn.return_value = r

        from web.entitlement_cache import invalidate_entitlements
        invalidate_entitlements(42)

        r.delete.assert_called_once_with("ent:42")

    @patch("web.entitlement_cache._get_redis")
    @patch("web.entitlement_cache._fetch_from_db")
    def test_redis_unavailable_falls_back_to_db(self, mock_db, mock_redis_fn):
        """When Redis is None, falls back to DB."""
        mock_redis_fn.return_value = None
        db_data = {"plan_tier": "demo"}
        mock_db.return_value = db_data

        from web.entitlement_cache import cached_entitlements
        result = cached_entitlements(42, 1)

        assert result == db_data

    @patch("web.entitlement_cache._get_redis")
    @patch("web.entitlement_cache._fetch_from_db")
    def test_singleflight_lock_prevents_stampede(self, mock_db, mock_redis_fn):
        """When lock is held by another, waits briefly then checks cache again."""
        r = _mock_redis()
        mock_redis_fn.return_value = r
        # First get: miss. Lock set: already held.
        # Second get (after sleep): cache populated by other request.
        r.get.side_effect = [None, json.dumps({"plan_tier": "racer"})]
        r.set.return_value = False  # Lock not acquired

        from web.entitlement_cache import cached_entitlements
        result = cached_entitlements(42, 1)

        assert result == {"plan_tier": "racer"}
        mock_db.assert_not_called()


# ===========================================================================
# 2. Webhook retry task
# ===========================================================================


class TestWebhookRetryTask:
    """Tests for tasks.billing_tasks._retry_failed_webhooks_impl."""

    @patch("tasks.billing_tasks.get_pg_connection")
    def test_no_failed_events_noop(self, mock_db):
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = []

        from tasks.billing_tasks import _retry_failed_webhooks_impl
        result = _retry_failed_webhooks_impl()

        assert result == {"checked": 0, "retried": 0, "deadlettered": 0}

    @patch("tasks.billing_tasks.get_pg_connection")
    def test_max_attempts_deadletters(self, mock_db):
        """Events exceeding max attempts get dead-lettered."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = [{
            "id": 1,
            "stripe_event_id": "evt_123",
            "event_type": "checkout.session.completed",
            "payload_json": "{}",
            "attempt_count": 7,  # Already at max
        }]

        from tasks.billing_tasks import _retry_failed_webhooks_impl
        result = _retry_failed_webhooks_impl()

        assert result["deadlettered"] == 1

    @patch("tasks.billing_tasks.get_pg_connection")
    def test_successful_retry_marks_processed(self, mock_db):
        """Successful retry updates status to 'processed'."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = [{
            "id": 1,
            "stripe_event_id": "evt_456",
            "event_type": "invoice.paid",
            "payload_json": json.dumps({"customer": "cus_test"}),
            "attempt_count": 1,
        }]

        with patch("web.routes.billing._handle_payment_succeeded") as mock_handler:
            from tasks.billing_tasks import _retry_failed_webhooks_impl
            result = _retry_failed_webhooks_impl()

        assert result["retried"] == 1
        mock_handler.assert_called_once()

    @patch("tasks.billing_tasks.get_pg_connection")
    def test_failed_retry_schedules_next(self, mock_db):
        """Failed retry schedules next attempt with backoff."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = [{
            "id": 1,
            "stripe_event_id": "evt_789",
            "event_type": "invoice.paid",
            "payload_json": json.dumps({"customer": "cus_test"}),
            "attempt_count": 2,
        }]

        with patch("web.routes.billing._handle_payment_succeeded", side_effect=Exception("DB error")):
            from tasks.billing_tasks import _retry_failed_webhooks_impl
            result = _retry_failed_webhooks_impl()

        assert result["retried"] == 0
        assert result["deadlettered"] == 0
        # Should have called execute to schedule next retry
        assert conn.execute.call_count > 1


# ===========================================================================
# 3. Grace period enforcement
# ===========================================================================


class TestGracePeriodEnforcement:
    """Tests for tasks.billing_tasks._enforce_grace_periods_impl."""

    @patch("tasks.billing_tasks.get_pg_connection")
    def test_canceled_past_grace_downgrades(self, mock_db):
        """Users with expired grace period get downgraded to demo."""
        conn = _mock_conn()
        mock_db.return_value = conn

        # Build per-call result mocks: the impl calls execute() multiple
        # times: (1) fetchall for canceled users, (2) fetchone for user
        # lookup inside transition_subscription, (3) execute for audit
        # inserts / updates / grace_period, (4) fetchall for past_due.
        canceled_result = MagicMock()
        canceled_result.fetchall.return_value = [
            {"id": 1, "email": "test@x.com", "plan_tier": "racer"},
        ]

        user_lookup = MagicMock()
        user_lookup.fetchone.return_value = {
            "email": "test@x.com",
            "subscription_status": "canceled",
            "plan_tier": "racer",
        }

        past_due_result = MagicMock()
        past_due_result.fetchall.return_value = []

        # Default for audit / update / commit calls
        default_result = MagicMock()
        default_result.fetchone.return_value = None
        default_result.fetchall.return_value = []

        conn.execute.side_effect = [
            canceled_result,   # SELECT canceled users (fetchall)
            user_lookup,       # SELECT user in transition_subscription (fetchone)
            default_result,    # INSERT audit_log
            default_result,    # UPDATE grace_period_end
            default_result,    # UPDATE users SET plan_tier='demo'
            past_due_result,   # SELECT past_due users (fetchall)
        ]

        with patch("auth.email._send"):
            from tasks.billing_tasks import _enforce_grace_periods_impl
            result = _enforce_grace_periods_impl()

        assert result["downgraded"] == 1

    @patch("tasks.billing_tasks.get_pg_connection")
    def test_no_expired_users_noop(self, mock_db):
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.side_effect = [[], []]

        from tasks.billing_tasks import _enforce_grace_periods_impl
        result = _enforce_grace_periods_impl()

        assert result["downgraded"] == 0
        assert result["warned"] == 0


# ===========================================================================
# 4. Webhook scheduling
# ===========================================================================


class TestScheduleWebhookRetry:
    """Tests for _schedule_webhook_retry in billing.py."""

    def test_schedules_retry_with_backoff(self):
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {"attempt_count": 2}

        from web.routes.billing import _schedule_webhook_retry
        _schedule_webhook_retry(conn, "evt_test")

        # Should have updated next_retry_at
        calls = conn.execute.call_args_list
        assert len(calls) >= 2  # SELECT + UPDATE

    def test_deadletters_at_max_attempts(self):
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {"attempt_count": 7}

        from web.routes.billing import _schedule_webhook_retry
        _schedule_webhook_retry(conn, "evt_max")

        # Should have set status to deadletter
        update_call = conn.execute.call_args_list[-1]
        assert "deadletter" in str(update_call)


# ===========================================================================
# 5. Cache invalidation by Stripe customer
# ===========================================================================


class TestCacheInvalidationByCustomer:
    @patch("web.entitlement_cache._get_redis")
    @patch("web.db_pg.get_pg_connection")
    def test_invalidates_by_customer_id(self, mock_pg, mock_redis_fn):
        """invalidate_by_stripe_customer looks up user_id and invalidates."""
        r = _mock_redis()
        mock_redis_fn.return_value = r

        conn = _mock_conn()
        mock_pg.return_value = conn
        conn.execute.return_value.fetchone.return_value = {"id": 42}

        from web.entitlement_cache import invalidate_by_stripe_customer
        invalidate_by_stripe_customer("cus_abc123")

        r.delete.assert_called_once_with("ent:42")

    @patch("web.entitlement_cache._get_redis")
    @patch("web.db_pg.get_pg_connection")
    def test_no_user_found_no_error(self, mock_pg, mock_redis_fn):
        """No crash when customer_id has no matching user."""
        r = _mock_redis()
        mock_redis_fn.return_value = r
        conn = _mock_conn()
        mock_pg.return_value = conn
        conn.execute.return_value.fetchone.return_value = None

        from web.entitlement_cache import invalidate_by_stripe_customer
        invalidate_by_stripe_customer("cus_nonexistent")

        r.delete.assert_not_called()


# ===========================================================================
# 6. Entitlement snapshot uses cache
# ===========================================================================


class TestEntitlementSnapshotCache:
    """Verify entitlement_snapshot() in middleware uses cache."""

    @patch("web.middleware.entitlements.get_user_entitlements")
    def test_snapshot_tries_cache_first(self, mock_get_ents):
        """entitlement_snapshot should call cached_entitlements, not DB."""
        import flask
        app = flask.Flask(__name__)
        app.config["USE_PG"] = True
        app.config["DEFAULT_WORKSPACE_ID"] = 1

        with app.test_request_context():
            flask.g.current_user_id = 42
            flask.g.workspace_id = 1

            cache_data = {"plan_tier": "racer", "features": ["comparison"]}
            with patch("web.entitlement_cache.cached_entitlements", return_value=cache_data) as mock_cache:
                from web.middleware.entitlements import entitlement_snapshot
                result = entitlement_snapshot()

            assert result == cache_data
            mock_cache.assert_called_once_with(42, 1)
            mock_get_ents.assert_not_called()


# ===========================================================================
# 7. Idempotency replay counter
# ===========================================================================


class TestIdempotencyReplayMetric:
    """Verify idempotency decorator increments replay counter."""

    def test_replay_increments_counter(self):
        import flask
        app = flask.Flask(__name__)

        with app.test_request_context(
            "/test",
            method="POST",
            headers={"Idempotency-Key": "key-123"},
        ):
            flask.g.workspace_id = 1

            mock_r = _mock_redis()
            # Simulate cache hit
            mock_r.get.return_value = json.dumps({"status": 200, "body": {"ok": True}})

            with patch("web.idempotency.get_redis", return_value=mock_r):
                with patch("web.metrics.incr_counter") as mock_incr:
                    from web.idempotency import idempotent

                    @idempotent
                    def dummy():
                        return flask.jsonify({"ok": True})

                    resp = dummy()

                    mock_incr.assert_called_with("idempotency_replay")
