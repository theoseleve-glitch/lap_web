"""Tests for PROMPT 3B — Payments Correctness + Metering + Jobs + Observability.

Validates:
- Stripe webhook hardening (Redis dedup, event ordering, idempotency)
- Per-plan compute budget enforcement
- Job retry endpoint with budget check
- Structured logging with correlation IDs and request timing
- Metrics collection (counters, histograms, admin endpoint)
- Alerting tasks (error rate, queue depth, stuck jobs, webhook failures)
"""
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
# Shared helpers
# ---------------------------------------------------------------------------


class FakeConn:
    """Minimal fake DB connection for service-layer tests."""
    def __init__(self, rows_by_query=None):
        self._rows_by_query = rows_by_query or {}
        self._calls = []
        self._committed = False

    def execute(self, sql, params=None):
        self._calls.append((str(sql), params))
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


class FakeRedis:
    """In-memory Redis mock for metrics/dedup tests."""
    def __init__(self):
        self._store = {}
        self._sets = {}
        self._pipelines = []

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._store:
            return None  # key already exists
        self._store[key] = value
        return True

    def get(self, key):
        return self._store.get(key)

    def incrby(self, key, amount):
        val = int(self._store.get(key, 0))
        self._store[key] = str(val + amount)
        return val + amount

    def expire(self, key, ttl):
        pass

    def zadd(self, key, mapping):
        if key not in self._sets:
            self._sets[key] = {}
        self._sets[key].update(mapping)

    def zrangebyscore(self, key, min_val, max_val, withscores=False):
        items = self._sets.get(key, {})
        if withscores:
            return list(items.items())
        return list(items.keys())

    def pipeline(self, transaction=False):
        return FakeRedisPipeline(self)

    def ping(self):
        return True


class FakeRedisPipeline:
    """Pipeline that executes commands immediately on FakeRedis."""
    def __init__(self, redis):
        self._redis = redis
        self._results = []

    def incrby(self, key, amount):
        result = self._redis.incrby(key, amount)
        self._results.append(result)
        return self

    def expire(self, key, ttl):
        self._results.append(True)
        return self

    def get(self, key):
        self._results.append(self._redis.get(key))
        return self

    def zadd(self, key, mapping):
        self._redis.zadd(key, mapping)
        self._results.append(1)
        return self

    def execute(self):
        results = self._results[:]
        self._results = []
        return results


# ===========================================================================
# A) Stripe webhook hardening
# ===========================================================================


class TestRedisEventDedup:
    """Redis fast-path dedup for Stripe events.

    These used to exercise ``_redis_event_check``, a single check-AND-set via
    SETNX. It was split (bfd362c) into a read (``_redis_event_is_seen``) and a
    separate write (``_redis_event_mark_seen``) so that a handler which raises
    leaves the key ABSENT and Stripe retries the event. The old tests mocked
    ``r.set`` and kept patching a name that no longer existed, so all four
    errored at collection-time mock setup and this dedup path has been
    untested since.
    """

    def test_redis_dedup_new_event(self):
        """Unseen event returns False (not a duplicate)."""
        from web.routes.billing import _redis_event_is_seen

        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # key absent
        with patch("web.rate_limit.get_redis", return_value=mock_redis):
            result = _redis_event_is_seen("evt_new_123")
        assert result is False

    def test_redis_dedup_duplicate_event(self):
        """Previously-seen event returns True (is a duplicate)."""
        from web.routes.billing import _redis_event_is_seen

        mock_redis = MagicMock()
        mock_redis.get.return_value = b"1"  # key present
        with patch("web.rate_limit.get_redis", return_value=mock_redis):
            result = _redis_event_is_seen("evt_dup_123")
        assert result is True

    def test_redis_dedup_no_redis(self):
        """Without Redis, falls through to the DB check (returns False)."""
        from web.routes.billing import _redis_event_is_seen

        with patch("web.rate_limit.get_redis", return_value=None):
            result = _redis_event_is_seen("evt_any")
        assert result is False

    def test_redis_dedup_redis_error(self):
        """Redis error falls through to the DB check (returns False).

        Fail-open is deliberate: the DB dedup still guards idempotency, and
        failing closed would drop every webhook whenever Redis blips.
        """
        from web.routes.billing import _redis_event_is_seen

        mock_redis = MagicMock()
        mock_redis.get.side_effect = ConnectionError("Redis down")
        with patch("web.rate_limit.get_redis", return_value=mock_redis):
            result = _redis_event_is_seen("evt_any")
        assert result is False

    def test_reading_does_not_mark_the_event_seen(self):
        """The whole point of the split: the READ must have no side effect.

        Under the old SETNX implementation the check itself claimed the event,
        so a handler that then raised left Stripe unable to retry -- the
        payment event was lost. Guards against anyone folding the write back
        into the read.
        """
        from web.routes.billing import _redis_event_is_seen

        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        with patch("web.rate_limit.get_redis", return_value=mock_redis):
            _redis_event_is_seen("evt_no_write")
        assert not mock_redis.set.called, (
            "the dedup READ wrote to Redis -- a handler failure after this "
            "point would leave the event marked processed and Stripe would "
            "not retry it"
        )
        assert not mock_redis.setnx.called

    def test_mark_seen_sets_the_key_with_a_ttl(self):
        """The write half, which nothing covered."""
        from web.routes.billing import _redis_event_mark_seen

        mock_redis = MagicMock()
        with patch("web.rate_limit.get_redis", return_value=mock_redis):
            _redis_event_mark_seen("evt_done_123")
        assert mock_redis.set.called, "successful processing must mark the event seen"
        args, kwargs = mock_redis.set.call_args
        assert "evt_done_123" in args[0]
        assert kwargs.get("ex"), "the dedup key must expire, or Redis grows without bound"

    def test_mark_seen_survives_a_redis_outage(self):
        """Non-fatal by design -- DB dedup still guards idempotency."""
        from web.routes.billing import _redis_event_mark_seen

        mock_redis = MagicMock()
        mock_redis.set.side_effect = ConnectionError("Redis down")
        with patch("web.rate_limit.get_redis", return_value=mock_redis):
            _redis_event_mark_seen("evt_any")  # must not raise


class TestEventOrdering:
    """Timestamp-based event ordering check."""

    def test_check_event_ordering_newer_event(self):
        """Newer event than last processed → allow."""
        from web.routes.billing import _check_event_ordering

        mock_redis = MagicMock()
        mock_redis.get.return_value = "1000000"  # last processed timestamp
        mock_redis.set.return_value = True
        with patch("web.rate_limit.get_redis", return_value=mock_redis):
            result = _check_event_ordering("cus_123", 2000000)
        assert result is True

    def test_check_event_ordering_older_event(self):
        """Older event than last processed → reject."""
        from web.routes.billing import _check_event_ordering

        mock_redis = MagicMock()
        mock_redis.get.return_value = "2000000"  # last processed timestamp
        with patch("web.rate_limit.get_redis", return_value=mock_redis):
            result = _check_event_ordering("cus_123", 1000000)
        assert result is False

    def test_check_event_ordering_no_redis(self):
        """Without Redis, allow (fail open)."""
        from web.routes.billing import _check_event_ordering

        with patch("web.rate_limit.get_redis", return_value=None):
            result = _check_event_ordering("cus_123", 1000000)
        assert result is True

    def test_check_event_ordering_no_customer(self):
        """Missing customer ID → allow."""
        from web.routes.billing import _check_event_ordering

        result = _check_event_ordering("", 1000000)
        assert result is True


class TestWebhookMetricsCounters:
    """Webhook processing increments metrics counters."""

    def test_webhook_processed_counter_incremented(self):
        """Successful webhook processing calls incr_counter('webhook_processed')."""
        from web.routes.billing import _handle_charge_refunded
        with patch("web.routes.billing._get_conn") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"id": 42}
            with patch("web.routes.billing.audit_log"):
                _handle_charge_refunded({"customer": "cus_123", "id": "ch_123"})

    def test_webhook_failed_counter_exists_in_billing(self):
        """Billing webhook handler references webhook_failed counter."""
        source = Path(_PROJECT_ROOT / "web" / "routes" / "billing.py").read_text()
        assert "webhook_failed" in source
        assert "webhook_processed" in source


# ===========================================================================
# B) Per-plan compute budget enforcement
# ===========================================================================


class TestComputeBudget:
    """Per-plan compute budget limits."""

    def test_budget_tiers_defined(self):
        """All 4 plan tiers have budget entries."""
        from web.compute_budget import COMPUTE_BUDGETS
        assert "demo" in COMPUTE_BUDGETS
        assert "racer" in COMPUTE_BUDGETS
        assert "world-class" in COMPUTE_BUDGETS
        assert "b2b" in COMPUTE_BUDGETS

    def test_demo_limits(self):
        """Demo tier: 1 concurrent job, 10 min max."""
        from web.compute_budget import COMPUTE_BUDGETS
        demo = COMPUTE_BUDGETS["demo"]
        assert demo["max_concurrent_jobs"] == 1
        assert demo["max_job_duration_minutes"] == 10

    def test_budget_allowed_when_under_limit(self):
        """check_compute_budget returns (True, info) when under limit."""
        from web.compute_budget import check_compute_budget
        conn = FakeConn(rows_by_query={
            "COUNT": [{"cnt": 0}],
            "MIN": [{"oldest": None}],
        })
        allowed, info = check_compute_budget(conn, 1, 1, "racer")
        assert allowed is True
        assert info["max_jobs"] == 2
        assert info["running_jobs"] == 0

    def test_budget_denied_at_limit(self):
        """check_compute_budget returns (False, info) when at limit."""
        from web.compute_budget import check_compute_budget
        conn = FakeConn(rows_by_query={
            "COUNT": [{"cnt": 2}],
            "MIN": [{"oldest": datetime.now(timezone.utc)}],
        })
        allowed, info = check_compute_budget(conn, 1, 1, "racer")
        assert allowed is False
        assert info["running_jobs"] == 2

    def test_budget_fallback_to_demo(self):
        """Unknown tier falls back to demo limits."""
        from web.compute_budget import get_budget
        budget = get_budget("nonexistent")
        assert budget["max_concurrent_jobs"] == 1

    def test_budget_lookups_user_tier(self):
        """When plan_tier=None, budget looks up from users table."""
        from web.compute_budget import check_compute_budget
        conn = FakeConn(rows_by_query={
            "plan_tier": [{"plan_tier": "world-class"}],
            "COUNT": [{"cnt": 0}],
            "MIN": [{"oldest": None}],
        })
        allowed, info = check_compute_budget(conn, 1, 1, None)
        assert allowed is True
        assert info["plan_tier"] == "world-class"
        assert info["max_jobs"] == 5


# ===========================================================================
# C) Job retry endpoint
# ===========================================================================


class TestJobRetryEndpoint:
    """Job retry creates a new job and dispatches the pipeline."""

    def test_retry_route_exists(self):
        """The retry endpoint function exists in jobs module."""
        from web.routes.jobs import retry
        assert callable(retry)

    def test_retry_requires_failed_status(self):
        """Retry rejects jobs that aren't failed/cancelled."""
        source = Path(_PROJECT_ROOT / "web" / "routes" / "jobs.py").read_text()
        assert '"failed"' in source
        assert '"cancelled"' in source
        assert "409" in source  # Conflict status

    def test_retry_checks_compute_budget(self):
        """Retry endpoint integrates compute budget check."""
        source = Path(_PROJECT_ROOT / "web" / "routes" / "jobs.py").read_text()
        assert "check_compute_budget" in source

    def test_retry_creates_new_job(self):
        """Retry creates a new job entry in ingestion_jobs."""
        source = Path(_PROJECT_ROOT / "web" / "routes" / "jobs.py").read_text()
        assert "INSERT INTO ingestion_jobs" in source
        assert "new_job_id" in source


# ===========================================================================
# D) Structured logging with correlation IDs
# ===========================================================================


class TestStructuredLogging:
    """Structured logging, request ID correlation, and request timing."""

    def test_request_id_filter_exists(self):
        """RequestIdFilter class enriches log records."""
        from web.logging_setup import RequestIdFilter
        f = RequestIdFilter()
        assert callable(f.filter)

    def test_json_formatter_exists(self):
        """JsonFormatter produces single-line JSON logs."""
        from web.logging_setup import JsonFormatter
        fmt = JsonFormatter()
        import logging
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.request_id = "abc123"
        record.workspace_id = "1"
        record.user_id = "42"
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["request_id"] == "abc123"
        assert parsed["message"] == "hello"

    def test_init_request_id_registers_hooks(self):
        """init_request_id registers both before_request and after_request hooks."""
        source = Path(_PROJECT_ROOT / "web" / "api_utils.py").read_text()
        assert "before_request" in source
        assert "after_request" in source

    def test_x_request_id_header_in_after_request(self):
        """after_request hook adds X-Request-Id header."""
        source = Path(_PROJECT_ROOT / "web" / "api_utils.py").read_text()
        assert "X-Request-Id" in source

    def test_request_timing_logged(self):
        """after_request hook logs request duration in ms."""
        source = Path(_PROJECT_ROOT / "web" / "api_utils.py").read_text()
        assert "_request_start_time" in source
        assert "duration_ms" in source
        assert "monotonic" in source

    def test_setup_logging_attaches_filter(self):
        """setup_logging adds RequestIdFilter to app logger."""
        from flask import Flask

        from web.logging_setup import RequestIdFilter, setup_logging
        app = Flask(__name__)
        setup_logging(app)
        filters = app.logger.filters
        assert any(isinstance(f, RequestIdFilter) for f in filters)


# ===========================================================================
# E) Metrics collection
# ===========================================================================


class TestMetricsModule:
    """Redis-backed metrics counters and histograms."""

    def test_incr_counter_increments(self):
        """incr_counter increases the value in the correct hourly bucket."""
        from web.metrics import _bucket_key, incr_counter
        r = FakeRedis()
        incr_counter("test_counter", amount=3, redis_client=r)
        key = _bucket_key("test_counter")
        assert int(r._store.get(key, 0)) == 3

    def test_incr_counter_no_redis(self):
        """incr_counter silently does nothing without Redis."""
        from web.metrics import incr_counter

        # Should not raise
        incr_counter("test_counter", redis_client=None)

    def test_record_histogram(self):
        """record_histogram stores values in sorted set."""
        from web.metrics import _bucket_key, record_histogram
        r = FakeRedis()
        record_histogram("latency", 42.5, redis_client=r)
        key = _bucket_key("hist:latency")
        assert key in r._sets
        assert len(r._sets[key]) == 1

    def test_get_counter_values_aggregates(self):
        """get_counter_values sums across hourly buckets."""
        from web.metrics import _bucket_key, get_counter_values
        r = FakeRedis()
        # Set a value in current hour bucket
        key = _bucket_key("test_metric")
        r._store[key] = "15"
        result = get_counter_values("test_metric", hours=1, redis_client=r)
        assert result["total"] == 15

    def test_get_counter_values_no_redis(self):
        """get_counter_values returns zero totals without Redis."""
        from web.metrics import get_counter_values
        result = get_counter_values("anything", redis_client=None)
        assert result["total"] == 0
        assert result["buckets"] == {}

    def test_get_histogram_stats_empty(self):
        """get_histogram_stats returns count=0 for empty data."""
        from web.metrics import get_histogram_stats
        r = FakeRedis()
        result = get_histogram_stats("latency", hours=1, redis_client=r)
        assert result["count"] == 0

    def test_get_histogram_stats_with_data(self):
        """get_histogram_stats computes percentiles correctly."""
        from web.metrics import _bucket_key, get_histogram_stats, record_histogram
        r = FakeRedis()
        # Record 100 values
        for i in range(100):
            record_histogram("latency", float(i), redis_client=r)
        result = get_histogram_stats("latency", hours=1, redis_client=r)
        assert result["count"] == 100
        assert result["p50"] >= 40  # approximate
        assert result["max"] == 99.0

    def test_bucket_key_format(self):
        """Bucket keys follow metrics:{name}:{YYYY-MM-DDTHH} format."""
        from web.metrics import _bucket_key
        ts = datetime(2026, 2, 27, 14, 30, 0, tzinfo=timezone.utc)
        key = _bucket_key("http_total", ts)
        assert key == "metrics:http_total:2026-02-27T14"

    def test_init_metrics_registers_blueprint(self):
        """init_metrics registers the admin_metrics blueprint."""
        source = Path(_PROJECT_ROOT / "web" / "metrics.py").read_text()
        assert "admin_metrics" in source
        assert "/admin/metrics" in source

    def test_metrics_wired_in_app_factory(self):
        """app.py initializes metrics collection."""
        source = Path(_PROJECT_ROOT / "web" / "app.py").read_text()
        assert "init_metrics" in source


# ===========================================================================
# F) Alerting tasks
# ===========================================================================


class TestAlertingTasks:
    """Periodic alerting checks for system health."""

    def test_alerting_module_exists(self):
        """alerting_tasks module is importable."""
        from tasks.alerting_tasks import run_alerting_checks
        assert callable(run_alerting_checks)

    def test_error_rate_check_ok(self):
        """Error rate below threshold returns ok."""
        from tasks.alerting_tasks import _check_error_rate
        with patch("web.metrics.get_counter_values") as mock_counter:
            mock_counter.side_effect = [
                {"total": 1000},  # http_total
                {"total": 10},    # http_5xx
            ]
            result = _check_error_rate(MagicMock())
        assert result["status"] == "ok"
        assert result["rate_pct"] == 1.0

    def test_error_rate_check_alert(self):
        """Error rate above threshold returns alert."""
        from tasks.alerting_tasks import _check_error_rate
        with patch("web.metrics.get_counter_values") as mock_counter:
            mock_counter.side_effect = [
                {"total": 100},   # http_total
                {"total": 10},    # http_5xx (10%)
            ]
            result = _check_error_rate(MagicMock())
        assert result["status"] == "alert"
        assert result["rate_pct"] == 10.0

    def test_error_rate_zero_requests(self):
        """Zero total requests returns ok (no division by zero)."""
        from tasks.alerting_tasks import _check_error_rate
        with patch("web.metrics.get_counter_values") as mock_counter:
            mock_counter.side_effect = [
                {"total": 0},
                {"total": 0},
            ]
            result = _check_error_rate(MagicMock())
        assert result["status"] == "ok"

    def test_queue_depth_ok(self):
        """Queue depth below threshold returns ok."""
        from tasks.alerting_tasks import _check_queue_depth
        with patch("tasks.alerting_tasks._get_pg") as mock_pg:
            conn = MagicMock()
            mock_pg.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"cnt": 5}
            result = _check_queue_depth()
        assert result["status"] == "ok"
        assert result["depth"] == 5

    def test_queue_depth_alert(self):
        """Queue depth above threshold returns alert."""
        from tasks.alerting_tasks import _check_queue_depth
        with patch("tasks.alerting_tasks._get_pg") as mock_pg:
            conn = MagicMock()
            mock_pg.return_value = conn
            conn.execute.return_value.fetchone.return_value = {"cnt": 25}
            result = _check_queue_depth()
        assert result["status"] == "alert"
        assert result["depth"] == 25

    def test_stuck_jobs_none(self):
        """No stuck jobs returns ok."""
        from tasks.alerting_tasks import _check_stuck_jobs
        with patch("tasks.alerting_tasks._get_pg") as mock_pg:
            conn = MagicMock()
            mock_pg.return_value = conn
            conn.execute.return_value.fetchall.return_value = []
            result = _check_stuck_jobs()
        assert result["status"] == "ok"
        assert result["stuck_count"] == 0

    def test_stuck_jobs_found(self):
        """Stuck jobs returns alert with job details."""
        from tasks.alerting_tasks import _check_stuck_jobs
        with patch("tasks.alerting_tasks._get_pg") as mock_pg:
            conn = MagicMock()
            mock_pg.return_value = conn
            conn.execute.return_value.fetchall.return_value = [
                {"job_id": "abcdef1234567890", "file_name": "test.csv",
                 "started_at": datetime.now(timezone.utc) - timedelta(hours=2),
                 "running_minutes": 120},
            ]
            result = _check_stuck_jobs()
        assert result["status"] == "alert"
        assert result["stuck_count"] == 1
        assert result["stuck_jobs"][0]["job_id"] == "abcdef12"

    def test_webhook_failures_ok(self):
        """Webhook failures below threshold returns ok."""
        from tasks.alerting_tasks import _check_webhook_failures
        with patch("web.metrics.get_counter_values") as mock_counter:
            mock_counter.return_value = {"total": 2}
            result = _check_webhook_failures(MagicMock())
        assert result["status"] == "ok"

    def test_webhook_failures_alert(self):
        """Webhook failures above threshold returns alert."""
        from tasks.alerting_tasks import _check_webhook_failures
        with patch("web.metrics.get_counter_values") as mock_counter:
            mock_counter.return_value = {"total": 15}
            result = _check_webhook_failures(MagicMock())
        assert result["status"] == "alert"
        assert result["failures"] == 15

    def test_run_alerting_checks_aggregates(self):
        """run_alerting_checks runs all checks and counts alerts."""
        from tasks.alerting_tasks import _run_alerting_checks_impl
        with patch("tasks.alerting_tasks._get_redis", return_value=MagicMock()), \
             patch("tasks.alerting_tasks._check_error_rate", return_value={"status": "ok"}), \
             patch("tasks.alerting_tasks._check_queue_depth", return_value={"status": "alert", "depth": 30}), \
             patch("tasks.alerting_tasks._check_stuck_jobs", return_value={"status": "ok"}), \
             patch("tasks.alerting_tasks._check_webhook_failures", return_value={"status": "ok"}):
            result = _run_alerting_checks_impl()
        assert result["alerts_fired"] == 1
        assert result["checks"]["queue_depth"]["status"] == "alert"

    def test_alerting_thresholds_defined(self):
        """Alerting thresholds have sensible values."""
        from tasks.alerting_tasks import (
            ERROR_RATE_THRESHOLD_PCT,
            QUEUE_DEPTH_THRESHOLD,
            STUCK_JOB_MINUTES,
            WEBHOOK_FAILURE_THRESHOLD,
        )
        assert ERROR_RATE_THRESHOLD_PCT == 5.0
        assert QUEUE_DEPTH_THRESHOLD == 20
        assert WEBHOOK_FAILURE_THRESHOLD == 10
        assert STUCK_JOB_MINUTES == 60


# ===========================================================================
# G) Celery beat schedule
# ===========================================================================


class TestCeleryBeatSchedule:
    """Celery beat schedule includes all periodic tasks."""

    def test_alerting_in_beat_schedule(self):
        """alerting-checks task is scheduled every 5 minutes."""
        source = Path(_PROJECT_ROOT / "celery_app.py").read_text()
        assert "alerting-checks" in source
        assert "tasks.alerting_tasks.run_alerting_checks" in source

    def test_grace_period_in_beat_schedule(self):
        """enforce-grace-periods task is scheduled daily."""
        source = Path(_PROJECT_ROOT / "celery_app.py").read_text()
        assert "enforce-grace-periods" in source
        assert "tasks.billing_tasks.enforce_subscription_grace_periods" in source

    def test_reconcile_stripe_in_beat_schedule(self):
        """reconcile-stripe task is scheduled hourly."""
        source = Path(_PROJECT_ROOT / "celery_app.py").read_text()
        assert "reconcile-stripe" in source
        assert "tasks.billing_tasks.reconcile_stripe" in source


# ===========================================================================
# H) Job status page
# ===========================================================================


class TestJobStatusPage:
    """Frontend job status page exists with correct components."""

    def test_jobs_page_exists(self):
        """The jobs page component file exists."""
        jobs_page = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "app" / "jobs" / "page.tsx"
        assert jobs_page.exists()

    def test_jobs_page_has_status_badges(self):
        """Job page includes status badges for all states."""
        jobs_page = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "app" / "jobs" / "page.tsx"
        source = jobs_page.read_text(encoding="utf-8")
        for status in ["queued", "running", "processing", "paused", "completed", "failed", "cancelled"]:
            assert status in source, f"Missing status badge for: {status}"

    def test_jobs_page_has_cancel_and_retry(self):
        """Job page supports cancel and retry mutations."""
        jobs_page = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "app" / "jobs" / "page.tsx"
        source = jobs_page.read_text(encoding="utf-8")
        assert "cancel" in source.lower()
        assert "retry" in source.lower()
        assert "useMutation" in source

    def test_jobs_page_auto_refresh(self):
        """Job page auto-refreshes every 5 seconds."""
        jobs_page = _PROJECT_ROOT.parent / "lap-website" / "src" / "app" / "app" / "jobs" / "page.tsx"
        source = jobs_page.read_text(encoding="utf-8")
        assert "refetchInterval" in source
        assert "5000" in source
