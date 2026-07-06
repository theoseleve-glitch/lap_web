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
    """Standalone maintenance connection (BYPASSRLS).

    These health checks aggregate ingestion_jobs across ALL workspaces, so
    they need the cross-tenant maintenance role — the app role is RLS-scoped
    and would fail closed with no workspace GUC. Caller MUST close it.
    """
    from web.db_pg import get_maint_connection
    return get_maint_connection()


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
    from web.db_pg import return_pg_connection
    conn = None
    try:
        conn = _get_pg()
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM ingestion_jobs "
            "WHERE status IN ('pending', 'running', 'processing')"
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
    finally:
        if conn is not None:
            return_pg_connection(conn)


def _reconcile_stuck_jobs(conn) -> list[dict]:
    """Flip 'running'/'processing' jobs past their tier's time budget to 'failed'.

    A HARD Celery time limit (``--time-limit`` / per-signature ``time_limit``)
    kills the worker child with SIGKILL — no Python exception is raised, so
    nothing marks the job row as failed and it is left 'running' forever (the
    SOFT limit, by contrast, raises ``SoftTimeLimitExceeded`` inside the task,
    which is already caught by each pipeline stage's ``except Exception``
    handler in tasks/pipeline_tasks.py and marks the job 'failed' — no change
    needed there).

    Resolves each job's plan tier via workspace owner (mirrors
    ``_resolve_session_owner`` in pipeline_tasks.py) and compares elapsed time
    against ``TIER_TIMEOUTS_S[tier] + HARD_LIMIT_MARGIN_S`` — the same ceiling
    ``build_pipeline_chain`` applied when the job was dispatched. Jobs whose
    tier can't be resolved (orphaned workspace, deleted owner) use the most
    generous ceiling across all tiers so an unresolved lookup never fails a
    job that might still be legitimately running.

    Reuses the existing ``status``/``error_message``/``error_class`` columns
    already written by the pipeline tasks — no new job-state machine.
    """
    from tasks.pipeline_tasks import HARD_LIMIT_MARGIN_S, TIER_TIMEOUTS_S

    max_ceiling_s = max(TIER_TIMEOUTS_S.values()) + HARD_LIMIT_MARGIN_S

    rows = conn.execute(
        "SELECT ij.job_id, "
        "EXTRACT(EPOCH FROM (NOW() - ij.started_at)) AS running_seconds, "
        "u.plan_tier "
        "FROM ingestion_jobs ij "
        "LEFT JOIN workspaces w ON w.id = ij.workspace_id "
        "LEFT JOIN users u ON u.id = w.owner_user_id "
        "WHERE ij.status IN ('running', 'processing')"
    ).fetchall()

    reconciled: list[dict] = []
    for r in rows:
        row = dict(r) if not isinstance(r, dict) else r
        tier = row.get("plan_tier")
        ceiling_s = (
            TIER_TIMEOUTS_S.get(tier, TIER_TIMEOUTS_S["racer"]) + HARD_LIMIT_MARGIN_S
            if tier else max_ceiling_s
        )
        running_s = row.get("running_seconds") or 0
        if running_s <= ceiling_s:
            continue

        job_id = row["job_id"]
        conn.execute(
            "UPDATE ingestion_jobs SET status = 'failed', "
            "error_message = %(msg)s, error_class = 'timeout', updated_at = NOW() "
            "WHERE job_id = %(jid)s AND status IN ('running', 'processing')",
            {
                "jid": job_id,
                "msg": (
                    f"Processing exceeded the {int(ceiling_s)}s tier ceiling "
                    f"(ran {int(running_s)}s) — worker was likely hard-killed mid-stage"
                ),
            },
        )
        reconciled.append({
            "job_id": job_id,
            "running_seconds": int(running_s),
            "ceiling_s": int(ceiling_s),
        })

    if reconciled:
        conn.commit()
        logger.error(
            "Reconciled %d stuck job(s) past tier ceiling -> failed: %s",
            len(reconciled),
            [j["job_id"][:8] for j in reconciled],
        )

    return reconciled


def _check_stuck_jobs() -> dict[str, Any]:
    """Check for jobs that have been running longer than the threshold.

    Also runs :func:`_reconcile_stuck_jobs` first so jobs whose worker was
    hard-killed mid-stage (no Python exception to catch — see that function's
    docstring) get flipped to 'failed' instead of staying 'running' forever.
    The informational stuck-job ALERT below then reports on whatever is
    genuinely still running past the (blanket, tier-agnostic) alert window.
    """
    from web.db_pg import return_pg_connection
    conn = None
    try:
        conn = _get_pg()
        reconciled = _reconcile_stuck_jobs(conn)

        rows = conn.execute(
            "SELECT job_id, file_path, started_at, "
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
            "reconciled_count": len(reconciled),
            "stuck_jobs": [
                {"job_id": j["job_id"][:8], "minutes": round(j.get("running_minutes", 0))}
                for j in stuck[:5]
            ],
        }
    except Exception:
        logger.warning("Stuck jobs check failed", exc_info=True)
        return {"status": "error", "message": "check failed"}
    finally:
        if conn is not None:
            return_pg_connection(conn)


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
