"""Pipeline step status tracking and version fingerprinting.

Provides structured per-step status capture for run_full_analysis(),
user-visible degradation flags, and deterministic pipeline versioning.

The ``StepStatus`` and ``PipelineStatus`` classes are plain data holders
that serialise to dicts suitable for JSON API responses.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class StepState(str, Enum):
    """Possible outcomes for a single pipeline step."""
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIPPED = "skipped"


class PipelineState(str, Enum):
    """Overall pipeline outcome."""
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class StepStatus:
    """Structured status of a single pipeline step."""
    name: str
    status: StepState = StepState.OK
    started_at: float = 0.0
    duration_ms: float = 0.0
    message_code: Optional[str] = None
    message: Optional[str] = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "status": self.status.value,
            "started_at": self.started_at,
            "duration_ms": round(self.duration_ms, 1),
        }
        if self.message_code:
            d["message_code"] = self.message_code
        if self.message:
            d["message"] = self.message
        if self.metrics:
            d["metrics"] = self.metrics
        return d


@dataclass
class PipelineStatus:
    """Aggregate pipeline execution status."""
    pipeline_version: str = ""
    model_version: str = "none"
    status: PipelineState = PipelineState.OK
    degraded: bool = False
    degraded_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    user_message: Optional[str] = None
    steps: list[StepStatus] = field(default_factory=list)

    def record_step(self, step: StepStatus) -> None:
        """Add a step result and update aggregate state."""
        self.steps.append(step)
        if step.status == StepState.FAIL:
            self.failed_steps.append(step.name)
            self.degraded = True
            self.degraded_steps.append(step.name)
            if self.status != PipelineState.FAILED:
                self.status = PipelineState.DEGRADED
        elif step.status == StepState.WARN:
            self.degraded = True
            self.degraded_steps.append(step.name)
            if self.status == PipelineState.OK:
                self.status = PipelineState.DEGRADED

    def mark_failed(self) -> None:
        """Mark the entire pipeline as failed (cannot proceed)."""
        self.status = PipelineState.FAILED

    def finalize(self) -> None:
        """Compute user_message after all steps have been recorded."""
        if self.degraded_steps:
            names = ", ".join(self.degraded_steps[:5])
            suffix = (
                f" (+{len(self.degraded_steps) - 5} more)"
                if len(self.degraded_steps) > 5
                else ""
            )
            self.user_message = f"Analysis degraded: {names}{suffix}"

    def to_dict(self) -> dict[str, Any]:
        self.finalize()
        return {
            "pipeline_version": self.pipeline_version,
            "model_version": self.model_version,
            "status": self.status.value,
            "degraded": self.degraded,
            "degraded_steps": self.degraded_steps,
            "user_message": self.user_message,
            "steps": [s.to_dict() for s in self.steps],
        }


# ---------------------------------------------------------------------------
# Deterministic pipeline fingerprint
# ---------------------------------------------------------------------------

# Ordered list of all pipeline step names as defined in run_full_analysis().
# This is the canonical step registry — adding/removing/renaming a step
# changes the pipeline hash and therefore the pipeline_version string.
PIPELINE_STEP_NAMES: list[str] = [
    "01_ingest",
    "02_filter",
    "03_derived_channels",
    "04_trim_session",
    "05_detect_track",
    "06_segment_laps",
    "06b_detect_corners",
    "07_normalise",
    "08_compute_metrics",
    "08b_consistency",
    "08c_robustness",
    "08d_condition_tracking",
    "08d2_track_evolution",
    "08d3_tyre_degradation",
    "08e_weather_timeline",
    "08e_invalid_laps",
    "08e2_best_n_laps",
    "08f_incomplete_laps",
    "08g_anomalous_laps",
    "08h_line_deviations",
    "08j_joker_detection",
    "09_compute_deltas",
    "09a_reference_line",
    "09b_curvature_profile",
    "09c_friction_model",
    "09d_vehicle_model",
    "09d2_kart_traction_fix",
    "09e_data_quality",
    "10_theoretical",
    "10b_theoretical_metrics",
    "10c_corner_analysis",
    "10d_per_lap_corners",
    "11_build_features",
    "12a_ml_train",
    "12b_anomaly_detection",
    "13_score_session",
    "13b_coaching_guide",
    "14a_driver_profile",
    "14a2_driving_style",
    "14b_html_report",
    "14c_pdf_report",
    "15_persist_db",
]


def compute_pipeline_hash() -> str:
    """Compute a deterministic SHA-256 hash of the pipeline step definition.

    The hash changes when steps are added, removed, or renamed — giving a
    reproducible fingerprint for the pipeline structure.

    Returns an 8-character hex prefix (sufficient for display + uniqueness).
    """
    payload = "|".join(PIPELINE_STEP_NAMES)
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


def compute_pipeline_version_string() -> str:
    """Build a version string like ``v1-a3f8b2c1``.

    Combines the integer PIPELINE_VERSION with the structural hash so
    identical code+structure always produces the same version string.
    """
    from pipeline_version import PIPELINE_VERSION
    return f"v{PIPELINE_VERSION}-{compute_pipeline_hash()}"


def get_model_version() -> str:
    """Return the current ML model version identifier, or 'none'."""
    try:
        from model_registry import get_latest_model_version
        version = get_latest_model_version("anomaly", "global")
        return version if version else "none"
    except Exception:
        return "none"


def now_monotonic() -> float:
    """Return current time in seconds (monotonic clock for duration)."""
    return time.monotonic()


def now_epoch() -> float:
    """Return current time as Unix epoch (for started_at)."""
    return time.time()
