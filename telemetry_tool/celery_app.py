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
            "cleanup-expired-exports": {
                "task": "tasks.gdpr_tasks.cleanup_expired_exports",
                "schedule": 86400,  # Daily
                "options": {"queue": "default"},
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
            "refresh-all-rollups": {
                "task": "tasks.rollup_tasks.refresh_all_rollups",
                "schedule": crontab(hour=4, minute=0),  # Daily 04:00 UTC
                "options": {"queue": "default"},
            },
        },
    )

    if app is not None:

        class ContextTask(celery.Task):  # type: ignore[name-defined]
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)

        celery.Task = ContextTask

    return celery


# Standalone entry point: celery -A telemetry_tool.celery_app worker
celery = make_celery()

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
