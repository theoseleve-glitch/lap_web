"""Celery task for track-surface analysis.

Follows the same import-guarded pattern as tasks/ocp_tasks.py so the module is
importable in test / CLI environments where Celery is absent.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_celery():
    try:
        from tasks.celery_app import celery
        return celery
    except ImportError:
        return None


def _run_impl(run_id: str) -> dict:
    """Execute one analysis run. Factored for testability.

    In production this runs inside a Celery worker with a Flask app context
    available via the worker-process `init`. In CLI/test it simply invokes
    the orchestrator with whatever deps are wired; the real session loader
    is not available here and will raise NotImplementedError — integration
    tests patch `run_pipeline_fn` on the orchestrator directly.
    """
    from track_surface_app.orchestrator import AnalysisOrchestrator

    orchestrator = _build_orchestrator()
    orchestrator.execute(run_id)
    return {"run_id": run_id, "status": "completed"}


def _build_orchestrator():
    """Wire the orchestrator against real dependencies.

    The production wiring of ``run_pipeline_fn`` against the full 14-stage
    session loader is out of scope for this initial app-layer landing —
    integration happens when the session-to-DatasetEntry adapter is published
    (see ``docs/plans/2026-04-15-track-surface-analysis-app-design.md`` §8.2).
    """
    from track_surface_app.orchestrator import AnalysisOrchestrator

    try:
        from flask import current_app   # type: ignore
        app_cfg = current_app.config
        base_dir = Path(app_cfg["RESULTS_DIR"]) / "track_surface"
        from web.db import get_conn
        conn_factory = get_conn
    except (ImportError, RuntimeError):
        # No Flask app context — fall back to sensible defaults
        base_dir = Path("./results/track_surface")

        def conn_factory():
            raise NotImplementedError(
                "No DB connection factory available outside Flask app context"
            )

    def run_pipeline(session_id: int, workspace_id: int):
        raise NotImplementedError(
            "run_pipeline adapter must be wired to session loader — see design doc §8.2"
        )

    def evaluate_release(pipeline_result):
        raise NotImplementedError(
            "evaluate_release adapter must be wired — see design doc §8.2"
        )

    return AnalysisOrchestrator(
        conn_factory=conn_factory,
        artifacts_base_dir=base_dir,
        run_pipeline_fn=run_pipeline,
        evaluate_release_fn=evaluate_release,
    )


_celery = _get_celery()
if _celery is not None:
    @_celery.task(
        name="tasks.track_surface_tasks.run_track_surface_analysis",
        bind=True,
        queue="pipeline",
        max_retries=1,
        retry_backoff=True,
        soft_time_limit=180,
        time_limit=240,
    )
    def run_track_surface_analysis(self, run_id: str) -> dict:
        return _run_impl(run_id)
else:
    def run_track_surface_analysis(run_id: str) -> dict:   # pragma: no cover - CLI fallback
        return _run_impl(run_id)
