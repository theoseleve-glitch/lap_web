"""SupportTierResolver — maps (PipelineResult, ReleaseSessionResult) → SupportTier.

This is the translation seam between research concepts and product concepts.
Inputs are duck-typed — we read attributes by name so the resolver can be tested
with fakes without importing the real validation harness.
"""
from __future__ import annotations

import logging
from typing import Any

from track_surface_app.domain import SupportTier

logger = logging.getLogger(__name__)

# Threshold constants. Kept here (not in a config file) because they encode
# the product-side tier contract, not a tunable physics parameter.
FB2_TIER_B_THRESHOLD_PCT = 10.0
FB2_TIER_C_THRESHOLD_PCT = 30.0

_VALIDATED_CALIBRATION_SOURCES = {"registry_active"}


def compute_fallback_depth_2_pct(dist: dict[int, int]) -> float:
    """Compute the percentage of points resolved by the global fallback (depth 2).

    Args:
        dist: Mapping depth (0/1/2) → count, as emitted by `bucket_fallback_distribution`
              on PipelineResult.

    Returns:
        Float percentage in [0, 100].
    """
    total = sum(dist.values()) if dist else 0
    if total <= 0:
        return 0.0
    return (dist.get(2, 0) / total) * 100.0


def _has_track_geometry(pipeline_result: Any) -> bool:
    """True iff the pipeline produced enough output to be meaningful."""
    if getattr(pipeline_result, "exception", None) is not None:
        return False
    if getattr(pipeline_result, "n_valid", 0) <= 0:
        return False
    if getattr(pipeline_result, "track_length_m", 0.0) <= 0.0:
        return False
    return True


def _is_validated_calibration(pipeline_result: Any) -> bool:
    src = getattr(pipeline_result, "calibration_source", None)
    return src in _VALIDATED_CALIBRATION_SOURCES


class SupportTierResolver:
    """Maps research-layer outputs to a user-facing SupportTier + reason code.

    Usage:
        tier, reason = SupportTierResolver().resolve(pipeline_result, release_result)

    Both inputs are duck-typed. They must expose:
      - pipeline_result: .n_valid, .exception, .track_length_m, .calibration_source,
        .bucket_fallback_distribution
      - release_result: .decision.value  (one of "pass"|"warn"|"fail")
    """

    def resolve(self, pipeline_result: Any, release_result: Any) -> tuple[SupportTier, str]:
        # Tier D — can't produce meaningful output at all
        if not _is_validated_calibration(pipeline_result):
            return SupportTier.D, "vehicle_profile_not_validated"
        if not _has_track_geometry(pipeline_result):
            return SupportTier.D, "track_geometry_missing"

        decision = getattr(release_result.decision, "value", None) if release_result is not None else None
        fb2_pct = compute_fallback_depth_2_pct(
            getattr(pipeline_result, "bucket_fallback_distribution", {}) or {}
        )

        # Tier C — ran but advanced outputs not trustworthy
        if decision == "fail":
            return SupportTier.C, "release_gate_fail"
        if fb2_pct >= FB2_TIER_C_THRESHOLD_PCT:
            return SupportTier.C, "high_global_fallback"

        # Tier B — partial
        if decision == "warn":
            return SupportTier.B, "release_gate_warn"
        if fb2_pct >= FB2_TIER_B_THRESHOLD_PCT:
            return SupportTier.B, "moderate_fallback"

        # Tier A — full
        return SupportTier.A, "all_checks_passed"
