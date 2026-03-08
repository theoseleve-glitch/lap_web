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
) -> list[CornerPerformance]:
    """
    Sort corners by total time loss (descending).

    The top items are where the driver has the most to gain.
    """
    return sorted(
        corner_performances,
        key=lambda p: p.time_loss_s,
        reverse=True,
    )


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

    # 3. MRP — placeholder (Task 3)
    mrp = CornerEvent("MRP", 0.0, 0.0, "yaw_rate", 0.0, False)

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
        mrp_strength=0.0,
        mrp_stability_std_m=0.0,
        event_stability={},
    )
