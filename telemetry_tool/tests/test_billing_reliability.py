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
        db_data = {"plan_tier": "locked"}
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

    @patch("tasks.billing_tasks.get_maint_connection")
    def test_canceled_past_grace_downgrades(self, mock_db):
        """Users with expired grace period get locked (no active subscription)."""
        conn = _mock_conn()
        mock_db.return_value = conn

        # Build per-call result mocks: the impl calls execute() multiple
        # times: (1) fetchall for canceled users, (2) fetchone for user
        # lookup inside transition_subscription, (3) execute for audit
        # inserts / updates / grace_period, (4) UPDATE users SET plan_tier,
        # (5) fetchall for past_due users, (6) fetchall for unpaid users.
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

        unpaid_result = MagicMock()
        unpaid_result.fetchall.return_value = []

        # Default for audit / update / commit calls
        default_result = MagicMock()
        default_result.fetchone.return_value = None
        default_result.fetchall.return_value = []

        conn.execute.side_effect = [
            canceled_result,   # SELECT canceled users (fetchall)
            user_lookup,       # SELECT user in transition_subscription (fetchone)
            default_result,    # INSERT audit_log
            default_result,    # UPDATE grace_period_end / subscription_status
            default_result,    # UPDATE users SET plan_tier='locked'
            past_due_result,   # SELECT past_due users (fetchall)
            unpaid_result,     # SELECT unpaid users (fetchall)  ← new section
        ]

        with patch("auth.email._send"):
            from tasks.billing_tasks import _enforce_grace_periods_impl
            result = _enforce_grace_periods_impl()

        assert result["downgraded"] == 1

    @patch("tasks.billing_tasks.get_maint_connection")
    def test_no_expired_users_noop(self, mock_db):
        conn = _mock_conn()
        mock_db.return_value = conn
        # Three fetchall calls: canceled, past_due, unpaid — all return empty.
        conn.execute.return_value.fetchall.side_effect = [[], [], []]

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


# ===========================================================================
# 8. Grace enforcement — B5/B10/B11 regression suite
# ===========================================================================


class TestGraceEnforcementB5:
    """B5: unpaid + past_due past grace → locked/expired; active/trialing safe."""

    # ------------------------------------------------------------------
    # (a) unpaid user past grace → demoted to locked/expired +
    #     stripe_subscription_id cleared
    # ------------------------------------------------------------------
    @patch("tasks.billing_tasks.get_maint_connection")
    def test_unpaid_user_demoted_to_expired(self, mock_db):
        """Unpaid user is immediately demoted to expired/locked; Stripe ID cleared."""
        conn = _mock_conn()
        mock_db.return_value = conn

        no_canceled = MagicMock(); no_canceled.fetchall.return_value = []
        no_past_due = MagicMock(); no_past_due.fetchall.return_value = []
        unpaid_list = MagicMock()
        unpaid_list.fetchall.return_value = [
            {"id": 7, "email": "unpaid@x.com", "plan_tier": "world-class"},
        ]
        user_lookup = MagicMock()
        user_lookup.fetchone.return_value = {
            "email": "unpaid@x.com",
            "subscription_status": "unpaid",
            "plan_tier": "world-class",
        }
        default = MagicMock()
        default.fetchone.return_value = None
        default.fetchall.return_value = []

        conn.execute.side_effect = [
            no_canceled,   # canceled SELECT
            no_past_due,   # past_due SELECT
            unpaid_list,   # unpaid SELECT
            user_lookup,   # transition_subscription: SELECT user
            default,       # transition_subscription: UPDATE status
            default,       # transition_subscription: INSERT audit_log
            default,       # UPDATE plan_tier + stripe_subscription_id
        ]

        with patch("auth.email._send"):
            from tasks.billing_tasks import _enforce_grace_periods_impl
            result = _enforce_grace_periods_impl()

        assert result["downgraded"] == 1, f"Expected 1 downgrade, got {result}"

        # Confirm stripe_subscription_id = NULL is part of the clearing UPDATE
        update_calls = [
            str(call) for call in conn.execute.call_args_list
            if "stripe_subscription_id" in str(call)
        ]
        assert update_calls, "Expected an UPDATE that clears stripe_subscription_id"

    # ------------------------------------------------------------------
    # (b) past_due user past their 7-day grace → demoted
    # ------------------------------------------------------------------
    @patch("tasks.billing_tasks.get_maint_connection")
    def test_past_due_past_grace_demoted(self, mock_db):
        """past_due user whose grace_period_end has passed is locked."""
        from datetime import datetime, timedelta, timezone

        conn = _mock_conn()
        mock_db.return_value = conn

        expired_grace = datetime.now(timezone.utc) - timedelta(days=1)

        no_canceled = MagicMock(); no_canceled.fetchall.return_value = []
        past_due_list = MagicMock()
        past_due_list.fetchall.return_value = [
            {
                "id": 5,
                "email": "pastdue@x.com",
                "plan_tier": "world-class",
                "grace_period_end": expired_grace,
            },
        ]
        no_unpaid = MagicMock(); no_unpaid.fetchall.return_value = []
        user_lookup = MagicMock()
        user_lookup.fetchone.return_value = {
            "email": "pastdue@x.com",
            "subscription_status": "past_due",
            "plan_tier": "world-class",
        }
        default = MagicMock()
        default.fetchone.return_value = None
        default.fetchall.return_value = []

        conn.execute.side_effect = [
            no_canceled,
            past_due_list,
            user_lookup,   # transition_subscription: SELECT user
            default,       # transition_subscription: UPDATE status
            default,       # transition_subscription: INSERT audit_log
            default,       # UPDATE plan_tier + stripe_subscription_id
            no_unpaid,
        ]

        with patch("auth.email._send"):
            from tasks.billing_tasks import _enforce_grace_periods_impl
            result = _enforce_grace_periods_impl()

        assert result["downgraded"] == 1, f"Expected 1 downgrade, got {result}"

    # ------------------------------------------------------------------
    # (c) active / trialing user → NOT demoted
    # ------------------------------------------------------------------
    @patch("tasks.billing_tasks.get_maint_connection")
    def test_active_trialing_users_never_demoted(self, mock_db):
        """Active and trialing users are not touched by the grace task."""
        conn = _mock_conn()
        mock_db.return_value = conn

        # All three SELECTs return empty — the task only queries for
        # canceled/past_due/unpaid, so active/trialing are never matched.
        conn.execute.return_value.fetchall.side_effect = [[], [], []]

        from tasks.billing_tasks import _enforce_grace_periods_impl
        result = _enforce_grace_periods_impl()

        assert result["downgraded"] == 0
        assert result["warned"] == 0

    # ------------------------------------------------------------------
    # (d) canceled within 7-day grace → still has access (no downgrade);
    #     past 7 days → locked
    # ------------------------------------------------------------------
    @patch("tasks.billing_tasks.get_maint_connection")
    def test_canceled_within_grace_not_demoted(self, mock_db):
        """canceled user still within 7-day grace window is NOT downgraded."""
        conn = _mock_conn()
        mock_db.return_value = conn

        # The SQL WHERE clause filters by grace_period_end < now, so a user
        # whose grace_period_end is in the future won't appear in the result.
        # Simulate this by returning an empty canceled list.
        no_canceled = MagicMock(); no_canceled.fetchall.return_value = []
        no_past_due = MagicMock(); no_past_due.fetchall.return_value = []
        no_unpaid = MagicMock(); no_unpaid.fetchall.return_value = []

        conn.execute.side_effect = [no_canceled, no_past_due, no_unpaid]

        from tasks.billing_tasks import _enforce_grace_periods_impl
        result = _enforce_grace_periods_impl()

        assert result["downgraded"] == 0

    @patch("tasks.billing_tasks.get_maint_connection")
    def test_canceled_past_7_day_grace_locked(self, mock_db):
        """canceled user past 7-day grace is locked/expired."""
        conn = _mock_conn()
        mock_db.return_value = conn

        canceled_list = MagicMock()
        canceled_list.fetchall.return_value = [
            {"id": 3, "email": "gone@x.com", "plan_tier": "world-class"},
        ]
        no_past_due = MagicMock(); no_past_due.fetchall.return_value = []
        no_unpaid = MagicMock(); no_unpaid.fetchall.return_value = []
        user_lookup = MagicMock()
        user_lookup.fetchone.return_value = {
            "email": "gone@x.com",
            "subscription_status": "canceled",
            "plan_tier": "world-class",
        }
        default = MagicMock()
        default.fetchone.return_value = None
        default.fetchall.return_value = []

        conn.execute.side_effect = [
            canceled_list,
            user_lookup,
            default,  # UPDATE status
            default,  # INSERT audit_log
            default,  # UPDATE plan_tier
            no_past_due,
            no_unpaid,
        ]

        with patch("auth.email._send"):
            from tasks.billing_tasks import _enforce_grace_periods_impl
            result = _enforce_grace_periods_impl()

        assert result["downgraded"] == 1


# ===========================================================================
# 9. State machine — B5 terminal transitions
# ===========================================================================


class TestStateMachineTerminalTransitions:
    """(e) State machine allows unpaid→expired and past_due→expired."""

    def test_unpaid_to_expired_allowed(self):
        from billing.state_machine import validate_transition
        assert validate_transition("unpaid", "expired") is True, (
            "unpaid→expired must be allowed (B5 fix)"
        )

    def test_past_due_to_expired_allowed(self):
        from billing.state_machine import validate_transition
        assert validate_transition("past_due", "expired") is True, (
            "past_due→expired must be allowed (B5 fix)"
        )

    def test_active_to_expired_still_rejected(self):
        """active→expired must remain invalid (safety: no direct lock of paying users)."""
        from billing.state_machine import validate_transition
        assert validate_transition("active", "expired") is False

    def test_trialing_to_expired_still_rejected(self):
        """trialing→expired must remain invalid."""
        from billing.state_machine import validate_transition
        assert validate_transition("trialing", "expired") is False

    def test_grace_period_days_constant_is_7(self):
        """GRACE_PERIOD_DAYS constant is 7 (B10/B11 standardization)."""
        from billing.state_machine import GRACE_PERIOD_DAYS
        assert GRACE_PERIOD_DAYS == 7

    def test_canceled_grace_days_is_7(self):
        """canceled state uses 7-day grace (B10 — was 30)."""
        from billing.state_machine import SUBSCRIPTION_STATES
        assert SUBSCRIPTION_STATES["canceled"]["grace_days"] == 7

    def test_past_due_grace_days_is_7(self):
        """past_due state uses 7-day grace (B11 — was 14 effective)."""
        from billing.state_machine import SUBSCRIPTION_STATES
        assert SUBSCRIPTION_STATES["past_due"]["grace_days"] == 7
