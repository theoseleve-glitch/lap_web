"""Celery application factory."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure telemetry_tool/ is on sys.path so that ``from web.config``
# resolves correctly when Celery runs as a standalone worker process.
_PKG_DIR = str(Path(__file__).resolve().parent)
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

from celery import Celery
from celery.schedules import crontab


def make_celery(app=None) -> Celery:
    """Create and configure a Celery instance.

    Parameters
    ----------
    app : Flask application, optional
        When provided, Celery tasks execute inside the Flask app context
        and broker/backend URLs are read from ``app.config``.  When *None*,
        settings are taken directly from :class:`web.config.Config`.

    Returns
    -------
    Celery
        Fully configured Celery application.
    """
    if app is None:
        from web.config import Config
        broker = Config.CELERY_BROKER_URL
        backend = Config.CELERY_RESULT_BACKEND
    else:
        broker = app.config.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        backend = app.config.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

    celery = Celery(
        "telemetry_tool",
        broker=broker,
        backend=backend,
        include=[
            "tasks.pipeline_tasks",
            "tasks.batch_tasks",
            "tasks.gdpr_tasks",
            "tasks.billing_tasks",
            "tasks.alerting_tasks",
            "tasks.email_tasks",
            "tasks.archival_tasks",
            "tasks.usage_tasks",
            "tasks.retention_tasks",
            "tasks.training_tasks",
            "tasks.rollup_tasks",
            "tasks.dead_letter_tasks",
            "tasks.ocp_tasks",
            "tasks.endurance_tasks",
            "tasks.recap_tasks",
            "tasks.racing_line_tasks",
            "admin.metrics_collector",
        ],
    )
    celery.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        result_expires=86400,  # 24 hours
        task_routes={
            "tasks.pipeline_tasks.*": {"queue": "pipeline"},
            "tasks.training_tasks.*": {"queue": "pipeline"},
            "tasks.ocp_tasks.*": {"queue": "pipeline"},
            "tasks.racing_line_tasks.*": {"queue": "pipeline"},
            "tasks.batch_tasks.*": {"queue": "default"},
        },
        task_default_queue="default",
        # Beat schedule for periodic tasks
        beat_schedule={
            "enforce-raw-data-retention": {
                "task": "tasks.gdpr_tasks.enforce_raw_data_retention",
                "schedule": crontab(hour=2, minute=15),
                "options": {"queue": "default"},
            },
            "purge-deleted-accounts": {
                "task": "tasks.gdpr_tasks.purge_deleted_accounts",
                "schedule": 86400,  # Daily (24h in seconds)
                "options": {"queue": "default"},
            },
            "purge-soft-deleted-sessions": {
                "task": "tasks.gdpr_tasks.purge_soft_deleted_sessions",
                "schedule": 86400,  # Daily — completes Art.17 erasure for the
                "options": {"queue": "default"},  # session soft-delete grace window
            },
            "cleanup-expired-exports": {
                "task": "tasks.gdpr_tasks.cleanup_expired_exports",
                "schedule": 86400,  # Daily
                "options": {"queue": "default"},
            },
            "prune-behavioral-events": {
                "task": "tasks.gdpr_tasks.prune_behavioral_events",
                "schedule": 86400,  # Daily (24h in seconds)
                "options": {"queue": "default"},
            },
            "reconcile-storage-usage": {
                "task": "tasks.usage_tasks.reconcile_storage_usage",
                "schedule": 86400,  # Daily — keep storage allocation matched to consumption
                "options": {"queue": "default"},
            },
            "aggregate-monthly-usage": {
                "task": "tasks.usage_tasks.aggregate_monthly_usage",
                "schedule": 86400,  # Daily — reconcile usage_monthly (the quota/billing
                "options": {"queue": "default"},  # source) from raw usage_events
            },
            "reconcile-stripe": {
                "task": "tasks.billing_tasks.reconcile_stripe",
                "schedule": 3600,  # Hourly
                "options": {"queue": "default"},
            },
            "enforce-grace-periods": {
                "task": "tasks.billing_tasks.enforce_subscription_grace_periods",
                "schedule": 86400,  # Daily
                "options": {"queue": "default"},
            },
            "retry-failed-webhooks": {
                "task": "tasks.billing_tasks.retry_failed_webhooks",
                "schedule": 300,  # Every 5 minutes
                "options": {"queue": "default"},
            },
            "alerting-checks": {
                "task": "tasks.alerting_tasks.run_alerting_checks",
                "schedule": 300,  # Every 5 minutes
                "options": {"queue": "default"},
            },
            "create-future-partitions": {
                "task": "tasks.archival_tasks.create_future_partitions",
                "schedule": 2592000,  # Monthly (30 days)
                "options": {"queue": "default"},
            },
            "archive-old-usage-events": {
                "task": "tasks.archival_tasks.archive_old_usage_events",
                "schedule": 2592000,  # Monthly (30 days)
                "options": {"queue": "default"},
            },
            "archive-old-audit-logs": {
                "task": "tasks.archival_tasks.archive_old_audit_logs",
                "schedule": 2592000,  # Monthly (30 days)
                "options": {"queue": "default"},
            },
            "collect-system-metrics": {
                "task": "admin.metrics_collector.collect_system_metrics_task",
                "schedule": 60,  # Every minute
                "options": {"queue": "default"},
            },
            "biweekly-retrain-and-reprocess": {
                "task": "tasks.training_tasks.weekly_retrain_and_reprocess",
                # Fires every Sunday midnight UTC; the task itself gates on
                # even ISO-week numbers for bi-weekly execution.
                "schedule": crontab(hour=0, minute=0, day_of_week=0),
                "options": {"queue": "pipeline"},
            },
            "enforce-tiered-retention": {
                "task": "tasks.retention_tasks.enforce_telemetry_retention",
                "schedule": crontab(hour=3, minute=0),  # Daily 03:00 UTC
                "options": {"queue": "default"},
            },
            "cleanup-retention-audit": {
                "task": "tasks.retention_tasks.cleanup_retention_audit",
                "schedule": 2592000,  # Monthly (30 days)
                "options": {"queue": "default"},
            },
            "refresh-all-rollups": {
                "task": "tasks.rollup_tasks.refresh_all_rollups",
                "schedule": crontab(hour=4, minute=0),  # Daily 04:00 UTC
                "options": {"queue": "default"},
            },
            "purge-dead-letter-queue": {
                "task": "tasks.dead_letter_tasks.purge_dead_letters",
                "schedule": 2592000,  # Monthly (30 days)
                "options": {"queue": "default"},
            },
            "weekly-recap": {
                "task": "tasks.recap_tasks.weekly_recap",
                "schedule": crontab(hour=6, minute=0, day_of_week=1),  # Monday 06:00 UTC
                "options": {"queue": "default"},
            },
            "nightly-racing-lines": {
                "task": "tasks.racing_line_tasks.compute_all_racing_lines",
                "schedule": crontab(hour=3, minute=30),  # Daily 03:30 UTC
                "options": {"queue": "pipeline"},
            },
        },
    )

    if app is not None:

        class ContextTask(celery.Task):  # type: ignore[name-defined]
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    # Propagate request context from message headers into Flask g
                    from flask import g
                    headers = getattr(self.request, "headers", None) or {}
                    if headers.get("request_id"):
                        g.request_id = headers["request_id"]
                    if headers.get("user_id"):
                        g.current_user_id = headers["user_id"]
                    if headers.get("workspace_id"):
                        g.workspace_id = headers["workspace_id"]
                    return self.run(*args, **kwargs)

        celery.Task = ContextTask

    # Auto-inject Flask request context into Celery task headers
    from celery.signals import before_task_publish

    @before_task_publish.connect
    def _propagate_request_context(headers=None, **kwargs):
        """Copy request_id, user_id, workspace_id into Celery message headers."""
        if headers is None:
            return
        try:
            from flask import g
            custom = {}
            for attr, key in [
                ("request_id", "request_id"),
                ("current_user_id", "user_id"),
                ("workspace_id", "workspace_id"),
            ]:
                val = getattr(g, attr, None)
                if val is not None:
                    custom[key] = str(val)
            if custom:
                headers.update(custom)
        except (ImportError, RuntimeError):
            pass  # Outside Flask context (e.g. beat scheduler)

    return celery


# Standalone entry point: celery -A telemetry_tool.celery_app worker
celery = make_celery()

# ── Fail-closed RLS preflight for workers ──────────────────────────
# Mirrors the web tier's app.py boot guard: refuse to start a worker whose DB
# role bypasses row-level security in multi-tenant mode, so pipeline/export/
# GDPR tasks can never silently run cross-tenant on a privileged DSN. Without
# this, only the web app was guarded — a misconfigured worker DSN would defeat
# the whole 064 RLS cutover for background work.
from celery.signals import worker_process_init as _worker_process_init


@_worker_process_init.connect
def _assert_worker_rls_enforcement(**_kwargs):
    auth_required = os.environ.get("AUTH_REQUIRED", "0") == "1"
    try:
        from web.db_pg import assert_rls_enforcement
        assert_rls_enforcement(auth_required=auth_required)
    except RuntimeError:
        # Privileged DSN in multi-tenant mode — abort worker boot (fail closed).
        raise
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Worker RLS preflight skipped: %s", exc)


# Register dead-letter-queue signal handler (captures tasks that exhaust retries)
try:
    import tasks.dead_letter  # noqa: F401 — registers @task_failure.connect
except ImportError:
    pass

# ── Sentry for Celery workers ──────────────────────────
_worker_dsn = os.environ.get("SENTRY_DSN_WORKER")
if _worker_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_worker_dsn,
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        )
    except ImportError:
        pass
