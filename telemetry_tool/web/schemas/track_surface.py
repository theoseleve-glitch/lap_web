"""HTTP request / response schemas for the track-surface analysis API.

All types are Pydantic v2 BaseModels. Requests use StrictSchema (reject unknown
fields); responses use LenientSchema (forgiving on ingestion, strict on output).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from web.schemas.common import LenientSchema, StrictSchema


# ── Request schemas ─────────────────────────────────────────

class RunAnalysisRequest(StrictSchema):
    """POST /sessions/<sid>/run body. All fields optional."""
    vehicle_profile_override: str | None = None
    planner_modes: list[Literal["nominal", "robust", "exploitable"]] | None = None
    force_rerun: bool = False


class ResolveSupportParams(StrictSchema):
    """Query params for GET /support/resolve."""
    sim: str = Field(..., min_length=1, max_length=64)
    vehicle: str = Field(..., min_length=1, max_length=64)
    track: str = Field(..., min_length=1, max_length=128)


# ── Shared response shapes ──────────────────────────────────

class PlannerModeAvailabilityDTO(LenientSchema):
    nominal: bool
    robust: bool
    exploitable: bool


# ── Response schemas ────────────────────────────────────────

class AnalysisRunSummary(LenientSchema):
    run_id: str
    session_id: int
    status: Literal["queued", "running", "succeeded", "failed"]
    support_tier: Literal["A", "B", "C", "D"] | None
    support_reason: str | None
    confidence_level: Literal["high", "medium", "low", "unknown"] | None
    fallback_depth_pct: dict[str, float] | None
    validated_vehicle_profile: str | None
    validated_track_profile: str | None
    planner_mode_availability: PlannerModeAvailabilityDTO | None
    warnings: list[str]
    artifacts_available: list[str]
    release_decision: Literal["pass", "warn", "fail"] | None
    error_code: str | None
    error_message: str | None
    created_at: str | None
    completed_at: str | None


class SessionSummary(LenientSchema):
    run_id: str
    session_id: int
    n_samples_total: int
    n_samples_accepted: int
    n_laps: int
    best_lap: int
    best_lap_time_s: float
    track_length_m: float
    lap_times_s: dict[str, float]
    warnings: list[str]
    calibration_profile_id: str | None
    calibration_source: str | None


class TrackSurfaceSummary(LenientSchema):
    run_id: str
    coverage_pct: float
    mean_confidence: float
    confidence_level: Literal["high", "medium", "low", "unknown"]
    fallback_depth_pct: dict[str, float]
    bucket_active_count: int
    bucket_sparse_count: int


class PlannerModeResult(LenientSchema):
    mode: Literal["nominal", "robust", "exploitable"]
    mu_eff_mean: float
    trusted_point_count: int
    degraded_point_count: int
    total_point_count: int
    max_robust_penalty: float


class PlannerSummary(LenientSchema):
    run_id: str
    support_tier: Literal["A", "B", "C", "D"]
    available_modes: list[str]
    nominal: PlannerModeResult | None
    robust: PlannerModeResult | None
    exploitable: PlannerModeResult | None
    unavailable_reason: str | None = None


class UncertaintySummary(LenientSchema):
    run_id: str
    mean_confidence: float
    confidence_level: Literal["high", "medium", "low", "unknown"]
    high_conf_cells: int
    zero_conf_cells: int
    fallback_depth_pct: dict[str, float]


class SupportSummary(LenientSchema):
    run_id: str | None
    sim: str | None
    vehicle: str | None
    track: str | None
    support_tier: Literal["A", "B", "C", "D"]
    support_reason: str
    validated_vehicle_profile: str | None
    validated_track_profile: str | None
    planner_mode_availability: PlannerModeAvailabilityDTO
    warnings: list[str]


class SupportMatrixEntryDTO(LenientSchema):
    sim: str
    vehicle: str
    track: str
    max_support_tier: Literal["A", "B", "C", "D"]
    validated_vehicle_profile: str | None
    validated_track_profile: str | None


class SupportMatrixResponse(LenientSchema):
    entries: list[SupportMatrixEntryDTO]
    last_updated: str


class ArtifactRef(LenientSchema):
    kind: str
    download_url: str
    size_bytes: int
    version: str


class ArtifactsIndex(LenientSchema):
    run_id: str
    artifacts: list[ArtifactRef]
