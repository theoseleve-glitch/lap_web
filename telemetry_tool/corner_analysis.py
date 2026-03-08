"""
corner_analysis.py
------------------
Physics-based corner-by-corner performance breakdown.

Uses the theoretical lap simulation, friction model, and actual driver
telemetry to produce a detailed per-corner analysis explaining *why* time
is lost — not just *where*.

Architecture
~~~~~~~~~~~~
1.  For each corner region (from ``corner_detection.py``), extract the
    theoretical speed profile and the driver's actual speed profile.
2.  Identify braking initiation, apex, and exit for both theoretical and
    actual.
3.  Compare entry / apex / exit speeds and braking points.
4.  Compute grip utilisation = actual lateral g / available lateral g.
5.  Decompose total corner time loss into braking / apex / exit components.
6.  Generate human-readable coaching hints.

Integration
~~~~~~~~~~~
The output feeds into ``debrief_engine.generate_next_session_drills()``
and ``reporting_html.py`` for specific, physics-based coaching.

Public API
~~~~~~~~~~
- ``analyze_corners(corners, driver_lap, theoretical_result, friction)``
- ``rank_improvement_opportunities(corner_performances)``
- ``summarize_corner_performances(perfs)`` -> dict for report embedding
- ``generate_coaching_hint(corner_perf, style, session_type)``
- ``update_best_practices(conn, track_id, corner_performances, session_id)``
"""

from __future__ import annotations

import logging
import math
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# =============================================================================

# Column constants (matching pipeline conventions)

# =============================================================================


_COL_DIST:  str = "Distance (m)"
_COL_SPEED: str = "Speed (m/s)"
_COL_LONG:  str = "accel_long_mps2"
_COL_LAT:   str = "accel_lat_mps2"

# Internal fallbacks

_COL_DIST_INT:  str = "distance_m"
_COL_SPEED_INT: str = "speed_mps"

# Physics defaults

_BRAKING_THRESHOLD_MPS2: float = -1.0    # a_long below this = braking
_TRACTION_THRESHOLD_MPS2: float = 0.5    # a_long above this = accelerating
_SEARCH_MARGIN_M: float = 50.0           # how far before s_start to look for braking initiation
_MIN_CORNER_LENGTH_M: float = 5.0        # ignore tiny corners


# =============================================================================

# Protocol for friction model (duck-typed for testability)

# =============================================================================


@runtime_checkable
class FrictionLike(Protocol):
    """Minimal interface expected from a friction model."""
    def lateral_max(self, speed: float | np.ndarray) -> np.ndarray: ...
    def braking_max(self, speed: float | np.ndarray) -> np.ndarray: ...
    def traction_max(self, speed: float | np.ndarray) -> np.ndarray: ...


# =============================================================================

# Data structures

# =============================================================================


# =============================================================================

# Corner Timeline data structures

# =============================================================================


@dataclass
class CornerEvent:
    """A single physics-defined event within a corner."""
    event_type: str           # "BP"|"EOB"|"MRP"|"MIN_SPEED"|"APEX"|"THROTTLE_ON"|"TRACK_OUT"
    s_position: float         # distance along lap [m]
    confidence: float         # 0-1 (channel quality × detection quality)
    source_channel: str       # which channel detected it
    value: float              # the signal value at that point
    available: bool           # False if channel missing

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "s_position": round(self.s_position, 2),
            "confidence": round(self.confidence, 3),
            "source_channel": self.source_channel,
            "value": round(self.value, 4),
            "available": self.available,
        }


@dataclass
class CornerTimeline:
    """Event-based timeline for a single corner across the lap."""
    corner_id: int
    events: list[CornerEvent]          # ordered by s_position
    segment_losses_s: dict[str, float] # "BP_EOB", "EOB_MRP", etc.
    segment_confidences: dict[str, float]
    mistakes: list[dict]               # [{"type": str, "severity": float, "evidence": dict}]
    mrp_strength: float                # peak prominence of yaw_rate
    mrp_stability_std_m: float         # lap-to-lap std-dev of MRP s-position
    event_stability: dict[str, float]  # std-dev per event type across laps

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id,
            "events": [e.to_dict() for e in self.events],
            "segment_losses_s": {k: round(v, 4) for k, v in self.segment_losses_s.items()},
            "segment_confidences": {k: round(v, 3) for k, v in self.segment_confidences.items()},
            "mistakes": self.mistakes,
            "mrp_strength": round(self.mrp_strength, 2),
            "mrp_stability_std_m": round(self.mrp_stability_std_m, 2),
            "event_stability": {k: round(v, 2) for k, v in self.event_stability.items()},
        }

    def get_event(self, event_type: str) -> Optional[CornerEvent]:
        """Return the first event of the given type, or None."""
        for e in self.events:
            if e.event_type == event_type:
                return e
        return None


@dataclass
class BrakeReleaseMetrics:
    """Per-corner brake release quality metrics."""
    peak_decel_mps2: float          # peak longitudinal deceleration
    peak_brake_pressure: float      # raw brake pressure if available (0 if inferred)
    brake_zone_length_m: float      # BP -> EOB distance
    brake_zone_time_s: float        # time in brake zone
    release_slope: float            # rate of brake release (units/m)
    release_linearity: float        # R^2 of release curve (1.0 = perfectly linear)
    over_drop: bool                 # pressure drops > 40% before EOB
    over_drop_severity: float       # 0-1
    late_release_risk: bool         # high brake retained into low-speed region
    late_release_severity: float    # 0-1
    terminal_trail_pct: float       # brake value at THROTTLE_ON as % of peak
    source: str                     # "brake_pressure" | "accel_inferred"
    confidence: float               # 1.0 for pressure, 0.6 for inferred

    def to_dict(self) -> dict:
        return {
            "peak_decel_mps2": round(self.peak_decel_mps2, 3),
            "peak_brake_pressure": round(self.peak_brake_pressure, 1),
            "brake_zone_length_m": round(self.brake_zone_length_m, 1),
            "brake_zone_time_s": round(self.brake_zone_time_s, 3),
            "release_slope": round(self.release_slope, 4),
            "release_linearity": round(self.release_linearity, 3),
            "over_drop": self.over_drop,
            "over_drop_severity": round(self.over_drop_severity, 2),
            "late_release_risk": self.late_release_risk,
            "late_release_severity": round(self.late_release_severity, 2),
            "terminal_trail_pct": round(self.terminal_trail_pct, 1),
            "source": self.source,
            "confidence": round(self.confidence, 2),
        }


class CornerAnalysisError(ValueError):
    """Raised when analysis encounters invalid data."""


@dataclass
class CornerPerformance:
    """Physics-based performance breakdown for a single corner."""

    corner_id:   int
    s_start:     float          # metres — corner entry distance
    s_end:       float          # metres — corner exit distance

    # Speed comparison (m/s)

    theoretical_entry_speed_mps: float = 0.0
    actual_entry_speed_mps:      float = 0.0
    theoretical_apex_speed_mps:  float = 0.0
    actual_apex_speed_mps:       float = 0.0
    theoretical_exit_speed_mps:  float = 0.0
    actual_exit_speed_mps:       float = 0.0

    # Braking point comparison (metres from lap start)

    braking_point_theoretical_m: float = float("nan")
    braking_point_actual_m:      float = float("nan")
    braking_point_delta_m:       float = 0.0     # positive = braked too early

    # Grip utilisation at apex (0–100 %)

    grip_utilisation_pct:        float = 0.0

    # Time loss decomposition (seconds, positive = time lost)

    time_loss_s:                 float = 0.0
    time_loss_braking_s:         float = 0.0
    time_loss_apex_speed_s:      float = 0.0
    time_loss_exit_s:            float = 0.0

    # Coaching

    coaching_hint: str = ""
    limiting_factor: str = ""       # "cornering"|"traction"|"braking"|"cap"
    corner_priority: str = ""       # "entry"|"exit"|"balanced"
    coaching_text: str = ""         # physics-aware coaching sentence

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id":                     self.corner_id,
            "s_start":                       round(self.s_start, 2),
            "s_end":                         round(self.s_end, 2),
            "theoretical_entry_speed_mps":   round(self.theoretical_entry_speed_mps, 2),
            "actual_entry_speed_mps":        round(self.actual_entry_speed_mps, 2),
            "theoretical_apex_speed_mps":    round(self.theoretical_apex_speed_mps, 2),
            "actual_apex_speed_mps":         round(self.actual_apex_speed_mps, 2),
            "theoretical_exit_speed_mps":    round(self.theoretical_exit_speed_mps, 2),
            "actual_exit_speed_mps":         round(self.actual_exit_speed_mps, 2),
            "braking_point_theoretical_m":   round(self.braking_point_theoretical_m, 1),
            "braking_point_actual_m":        round(self.braking_point_actual_m, 1),
            "braking_point_delta_m":         round(self.braking_point_delta_m, 1),
            "grip_utilisation_pct":          round(self.grip_utilisation_pct, 1),
            "time_loss_s":                   round(self.time_loss_s, 3),
            "time_loss_braking_s":           round(self.time_loss_braking_s, 3),
            "time_loss_apex_speed_s":        round(self.time_loss_apex_speed_s, 3),
            "time_loss_exit_s":              round(self.time_loss_exit_s, 3),
            "coaching_hint":                 self.coaching_hint,
            "limiting_factor":               self.limiting_factor,
            "corner_priority":               self.corner_priority,
            "coaching_text":                 self.coaching_text,
        }


# =============================================================================

# Internal helpers

# =============================================================================


def _resolve_dist(df: pd.DataFrame) -> np.ndarray:
    """Extract distance array from a DataFrame, trying multiple column names."""
    for col in (_COL_DIST, _COL_DIST_INT, "dist_m"):
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").values.astype(float)
    raise CornerAnalysisError(
        f"No distance column found.  Tried: {_COL_DIST}, {_COL_DIST_INT}, dist_m"
    )


def _resolve_speed(df: pd.DataFrame) -> np.ndarray:
    """Extract speed array from a DataFrame."""
    for col in (_COL_SPEED, _COL_SPEED_INT, "v_env_mps"):
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").values.astype(float)
    raise CornerAnalysisError(
        f"No speed column found.  Tried: {_COL_SPEED}, {_COL_SPEED_INT}, v_env_mps"
    )


def _resolve_accel_long(df: pd.DataFrame) -> np.ndarray:
    """Extract longitudinal acceleration, computing from speed if absent."""
    for col in (_COL_LONG, "Longitudinal acceleration (G) *calc"):
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").values.astype(float)
            # Convert from G if the column name says so

            if "(G)" in col:
                vals = vals * 9.80665
            return vals

    # Fall back: finite differences of speed vs distance

    try:
        dist = _resolve_dist(df)
        speed = _resolve_speed(df)
        ds = np.diff(dist)
        ds[ds == 0] = 1e-6
        dv = np.diff(speed)
        # a = v * dv/ds

        mid_speed = 0.5 * (speed[:-1] + speed[1:])
        a_long = mid_speed * dv / ds
        return np.append(a_long, a_long[-1] if len(a_long) > 0 else 0.0)
    except Exception:
        return np.full(len(df), np.nan)


def _resolve_accel_lat(df: pd.DataFrame) -> np.ndarray:
    """Extract lateral acceleration."""
    for col in (_COL_LAT, "Lateral acceleration (G) *calc"):
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").values.astype(float)
            if "(G)" in col:
                vals = vals * 9.80665
            return np.abs(vals)
    return np.full(len(df), np.nan)


def _interp_at(x: np.ndarray, y: np.ndarray, xi: float) -> float:
    """Linearly interpolate y at xi from sorted x/y arrays."""
    if len(x) == 0 or len(y) == 0:
        return float("nan")
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 2:
        return float("nan")
    return float(np.interp(xi, x[mask], y[mask]))


def _slice_range(
    dist: np.ndarray,
    s_start: float,
    s_end: float,
) -> np.ndarray:
    """Return boolean mask for points within [s_start, s_end]."""
    return (dist >= s_start) & (dist <= s_end)


def _integrate_time(dist: np.ndarray, speed: np.ndarray) -> float:
    """Integrate dt = ds / v over a distance-speed profile."""
    mask = np.isfinite(dist) & np.isfinite(speed) & (speed > 0.1)
    if mask.sum() < 2:
        return 0.0
    d = dist[mask]
    v = speed[mask]
    ds = np.diff(d)
    inv_v = 1.0 / v
    dt = 0.5 * (inv_v[:-1] + inv_v[1:]) * np.abs(ds)
    return float(np.sum(dt))


def _find_braking_point(
    dist: np.ndarray,
    accel: np.ndarray,
    corner_entry_m: float,
    search_margin_m: float = _SEARCH_MARGIN_M,
    threshold: float = _BRAKING_THRESHOLD_MPS2,
) -> float:
    """
    Find the distance where sustained braking begins before a corner entry.

    Scans backward from ``corner_entry_m`` looking for where longitudinal
    acceleration drops below *threshold* (sustained for at least 2 points).
    """
    search_start = corner_entry_m - search_margin_m
    mask = (dist >= search_start) & (dist <= corner_entry_m)
    if mask.sum() < 3:
        return float("nan")

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    a_seg = accel[idx]

    # Scan backward from the end (closest to corner entry)

    braking_idx = len(a_seg) - 1
    consecutive = 0
    for i in range(len(a_seg) - 1, -1, -1):
        if np.isfinite(a_seg[i]) and a_seg[i] < threshold:
            consecutive += 1
            if consecutive >= 2:
                braking_idx = i
        else:
            if consecutive >= 2:
                break
            consecutive = 0

    if consecutive < 2:
        return float("nan")

    return float(d_seg[braking_idx])


def _generate_coaching_hint(perf: CornerPerformance) -> str:
    """Build a human-readable coaching hint from corner performance data."""
    parts: list[str] = []

    # Braking point advice

    delta_m = perf.braking_point_delta_m
    if math.isfinite(delta_m) and abs(delta_m) > 2.0:
        if delta_m > 0:
            parts.append(f"Brake {delta_m:.0f}m later")
        else:
            parts.append(f"Brake {abs(delta_m):.0f}m earlier")

    # Apex speed advice

    apex_deficit = perf.theoretical_apex_speed_mps - perf.actual_apex_speed_mps
    if apex_deficit > 0.5:
        parts.append(f"carry {apex_deficit:.1f} m/s more apex speed")

    # Grip utilisation advice

    if perf.grip_utilisation_pct < 80.0 and perf.grip_utilisation_pct > 0:
        parts.append(
            f"you're using {perf.grip_utilisation_pct:.0f}% of available "
            f"grip — trust the front end more"
        )

    # Exit advice

    exit_deficit = perf.theoretical_exit_speed_mps - perf.actual_exit_speed_mps
    if exit_deficit > 1.0:
        parts.append(f"get on the throttle earlier for {exit_deficit:.1f} m/s more exit speed")

    if not parts:
        if perf.time_loss_s < 0.05:
            return "On pace — well driven."
        return "Small time loss — refine your line through this section."

    # Capitalise first part

    hint = ", ".join(parts)
    hint = hint[0].upper() + hint[1:]
    if not hint.endswith("."):
        hint += "."
    return hint


# =============================================================================

# Public API

# =============================================================================


def analyze_corners(
    corners:              list[dict[str, Any]],
    driver_lap:           pd.DataFrame,
    theoretical_result:   Any,
    friction:             Any,
    *,
    braking_threshold:    float = _BRAKING_THRESHOLD_MPS2,
    search_margin_m:      float = _SEARCH_MARGIN_M,
) -> list[CornerPerformance]:
    """
    Produce a physics-based performance breakdown for every corner.

    Parameters
    ----------
    corners:
        List of dicts from ``corner_detection.detect_corners``.
        Each has ``corner_id``, ``s_start``, ``s_end``.
    driver_lap:
        Distance-resampled DataFrame for the driver's lap.
        Expected columns: ``Distance (m)``, ``Speed (m/s)``,
        ``accel_long_mps2``, ``accel_lat_mps2``.
    theoretical_result:
        ``TheoreticalLapResult`` from ``lap_simulation.simulate_theoretical_lap``.
        Must have ``distance_m``, ``speed_profile``, ``accel_profile``.
    friction:
        ``FrictionCircle`` (or compatible object) with ``lateral_max(speed)``.

    Returns
    -------
    list[CornerPerformance]
        One entry per corner, sorted by ``corner_id``.
    """
    if not corners:
        return []

    # Extract arrays from the driver lap

    drv_dist  = _resolve_dist(driver_lap)
    drv_speed = _resolve_speed(driver_lap)
    drv_along = _resolve_accel_long(driver_lap)
    drv_alat  = _resolve_accel_lat(driver_lap)

    # Extract arrays from theoretical result — supports both
    # SimulationResult (attributes) and DataFrame (columns) formats.

    if isinstance(theoretical_result, pd.DataFrame):
        # DataFrame from build_theoretical_lap / result_to_theoretical_df
        _dist_col  = "distance_m"
        _speed_col = next(
            (c for c in ("v_env_mps", "speed_mps", "Speed (m/s)")
             if c in theoretical_result.columns),
            None,
        )
        _accel_col = next(
            (c for c in ("accel_max_mps2", "accel_long_mps2")
             if c in theoretical_result.columns),
            None,
        )
        if _dist_col not in theoretical_result.columns or _speed_col is None:
            return []  # cannot proceed without distance + speed

        theo_dist  = theoretical_result[_dist_col].to_numpy(dtype=float)
        theo_speed = theoretical_result[_speed_col].to_numpy(dtype=float)
        if _accel_col is not None:
            theo_accel = theoretical_result[_accel_col].to_numpy(dtype=float)
        else:
            # Derive accel from speed gradient
            dt_approx = np.gradient(theo_dist) / np.clip(theo_speed, 1.0, None)
            theo_accel = np.gradient(theo_speed) / np.clip(dt_approx, 1e-6, None)
    else:
        # SimulationResult-like object with attributes
        theo_dist  = np.asarray(theoretical_result.distance_m, dtype=float)
        theo_speed = np.asarray(
            getattr(theoretical_result, "speed_profile",
                    getattr(theoretical_result, "v_env_mps", [])),
            dtype=float,
        )
        theo_accel = np.asarray(
            getattr(theoretical_result, "accel_profile",
                    getattr(theoretical_result, "accel_max_mps2", [])),
            dtype=float,
        )

    results: list[CornerPerformance] = []

    for corner in corners:
        cid     = int(corner.get("corner_id", 0))
        s_start = float(corner.get("s_start", 0.0))
        s_end   = float(corner.get("s_end", 0.0))

        if s_end - s_start < _MIN_CORNER_LENGTH_M:
            continue

        try:
            perf = _analyze_single_corner(
                cid, s_start, s_end,
                drv_dist, drv_speed, drv_along, drv_alat,
                theo_dist, theo_speed, theo_accel,
                friction,
                braking_threshold=braking_threshold,
                search_margin_m=search_margin_m,
            )
            results.append(perf)
        except Exception as exc:
            logger.warning("Corner %d analysis failed: %s", cid, exc)
            results.append(CornerPerformance(
                corner_id=cid, s_start=s_start, s_end=s_end,
                coaching_hint=f"Analysis failed: {exc}",
            ))

    return sorted(results, key=lambda p: p.corner_id)


def _analyze_single_corner(
    cid: int,
    s_start: float,
    s_end: float,
    drv_dist: np.ndarray,
    drv_speed: np.ndarray,
    drv_along: np.ndarray,
    drv_alat: np.ndarray,
    theo_dist: np.ndarray,
    theo_speed: np.ndarray,
    theo_accel: np.ndarray,
    friction: Any,
    *,
    braking_threshold: float,
    search_margin_m: float,
) -> CornerPerformance:
    """Analyse a single corner (called by analyze_corners)."""

    corner_len = s_end - s_start
    s_mid = (s_start + s_end) / 2.0

    # Entry = first 20% of corner, exit = last 20%

    entry_end  = s_start + corner_len * 0.20
    exit_start = s_end   - corner_len * 0.20

    # --- Theoretical speeds at key points
    theo_entry = _interp_at(theo_dist, theo_speed, s_start)
    theo_exit  = _interp_at(theo_dist, theo_speed, s_end)

    # Apex = minimum speed within corner region

    theo_mask = _slice_range(theo_dist, s_start, s_end)
    if theo_mask.sum() > 0:
        theo_corner_speed = theo_speed[theo_mask]
        finite = np.isfinite(theo_corner_speed)
        if finite.sum() > 0:
            theo_apex = float(np.min(theo_corner_speed[finite]))
        else:
            theo_apex = _interp_at(theo_dist, theo_speed, s_mid)
    else:
        theo_apex = _interp_at(theo_dist, theo_speed, s_mid)

    # --- Driver speeds at key points -- -

    drv_entry = _interp_at(drv_dist, drv_speed, s_start)
    drv_exit  = _interp_at(drv_dist, drv_speed, s_end)

    drv_mask = _slice_range(drv_dist, s_start, s_end)
    if drv_mask.sum() > 0:
        drv_corner_speed = drv_speed[drv_mask]
        finite = np.isfinite(drv_corner_speed)
        if finite.sum() > 0:
            drv_apex = float(np.min(drv_corner_speed[finite]))
        else:
            drv_apex = _interp_at(drv_dist, drv_speed, s_mid)
    else:
        drv_apex = _interp_at(drv_dist, drv_speed, s_mid)

    # --- Braking point comparison
    bp_theo = _find_braking_point(
        theo_dist, theo_accel, s_start,
        search_margin_m=search_margin_m,
        threshold=braking_threshold,
    )
    bp_drv = _find_braking_point(
        drv_dist, drv_along, s_start,
        search_margin_m=search_margin_m,
        threshold=braking_threshold,
    )

    bp_delta = 0.0
    if math.isfinite(bp_theo) and math.isfinite(bp_drv):
        bp_delta = bp_theo - bp_drv  # positive = driver braked earlier

    # --- Grip utilisation at apex
    grip_pct = 0.0
    if drv_mask.sum() > 0:
        drv_lat_corner = drv_alat[drv_mask]
        drv_spd_corner = drv_speed[drv_mask]

        # Find the apex region (points near minimum speed)

        finite_spd = np.isfinite(drv_spd_corner)
        if finite_spd.sum() > 0:
            min_spd = float(np.min(drv_spd_corner[finite_spd]))
            apex_region = finite_spd & (drv_spd_corner <= min_spd * 1.05)

            if apex_region.sum() > 0 and friction is not None:
                actual_lat = np.nanmean(np.abs(drv_lat_corner[apex_region]))
                apex_speed_for_grip = max(min_spd, 0.1)

                try:
                    available_lat = float(
                        np.asarray(friction.lateral_max(apex_speed_for_grip)).flat[0]
                    )
                    if available_lat > 0:
                        grip_pct = min(100.0, actual_lat / available_lat * 100.0)
                except Exception:
                    pass

    # --- Time loss decomposition -- -

    # Total time through corner: integrate dt = ds / v

    # Extend window slightly to capture approach braking zone

    approach_start = max(
        min(bp_theo, bp_drv) if (math.isfinite(bp_theo) and math.isfinite(bp_drv))
        else s_start - 30.0,
        0.0,
    )

    total_theo_time = _integrate_time(
        theo_dist[_slice_range(theo_dist, approach_start, s_end)],
        theo_speed[_slice_range(theo_dist, approach_start, s_end)],
    )
    total_drv_time = _integrate_time(
        drv_dist[_slice_range(drv_dist, approach_start, s_end)],
        drv_speed[_slice_range(drv_dist, approach_start, s_end)],
    )
    total_loss = max(0.0, total_drv_time - total_theo_time)

    # Decompose into three phases:

    #   braking: approach_start -> s_start

    #   apex:    s_start -> exit_start

    #   exit:    exit_start -> s_end


    def _phase_loss(s0: float, s1: float) -> float:
        t_theo = _integrate_time(
            theo_dist[_slice_range(theo_dist, s0, s1)],
            theo_speed[_slice_range(theo_dist, s0, s1)],
        )
        t_drv = _integrate_time(
            drv_dist[_slice_range(drv_dist, s0, s1)],
            drv_speed[_slice_range(drv_dist, s0, s1)],
        )
        return max(0.0, t_drv - t_theo)

    loss_braking = _phase_loss(approach_start, s_start)
    loss_apex    = _phase_loss(s_start, exit_start)
    loss_exit    = _phase_loss(exit_start, s_end)

    # Normalise so components sum to total (avoid floating-point drift)

    component_sum = loss_braking + loss_apex + loss_exit
    if component_sum > 0 and total_loss > 0:
        scale = total_loss / component_sum
        loss_braking *= scale
        loss_apex    *= scale
        loss_exit    *= scale

    perf = CornerPerformance(
        corner_id=cid,
        s_start=s_start,
        s_end=s_end,
        theoretical_entry_speed_mps=theo_entry if math.isfinite(theo_entry) else 0.0,
        actual_entry_speed_mps=drv_entry if math.isfinite(drv_entry) else 0.0,
        theoretical_apex_speed_mps=theo_apex if math.isfinite(theo_apex) else 0.0,
        actual_apex_speed_mps=drv_apex if math.isfinite(drv_apex) else 0.0,
        theoretical_exit_speed_mps=theo_exit if math.isfinite(theo_exit) else 0.0,
        actual_exit_speed_mps=drv_exit if math.isfinite(drv_exit) else 0.0,
        braking_point_theoretical_m=bp_theo,
        braking_point_actual_m=bp_drv,
        braking_point_delta_m=round(bp_delta, 1),
        grip_utilisation_pct=round(grip_pct, 1),
        time_loss_s=round(total_loss, 4),
        time_loss_braking_s=round(loss_braking, 4),
        time_loss_apex_speed_s=round(loss_apex, 4),
        time_loss_exit_s=round(loss_exit, 4),
    )

    perf.coaching_hint = _generate_coaching_hint(perf)
    return perf


def rank_improvement_opportunities(
    corner_performances: list[CornerPerformance],
    corner_timelines: Optional[list] = None,
) -> list[CornerPerformance]:
    """
    Sort corners by composite priority (descending).

    Weights: time_loss_s (0.6), mistake_severities (0.2),
    mrp_stability (0.1, inverted), max_segment_loss (0.1).

    When *corner_timelines* is ``None`` (legacy callers), falls back
    to simple time-loss sorting.
    """
    if corner_timelines is None:
        return sorted(corner_performances, key=lambda p: p.time_loss_s, reverse=True)

    # Build lookup: corner_id -> timeline (dict or CornerTimeline)
    tl_map: dict = {}
    for tl in corner_timelines:
        cid = tl.corner_id if hasattr(tl, "corner_id") else tl.get("corner_id")
        if cid is not None:
            tl_map[cid] = tl

    def _score(p: CornerPerformance) -> float:
        score = p.time_loss_s * 0.6
        tl = tl_map.get(p.corner_id)
        if tl is not None:
            mistakes = tl.mistakes if hasattr(tl, "mistakes") else tl.get("mistakes", [])
            mistake_sum = sum(m.get("severity", 0) for m in mistakes)
            score += mistake_sum * 0.2

            mrp_std = (tl.mrp_stability_std_m if hasattr(tl, "mrp_stability_std_m")
                       else tl.get("mrp_stability_std_m", 0.0))
            score += min(mrp_std / 20.0, 1.0) * 0.1

            seg_losses = (tl.segment_losses_s if hasattr(tl, "segment_losses_s")
                          else tl.get("segment_losses_s", {}))
            if seg_losses:
                score += max(seg_losses.values()) * 0.1
        return score

    return sorted(corner_performances, key=_score, reverse=True)


def summarize_corner_performances(
    perfs: list[CornerPerformance],
) -> dict[str, Any]:
    """
    Produce a summary dict suitable for embedding in pipeline summary or
    report data.

    Returns
    -------
    dict with keys:
        ``n_corners``              -- total corners analysed
        ``total_corner_time_loss_s`` -- sum of all corner time losses
        ``worst_corner_id``        -- corner with most time loss
        ``worst_corner_loss_s``    -- time loss at worst corner
        ``mean_grip_utilisation_pct`` -- average grip usage at apexes
        ``corners``                -- list of per-corner dicts
        ``improvement_priority``   -- ordered list of corner_ids
    """
    if not perfs:
        return {
            "n_corners": 0,
            "total_corner_time_loss_s": 0.0,
            "worst_corner_id": None,
            "worst_corner_loss_s": 0.0,
            "mean_grip_utilisation_pct": 0.0,
            "corners": [],
            "improvement_priority": [],
        }

    total_loss = sum(p.time_loss_s for p in perfs)
    ranked = rank_improvement_opportunities(perfs)

    grip_vals = [p.grip_utilisation_pct for p in perfs if p.grip_utilisation_pct > 0]
    mean_grip = float(np.mean(grip_vals)) if grip_vals else 0.0

    return {
        "n_corners":                 len(perfs),
        "total_corner_time_loss_s":  round(total_loss, 3),
        "worst_corner_id":           ranked[0].corner_id if ranked else None,
        "worst_corner_loss_s":       round(ranked[0].time_loss_s, 3) if ranked else 0.0,
        "mean_grip_utilisation_pct": round(mean_grip, 1),
        "corners":                   [p.to_dict() for p in perfs],
        "improvement_priority":      [p.corner_id for p in ranked],
    }


def generate_coaching_hint(
    corner_perf: dict[str, Any],
    style: Optional[str] = None,
    session_type: Optional[str] = None,
) -> str:
    """
    Generate a context-aware coaching hint for a corner.

    Combines physics-based analysis with driving style and session type
    to produce actionable, 1-sentence coaching cues.

    Parameters
    ----------
    corner_perf : dict
        Corner performance dict (from CornerPerformance.to_dict()).
    style : str, optional
        Driver's classified style (e.g. 'smooth', 'aggressive').
    session_type : str, optional
        Session type (e.g. 'qualifying', 'race', 'practice').

    Returns
    -------
    str — coaching hint tailored to context.
    """
    parts: list[str] = []
    style = (style or "").lower()
    session_type = (session_type or "practice").lower()

    # Braking advice
    delta_m = corner_perf.get("braking_point_delta_m", 0.0)
    if delta_m is not None and abs(delta_m) > 2.0:
        if delta_m > 0:
            if style == "aggressive":
                parts.append(f"hold brakes {delta_m:.0f}m longer — trust your late-braking instinct")
            elif style == "conservative":
                parts.append(f"try braking {delta_m:.0f}m later — you have more grip available")
            else:
                parts.append(f"brake {delta_m:.0f}m later")
        else:
            if style == "aggressive":
                parts.append(f"ease the brake point {abs(delta_m):.0f}m earlier — protect tyre life")
            else:
                parts.append(f"brake {abs(delta_m):.0f}m earlier for stability")

    # Apex speed advice
    theo_apex = corner_perf.get("theoretical_apex_speed_mps", 0)
    actual_apex = corner_perf.get("actual_apex_speed_mps", 0)
    if theo_apex and actual_apex:
        apex_deficit = theo_apex - actual_apex
        if apex_deficit > 0.5:
            if session_type in ("qualifying", "sprint"):
                parts.append(f"commit to {apex_deficit:.1f} m/s more apex speed — it's worth it for the lap time")
            elif session_type in ("race", "endurance_race", "endurance_stint"):
                parts.append(f"consider carrying {apex_deficit:.1f} m/s more through apex while managing tyres")
            else:
                parts.append(f"carry {apex_deficit:.1f} m/s more apex speed")

    # Grip utilisation
    grip = corner_perf.get("grip_utilisation_pct", 0)
    if grip and 0 < grip < 80:
        if style == "conservative":
            parts.append(f"using only {grip:.0f}% grip — build confidence to push harder")
        else:
            parts.append(f"using {grip:.0f}% grip — trust the front end")

    # Exit advice
    theo_exit = corner_perf.get("theoretical_exit_speed_mps", 0)
    actual_exit = corner_perf.get("actual_exit_speed_mps", 0)
    if theo_exit and actual_exit:
        exit_deficit = theo_exit - actual_exit
        if exit_deficit > 1.0:
            parts.append(f"get on throttle earlier for {exit_deficit:.1f} m/s more exit speed")

    if not parts:
        time_loss = corner_perf.get("time_loss_s", 0)
        if time_loss is not None and time_loss < 0.05:
            return "On pace — well driven."
        return "Small time loss — refine your line through this section."

    hint = ", ".join(parts)
    hint = hint[0].upper() + hint[1:]
    if not hint.endswith("."):
        hint += "."
    return hint


def update_best_practices(
    conn: Any,
    track_id: str,
    corner_performances: list[dict[str, Any]],
    session_id: str,
) -> int:
    """
    Update corner best practices from a session's corner performance data.

    For each corner, if the session's best time at that corner is faster
    than the stored best practice, update it. Also increments sample count
    and appends session_id to source_sessions.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database connection.
    track_id : str
        Track identifier.
    corner_performances : list[dict]
        List of corner performance dicts (from CornerPerformance.to_dict()).
    session_id : str
        Current session ID.

    Returns
    -------
    int — number of corners updated.
    """
    if not corner_performances or not track_id:
        return 0

    updated = 0
    for perf in corner_performances:
        cid = perf.get("corner_id")
        if cid is None:
            continue

        # Get existing best practice
        existing = conn.execute(
            "SELECT * FROM corner_best_practices "
            "WHERE track_id = :track_id AND corner_id = :corner_id",
            {"track_id": track_id, "corner_id": cid},
        ).fetchone()

        # Calculate time through corner from integration (s_end - s_start) / speed
        entry_spd = perf.get("actual_entry_speed_mps", 0) or 0
        apex_spd = perf.get("actual_apex_speed_mps", 0) or 0
        exit_spd = perf.get("actual_exit_speed_mps", 0) or 0
        s_start = perf.get("s_start", 0) or 0
        s_end = perf.get("s_end", 0) or 0
        corner_length = s_end - s_start

        # Approximate corner time via trapezoidal speed integration
        avg_speed = (entry_spd + apex_spd + exit_spd) / 3.0
        corner_time = corner_length / max(avg_speed, 0.1) if corner_length > 0 else 0

        if existing:
            existing = dict(existing)
            old_time = existing.get("best_time_s") or float("inf")
            old_sources = existing.get("source_sessions", "") or ""
            sample_count = (existing.get("sample_count") or 0) + 1

            # Append session_id to source list (keep last 10)
            sources = [s for s in old_sources.split(",") if s.strip()]
            if session_id not in sources:
                sources.append(session_id)
            sources = sources[-10:]

            if corner_time > 0 and corner_time < old_time:
                # New best time — update all fields
                conn.execute(
                    "UPDATE corner_best_practices SET "
                    "best_entry_mps = :entry, best_apex_mps = :apex, "
                    "best_exit_mps = :exit, best_brake_m = :brake, "
                    "best_throttle_onset_m = :throttle, best_time_s = :time, "
                    "sample_count = :count, source_sessions = :sources, "
                    "updated_at = datetime('now') "
                    "WHERE track_id = :track_id AND corner_id = :corner_id",
                    {
                        "entry": entry_spd, "apex": apex_spd, "exit": exit_spd,
                        "brake": perf.get("braking_point_actual_m"),
                        "throttle": None,  # Would need throttle onset data
                        "time": round(corner_time, 4),
                        "count": sample_count,
                        "sources": ",".join(sources),
                        "track_id": track_id, "corner_id": cid,
                    },
                )
                updated += 1
            else:
                # Just update sample count and sources
                conn.execute(
                    "UPDATE corner_best_practices SET "
                    "sample_count = :count, source_sessions = :sources, "
                    "updated_at = datetime('now') "
                    "WHERE track_id = :track_id AND corner_id = :corner_id",
                    {
                        "count": sample_count,
                        "sources": ",".join(sources),
                        "track_id": track_id, "corner_id": cid,
                    },
                )
        else:
            # First time seeing this corner — insert
            conn.execute(
                "INSERT INTO corner_best_practices "
                "(track_id, corner_id, best_entry_mps, best_apex_mps, "
                "best_exit_mps, best_brake_m, best_throttle_onset_m, "
                "best_time_s, sample_count, source_sessions) "
                "VALUES (:track_id, :corner_id, :entry, :apex, :exit, "
                ":brake, :throttle, :time, 1, :sources)",
                {
                    "track_id": track_id, "corner_id": cid,
                    "entry": entry_spd, "apex": apex_spd, "exit": exit_spd,
                    "brake": perf.get("braking_point_actual_m"),
                    "throttle": None,
                    "time": round(corner_time, 4) if corner_time > 0 else None,
                    "sources": session_id,
                },
            )
            updated += 1

    conn.commit()
    return updated


# =============================================================================

# Corner coaching labels

# =============================================================================


_COACHING_TEMPLATES: dict[tuple[str, str], str] = {
    ("cornering", "balanced"): (
        "Grip-limited through corner {cid}. Focus on racing line "
        "to increase minimum speed."
    ),
    ("cornering", "exit"): (
        "Grip-limited through corner {cid}. Smooth throttle application "
        "after apex — the {straight_m:.0f}m straight rewards exit speed."
    ),
    ("traction", "exit"): (
        "Traction-limited on exit of corner {cid}. Prioritize rotation "
        "before throttle — the {straight_m:.0f}m straight amplifies "
        "exit speed gain."
    ),
    ("traction", "balanced"): (
        "Traction-limited through corner {cid}. Progressive throttle "
        "to manage wheelspin."
    ),
    ("braking", "entry"): (
        "Braking-limited into corner {cid}. You can brake later — "
        "entry speed directly feeds the {straight_m:.0f}m straight."
    ),
    ("braking", "balanced"): (
        "Braking-limited into corner {cid}. Trail-braking deeper "
        "may unlock more rotation."
    ),
    ("cap", "exit"): (
        "Near vehicle limit through corner {cid}. Focus on consistency."
    ),
    ("cap", "balanced"): (
        "At speed cap through corner {cid}. You are driving near "
        "the vehicle's maximum capability."
    ),
}


def compute_corner_coaching_labels(
    *,
    corners: list[dict],
    limiting_factors: "np.ndarray",
    distance_m: "np.ndarray",
    lap_length_m: float,
) -> list[dict]:
    """Compute per-corner coaching labels from solver limiting factors."""
    if not corners or len(limiting_factors) == 0:
        return []

    sorted_corners = sorted(corners, key=lambda c: c.get("s_start", 0))
    results = []

    for idx, corner in enumerate(sorted_corners):
        cid = corner.get("corner_id", idx + 1)
        s_start = corner.get("s_start", 0)
        s_end = corner.get("s_end", 0)

        if idx + 1 < len(sorted_corners):
            next_s_start = sorted_corners[idx + 1].get("s_start", lap_length_m)
        else:
            next_s_start = lap_length_m
        next_straight_m = max(0, next_s_start - s_end)

        mask = (distance_m >= s_start) & (distance_m <= s_end)
        if not mask.any():
            results.append({
                "corner_id": cid,
                "limiting_factor": "cap",
                "corner_priority": "balanced",
                "coaching_text": f"No data for corner {cid}.",
            })
            continue

        factors = limiting_factors[mask]
        counts = {}
        for f in factors:
            counts[f] = counts.get(f, 0) + 1
        dominant = max(counts, key=counts.get)

        if dominant == "braking" and next_straight_m > 100:
            priority = "entry"
        elif dominant == "traction" and next_straight_m > 80:
            priority = "exit"
        elif dominant == "cornering":
            priority = "balanced"
        else:
            priority = "exit"

        template_key = (dominant, priority)
        template = _COACHING_TEMPLATES.get(
            template_key,
            _COACHING_TEMPLATES.get(
                (dominant, "balanced"),
                "Focus on corner {cid} technique.",
            ),
        )
        coaching_text = template.format(cid=cid, straight_m=next_straight_m)

        results.append({
            "corner_id": cid,
            "limiting_factor": dominant,
            "corner_priority": priority,
            "coaching_text": coaching_text,
        })

    return results


# =============================================================================

# Self-test

# =============================================================================


def _run_tests() -> None:
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Synthetic data factories -- -


    _G = 9.80665
    N_PTS = 500
    TRACK_LEN = 800.0

    def _make_oval_dist() -> np.ndarray:
        return np.linspace(0, TRACK_LEN, N_PTS, endpoint=False)

    def _make_speed_profile(
        dist: np.ndarray,
        base: float = 25.0,
        amplitude: float = 10.0,
    ) -> np.ndarray:
        """Sinusoidal speed: fast on straights, slow at corners."""
        s = dist / TRACK_LEN
        return base + amplitude * np.cos(4 * np.pi * s)

    def _make_driver_lap(
        dist: np.ndarray,
        speed: np.ndarray,
        noise: float = 0.5,
        seed: int = 42,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        drv_speed = speed - abs(rng.normal(1.0, noise, len(speed)))
        drv_speed = np.clip(drv_speed, 3.0, 50.0)
        dt = np.diff(dist) / np.maximum(0.5 * (drv_speed[:-1] + drv_speed[1:]), 0.1)
        t = np.concatenate([[0.0], np.cumsum(dt)])

        a_long = np.gradient(drv_speed, t)
        a_lat = drv_speed ** 2 / 50.0 * np.abs(np.sin(4 * np.pi * dist / TRACK_LEN))

        return pd.DataFrame({
            _COL_DIST: dist,
            _COL_SPEED: drv_speed,
            _COL_LONG: a_long,
            _COL_LAT: a_lat,
            "Time (s)": t,
        })

    class MockTheoResult:
        def __init__(self, dist, speed):
            self.distance_m = dist
            self.speed_profile = speed
            self.accel_profile = np.gradient(speed, dist)
            self.lap_time_s = _integrate_time(dist, speed)

    class MockFriction:
        def lateral_max(self, speed):
            return np.full_like(np.atleast_1d(speed), 1.2 * _G, dtype=float)
        def braking_max(self, speed):
            return np.full_like(np.atleast_1d(speed), 1.3 * _G, dtype=float)
        def traction_max(self, speed):
            return np.full_like(np.atleast_1d(speed), 0.8 * _G, dtype=float)

    def _make_corners() -> list[dict[str, Any]]:
        """Two corners at the speed minima of our sinusoidal profile."""
        return [
            {"corner_id": 1, "s_start": 150.0, "s_end": 250.0},
            {"corner_id": 2, "s_start": 550.0, "s_end": 650.0},
        ]

    # -- Tests

    def t_resolve_dist():
        df = pd.DataFrame({_COL_DIST: [0, 1, 2]})
        d = _resolve_dist(df)
        assert len(d) == 3
        assert d[2] == 2.0

    _test("resolve_dist", t_resolve_dist)

    def t_resolve_dist_internal():
        df = pd.DataFrame({"distance_m": [0, 5, 10]})
        d = _resolve_dist(df)
        assert d[1] == 5.0

    _test("resolve_dist_internal", t_resolve_dist_internal)

    def t_resolve_speed():
        df = pd.DataFrame({_COL_SPEED: [10, 20, 30]})
        s = _resolve_speed(df)
        assert s[1] == 20.0

    _test("resolve_speed", t_resolve_speed)

    def t_resolve_dist_missing():
        df = pd.DataFrame({"other": [1, 2]})
        try:
            _resolve_dist(df)
            assert False, "Should have raised"
        except CornerAnalysisError:
            pass

    _test("resolve_dist_missing", t_resolve_dist_missing)

    def t_interp_at():
        x = np.array([0.0, 10.0, 20.0])
        y = np.array([0.0, 5.0, 10.0])
        assert abs(_interp_at(x, y, 15.0) - 7.5) < 0.01

    _test("interp_at", t_interp_at)

    def t_integrate_time():
        dist = np.array([0.0, 100.0])
        speed = np.array([20.0, 20.0])
        t = _integrate_time(dist, speed)
        assert abs(t - 5.0) < 0.01, f"Expected 5.0, got {t}"

    _test("integrate_time", t_integrate_time)

    def t_find_braking_point():
        dist = np.linspace(0, 200, 100)
        accel = np.full(100, 2.0)
        # Start braking at 150m

        accel[dist >= 150] = -5.0
        bp = _find_braking_point(dist, accel, 200.0, search_margin_m=100.0)
        assert math.isfinite(bp), "Should find a braking point"
        assert abs(bp - 150.0) < 5.0, f"Braking point should be ~150m, got {bp}"

    _test("find_braking_point", t_find_braking_point)

    def t_find_braking_point_no_braking():
        dist = np.linspace(0, 100, 50)
        accel = np.full(50, 2.0)  # all acceleration
        bp = _find_braking_point(dist, accel, 100.0)
        assert math.isnan(bp), "No braking should return NaN"

    _test("find_braking_point_no_braking", t_find_braking_point_no_braking)

    def t_analyze_corners_basic():
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist)
        theo = MockTheoResult(dist, theo_speed)
        drv = _make_driver_lap(dist, theo_speed)
        friction = MockFriction()
        corners = _make_corners()

        perfs = analyze_corners(corners, drv, theo, friction)
        assert len(perfs) == 2, f"Expected 2 corners, got {len(perfs)}"
        assert perfs[0].corner_id == 1
        assert perfs[1].corner_id == 2

    _test("analyze_corners_basic", t_analyze_corners_basic)

    def t_analyze_corners_time_loss():
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist)
        theo = MockTheoResult(dist, theo_speed)
        drv = _make_driver_lap(dist, theo_speed, noise=2.0)
        friction = MockFriction()
        corners = _make_corners()

        perfs = analyze_corners(corners, drv, theo, friction)
        for p in perfs:
            assert p.time_loss_s >= 0, f"Corner {p.corner_id}: negative time loss"

    _test("analyze_corners_time_loss", t_analyze_corners_time_loss)

    def t_analyze_corners_speeds_populated():
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist)
        theo = MockTheoResult(dist, theo_speed)
        drv = _make_driver_lap(dist, theo_speed)
        friction = MockFriction()
        corners = _make_corners()

        perfs = analyze_corners(corners, drv, theo, friction)
        for p in perfs:
            assert p.theoretical_apex_speed_mps > 0, f"Corner {p.corner_id}: no theo apex"
            assert p.actual_apex_speed_mps > 0, f"Corner {p.corner_id}: no actual apex"
            assert p.theoretical_entry_speed_mps > 0
            assert p.actual_entry_speed_mps > 0

    _test("analyze_corners_speeds_populated", t_analyze_corners_speeds_populated)

    def t_apex_speed_driver_slower():
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist)
        theo = MockTheoResult(dist, theo_speed)
        # Make driver significantly slower

        drv = _make_driver_lap(dist, theo_speed, noise=5.0, seed=99)
        friction = MockFriction()
        corners = _make_corners()

        perfs = analyze_corners(corners, drv, theo, friction)
        for p in perfs:
            assert p.actual_apex_speed_mps <= p.theoretical_apex_speed_mps + 1.0, (
                f"Corner {p.corner_id}: driver faster than theoretical "
                f"({p.actual_apex_speed_mps:.1f} vs {p.theoretical_apex_speed_mps:.1f})"
            )

    _test("apex_speed_driver_slower", t_apex_speed_driver_slower)

    def t_grip_utilisation():
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist)
        theo = MockTheoResult(dist, theo_speed)
        drv = _make_driver_lap(dist, theo_speed)
        friction = MockFriction()
        corners = _make_corners()

        perfs = analyze_corners(corners, drv, theo, friction)
        for p in perfs:
            assert 0 <= p.grip_utilisation_pct <= 100, (
                f"Corner {p.corner_id}: grip_pct={p.grip_utilisation_pct}"
            )

    _test("grip_utilisation", t_grip_utilisation)

    def t_time_loss_decomposition():
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist)
        theo = MockTheoResult(dist, theo_speed)
        drv = _make_driver_lap(dist, theo_speed, noise=2.0)
        friction = MockFriction()
        corners = _make_corners()

        perfs = analyze_corners(corners, drv, theo, friction)
        for p in perfs:
            components = p.time_loss_braking_s + p.time_loss_apex_speed_s + p.time_loss_exit_s
            if p.time_loss_s > 0.001:
                assert abs(components - p.time_loss_s) < 0.01, (
                    f"Corner {p.corner_id}: components ({components:.4f}) "
                    f"don't sum to total ({p.time_loss_s:.4f})"
                )

    _test("time_loss_decomposition", t_time_loss_decomposition)

    def t_coaching_hint_generated():
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist)
        theo = MockTheoResult(dist, theo_speed)
        drv = _make_driver_lap(dist, theo_speed, noise=3.0)
        friction = MockFriction()
        corners = _make_corners()

        perfs = analyze_corners(corners, drv, theo, friction)
        for p in perfs:
            assert isinstance(p.coaching_hint, str)
            assert len(p.coaching_hint) > 0, f"Corner {p.corner_id}: empty hint"

    _test("coaching_hint_generated", t_coaching_hint_generated)

    def t_coaching_hint_content():
        perf = CornerPerformance(
            corner_id=1, s_start=100, s_end=200,
            theoretical_apex_speed_mps=20.0,
            actual_apex_speed_mps=17.0,
            braking_point_delta_m=8.0,
            grip_utilisation_pct=70.0,
            theoretical_exit_speed_mps=25.0,
            actual_exit_speed_mps=22.0,
            time_loss_s=0.5,
        )
        hint = _generate_coaching_hint(perf)
        assert "8m later" in hint.lower() or "8" in hint
        assert "apex" in hint.lower() or "3.0" in hint
        assert "grip" in hint.lower() or "70" in hint

    _test("coaching_hint_content", t_coaching_hint_content)

    def t_coaching_hint_on_pace():
        perf = CornerPerformance(
            corner_id=1, s_start=100, s_end=200,
            theoretical_apex_speed_mps=20.0,
            actual_apex_speed_mps=19.8,
            braking_point_delta_m=0.5,
            grip_utilisation_pct=95.0,
            theoretical_exit_speed_mps=25.0,
            actual_exit_speed_mps=24.5,
            time_loss_s=0.02,
        )
        hint = _generate_coaching_hint(perf)
        assert "on pace" in hint.lower() or "well driven" in hint.lower()

    _test("coaching_hint_on_pace", t_coaching_hint_on_pace)

    def t_rank_improvement():
        perfs = [
            CornerPerformance(corner_id=1, s_start=0, s_end=100, time_loss_s=0.1),
            CornerPerformance(corner_id=2, s_start=100, s_end=200, time_loss_s=0.5),
            CornerPerformance(corner_id=3, s_start=200, s_end=300, time_loss_s=0.3),
        ]
        ranked = rank_improvement_opportunities(perfs)
        assert ranked[0].corner_id == 2
        assert ranked[1].corner_id == 3
        assert ranked[2].corner_id == 1

    _test("rank_improvement", t_rank_improvement)

    def t_summarize():
        perfs = [
            CornerPerformance(
                corner_id=1, s_start=0, s_end=100,
                time_loss_s=0.2, grip_utilisation_pct=85.0,
            ),
            CornerPerformance(
                corner_id=2, s_start=100, s_end=200,
                time_loss_s=0.5, grip_utilisation_pct=70.0,
            ),
        ]
        s = summarize_corner_performances(perfs)
        assert s["n_corners"] == 2
        assert abs(s["total_corner_time_loss_s"] - 0.7) < 0.01
        assert s["worst_corner_id"] == 2
        assert abs(s["mean_grip_utilisation_pct"] - 77.5) < 0.1
        assert s["improvement_priority"] == [2, 1]

    _test("summarize", t_summarize)

    def t_summarize_empty():
        s = summarize_corner_performances([])
        assert s["n_corners"] == 0
        assert s["worst_corner_id"] is None

    _test("summarize_empty", t_summarize_empty)

    def t_empty_corners():
        perfs = analyze_corners([], pd.DataFrame(), None, None)
        assert perfs == []

    _test("empty_corners", t_empty_corners)

    def t_to_dict():
        perf = CornerPerformance(
            corner_id=1, s_start=100.123, s_end=200.456,
            time_loss_s=0.1234, coaching_hint="Test hint.",
        )
        d = perf.to_dict()
        assert d["corner_id"] == 1
        assert d["s_start"] == 100.12
        assert d["time_loss_s"] == 0.123
        assert d["coaching_hint"] == "Test hint."

    _test("to_dict", t_to_dict)

    def t_tiny_corner_skipped():
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist)
        theo = MockTheoResult(dist, theo_speed)
        drv = _make_driver_lap(dist, theo_speed)
        friction = MockFriction()
        corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 102.0}]  # 2m = too small

        perfs = analyze_corners(corners, drv, theo, friction)
        assert len(perfs) == 0

    _test("tiny_corner_skipped", t_tiny_corner_skipped)

    def t_analyze_many_corners():
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist, amplitude=12.0)
        theo = MockTheoResult(dist, theo_speed)
        drv = _make_driver_lap(dist, theo_speed, noise=1.5)
        friction = MockFriction()
        corners = [
            {"corner_id": i, "s_start": i * 100.0, "s_end": i * 100.0 + 60.0}
            for i in range(1, 8)
        ]

        perfs = analyze_corners(corners, drv, theo, friction)
        assert len(perfs) == 7
        assert all(p.time_loss_s >= 0 for p in perfs)

    _test("analyze_many_corners", t_analyze_many_corners)

    def t_corner_perf_no_friction():
        """Analyse without a friction model (grip_pct should be 0)."""
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist)
        theo = MockTheoResult(dist, theo_speed)
        drv = _make_driver_lap(dist, theo_speed)
        corners = [{"corner_id": 1, "s_start": 150.0, "s_end": 250.0}]

        perfs = analyze_corners(corners, drv, theo, None)
        assert len(perfs) == 1
        assert perfs[0].grip_utilisation_pct == 0.0

    _test("corner_perf_no_friction", t_corner_perf_no_friction)

    def t_debrief_integration_format():
        """Output format should be compatible with debrief_engine drills."""
        dist = _make_oval_dist()
        theo_speed = _make_speed_profile(dist)
        theo = MockTheoResult(dist, theo_speed)
        drv = _make_driver_lap(dist, theo_speed, noise=3.0)
        friction = MockFriction()
        corners = _make_corners()

        perfs = analyze_corners(corners, drv, theo, friction)
        ranked = rank_improvement_opportunities(perfs)

        # Should be able to construct drill strings

        for p in ranked[:3]:
            drill = (
                f"Corner {p.corner_id} ({p.s_start:.0f}m): "
                f"{p.coaching_hint} "
                f"[{p.time_loss_s:.2f}s to gain]"
            )
            assert len(drill) > 20
            assert "Corner" in drill

    _test("debrief_integration_format", t_debrief_integration_format)

    # Test: generate_coaching_hint with style
    def t_coaching_hint_style():
        perf = {
            "braking_point_delta_m": 8.0,
            "theoretical_apex_speed_mps": 20.0,
            "actual_apex_speed_mps": 17.0,
            "grip_utilisation_pct": 65.0,
            "theoretical_exit_speed_mps": 25.0,
            "actual_exit_speed_mps": 22.0,
            "time_loss_s": 0.5,
        }
        hint_aggressive = generate_coaching_hint(perf, style="aggressive")
        assert "hold brakes" in hint_aggressive.lower() or "longer" in hint_aggressive.lower()
        hint_conservative = generate_coaching_hint(perf, style="conservative")
        assert "try braking" in hint_conservative.lower() or "later" in hint_conservative.lower()

    _test("coaching_hint_style", t_coaching_hint_style)

    # Test: generate_coaching_hint with session type
    def t_coaching_hint_session_type():
        perf = {
            "braking_point_delta_m": 0.5,
            "theoretical_apex_speed_mps": 20.0,
            "actual_apex_speed_mps": 18.0,
            "grip_utilisation_pct": 90.0,
            "theoretical_exit_speed_mps": 25.0,
            "actual_exit_speed_mps": 24.5,
            "time_loss_s": 0.3,
        }
        hint_quali = generate_coaching_hint(perf, session_type="qualifying")
        assert "commit" in hint_quali.lower() or "worth it" in hint_quali.lower()
        hint_race = generate_coaching_hint(perf, session_type="race")
        assert "consider" in hint_race.lower() or "managing" in hint_race.lower()

    _test("coaching_hint_session_type", t_coaching_hint_session_type)

    # Test: update_best_practices
    def t_update_best_practices():
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE corner_best_practices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id TEXT NOT NULL, corner_id INTEGER NOT NULL,
            best_entry_mps REAL, best_apex_mps REAL, best_exit_mps REAL,
            best_brake_m REAL, best_throttle_onset_m REAL, best_time_s REAL,
            sample_count INTEGER DEFAULT 0, source_sessions TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(track_id, corner_id)
        )""")
        perfs = [
            {"corner_id": 1, "s_start": 100, "s_end": 200,
             "actual_entry_speed_mps": 20.0, "actual_apex_speed_mps": 15.0,
             "actual_exit_speed_mps": 22.0, "braking_point_actual_m": 90.0},
            {"corner_id": 2, "s_start": 300, "s_end": 400,
             "actual_entry_speed_mps": 18.0, "actual_apex_speed_mps": 12.0,
             "actual_exit_speed_mps": 20.0, "braking_point_actual_m": 280.0},
        ]
        n = update_best_practices(conn, "track_a", perfs, "session_1")
        assert n == 2, f"Expected 2 updates, got {n}"

        # Verify data
        rows = conn.execute("SELECT * FROM corner_best_practices ORDER BY corner_id").fetchall()
        assert len(rows) == 2
        assert dict(rows[0])["sample_count"] == 1

        # Second call with same session — should increment sample_count
        n2 = update_best_practices(conn, "track_a", perfs, "session_2")
        rows2 = conn.execute("SELECT * FROM corner_best_practices ORDER BY corner_id").fetchall()
        assert dict(rows2[0])["sample_count"] == 2
        conn.close()

    _test("update_best_practices", t_update_best_practices)

    # -- Summary
    total = len(passed) + len(failed)
    print(f"\nCorner Analysis Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  \u2713 {name}")
    for name, tb in failed:
        print(f"  \u2717 {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()


# =============================================================================

# Corner Timeline — Hysteresis parameters

# =============================================================================

_BP_THRESHOLD_MPS2: float = -1.0
_EOB_THRESHOLD_MPS2: float = -0.5
_TRACTION_THRESHOLD_MPS2_TL: float = 0.5
_MIN_SUSTAINED_M: float = 5.0
_TL_SEARCH_MARGIN_M: float = 50.0
_COL_YAW: str = "yaw_rate_dps"
_COL_HEADING: str = "heading_deg"
_COL_X: str = "X (m)"
_COL_Y: str = "Y (m)"


# =============================================================================

# Corner Timeline — Private detectors

# =============================================================================


def _detect_bp(
    dist: np.ndarray,
    accel: np.ndarray,
    s_start: float,
    search_margin_m: float = _TL_SEARCH_MARGIN_M,
    threshold: float = _BP_THRESHOLD_MPS2,
    min_sustained_m: float = _MIN_SUSTAINED_M,
) -> CornerEvent:
    """Detect Braking Point by scanning backward from s_start for sustained deceleration."""
    search_start = s_start - search_margin_m
    mask = (dist >= search_start) & (dist <= s_start)
    if mask.sum() < 3:
        # Fallback to existing helper
        bp_s = _find_braking_point(dist, accel, s_start, search_margin_m, threshold)
        if np.isfinite(bp_s):
            return CornerEvent("BP", float(bp_s), 0.7, "accel_long", float(threshold), True)
        return CornerEvent("BP", 0.0, 0.0, "accel_long", 0.0, False)

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    a_seg = accel[idx]

    # Scan backward from corner entry looking for sustained braking
    bp_pos = float("nan")
    for i in range(len(d_seg) - 1, -1, -1):
        if not np.isfinite(a_seg[i]) or a_seg[i] >= threshold:
            continue
        # Found a point below threshold — check if sustained for min_sustained_m
        start_d = d_seg[i]
        sustained = True
        for j in range(i, len(d_seg)):
            if d_seg[j] - start_d > min_sustained_m:
                break
            if np.isfinite(a_seg[j]) and a_seg[j] >= threshold:
                sustained = False
                break
        if sustained:
            bp_pos = float(d_seg[i])

    if np.isfinite(bp_pos):
        # Interpolate the accel value at BP
        val = float(np.interp(bp_pos, dist, accel))
        return CornerEvent("BP", bp_pos, 0.9, "accel_long", val, True)

    # Fallback to existing helper
    bp_s = _find_braking_point(dist, accel, s_start, search_margin_m, threshold)
    if np.isfinite(bp_s):
        return CornerEvent("BP", float(bp_s), 0.7, "accel_long", float(threshold), True)
    return CornerEvent("BP", 0.0, 0.0, "accel_long", 0.0, False)


def _detect_eob(
    dist: np.ndarray,
    accel: np.ndarray,
    bp_s: float,
    s_end: float,
    threshold: float = _EOB_THRESHOLD_MPS2,
    min_sustained_m: float = _MIN_SUSTAINED_M,
) -> CornerEvent:
    """Detect End-Of-Braking: first point after BP where accel rises above threshold, sustained."""
    if not np.isfinite(bp_s):
        return CornerEvent("EOB", 0.0, 0.0, "accel_long", 0.0, False)

    mask = (dist >= bp_s) & (dist <= s_end)
    if mask.sum() < 2:
        return CornerEvent("EOB", 0.0, 0.0, "accel_long", 0.0, False)

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    a_seg = accel[idx]

    for i in range(len(d_seg)):
        if not np.isfinite(a_seg[i]):
            continue
        if a_seg[i] > threshold:
            # Check sustained
            start_d = d_seg[i]
            sustained = True
            for j in range(i, len(d_seg)):
                if d_seg[j] - start_d > min_sustained_m:
                    break
                if np.isfinite(a_seg[j]) and a_seg[j] <= threshold:
                    sustained = False
                    break
            if sustained:
                val = float(a_seg[i])
                return CornerEvent("EOB", float(d_seg[i]), 0.85, "accel_long", val, True)

    return CornerEvent("EOB", 0.0, 0.0, "accel_long", 0.0, False)


def _detect_min_speed(
    dist: np.ndarray,
    speed: np.ndarray,
    s_start: float,
    s_end: float,
    margin_m: float = 5.0,
) -> CornerEvent:
    """Detect minimum speed point within the corner region."""
    mask = (dist >= s_start - margin_m) & (dist <= s_end + margin_m)
    if mask.sum() < 1:
        return CornerEvent("MIN_SPEED", 0.0, 0.0, "speed", 0.0, False)

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    v_seg = speed[idx]

    finite_mask = np.isfinite(v_seg)
    if not finite_mask.any():
        return CornerEvent("MIN_SPEED", 0.0, 0.0, "speed", 0.0, False)

    min_i = np.argmin(v_seg[finite_mask])
    finite_idx = np.where(finite_mask)[0]
    pos = float(d_seg[finite_idx[min_i]])
    val = float(v_seg[finite_idx[min_i]])
    return CornerEvent("MIN_SPEED", pos, 1.0, "speed", val, True)


def _detect_throttle_on(
    dist: np.ndarray,
    accel: np.ndarray,
    min_speed_s: float,
    s_end: float,
    threshold: float = _TRACTION_THRESHOLD_MPS2_TL,
    min_sustained_m: float = _MIN_SUSTAINED_M,
) -> CornerEvent:
    """Detect Throttle-On: first point after min-speed where accel exceeds threshold, sustained."""
    if not np.isfinite(min_speed_s):
        return CornerEvent("THROTTLE_ON", 0.0, 0.0, "accel_long", 0.0, False)

    search_end = s_end + _TL_SEARCH_MARGIN_M
    mask = (dist >= min_speed_s) & (dist <= search_end)
    if mask.sum() < 2:
        return CornerEvent("THROTTLE_ON", 0.0, 0.0, "accel_long", 0.0, False)

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    a_seg = accel[idx]

    for i in range(len(d_seg)):
        if not np.isfinite(a_seg[i]):
            continue
        if a_seg[i] > threshold:
            start_d = d_seg[i]
            sustained = True
            for j in range(i, len(d_seg)):
                if d_seg[j] - start_d > min_sustained_m:
                    break
                if np.isfinite(a_seg[j]) and a_seg[j] <= threshold:
                    sustained = False
                    break
            if sustained:
                val = float(a_seg[i])
                return CornerEvent("THROTTLE_ON", float(d_seg[i]), 0.85, "accel_long", val, True)

    return CornerEvent("THROTTLE_ON", 0.0, 0.0, "accel_long", 0.0, False)


def _detect_mrp(
    dist: np.ndarray,
    df: pd.DataFrame,
    s_start: float,
    s_end: float,
    min_prominence_dps: float = 0.5,
    data_quality: float = 1.0,
) -> tuple[CornerEvent, float]:
    """Detect Maximum Rate Point — peak yaw rate within the corner region.

    Falls back to heading-derived yaw rate if ``yaw_rate_dps`` is absent.
    Returns ``(CornerEvent, prominence_value)``.
    """
    # --- resolve yaw channel ---
    if "yaw_rate_dps" in df.columns:
        yaw = df["yaw_rate_dps"].values.astype(float)
        channel_conf = 1.0
        source = "yaw_rate"
    elif "heading_deg" in df.columns:
        heading = df["heading_deg"].values.astype(float)
        dd = np.gradient(dist)
        dd[dd == 0] = 1e-6
        yaw = np.gradient(heading) / dd  # deg / m  (rough proxy)
        channel_conf = 0.6
        source = "heading_derived"
    else:
        return (CornerEvent("MRP", 0.0, 0.0, "yaw_rate", 0.0, False), 0.0)

    # --- slice to corner region ---
    mask = (dist >= s_start) & (dist <= s_end)
    if mask.sum() < 3:
        return (CornerEvent("MRP", 0.0, 0.0, source, 0.0, False), 0.0)

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    y_seg = np.abs(yaw[idx])

    # --- find dominant peak ---
    prominence = 0.0
    peak_i = None
    try:
        from scipy.signal import find_peaks as _find_peaks

        peaks, props = _find_peaks(y_seg, prominence=min_prominence_dps)
        if len(peaks) > 0:
            best = int(np.argmax(props["prominences"]))
            peak_i = peaks[best]
            prominence = float(props["prominences"][best])
    except ImportError:
        pass

    if peak_i is None:
        # fallback: simple argmax
        finite = np.isfinite(y_seg)
        if not finite.any():
            return (CornerEvent("MRP", 0.0, 0.0, source, 0.0, False), 0.0)
        peak_i = int(np.argmax(np.where(finite, y_seg, -np.inf)))
        prominence = float(y_seg[peak_i]) - float(np.nanmin(y_seg))
        if prominence < min_prominence_dps:
            return (CornerEvent("MRP", 0.0, 0.0, source, 0.0, False), 0.0)

    pos = float(d_seg[peak_i])
    val = float(y_seg[peak_i])

    det_conf = min(1.0, prominence / 5.0)
    conf = channel_conf * det_conf * data_quality

    return (CornerEvent("MRP", pos, conf, source, val, True), prominence)


def _detect_track_out(
    dist: np.ndarray,
    s_end: float,
    df: pd.DataFrame,
) -> CornerEvent:
    """Detect Track-Out point. Falls back to s_end (XY analysis deferred)."""
    return CornerEvent("TRACK_OUT", s_end, 0.5, "position", 0.0, True)


# =============================================================================

# Corner Timeline — Public API

# =============================================================================


def detect_corner_events(
    corner: dict,
    lap_df: pd.DataFrame,
    theoretical_df: Optional[pd.DataFrame] = None,
    data_quality: float = 1.0,
) -> CornerTimeline:
    """
    Detect physics-defined events within a single corner.

    Parameters
    ----------
    corner : dict
        Must contain ``corner_id``, ``s_start``, ``s_end``.
    lap_df : pd.DataFrame
        Lap telemetry with distance, speed, and longitudinal acceleration.
    theoretical_df : pd.DataFrame, optional
        Theoretical lap data (unused for now — reserved for delta).
    data_quality : float
        Overall data quality score 0-1 (scales confidence).

    Returns
    -------
    CornerTimeline
        Timeline with detected events sorted by s_position.
    """
    cid = corner.get("corner_id", 0)
    s_start = float(corner["s_start"])
    s_end = float(corner["s_end"])

    dist = _resolve_dist(lap_df)
    speed = _resolve_speed(lap_df)
    accel = _resolve_accel_long(lap_df)

    # 1. Braking Point
    bp = _detect_bp(dist, accel, s_start)

    # 2. End of Braking
    bp_s = bp.s_position if bp.available else float("nan")
    eob = _detect_eob(dist, accel, bp_s, s_end)

    # 3. MRP — Maximum Rate Point (peak yaw rate)
    mrp, mrp_strength = _detect_mrp(dist, lap_df, s_start, s_end, data_quality=data_quality)

    # 4. Minimum Speed
    ms = _detect_min_speed(dist, speed, s_start, s_end)

    # 5. APEX — placeholder using MIN_SPEED position as proxy
    apex = CornerEvent(
        "APEX",
        ms.s_position if ms.available else 0.0,
        0.0,
        "position",
        0.0,
        False,
    )

    # 6. Throttle On
    ms_s = ms.s_position if ms.available else s_start
    thr_on = _detect_throttle_on(dist, accel, ms_s, s_end)

    # 7. Track Out
    t_out = _detect_track_out(dist, s_end, lap_df)

    # Collect and sort: unavailable events go last, then by s_position
    events = [bp, eob, mrp, ms, apex, thr_on, t_out]
    events.sort(key=lambda e: (not e.available, e.s_position))

    return CornerTimeline(
        corner_id=cid,
        events=events,
        segment_losses_s={},
        segment_confidences={},
        mistakes=[],
        mrp_strength=mrp_strength,
        mrp_stability_std_m=0.0,
        event_stability={},
    )


def compute_segment_losses(
    timeline: CornerTimeline,
    driver_df: pd.DataFrame,
    theoretical_df: pd.DataFrame,
) -> dict[str, float]:
    """
    Compute per-segment time losses between consecutive events.
    Segments: BP->EOB, EOB->MRP, MRP->ThrottleOn, ThrottleOn->TrackOut.
    """
    segment_pairs = [
        ("BP_EOB", "BP", "EOB"),
        ("EOB_MRP", "EOB", "MRP"),
        ("MRP_THROTTLE_ON", "MRP", "THROTTLE_ON"),
        ("THROTTLE_ON_TRACK_OUT", "THROTTLE_ON", "TRACK_OUT"),
    ]

    drv_dist = _resolve_dist(driver_df)
    drv_speed = _resolve_speed(driver_df)

    theo_dist = None
    theo_speed = None
    for dcol in ("distance_m", "Distance (m)"):
        if dcol in theoretical_df.columns:
            theo_dist = theoretical_df[dcol].to_numpy(dtype=float)
            break
    for scol in ("v_env_mps", "speed_mps", "Speed (m/s)"):
        if scol in theoretical_df.columns:
            theo_speed = theoretical_df[scol].to_numpy(dtype=float)
            break

    if theo_dist is None or theo_speed is None:
        return {}

    losses = {}
    confidences = {}

    for seg_name, start_type, end_type in segment_pairs:
        ev_start = timeline.get_event(start_type)
        ev_end = timeline.get_event(end_type)

        if (ev_start is None or ev_end is None or
                not ev_start.available or not ev_end.available):
            losses[seg_name] = 0.0
            confidences[seg_name] = 0.0
            continue

        s0 = ev_start.s_position
        s1 = ev_end.s_position
        if s1 <= s0:
            losses[seg_name] = 0.0
            confidences[seg_name] = 0.0
            continue

        t_drv = _integrate_time(
            drv_dist[_slice_range(drv_dist, s0, s1)],
            drv_speed[_slice_range(drv_dist, s0, s1)],
        )
        t_theo = _integrate_time(
            theo_dist[_slice_range(theo_dist, s0, s1)],
            theo_speed[_slice_range(theo_dist, s0, s1)],
        )
        losses[seg_name] = max(0.0, round(t_drv - t_theo, 4))
        confidences[seg_name] = min(ev_start.confidence, ev_end.confidence)

    timeline.segment_losses_s = losses
    timeline.segment_confidences = confidences
    return losses


def compute_event_stability(
    corners: list[dict],
    all_lap_dfs: list[pd.DataFrame],
    data_quality: float = 1.0,
) -> dict[int, dict[str, float]]:
    """
    Compute std-dev of each event's s_position across multiple laps.
    Skips if fewer than 3 laps.
    Returns: corner_id -> {event_type -> std_dev_m}
    """
    if len(all_lap_dfs) < 3:
        return {}

    result = {}
    for corner in corners:
        cid = int(corner.get("corner_id", 0))
        event_positions: dict[str, list[float]] = {}

        for lap_df in all_lap_dfs:
            if lap_df is None or len(lap_df) < 10:
                continue
            try:
                tl = detect_corner_events(corner, lap_df, data_quality=data_quality)
                for ev in tl.events:
                    if ev.available and ev.s_position > 0:
                        event_positions.setdefault(ev.event_type, []).append(ev.s_position)
            except Exception:
                continue

        stability: dict[str, float] = {}
        for ev_type, positions in event_positions.items():
            if len(positions) >= 3:
                stability[ev_type] = float(np.std(positions))
        result[cid] = stability

    return result


def detect_corner_mistakes(
    timeline: CornerTimeline,
    lap_df: pd.DataFrame,
    corner: dict,
) -> list[dict]:
    """
    Classify mistakes from a CornerTimeline.

    Returns a list of mistake dicts, each with keys:
        type     — one of 6 classifier names
        severity — float in [0, 1]
        evidence — dict with supporting data
    """
    mistakes: list[dict] = []

    mrp_ev = timeline.get_event("MRP")
    eob_ev = timeline.get_event("EOB")
    min_speed_ev = timeline.get_event("MIN_SPEED")
    throttle_ev = timeline.get_event("THROTTLE_ON")

    # --- 1. no_clear_mrp ---
    if mrp_ev is None or not mrp_ev.available or mrp_ev.confidence < 0.3:
        mistakes.append({
            "type": "no_clear_mrp",
            "severity": 0.5,
            "evidence": {
                "mrp_confidence": mrp_ev.confidence if mrp_ev else 0.0,
                "mrp_available": mrp_ev.available if mrp_ev else False,
            },
        })

    # --- 2. mrp_plateau ---
    if (mrp_ev is not None and mrp_ev.available
            and timeline.mrp_strength < 1.0):
        mistakes.append({
            "type": "mrp_plateau",
            "severity": round(1.0 - timeline.mrp_strength, 4),
            "evidence": {"mrp_strength": timeline.mrp_strength},
        })

    # --- 3. mrp_drift ---
    mrp_std = timeline.event_stability.get("MRP", 0.0)
    if mrp_std > 10.0:
        mistakes.append({
            "type": "mrp_drift",
            "severity": round(min(1.0, mrp_std / 20.0), 4),
            "evidence": {"mrp_stability_std_m": mrp_std},
        })

    # --- 4. mrp_after_apex ---
    if (mrp_ev is not None and mrp_ev.available
            and min_speed_ev is not None and min_speed_ev.available):
        delta = mrp_ev.s_position - min_speed_ev.s_position
        if delta > 5.0:
            mistakes.append({
                "type": "mrp_after_apex",
                "severity": round(min(1.0, delta / 15.0), 4),
                "evidence": {
                    "mrp_s": mrp_ev.s_position,
                    "min_speed_s": min_speed_ev.s_position,
                    "delta_m": round(delta, 2),
                },
            })

    # --- 5. power_before_rotation ---
    if (throttle_ev is not None and throttle_ev.available
            and mrp_ev is not None and mrp_ev.available
            and throttle_ev.s_position < mrp_ev.s_position):
        yaw_ratio = 0.0
        if _COL_YAW in lap_df.columns:
            dist_arr = _resolve_dist(lap_df)
            yaw_arr = np.abs(lap_df[_COL_YAW].to_numpy(dtype=float))
            peak_yaw = float(np.nanmax(yaw_arr))
            if peak_yaw > 0:
                yaw_at_throttle = float(np.interp(
                    throttle_ev.s_position, dist_arr, yaw_arr,
                ))
                yaw_ratio = yaw_at_throttle / peak_yaw

        if yaw_ratio > 0.5:
            mistakes.append({
                "type": "power_before_rotation",
                "severity": round(min(1.0, yaw_ratio * 0.8), 4),
                "evidence": {
                    "throttle_on_s": throttle_ev.s_position,
                    "mrp_s": mrp_ev.s_position,
                    "yaw_ratio": round(yaw_ratio, 4),
                },
            })

    # --- 6. rotation_too_late ---
    if (mrp_ev is not None and mrp_ev.available
            and eob_ev is not None and eob_ev.available):
        s_start = float(corner.get("s_start", 0.0))
        s_end = float(corner.get("s_end", 0.0))
        corner_len = s_end - s_start
        if corner_len > 0:
            delta = mrp_ev.s_position - eob_ev.s_position
            delta_pct = delta / corner_len
            if delta_pct > 0.3:
                mistakes.append({
                    "type": "rotation_too_late",
                    "severity": round(min(1.0, delta_pct / 0.5), 4),
                    "evidence": {
                        "mrp_s": mrp_ev.s_position,
                        "eob_s": eob_ev.s_position,
                        "delta_pct": round(delta_pct, 4),
                        "corner_length_m": round(corner_len, 2),
                    },
                })

    return mistakes


# =============================================================================

# Brake Release Quality Metrics

# =============================================================================


_BRAKE_PRESSURE_COLS = ["Brake (%)", "Brake Pressure (bar)", "brake_pct", "brake_pressure"]


def compute_brake_release_metrics(
    timeline: CornerTimeline,
    lap_df: pd.DataFrame,
    corner: dict,
    data_quality: float = 1.0,
) -> Optional[BrakeReleaseMetrics]:
    """Compute brake release quality metrics for a corner.

    Uses brake pressure channel if available (high confidence), otherwise
    falls back to longitudinal acceleration as a proxy (lower confidence).

    Parameters
    ----------
    timeline : CornerTimeline
        Must contain at least BP and EOB events.
    lap_df : pd.DataFrame
        Lap data with distance, speed, and accel columns.
    corner : dict
        Corner definition with ``s_start`` and ``s_end``.
    data_quality : float
        Overall data quality multiplier (0-1).

    Returns
    -------
    BrakeReleaseMetrics or None if BP/EOB events are missing.
    """
    bp = timeline.get_event("BP")
    eob = timeline.get_event("EOB")
    throttle_on = timeline.get_event("THROTTLE_ON")

    if bp is None or not bp.available or eob is None or not eob.available:
        return None

    dist = _resolve_dist(lap_df)
    speed = _resolve_speed(lap_df)
    accel = _resolve_accel_long(lap_df)

    # Detect brake channel
    brake_col = None
    for col in _BRAKE_PRESSURE_COLS:
        if col in lap_df.columns:
            brake_col = col
            break

    source = "brake_pressure" if brake_col else "accel_inferred"
    base_confidence = 1.0 if brake_col else 0.6

    # Get brake signal in BP -> EOB+margin zone
    zone_end = eob.s_position + 20.0  # margin past EOB for trail analysis
    if throttle_on and throttle_on.available:
        zone_end = max(zone_end, throttle_on.s_position + 5.0)

    mask = (dist >= bp.s_position) & (dist <= zone_end)
    if mask.sum() < 3:
        return None

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    s_seg = speed[idx]
    a_seg = accel[idx]

    if brake_col:
        brake_signal = pd.to_numeric(lap_df[brake_col], errors="coerce").values[idx].astype(float)
    else:
        # Infer: use negative accel as proxy (flip sign so braking = positive)
        brake_signal = np.clip(-a_seg, 0, None)

    # Peak decel
    peak_decel = float(np.nanmin(a_seg))

    # Peak brake pressure
    finite_brake = np.isfinite(brake_signal)
    peak_brake = float(np.nanmax(brake_signal[finite_brake])) if finite_brake.sum() > 0 else 0.0

    # Brake zone length and time
    bz_length = eob.s_position - bp.s_position
    bz_mask = (dist >= bp.s_position) & (dist <= eob.s_position)
    bz_speed = speed[bz_mask]
    if bz_mask.sum() > 1 and np.all(bz_speed > 0.1):
        bz_dist = dist[bz_mask]
        ds = np.diff(bz_dist)
        inv_v = 1.0 / bz_speed[:-1]
        bz_time = float(np.sum(ds * inv_v))
    else:
        bz_time = 0.0

    # Release slope: rate of brake signal decrease from peak to EOB
    eob_mask_local = d_seg <= eob.s_position
    if eob_mask_local.sum() > 2:
        peak_local_idx = int(np.nanargmax(brake_signal[:eob_mask_local.sum()]))
        release_segment = brake_signal[peak_local_idx:eob_mask_local.sum()]
        release_dist = d_seg[peak_local_idx:eob_mask_local.sum()]
        if len(release_segment) > 1 and (release_dist[-1] - release_dist[0]) > 0:
            release_slope = float(
                (release_segment[-1] - release_segment[0])
                / (release_dist[-1] - release_dist[0])
            )
        else:
            release_slope = 0.0
    else:
        release_slope = 0.0

    # Release linearity: R^2 of linear fit from peak to EOB
    release_linearity = 0.0
    if eob_mask_local.sum() > 3:
        peak_local_idx2 = int(np.nanargmax(brake_signal[:eob_mask_local.sum()]))
        rel_brake = brake_signal[peak_local_idx2:eob_mask_local.sum()]
        rel_dist = d_seg[peak_local_idx2:eob_mask_local.sum()]
        if len(rel_brake) > 2:
            fin = np.isfinite(rel_brake)
            if fin.sum() > 2:
                coeffs = np.polyfit(rel_dist[fin], rel_brake[fin], 1)
                predicted = np.polyval(coeffs, rel_dist[fin])
                ss_res = np.sum((rel_brake[fin] - predicted) ** 2)
                ss_tot = np.sum((rel_brake[fin] - np.mean(rel_brake[fin])) ** 2)
                if ss_tot > 0:
                    release_linearity = max(0.0, 1.0 - ss_res / ss_tot)

    # Over-drop: brake drops > 40% of peak before EOB
    over_drop = False
    over_drop_severity = 0.0
    if peak_brake > 0 and eob_mask_local.sum() > 3:
        mid_mask = d_seg < (bp.s_position + bz_length * 0.5)
        eob_local = d_seg <= eob.s_position
        early_zone = mid_mask & eob_local
        if early_zone.sum() > 0:
            min_early = float(np.nanmin(brake_signal[early_zone]))
            drop_pct = (peak_brake - min_early) / peak_brake
            if drop_pct > 0.4:
                over_drop = True
                over_drop_severity = min(1.0, drop_pct)

    # Late release risk: high brake retained when speed < 50% of entry
    late_release = False
    late_release_severity = 0.0
    entry_speed = float(s_seg[0]) if len(s_seg) > 0 else 1.0
    if entry_speed > 0:
        low_speed_mask = s_seg < (entry_speed * 0.5)
        if low_speed_mask.sum() > 0:
            brake_at_low_speed = brake_signal[low_speed_mask]
            if np.isfinite(brake_at_low_speed).sum() > 0:
                mean_brake_low = float(np.nanmean(brake_at_low_speed))
                if peak_brake > 0 and mean_brake_low / peak_brake > 0.6:
                    late_release = True
                    late_release_severity = min(1.0, mean_brake_low / peak_brake)

    # Terminal trail T%: brake at THROTTLE_ON as % of peak
    terminal_trail = 0.0
    if throttle_on and throttle_on.available and peak_brake > 0:
        to_idx = int(np.argmin(np.abs(dist - throttle_on.s_position)))
        if brake_col:
            brake_vals = pd.to_numeric(
                lap_df[brake_col], errors="coerce"
            ).values.astype(float)
        else:
            brake_vals = np.clip(-accel, 0, None)
        if to_idx < len(brake_vals) and np.isfinite(brake_vals[to_idx]):
            terminal_trail = float(brake_vals[to_idx] / peak_brake * 100.0)
            terminal_trail = max(0.0, min(100.0, terminal_trail))

    confidence = base_confidence * data_quality

    return BrakeReleaseMetrics(
        peak_decel_mps2=peak_decel,
        peak_brake_pressure=peak_brake if brake_col else 0.0,
        brake_zone_length_m=max(0.0, bz_length),
        brake_zone_time_s=bz_time,
        release_slope=release_slope,
        release_linearity=release_linearity,
        over_drop=over_drop,
        over_drop_severity=over_drop_severity,
        late_release_risk=late_release,
        late_release_severity=late_release_severity,
        terminal_trail_pct=terminal_trail,
        source=source,
        confidence=confidence,
    )


# =============================================================================

# Brake-Yaw Coupling Scores

# =============================================================================


@dataclass
class BrakeYawCoupling:
    """Correlation between brake release and yaw response."""
    coupling_score: float           # correlation magnitude (0-1)
    lag_m: float                    # distance lag: +ve = yaw lags brake release
    pattern: str                    # "well_coupled"|"under_rotation"|"over_rotation"|"unavailable"
    terminal_trail_pct: float       # T% at first positive accel
    coaching_action: str            # specific coaching string
    confidence: float               # 0-1

    def to_dict(self) -> dict:
        return {
            "coupling_score": round(self.coupling_score, 3),
            "lag_m": round(self.lag_m, 1),
            "pattern": self.pattern,
            "terminal_trail_pct": round(self.terminal_trail_pct, 1),
            "coaching_action": self.coaching_action,
            "confidence": round(self.confidence, 2),
        }


def compute_brake_yaw_coupling(
    timeline: CornerTimeline,
    lap_df: pd.DataFrame,
    corner: dict,
    data_quality: float = 1.0,
) -> BrakeYawCoupling:
    """Compute coupling score between brake release and yaw response.

    Analyses the correlation between the rate of brake release and the rate
    of yaw growth in the EOB → THROTTLE_ON window.  Returns a pattern
    classification (well_coupled / under_rotation / over_rotation /
    unavailable) together with a numeric coupling score (0-1) and
    distance-domain lag estimate.

    Parameters
    ----------
    timeline : CornerTimeline
        Must contain at least an EOB event.
    lap_df : pd.DataFrame
        Lap data with distance, speed, accel, and (optionally) yaw columns.
    corner : dict
        Corner definition with ``s_start`` and ``s_end``.
    data_quality : float
        Overall data quality multiplier (0-1).

    Returns
    -------
    BrakeYawCoupling — always non-None; ``pattern="unavailable"`` when data
    is insufficient.
    """
    _UNAVAILABLE = BrakeYawCoupling(0.0, 0.0, "unavailable", 0.0, "", 0.0)

    eob = timeline.get_event("EOB")
    throttle_on = timeline.get_event("THROTTLE_ON")
    mrp = timeline.get_event("MRP")

    if eob is None or not eob.available:
        return _UNAVAILABLE

    # Need yaw channel
    if _COL_YAW not in lap_df.columns:
        return _UNAVAILABLE

    dist = _resolve_dist(lap_df)
    accel = _resolve_accel_long(lap_df)
    yaw = np.abs(pd.to_numeric(lap_df[_COL_YAW], errors="coerce").values.astype(float))

    # Analysis window: EOB → THROTTLE_ON (or EOB + 50m)
    window_end = (
        throttle_on.s_position
        if (throttle_on and throttle_on.available)
        else eob.s_position + 50.0
    )
    mask = (dist >= eob.s_position) & (dist <= window_end)

    if mask.sum() < 10:
        return _UNAVAILABLE

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    a_seg = accel[idx]
    y_seg = yaw[idx]

    # Brake release signal: negative accel becoming less negative
    brake_intensity = np.clip(-a_seg, 0, None)  # positive = braking

    # Compute derivatives (rate of change w.r.t. distance)
    ds = np.gradient(d_seg)
    ds[ds == 0] = 1e-6
    d_brake = np.gradient(brake_intensity) / ds  # brake release rate
    d_yaw = np.gradient(y_seg) / ds              # yaw growth rate

    # Replace NaN / Inf
    d_brake = np.where(np.isfinite(d_brake), d_brake, 0.0)
    d_yaw = np.where(np.isfinite(d_yaw), d_yaw, 0.0)

    # Cross-correlation for coupling score
    if np.std(d_brake) > 1e-6 and np.std(d_yaw) > 1e-6:
        corr = np.corrcoef(d_brake, d_yaw)[0, 1]
        coupling_score = abs(float(corr)) if np.isfinite(corr) else 0.0
    else:
        coupling_score = 0.0

    # Lag: find peak cross-correlation offset
    lag_m = 0.0
    if len(d_brake) > 5:
        try:
            cross_corr = np.correlate(
                d_brake - np.mean(d_brake),
                d_yaw - np.mean(d_yaw),
                mode="full",
            )
            lags = np.arange(-len(d_brake) + 1, len(d_brake))
            if len(cross_corr) > 0:
                peak_lag_idx = int(np.argmax(np.abs(cross_corr)))
                lag_samples = lags[peak_lag_idx]
                avg_ds = float(np.mean(np.abs(np.diff(d_seg))))
                lag_m = float(lag_samples * avg_ds)
        except Exception:
            lag_m = 0.0

    # Detect pattern --------------------------------------------------------
    # Over-rotation: yaw spikes while brake still high
    peak_yaw_in_window = float(np.nanmax(y_seg))
    peak_yaw_idx = int(np.nanargmax(y_seg))
    brake_at_peak_yaw = (
        brake_intensity[peak_yaw_idx]
        if peak_yaw_idx < len(brake_intensity)
        else 0.0
    )
    peak_brake = (
        float(np.nanmax(brake_intensity))
        if len(brake_intensity) > 0
        else 1.0
    )

    if (
        peak_brake > 0
        and brake_at_peak_yaw / peak_brake > 0.5
        and peak_yaw_in_window > 5.0
    ):
        pattern = "over_rotation"
        coaching = (
            f"Release brake {abs(lag_m):.0f}m earlier; "
            "reduce trail to avoid yaw spike under braking"
        )
    elif coupling_score < 0.3 and peak_yaw_in_window < 5.0:
        pattern = "under_rotation"
        coaching = (
            "Hold trail brake longer to build yaw; "
            "delay throttle until rotation established"
        )
    else:
        pattern = "well_coupled"
        coaching = "Rotation timing is well matched to brake release"

    # Terminal trail T%
    terminal_trail = 0.0
    if throttle_on and throttle_on.available:
        to_idx = int(np.argmin(np.abs(dist - throttle_on.s_position)))
        if to_idx < len(accel):
            brake_at_to = max(0.0, -float(accel[to_idx]))
            if peak_brake > 0:
                terminal_trail = brake_at_to / peak_brake * 100.0

    confidence = min(1.0, data_quality * (0.5 + coupling_score * 0.5))

    return BrakeYawCoupling(
        coupling_score=coupling_score,
        lag_m=lag_m,
        pattern=pattern,
        terminal_trail_pct=terminal_trail,
        coaching_action=coaching,
        confidence=confidence,
    )


# =============================================================================

# Compound Corner Metrics

# =============================================================================


@dataclass
class CompoundCornerMetrics:
    """Metrics for a compound corner sequence."""
    compound_id: int
    corner_ids: list[int]
    blame_attribution: dict[int, float]    # corner_id -> fraction of total loss
    leverage_corner_id: int                # earliest high-impact corner
    coaching: str

    def to_dict(self) -> dict:
        return {
            "compound_id": self.compound_id,
            "corner_ids": self.corner_ids,
            "blame_attribution": {k: round(v, 3) for k, v in self.blame_attribution.items()},
            "leverage_corner_id": self.leverage_corner_id,
            "coaching": self.coaching,
        }


def compute_compound_metrics(
    compound: dict,
    corner_performances: list[CornerPerformance],
    corners: list[dict],
) -> Optional[CompoundCornerMetrics]:
    """Compute compound corner metrics with blame attribution."""
    corner_ids = compound.get("corner_ids", [])
    comp_id = compound.get("compound_id", 0)

    if len(corner_ids) < 2:
        return None

    # Get performances for compound members
    perf_map = {p.corner_id: p for p in corner_performances}
    member_perfs = [perf_map[cid] for cid in corner_ids if cid in perf_map]

    if not member_perfs:
        return None

    # Blame attribution: proportion of total time loss
    total_loss = sum(p.time_loss_s for p in member_perfs)
    if total_loss <= 0:
        blame = {p.corner_id: 1.0 / len(member_perfs) for p in member_perfs}
    else:
        blame = {p.corner_id: p.time_loss_s / total_loss for p in member_perfs}

    # Leverage corner: earliest with >= average blame
    avg_blame = 1.0 / len(member_perfs)
    leverage_id = corner_ids[0]
    for cid in corner_ids:
        if blame.get(cid, 0) >= avg_blame:
            leverage_id = cid
            break

    coaching = f"Focus on C{leverage_id} first — fixing it improves the whole {len(corner_ids)}-corner sequence"

    return CompoundCornerMetrics(
        compound_id=comp_id,
        corner_ids=corner_ids,
        blame_attribution=blame,
        leverage_corner_id=leverage_id,
        coaching=coaching,
    )


# =============================================================================

# Theoretical Per-Corner Targets (Feature 6)

# =============================================================================


@dataclass
class CornerTargets:
    """Theoretical target event positions and speeds for a corner."""

    corner_id: int
    target_events: list[CornerEvent]      # theoretical event positions
    target_speeds: dict[str, float]       # event_type -> target speed_mps
    priority: str                         # "entry"|"exit"|"balanced"
    priority_reason: str                  # e.g. "long straight follows"
    recommended_changes: list[dict]       # [{"event": "BP", "delta_m": -3.2, ...}]
    confidence: float

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id,
            "target_events": [e.to_dict() for e in self.target_events],
            "target_speeds": {k: round(v, 2) for k, v in self.target_speeds.items()},
            "priority": self.priority,
            "priority_reason": self.priority_reason,
            "recommended_changes": self.recommended_changes,
            "confidence": round(self.confidence, 2),
        }


def compute_corner_targets(
    corner: dict,
    driver_timeline: CornerTimeline,
    theoretical_timeline: CornerTimeline,
    theoretical_df: pd.DataFrame,
    driver_df: pd.DataFrame,
    data_quality: float = 1.0,
) -> Optional[CornerTargets]:
    """
    Compute theoretical target positions and recommended changes for a corner.

    Compares the driver's actual corner events (braking point, throttle-on, etc.)
    against the theoretical optimal events to produce actionable deltas.

    Parameters
    ----------
    corner : dict
        Corner definition with ``corner_id``, ``s_start``, ``s_end``.
        Optional keys: ``next_straight_m``, ``prev_straight_m``, ``corner_type``.
    driver_timeline : CornerTimeline
        Events detected from the driver's actual lap.
    theoretical_timeline : CornerTimeline
        Events detected from the theoretical optimal lap.
    theoretical_df : pd.DataFrame
        Theoretical lap telemetry (distance + speed columns).
    driver_df : pd.DataFrame
        Driver lap telemetry (distance + speed columns).
    data_quality : float
        Overall data quality score 0-1 (scales confidence).

    Returns
    -------
    CornerTargets or None
        Target events, speeds, priority, and recommended changes.
    """
    cid = int(corner.get("corner_id", 0))

    # ------------------------------------------------------------------
    # Determine priority from corner context
    # ------------------------------------------------------------------
    next_straight = corner.get("next_straight_m", 0)
    prev_straight = corner.get("prev_straight_m", 0)
    corner_type = corner.get("corner_type", "medium")

    if next_straight > 200:
        priority = "exit"
        priority_reason = "long straight follows — maximize exit speed"
    elif prev_straight > 200:
        priority = "entry"
        priority_reason = "long straight precedes — maximize entry speed"
    elif corner_type == "hairpin":
        priority = "entry"
        priority_reason = "hairpin requires full rotation commitment"
    else:
        priority = "balanced"
        priority_reason = "balanced entry and exit importance"

    # ------------------------------------------------------------------
    # Target events from theoretical timeline
    # ------------------------------------------------------------------
    target_events = [e for e in theoretical_timeline.events if e.available]

    # ------------------------------------------------------------------
    # Target speeds at each event position
    # ------------------------------------------------------------------
    try:
        theo_dist = _resolve_dist(theoretical_df)
        theo_speed = _resolve_speed(theoretical_df)
    except CornerAnalysisError:
        theo_dist = None
        theo_speed = None

    target_speeds: dict[str, float] = {}
    if theo_dist is not None and theo_speed is not None:
        for ev in target_events:
            idx = int(np.argmin(np.abs(theo_dist - ev.s_position)))
            if idx < len(theo_speed) and np.isfinite(theo_speed[idx]):
                target_speeds[ev.event_type] = float(theo_speed[idx])

    # ------------------------------------------------------------------
    # Recommended changes: compare driver vs theoretical events
    # ------------------------------------------------------------------
    recommended: list[dict] = []

    try:
        drv_dist_arr = _resolve_dist(driver_df)
        drv_speed_arr = _resolve_speed(driver_df)
    except CornerAnalysisError:
        drv_dist_arr = None
        drv_speed_arr = None

    for theo_ev in target_events:
        drv_ev = driver_timeline.get_event(theo_ev.event_type)
        if drv_ev is None or not drv_ev.available:
            continue

        delta_m = round(theo_ev.s_position - drv_ev.s_position, 1)

        # Speed delta at event position
        drv_speed_val = 0.0
        if drv_dist_arr is not None and drv_speed_arr is not None:
            drv_idx = int(np.argmin(np.abs(drv_dist_arr - drv_ev.s_position)))
            if drv_idx < len(drv_speed_arr):
                drv_speed_val = float(drv_speed_arr[drv_idx])

        theo_spd = target_speeds.get(theo_ev.event_type, 0)
        delta_kmh = round((theo_spd - drv_speed_val) * 3.6, 1)

        if abs(delta_m) > 1.0 or abs(delta_kmh) > 1.0:
            if theo_ev.event_type == "BP":
                action = f"Brake {abs(delta_m):.0f}m {'later' if delta_m > 0 else 'earlier'}"
            elif theo_ev.event_type == "THROTTLE_ON":
                action = f"Throttle {abs(delta_m):.0f}m {'earlier' if delta_m > 0 else 'later'}"
            elif theo_ev.event_type == "EOB":
                action = f"Release brakes {abs(delta_m):.0f}m {'later' if delta_m > 0 else 'earlier'}"
            else:
                action = f"Adjust {theo_ev.event_type} by {delta_m:+.0f}m"

            recommended.append({
                "event": theo_ev.event_type,
                "delta_m": delta_m,
                "delta_kmh": delta_kmh,
                "action": action,
            })

    confidence = data_quality * 0.9

    return CornerTargets(
        corner_id=cid,
        target_events=target_events,
        target_speeds=target_speeds,
        priority=priority,
        priority_reason=priority_reason,
        recommended_changes=recommended,
        confidence=confidence,
    )


def validate_corner_targets(
    targets: CornerTargets,
    corner: dict,
    confidence_penalty: float = 0.3,
) -> list[str]:
    """
    Validate corner targets against physics feasibility constraints.

    Rules:
    1. THROTTLE_ON must not be before MRP
    2. EOB must not be after MRP
    3. BP should be before or near corner entry
    4. Event order must be: BP < EOB < MRP < THROTTLE_ON

    Modifies targets.confidence on violation.
    Returns list of warning strings.
    """
    warnings: list[str] = []

    # Build event position lookup
    ev_map: dict[str, float] = {}
    for ev in targets.target_events:
        if ev.available:
            ev_map[ev.event_type] = ev.s_position

    s_start = float(corner.get("s_start", 0))

    # Rule 1: THROTTLE_ON must not be before MRP
    if "THROTTLE_ON" in ev_map and "MRP" in ev_map:
        if ev_map["THROTTLE_ON"] < ev_map["MRP"]:
            warnings.append(
                f"THROTTLE_ON ({ev_map['THROTTLE_ON']:.0f}m) before MRP "
                f"({ev_map['MRP']:.0f}m) — can't power out while still rotating"
            )
            targets.confidence = max(0.0, targets.confidence - confidence_penalty)

    # Rule 2: EOB must not be after MRP
    if "EOB" in ev_map and "MRP" in ev_map:
        if ev_map["EOB"] > ev_map["MRP"]:
            warnings.append(
                f"EOB ({ev_map['EOB']:.0f}m) after MRP "
                f"({ev_map['MRP']:.0f}m) — still braking at max rotation"
            )
            targets.confidence = max(0.0, targets.confidence - confidence_penalty)

    # Rule 3: BP should be before corner entry (with 15m tolerance)
    if "BP" in ev_map:
        if ev_map["BP"] > s_start + 15.0:
            warnings.append(
                f"BP ({ev_map['BP']:.0f}m) well inside corner entry "
                f"({s_start:.0f}m) — braking too late for this corner"
            )
            targets.confidence = max(0.0, targets.confidence - confidence_penalty * 0.5)

    # Rule 4: Overall ordering check
    order = ["BP", "EOB", "MRP", "THROTTLE_ON"]
    positions = [(t, ev_map[t]) for t in order if t in ev_map]
    for i in range(len(positions) - 1):
        if positions[i][1] > positions[i + 1][1]:
            warnings.append(
                f"Event ordering violation: {positions[i][0]} ({positions[i][1]:.0f}m) "
                f"after {positions[i + 1][0]} ({positions[i + 1][1]:.0f}m)"
            )
            targets.confidence = max(0.0, targets.confidence - confidence_penalty)
            break  # only report first ordering violation

    return warnings
