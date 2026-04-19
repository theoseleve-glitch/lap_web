"""Understeer / oversteer handling detector with causal attribution.

Detects handling events by comparing actual yaw rate against the expected
yaw rate derived from reference curvature and speed.  Each event is tagged
with severity, corner phase, root cause, and estimated time cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class HandlingEvent:
    corner_id: int
    event_type: str           # "understeer" | "oversteer"
    severity: str             # "mild" | "moderate" | "severe"
    s_start: float
    s_end: float
    duration_s: float
    magnitude: float          # 0.0-1.0
    cause: str
    cause_detail: str
    time_cost_s: Optional[float]
    corner_phase: str         # "entry" | "mid" | "exit"
    # New fields from multi-detector fusion (Phase 5, optional for backward compat)
    confidence: Optional[float] = None           # 0-1, from Bayesian fusion
    direction: Optional[float] = None            # -1 (OS) to +1 (US)
    n_voters: Optional[int] = None               # number of detectors that voted
    conflict: Optional[bool] = None              # True if detectors disagree
    detector_votes: Optional[dict] = None        # {name: {direction, confidence}}


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_UNDERSTEER_RATIO = 0.90   # actual/expected < this → understeer
_OVERSTEER_RATIO = 1.10    # actual/expected > this → oversteer

_MILD_DEVIATION = 0.15     # deviation < 15% → mild
_MODERATE_DEVIATION = 0.30 # deviation 15-30% → moderate; >30% → severe


# ---------------------------------------------------------------------------
# BasicHandlingDetector — GPS-only
# ---------------------------------------------------------------------------

class BasicHandlingDetector:
    """Detect understeer / oversteer from GPS-derived yaw vs reference curvature."""

    def detect(
        self,
        corner_id: int,
        distances: np.ndarray,
        speeds: np.ndarray,
        reference_curvature: np.ndarray,
        actual_headings: np.ndarray,
        *,
        accel_long: Optional[np.ndarray] = None,
        steering: Optional[np.ndarray] = None,
        brake_pressure: Optional[np.ndarray] = None,
        rpm: Optional[np.ndarray] = None,
        dt: float = 0.01,
        geometric_apex_m: Optional[float] = None,
    ) -> List[HandlingEvent]:
        n = len(distances)
        if n < 3:
            return []

        # 1. Expected yaw rate (rad/m) = curvature
        expected_yaw = np.abs(reference_curvature)

        # 2. Actual yaw rate = d(heading)/d(distance)
        dh = np.diff(actual_headings)
        dd = np.diff(distances)
        dd[dd == 0] = 1e-9
        actual_yaw_raw = np.abs(dh / dd)
        # Pad to same length (forward-fill last value)
        actual_yaw = np.empty(n)
        actual_yaw[:-1] = actual_yaw_raw
        actual_yaw[-1] = actual_yaw_raw[-1]

        # 3. Ratio (guard against zero expected)
        safe_expected = np.where(expected_yaw > 1e-9, expected_yaw, 1e-9)
        ratio = actual_yaw / safe_expected

        # 4. Label each point
        labels = np.zeros(n, dtype=int)  # 0=clean, -1=understeer, +1=oversteer
        labels[ratio < _UNDERSTEER_RATIO] = -1
        labels[ratio > _OVERSTEER_RATIO] = 1

        # 5. Group contiguous spans
        spans = self._group_spans(labels, distances)

        # 6. Build events
        corner_length = distances[-1] - distances[0]
        if geometric_apex_m is None:
            geometric_apex_m = distances[0] + corner_length * 0.5

        events: List[HandlingEvent] = []
        for event_label, idx_start, idx_end in spans:
            event_type = "understeer" if event_label == -1 else "oversteer"

            # Deviation magnitude (mean absolute deviation from 1.0)
            span_ratio = ratio[idx_start:idx_end + 1]
            deviation = float(np.mean(np.abs(span_ratio - 1.0)))
            magnitude = min(deviation, 1.0)

            severity = self._classify_severity(deviation)

            s_start = float(distances[idx_start])
            s_end = float(distances[idx_end])
            span_speeds = speeds[idx_start:idx_end + 1]
            avg_speed = float(np.mean(span_speeds))
            duration_s = (s_end - s_start) / max(avg_speed, 1e-3)

            phase = self._classify_phase(
                s_start, s_end, distances[0], distances[-1], geometric_apex_m
            )

            cause, cause_detail = self._attribute_cause(
                event_type=event_type,
                phase=phase,
                accel_long=accel_long[idx_start:idx_end + 1] if accel_long is not None else None,
                speeds=span_speeds,
            )

            time_cost = magnitude * duration_s * avg_speed * 0.01

            events.append(HandlingEvent(
                corner_id=corner_id,
                event_type=event_type,
                severity=severity,
                s_start=s_start,
                s_end=s_end,
                duration_s=duration_s,
                magnitude=magnitude,
                cause=cause,
                cause_detail=cause_detail,
                time_cost_s=time_cost if time_cost > 0 else None,
                corner_phase=phase,
            ))

        return events

    # -- helpers --

    @staticmethod
    def _group_spans(labels: np.ndarray, distances: np.ndarray):
        """Return list of (label, idx_start, idx_end) for contiguous non-zero runs."""
        spans = []
        n = len(labels)
        i = 0
        while i < n:
            if labels[i] != 0:
                label = labels[i]
                start = i
                while i < n and labels[i] == label:
                    i += 1
                spans.append((label, start, i - 1))
            else:
                i += 1
        return spans

    @staticmethod
    def _classify_severity(deviation: float) -> str:
        if deviation < _MILD_DEVIATION:
            return "mild"
        elif deviation < _MODERATE_DEVIATION:
            return "moderate"
        return "severe"

    @staticmethod
    def _classify_phase(
        s_start: float,
        s_end: float,
        corner_start: float,
        corner_end: float,
        apex_m: float,
    ) -> str:
        span_mid = (s_start + s_end) / 2.0
        corner_length = corner_end - corner_start
        apex_band = 0.20 * corner_length  # 20% of corner length around apex
        if abs(span_mid - apex_m) < apex_band / 2.0:
            return "mid"
        if span_mid < apex_m:
            return "entry"
        return "exit"

    @staticmethod
    def _attribute_cause(
        event_type: str,
        phase: str,
        accel_long: Optional[np.ndarray],
        speeds: np.ndarray,
    ) -> tuple[str, str]:
        if accel_long is None:
            return "unknown", "Insufficient data for causal attribution."

        mean_accel = float(np.mean(accel_long))

        if event_type == "understeer":
            if mean_accel > 0:
                return "early_throttle", (
                    "Understeer caused by throttle application; "
                    "front tyres exceeded grip under acceleration."
                )
            if mean_accel < -1.0:
                return "brake_understeer", (
                    "Understeer under braking; front axle overloaded."
                )
            return "entry_speed", (
                "Understeer likely caused by excess entry speed."
            )

        # oversteer
        if mean_accel < -2.0:
            return "trail_brake_too_deep", (
                "Oversteer under hard trail braking; "
                "rear axle lost grip from excessive weight transfer."
            )
        if mean_accel > 0 and phase == "exit":
            return "power_oversteer", (
                "Oversteer on exit under throttle; "
                "rear tyres broke traction from power application."
            )
        if phase == "exit" and float(np.mean(speeds)) > 25.0:
            return "snap_oversteer", (
                "Snap oversteer at high speed on corner exit."
            )
        return "unknown", "Oversteer detected but cause could not be determined."


# ---------------------------------------------------------------------------
# AdvancedHandlingDetector — adds steering / brake / RPM channels
# ---------------------------------------------------------------------------

class AdvancedHandlingDetector(BasicHandlingDetector):
    """Extended detector using steering angle, brake pressure, and RPM."""

    def detect(self, *args, **kwargs) -> List[HandlingEvent]:
        events = super().detect(*args, **kwargs)
        steering = kwargs.get("steering")
        brake_pressure = kwargs.get("brake_pressure")
        rpm = kwargs.get("rpm")
        # Future: refine cause using these channels
        return events


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def detect_handling(
    corner_id: int,
    distances: np.ndarray,
    speeds: np.ndarray,
    reference_curvature: np.ndarray,
    actual_headings: np.ndarray,
    *,
    accel_long: Optional[np.ndarray] = None,
    steering: Optional[np.ndarray] = None,
    brake_pressure: Optional[np.ndarray] = None,
    rpm: Optional[np.ndarray] = None,
    dt: float = 0.01,
    geometric_apex_m: Optional[float] = None,
) -> List[HandlingEvent]:
    """Detect understeer / oversteer events for a single corner.

    Uses ``AdvancedHandlingDetector`` when extra channels are provided,
    otherwise falls back to ``BasicHandlingDetector``.
    """
    if any(ch is not None for ch in (steering, brake_pressure, rpm)):
        detector = AdvancedHandlingDetector()
    else:
        detector = BasicHandlingDetector()

    return detector.detect(
        corner_id=corner_id,
        distances=distances,
        speeds=speeds,
        reference_curvature=reference_curvature,
        actual_headings=actual_headings,
        accel_long=accel_long,
        steering=steering,
        brake_pressure=brake_pressure,
        rpm=rpm,
        dt=dt,
        geometric_apex_m=geometric_apex_m,
    )
