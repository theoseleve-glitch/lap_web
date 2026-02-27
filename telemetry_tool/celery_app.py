"""Celery application factory."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure telemetry_tool/ is on sys.path so that ``from web.config``
# resolves correctly when Celery runs as a standalone worker process.
_PKG_DIR = str(Path(__file__).resolve().parent)
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

from celery import Celery


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

    celery = Celery("telemetry_tool", broker=broker, backend=backend)
    celery.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        result_expires=86400,  # 24 hours
        task_routes={
            "tasks.pipeline_tasks.*": {"queue": "pipeline"},
            "tasks.batch_tasks.*": {"queue": "default"},
        },
        task_default_queue="default",
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
