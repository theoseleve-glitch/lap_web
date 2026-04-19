"""Pydantic v2 HTTP schemas for bundle intake endpoints."""
from __future__ import annotations

from typing import Literal

from web.schemas.common import LenientSchema, StrictSchema


class ReadinessSummary(LenientSchema):
    is_ready: bool
    reasons: list[str]
    degraded_fields: list[str]


class IntakeResult(LenientSchema):
    bundle_id: str
    status: Literal["accepted", "degraded", "rejected"]
    schema_version: int
    checksum_sha256: str
    size_bytes: int
    identity_fingerprint: str
    readiness: ReadinessSummary
    intake_reasons: list[str]
    self_url: str
    analyze_url: str | None
    duplicate_of: str | None = None


class SessionOverview(LenientSchema):
    bundle_id: str
    sim: str
    vehicle_name: str
    vehicle_key: str
    track_name: str
    track_key: str
    track_regime: str
    session_type: str
    started_at: str
    lap_count: int
    duration_s: float
    status: Literal["accepted", "degraded"]
    readiness: ReadinessSummary
    latest_run_id: str | None


class BundleArtifactRef(LenientSchema):
    role: str
    path: str
    size_bytes: int
    checksum_sha256: str
    download_url: str


class BundleArtifactIndex(LenientSchema):
    bundle_id: str
    artifacts: list[BundleArtifactRef]


class AnalyzeRequest(StrictSchema):
    force_rerun: bool = False


class AnalyzeResponse(LenientSchema):
    bundle_id: str
    run_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    analyze_url: str
