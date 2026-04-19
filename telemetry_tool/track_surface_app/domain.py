"""Domain enums and value objects for the track-surface analysis app.

These types are the vocabulary of the application layer. They are translated
from research-layer concepts (ReleaseDecision, fallback_depth, confidence) by
SupportTierResolver, and translated to HTTP shapes by web/schemas/track_surface.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SupportTier(str, Enum):
    """User-facing gating tier. Derived from release decision + fallback + calibration."""
    A = "A"    # full: nominal + robust + exploitable
    B = "B"    # partial: nominal + robust
    C = "C"    # descriptive only: no planner
    D = "D"    # unsupported: no analysis


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"

    @classmethod
    def from_mean_confidence(cls, mean: float | None) -> "ConfidenceLevel":
        if mean is None:
            return cls.UNKNOWN
        if mean >= 0.80:
            return cls.HIGH
        if mean >= 0.50:
            return cls.MEDIUM
        return cls.LOW


class AnalysisRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    def is_terminal(self) -> bool:
        return self in (AnalysisRunStatus.SUCCEEDED, AnalysisRunStatus.FAILED)


@dataclass(frozen=True)
class PlannerModeAvailability:
    """Which planner modes (nominal/robust/exploitable) a tier exposes."""
    nominal: bool
    robust: bool
    exploitable: bool

    @classmethod
    def for_tier(cls, tier: SupportTier) -> "PlannerModeAvailability":
        if tier is SupportTier.A:
            return cls(nominal=True, robust=True, exploitable=True)
        if tier is SupportTier.B:
            return cls(nominal=True, robust=True, exploitable=False)
        return cls(nominal=False, robust=False, exploitable=False)

    def to_dict(self) -> dict[str, bool]:
        return {"nominal": self.nominal, "robust": self.robust, "exploitable": self.exploitable}


# Closed set of machine-readable support reasons. Frontend can switch on these.
SUPPORT_REASONS = frozenset({
    "all_checks_passed",
    "release_gate_warn",
    "release_gate_fail",
    "moderate_fallback",
    "high_global_fallback",
    "vehicle_profile_not_validated",
    "track_profile_not_validated",
    "track_geometry_missing",
    "calibration_missing",
    "insufficient_channels",
    "gps_speed_only_available",
    "no_pipeline_run",
})
