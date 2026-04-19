"""Celery task for track-surface analysis.

Follows the same import-guarded pattern as tasks/ocp_tasks.py so the module is
importable in test / CLI environments where Celery is absent.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_celery():
    try:
        from tasks.celery_app import celery
        return celery
    except ImportError:
        return None


def _run_impl(run_id: str) -> dict:
    """Execute one analysis run. Factored for testability."""
    from track_surface_app.orchestrator import AnalysisOrchestrator   # noqa: F401

    orchestrator = _build_orchestrator()
    orchestrator.execute(run_id)
    return {"run_id": run_id, "status": "completed"}


def _build_orchestrator():
    """Wire the orchestrator against real dependencies.

    Resolution order for configuration:
      1. Flask app context (current_app.config) — production path
      2. Environment variables — Celery worker / CLI path
      3. Sensible defaults — dev / test path
    """
    from track_surface_app.orchestrator import AnalysisOrchestrator
    from track_surface_app.pipeline_adapters import AdapterConfig, build_adapters
    from track_surface_app.session_loader import SessionLoader

    # ── Resolve configuration ───────────────────────────────

    results_dir, release_thresholds_path, calibration_registry_path, accumulator_dir = \
        _resolve_config()

    # ── Resolve the DB connection factory ──────────────────

    conn_factory, set_ws_fn = _resolve_db_helpers()

    # ── Build the loader and adapters ──────────────────────

    loader = SessionLoader(
        conn_factory=conn_factory,
        set_workspace_context_fn=set_ws_fn,
    )
    run_pipeline_adapter, evaluate_release_adapter = build_adapters(
        session_loader=loader,
        config=AdapterConfig(
            release_thresholds_path=release_thresholds_path,
            calibration_registry_path=calibration_registry_path,
            accumulator_dir=accumulator_dir,
        ),
    )

    return AnalysisOrchestrator(
        conn_factory=conn_factory,
        artifacts_base_dir=results_dir,
        run_pipeline_fn=run_pipeline_adapter,
        evaluate_release_fn=evaluate_release_adapter,
    )


def _resolve_config() -> tuple[Path, str | None, str | None, str | None]:
    """Return ``(results_dir, release_thresholds_path, calibration_registry_path,
    accumulator_dir)`` using Flask context if available, else env vars."""
    results_base = None
    release_thresholds_path = None
    calibration_registry_path = None
    accumulator_dir = None

    try:
        from flask import current_app, has_app_context   # type: ignore
        if has_app_context():
            cfg = current_app.config
            results_base = cfg.get("RESULTS_DIR")
            release_thresholds_path = cfg.get("RELEASE_THRESHOLDS_PATH")
            calibration_registry_path = cfg.get("CALIBRATION_REGISTRY_PATH")
            accumulator_dir = cfg.get("TRACK_SURFACE_ACCUMULATOR_DIR")
    except ImportError:
        pass

    results_base = results_base or os.environ.get("RESULTS_DIR") or "./results"
    release_thresholds_path = release_thresholds_path or os.environ.get(
        "RELEASE_THRESHOLDS_PATH") or _default_thresholds_path()
    calibration_registry_path = calibration_registry_path or os.environ.get(
        "CALIBRATION_REGISTRY_PATH")
    accumulator_dir = accumulator_dir or os.environ.get("TRACK_SURFACE_ACCUMULATOR_DIR")

    return (
        Path(results_base) / "track_surface",
        release_thresholds_path,
        calibration_registry_path,
        accumulator_dir,
    )


def _default_thresholds_path() -> str | None:
    """Best-effort default — ``<repo>/data/release_thresholds.json``."""
    # tasks/ lives at telemetry_tool/tasks/ ; the data dir is at repo root.
    candidate = Path(__file__).resolve().parent.parent.parent / "data" / "release_thresholds.json"
    return str(candidate) if candidate.is_file() else None


def _resolve_db_helpers():
    """Return (conn_factory, set_workspace_context_fn) using whatever is available.

    Prefers ``web.db.get_db_connection`` (the canonical helper used by
    ocp_tasks.py). Falls back to returning a factory that raises — the caller
    should have injected one in tests.
    """
    try:
        from web.db import get_db_connection  # type: ignore
        conn_factory = get_db_connection
    except ImportError:
        def conn_factory():
            raise RuntimeError(
                "No DB connection factory configured — inject one via tests or "
                "ensure web.db.get_db_connection is importable at runtime."
            )

    try:
        from web.middleware.tenant import _set_rls_context as set_ws   # type: ignore

        def set_workspace_context_fn(conn, workspace_id):
            set_ws(conn, workspace_id)
    except Exception:
        set_workspace_context_fn = None

    return conn_factory, set_workspace_context_fn


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
