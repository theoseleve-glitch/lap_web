"""Alerting Celery tasks: error rate, queue depth, webhook failure checks.

Runs every 5 minutes via Celery Beat. Checks system health metrics and
logs warnings/errors that can be picked up by log-based alerting
(e.g., CloudWatch, Datadog, or a simple grep on structured JSON logs).

All checks fail open — alerting failures never affect production.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Outbound notification webhook (Slack, Discord, generic HTTP POST).
# Set ALERT_WEBHOOK_URL to enable. Payload follows Slack's format:
#   {"text": "ALERT: ...", "blocks": [...]}
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")

# ---------------------------------------------------------------------------
# Celery app import (graceful fallback for testing)
# ---------------------------------------------------------------------------

_USE_CELERY = False
try:
    from celery_app import celery as _celery_app
    _USE_CELERY = True
except Exception:
    _celery_app = None

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Error rate: fire if >5% of requests in the last hour returned 5xx
ERROR_RATE_THRESHOLD_PCT = 5.0

# Queue depth: fire if >20 jobs are queued/running
QUEUE_DEPTH_THRESHOLD = 20

# Webhook failures: fire if >10 webhook processing failures in the last hour
WEBHOOK_FAILURE_THRESHOLD = 10

# Stuck jobs: fire if any job has been running for >60 minutes
STUCK_JOB_MINUTES = 60


# ---------------------------------------------------------------------------
# PG + Redis helpers
# ---------------------------------------------------------------------------


def _get_redis():
    """Get a Redis client from config."""
    try:
        import redis
        from web.config import Config
        return redis.Redis.from_url(Config.REDIS_URL, socket_timeout=2, decode_responses=True)
    except Exception:
        return None


def _get_pg():
    """Get a PostgreSQL connection."""
    from web.db_pg import get_pg_connection
    return get_pg_connection()


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_error_rate(r) -> dict[str, Any]:
    """Check if the 5xx error rate exceeds the threshold."""
    try:
        from web.metrics import get_counter_values
        total = get_counter_values("http_total", hours=1, redis_client=r)
        errors = get_counter_values("http_5xx", hours=1, redis_client=r)

        total_count = total["total"]
        error_count = errors["total"]

        if total_count == 0:
            return {"status": "ok", "total": 0, "errors": 0, "rate_pct": 0}

        rate = (error_count / total_count) * 100
        status = "alert" if rate > ERROR_RATE_THRESHOLD_PCT else "ok"

        if status == "alert":
            logger.error(
                "ALERT: High 5xx error rate: %.1f%% (%d/%d requests in last hour)",
                rate, error_count, total_count,
            )

        return {
            "status": status,
            "total": total_count,
            "errors": error_count,
            "rate_pct": round(rate, 2),
            "threshold_pct": ERROR_RATE_THRESHOLD_PCT,
        }
    except Exception:
        logger.warning("Error rate check failed", exc_info=True)
        return {"status": "error", "message": "check failed"}


def _check_queue_depth() -> dict[str, Any]:
    """Check if the job queue is deeper than the threshold."""
    try:
        conn = _get_pg()
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM ingestion_jobs "
            "WHERE status IN ('queued', 'running', 'processing')"
        ).fetchone()
        depth = (dict(row) if row and not isinstance(row, dict) else (row or {})).get("cnt", 0)
        status = "alert" if depth > QUEUE_DEPTH_THRESHOLD else "ok"

        if status == "alert":
            logger.error(
                "ALERT: Job queue depth %d exceeds threshold %d",
                depth, QUEUE_DEPTH_THRESHOLD,
            )

        return {
            "status": status,
            "depth": depth,
            "threshold": QUEUE_DEPTH_THRESHOLD,
        }
    except Exception:
        logger.warning("Queue depth check failed", exc_info=True)
        return {"status": "error", "message": "check failed"}


def _check_stuck_jobs() -> dict[str, Any]:
    """Check for jobs that have been running longer than the threshold."""
    try:
        conn = _get_pg()
        rows = conn.execute(
            "SELECT job_id, file_name, started_at, "
            "EXTRACT(EPOCH FROM (NOW() - started_at))/60 AS running_minutes "
            "FROM ingestion_jobs "
            "WHERE status IN ('running', 'processing') "
            "AND started_at < NOW() - INTERVAL '%(mins)s minutes'" % {"mins": STUCK_JOB_MINUTES}
        ).fetchall()
        stuck = [dict(r) if not isinstance(r, dict) else r for r in rows]

        if stuck:
            logger.error(
                "ALERT: %d stuck job(s) running > %d minutes: %s",
                len(stuck),
                STUCK_JOB_MINUTES,
                [j["job_id"][:8] for j in stuck],
            )

        return {
            "status": "alert" if stuck else "ok",
            "stuck_count": len(stuck),
            "threshold_minutes": STUCK_JOB_MINUTES,
            "stuck_jobs": [
                {"job_id": j["job_id"][:8], "minutes": round(j.get("running_minutes", 0))}
                for j in stuck[:5]
            ],
        }
    except Exception:
        logger.warning("Stuck jobs check failed", exc_info=True)
        return {"status": "error", "message": "check failed"}


def _check_webhook_failures(r) -> dict[str, Any]:
    """Check if webhook processing failures exceed the threshold."""
    try:
        from web.metrics import get_counter_values
        failures = get_counter_values("webhook_failed", hours=1, redis_client=r)
        count = failures["total"]
        status = "alert" if count > WEBHOOK_FAILURE_THRESHOLD else "ok"

        if status == "alert":
            logger.error(
                "ALERT: %d webhook failures in last hour (threshold: %d)",
                count, WEBHOOK_FAILURE_THRESHOLD,
            )

        return {
            "status": status,
            "failures": count,
            "threshold": WEBHOOK_FAILURE_THRESHOLD,
        }
    except Exception:
        logger.warning("Webhook failure check failed", exc_info=True)
        return {"status": "error", "message": "check failed"}


# ---------------------------------------------------------------------------
# Outbound notification
# ---------------------------------------------------------------------------


def _send_webhook_notification(
    alert_names: list[str],
    checks: dict[str, Any],
) -> None:
    """POST alert payload to ALERT_WEBHOOK_URL (Slack/Discord/generic)."""
    if not ALERT_WEBHOOK_URL:
        return

    try:
        import urllib.request

        summary = ", ".join(alert_names)
        details = []
        for name in alert_names:
            info = checks.get(name, {})
            details.append(f"• *{name}*: {json.dumps(info, default=str)}")

        payload = json.dumps({
            "text": f":rotating_light: LAP Alert: {summary}",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"LAP Alert: {len(alert_names)} check(s) firing"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(details)}},
            ],
        }).encode()

        req = urllib.request.Request(
            ALERT_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        logger.info("Alert webhook sent to %s", ALERT_WEBHOOK_URL[:40])
    except Exception:
        logger.warning("Failed to send alert webhook", exc_info=True)


# ---------------------------------------------------------------------------
# Main check runner
# ---------------------------------------------------------------------------


def _run_alerting_checks_impl() -> dict[str, Any]:
    """Run all alerting checks and return a summary.

    Returns::

        {"checks": {"error_rate": {...}, "queue_depth": {...}, ...},
         "alerts_fired": int}
    """
    r = _get_redis()

    checks = {
        "error_rate": _check_error_rate(r),
        "queue_depth": _check_queue_depth(),
        "stuck_jobs": _check_stuck_jobs(),
        "webhook_failures": _check_webhook_failures(r),
    }

    alerts_fired = sum(1 for c in checks.values() if c.get("status") == "alert")

    if alerts_fired:
        alert_names = [k for k, v in checks.items() if v.get("status") == "alert"]
        logger.warning(
            "Alerting: %d alert(s) fired — %s",
            alerts_fired, alert_names,
        )
        _send_webhook_notification(alert_names, checks)
    else:
        logger.debug("Alerting: all checks passed")

    return {"checks": checks, "alerts_fired": alerts_fired}


# ---------------------------------------------------------------------------
# Register as Celery task
# ---------------------------------------------------------------------------

if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(name="tasks.alerting_tasks.run_alerting_checks")
    def run_alerting_checks() -> dict[str, Any]:
        return _run_alerting_checks_impl()
else:
    def run_alerting_checks() -> dict[str, Any]:  # type: ignore[misc]
        return _run_alerting_checks_impl()
