"""HTTP endpoints for the track-surface analysis app.

All endpoints use the standard ``{ok, data, error, meta}`` envelope and rely on
``g.workspace_id`` set by the tenant middleware.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from flask import Blueprint, current_app, g, request, send_file
from pydantic import ValidationError

from track_surface_app.domain import (
    PlannerModeAvailability,
    SupportTier,
)
from track_surface_app.gating import OutputGate, ALL_ARTIFACT_KINDS
from track_surface_app.orchestrator import AnalysisOrchestrator
from track_surface_app.persistence import AnalysisRunRecord, AnalysisRunRepository
from track_surface_app.support_matrix import SupportMatrix
from web.api_utils import (
    ErrorCode,
    api_error,
    api_response,
)
from web.rate_limit import rate_limit
from web.schemas.track_surface import (
    ResolveSupportParams,
    RunAnalysisRequest,
)

logger = logging.getLogger(__name__)

bp = Blueprint("track_surface_analysis", __name__, url_prefix="/api/v1/track-surface")

# ── Dependency injection (for tests) ─────────────────────────

_CONN_FACTORY: Callable[[], Any] | None = None
_SUPPORT_MATRIX: SupportMatrix | None = None


def inject_conn_factory(factory: Callable[[], Any]) -> None:
    """Override the DB conn factory (used in tests)."""
    global _CONN_FACTORY
    _CONN_FACTORY = factory


def inject_support_matrix(matrix: SupportMatrix) -> None:
    """Override the support matrix (used in tests)."""
    global _SUPPORT_MATRIX
    _SUPPORT_MATRIX = matrix


def _get_conn():
    if _CONN_FACTORY is not None:
        return _CONN_FACTORY()
    # NOTE: web.db exports `get_db_connection` (dual-mode: PG when USE_PG=1,
    # else SQLite) — there is no `get_conn` symbol. The previous
    # `from web.db import get_conn` raised ImportError on every call,
    # silently swallowed by the broad `except Exception` around the shared
    # compute-budget check in run_analysis(), so that check has never
    # actually run in production (see web/routes/endurance_upload.py for
    # the same bug, fixed the same way).
    from web.db import get_db_connection
    return get_db_connection()


def _get_matrix() -> SupportMatrix:
    global _SUPPORT_MATRIX
    if _SUPPORT_MATRIX is None:
        _SUPPORT_MATRIX = SupportMatrix.load_default()
    return _SUPPORT_MATRIX


def dispatch_celery_task(run_id: str) -> None:
    """Dispatch the Celery task. Isolated so tests can patch it."""
    try:
        from tasks.track_surface_tasks import run_track_surface_analysis
        delay = getattr(run_track_surface_analysis, "delay", None)
        if callable(delay):
            run_track_surface_analysis.delay(run_id)
        else:
            # Celery not available — run inline (dev/test)
            run_track_surface_analysis(run_id)
    except Exception as exc:   # celery layer issue — don't fail the request
        logger.exception("Failed to dispatch Celery task for run %s: %s", run_id, exc)


# ── Serialization helpers ────────────────────────────────────

def _run_to_summary_dict(run: AnalysisRunRecord) -> dict[str, Any]:
    gate = OutputGate(run.support_tier) if run.support_tier else OutputGate(SupportTier.D)
    artifacts_available = [
        k for k in (run.artifacts_index or {}).keys() if gate.is_artifact_allowed(k)
    ]
    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "status": run.status.value,
        "support_tier": run.support_tier.value if run.support_tier else None,
        "support_reason": run.support_reason,
        "confidence_level": run.confidence_level.value if run.confidence_level else None,
        "fallback_depth_pct": run.fallback_depth_distribution,
        "validated_vehicle_profile": run.validated_vehicle_profile,
        "validated_track_profile": run.validated_track_profile,
        "planner_mode_availability": run.planner_mode_availability,
        "warnings": run.warnings,
        "artifacts_available": artifacts_available,
        "release_decision": run.release_decision,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": str(run.created_at) if run.created_at else None,
        "completed_at": str(run.completed_at) if run.completed_at else None,
    }


def _tier_refused(tier: SupportTier, reason: str, *, endpoint: str):
    """Build the SUPPORT_TIER_REFUSED error envelope (HTTP 451)."""
    return api_error(
        ErrorCode.SUPPORT_TIER_REFUSED,
        message=f"{endpoint} unavailable at support tier {tier.value}.",
        details=[{
            "support_tier": tier.value,
            "support_reason": reason,
            "planner_mode_availability":
                PlannerModeAvailability.for_tier(tier).to_dict(),
        }],
        status=451,
    )


def _require_run(session_id: int):
    """Load the latest run for this session or return a 404 envelope tuple."""
    repo = AnalysisRunRepository(_get_conn())
    run = repo.get_latest_for_session(session_id)
    if run is None:
        return api_error(ErrorCode.NOT_FOUND,
                         message=f"No analysis run found for session {session_id}",
                         status=404)
    return run


# ── POST /sessions/<sid>/run ────────────────────────────────

@bp.route("/sessions/<int:session_id>/run", methods=["POST"])
@rate_limit(tier="analyze")
def run_analysis(session_id: int):
    try:
        req = RunAnalysisRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return api_error(ErrorCode.VALIDATION_ERROR, message=str(exc), status=422)

    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, message="missing workspace context",
                         status=401)

    # force_rerun bypasses the "already in flight" conflict check (see
    # AnalysisOrchestrator.enqueue), letting a caller queue another full
    # solver run even while one is already running for this session. That
    # forced-recompute path must require an active entitlement — a
    # locked/lapsed account must not be able to force expensive recompute
    # just because it can still reach this route. Fails CLOSED (unlike the
    # compute-budget check below): an error here must not grant access.
    if (req.force_rerun and current_app.config.get("USE_PG")
            and current_app.config.get("AUTH_REQUIRED")):
        from auth.entitlements import authorize_feature
        allowed, ctx = authorize_feature(
            _get_conn(), getattr(g, "current_user_id", None), "race_strategy",
        )
        if not allowed:
            from web.api_utils import ReasonCode, billing_error
            return billing_error(
                reason_code=ReasonCode.FEATURE_LOCKED,
                message=ctx.get("reason", "Forcing a re-analysis requires an active plan."),
                current_plan=ctx.get("current_tier"),
                required_plan=ctx.get("upgrade_tier"),
                upgrade_url=ctx.get("upgrade_url"),
                status=403,
            )

    # Shared per-tier compute budget (analysis + export + surface pool).
    # Fail-open: a metering error must never block a legitimate analysis run.
    try:
        from web.compute_budget import check_shared_compute_budget
        allowed, info = check_shared_compute_budget(
            _get_conn(), getattr(g, "current_user_id", 0) or 0, workspace_id,
            getattr(g, "plan_tier", None),
        )
        if not allowed:
            return api_error(
                ErrorCode.RATE_LIMITED,
                message=f"Compute budget exceeded: {info['running_jobs']}/{info['max_jobs']} jobs running",
                status=429,
            )
    except Exception:
        logger.warning("Shared compute budget check failed — allowing analysis", exc_info=True)

    # Build a minimal orchestrator for the enqueue step only; execute happens
    # in the Celery worker.
    orchestrator = AnalysisOrchestrator(
        conn_factory=_get_conn,
        artifacts_base_dir=".",    # not used by enqueue
        run_pipeline_fn=lambda *a, **kw: None,
        evaluate_release_fn=lambda *a, **kw: None,
    )
    try:
        run_id = orchestrator.enqueue(
            session_id=session_id,
            workspace_id=workspace_id,
            force_rerun=req.force_rerun,
        )
    except RuntimeError as exc:
        if "in_flight" in str(exc):
            return api_error(
                ErrorCode.CONFLICT,
                message="An analysis run is already in flight for this session.",
                status=409,
            )
        raise

    dispatch_celery_task(run_id)

    # Return the just-created queued row
    repo = AnalysisRunRepository(_get_conn())
    run = repo.get(run_id)
    return api_response(_run_to_summary_dict(run), status=202)


# ── GET /sessions/<sid> ─────────────────────────────────────

@bp.route("/sessions/<int:session_id>", methods=["GET"])
def get_session_run(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    return api_response(_run_to_summary_dict(run))


# ── GET /sessions/<sid>/summary ─────────────────────────────

@bp.route("/sessions/<int:session_id>/summary", methods=["GET"])
def get_session_summary(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    if run.pipeline_summary is None:
        return api_error(ErrorCode.NOT_FOUND, message="No summary for this run",
                         status=404)
    ps = run.pipeline_summary
    return api_response({
        "run_id": run.run_id,
        "session_id": run.session_id,
        "n_samples_total": ps.get("n_samples_total", 0),
        "n_samples_accepted": ps.get("n_valid", 0),
        "n_laps": ps.get("n_laps", 0),
        "best_lap": ps.get("best_lap", -1),
        "best_lap_time_s": ps.get("best_lap_time_s", 0.0),
        "track_length_m": ps.get("track_length_m", 0.0),
        "lap_times_s": ps.get("lap_times_s", {}),
        "warnings": run.warnings,
        "calibration_profile_id": ps.get("calibration_profile_id"),
        "calibration_source": ps.get("calibration_source"),
    })


# ── GET /sessions/<sid>/surface ─────────────────────────────

@bp.route("/sessions/<int:session_id>/surface", methods=["GET"])
def get_session_surface(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    tier = run.support_tier or SupportTier.D
    if not OutputGate(tier).is_endpoint_allowed("surface"):
        return _tier_refused(tier, run.support_reason or "no_pipeline_run",
                             endpoint="surface")
    ps = run.pipeline_summary or {}
    return api_response({
        "run_id": run.run_id,
        "coverage_pct": ps.get("field_coverage_pct", 0.0),
        "mean_confidence": ps.get("field_mean_confidence", 0.0),
        "confidence_level": run.confidence_level.value if run.confidence_level else "unknown",
        "fallback_depth_pct": run.fallback_depth_distribution or {},
        "bucket_active_count": ps.get("bucket_active_count", 0),
        "bucket_sparse_count": ps.get("bucket_sparse_count", 0),
    })


# ── GET /sessions/<sid>/planner ─────────────────────────────

@bp.route("/sessions/<int:session_id>/planner", methods=["GET"])
def get_session_planner(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    tier = run.support_tier or SupportTier.D
    if not OutputGate(tier).is_endpoint_allowed("planner"):
        return _tier_refused(tier, run.support_reason or "no_pipeline_run",
                             endpoint="planner")

    ps = run.pipeline_summary or {}
    av = PlannerModeAvailability.for_tier(tier)
    data: dict[str, Any] = {
        "run_id": run.run_id,
        "support_tier": tier.value,
        "available_modes": [m for m, on in av.to_dict().items() if on],
        "nominal": None,
        "robust": None,
        "exploitable": None,
        "unavailable_reason": None,
    }
    for mode in ("nominal", "robust", "exploitable"):
        if not getattr(av, mode):
            continue
        mean_mu_key = f"planner_{mode}_mean_mu"
        data[mode] = {
            "mode": mode,
            "mu_eff_mean": ps.get(mean_mu_key, 0.0),
            "trusted_point_count": ps.get("planner_n_trusted", 0),
            "degraded_point_count": ps.get("planner_n_degraded", 0),
            "total_point_count": ps.get("planner_n_trusted", 0) + ps.get("planner_n_degraded", 0),
            "max_robust_penalty": ps.get("planner_max_robust_penalty", 0.0),
        }
    return api_response(data)


# ── GET /sessions/<sid>/uncertainty ─────────────────────────

@bp.route("/sessions/<int:session_id>/uncertainty", methods=["GET"])
def get_session_uncertainty(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    tier = run.support_tier or SupportTier.D
    if not OutputGate(tier).is_endpoint_allowed("uncertainty"):
        return _tier_refused(tier, run.support_reason or "no_pipeline_run",
                             endpoint="uncertainty")
    ps = run.pipeline_summary or {}
    return api_response({
        "run_id": run.run_id,
        "mean_confidence": ps.get("field_mean_confidence", 0.0),
        "confidence_level": run.confidence_level.value if run.confidence_level else "unknown",
        "high_conf_cells": ps.get("field_high_conf_cells", 0),
        "zero_conf_cells": ps.get("field_zero_conf_cells", 0),
        "fallback_depth_pct": run.fallback_depth_distribution or {},
    })


# ── GET /sessions/<sid>/artifacts ───────────────────────────

@bp.route("/sessions/<int:session_id>/artifacts", methods=["GET"])
def get_session_artifacts(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    tier = run.support_tier or SupportTier.D
    gate = OutputGate(tier)
    refs: list[dict[str, Any]] = []
    for kind in (run.artifacts_index or {}).keys():
        if not gate.is_artifact_allowed(kind):
            continue
        refs.append({
            "kind": kind,
            "download_url": f"/api/v1/track-surface/sessions/{run.session_id}"
                            f"/artifacts/{kind}",
            "size_bytes": 0,
            "version": "v1",
        })
    return api_response({"run_id": run.run_id, "artifacts": refs})


# ── GET /sessions/<sid>/artifacts/<kind> ───────────────────

@bp.route("/sessions/<int:session_id>/artifacts/<string:kind>", methods=["GET"])
def download_artifact(session_id: int, kind: str):
    if kind not in ALL_ARTIFACT_KINDS:
        return api_error(ErrorCode.NOT_FOUND,
                         message=f"Unknown artifact kind: {kind}", status=404)
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    tier = run.support_tier or SupportTier.D
    if not OutputGate(tier).is_artifact_allowed(kind):
        return _tier_refused(tier, run.support_reason or "no_pipeline_run",
                             endpoint=f"artifact:{kind}")
    rel_path = (run.artifacts_index or {}).get(kind)
    if not rel_path:
        return api_error(ErrorCode.NOT_FOUND,
                         message=f"Artifact {kind} not generated for this run",
                         status=404)
    base = Path(current_app.config.get("RESULTS_DIR", ".")) / "track_surface"
    full_path = base / rel_path
    if not full_path.is_file():
        return api_error(ErrorCode.NOT_FOUND,
                         message="Artifact file missing on disk", status=404)
    return send_file(full_path, mimetype="application/json")


# ── GET /support/resolve ────────────────────────────────────

@bp.route("/support/resolve", methods=["GET"])
def resolve_support():
    try:
        params = ResolveSupportParams.model_validate(dict(request.args))
    except ValidationError as exc:
        return api_error(ErrorCode.VALIDATION_ERROR, message=str(exc), status=422)

    entry = _get_matrix().resolve(sim=params.sim, vehicle=params.vehicle,
                                  track=params.track)
    if entry is None:
        tier = SupportTier.D
        av = PlannerModeAvailability.for_tier(tier)
        return api_response({
            "run_id": None,
            "sim": params.sim, "vehicle": params.vehicle, "track": params.track,
            "support_tier": tier.value,
            "support_reason": "vehicle_profile_not_validated",
            "validated_vehicle_profile": None,
            "validated_track_profile": None,
            "planner_mode_availability": av.to_dict(),
            "warnings": ["combination_not_in_support_matrix"],
        })

    tier = entry.max_support_tier
    av = PlannerModeAvailability.for_tier(tier)
    reason_map = {
        SupportTier.A: "all_checks_passed",
        SupportTier.B: "moderate_fallback",
        SupportTier.C: "release_gate_fail",
        SupportTier.D: "vehicle_profile_not_validated",
    }
    return api_response({
        "run_id": None,
        "sim": params.sim, "vehicle": params.vehicle, "track": params.track,
        "support_tier": tier.value,
        "support_reason": reason_map[tier],
        "validated_vehicle_profile": entry.validated_vehicle_profile,
        "validated_track_profile": entry.validated_track_profile,
        "planner_mode_availability": av.to_dict(),
        "warnings": [],
    })


# ── GET /support/matrix ─────────────────────────────────────

@bp.route("/support/matrix", methods=["GET"])
def get_support_matrix():
    matrix = _get_matrix()
    return api_response({
        "entries": [
            {
                "sim": e.sim,
                "vehicle": e.vehicle,
                "track": e.track,
                "max_support_tier": e.max_support_tier.value,
                "validated_vehicle_profile": e.validated_vehicle_profile,
                "validated_track_profile": e.validated_track_profile,
            }
            for e in matrix.entries
        ],
        "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
