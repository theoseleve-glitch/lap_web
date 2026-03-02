"""Wheel slip detection module for motorsport telemetry.

Detects lockup events, wheelspin, and per-corner traction utilisation
from wheel-speed and vehicle-speed channels.  All analysis is
distance-based (not time-based).
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Slip ratio computation
# ---------------------------------------------------------------------------

def compute_slip_ratios(
    wheel_speed_fl: np.ndarray,
    wheel_speed_fr: np.ndarray,
    wheel_speed_rl: np.ndarray,
    wheel_speed_rr: np.ndarray,
    vehicle_speed: np.ndarray,
) -> dict:
    """Compute per-wheel slip ratios.

    ``slip = (wheel_speed - vehicle_speed) / max(wheel_speed, vehicle_speed, 0.1)``

    * Negative slip -> lockup (wheel slower than car).
    * Positive slip -> wheelspin (wheel faster than car).

    The denominator is clamped at 0.1 m/s to avoid division by zero when
    both speeds are near zero.

    Returns
    -------
    dict
        ``{'fl': ndarray, 'fr': ndarray, 'rl': ndarray, 'rr': ndarray}``
    """
    ws = {
        "fl": np.asarray(wheel_speed_fl, dtype=float),
        "fr": np.asarray(wheel_speed_fr, dtype=float),
        "rl": np.asarray(wheel_speed_rl, dtype=float),
        "rr": np.asarray(wheel_speed_rr, dtype=float),
    }
    vs = np.asarray(vehicle_speed, dtype=float)

    result = {}
    for corner, w in ws.items():
        denom = np.maximum(np.maximum(np.abs(w), np.abs(vs)), 0.1)
        slip = (w - vs) / denom
        # Replace NaN with 0
        slip = np.where(np.isfinite(slip), slip, 0.0)
        result[corner] = slip

    return result


# ---------------------------------------------------------------------------
# Event detection helpers
# ---------------------------------------------------------------------------

def _find_events(
    distances: np.ndarray,
    slip: np.ndarray,
    condition_mask: np.ndarray,
    min_duration_m: float,
    severity_fn,
) -> list[dict]:
    """Generic run-length event detector on a boolean mask.

    Groups contiguous True regions, filters by *min_duration_m*, and
    annotates each event with peak slip and severity.
    """
    events: list[dict] = []
    if len(distances) == 0 or condition_mask.sum() == 0:
        return events

    # Pad with False to detect edges
    padded = np.concatenate([[False], condition_mask, [False]])
    diffs = np.diff(padded.astype(int))
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]

    for s, e in zip(starts, ends):
        if e > len(distances):
            e = len(distances)
        if s >= len(distances):
            continue

        start_m = float(distances[s])
        end_m = float(distances[min(e - 1, len(distances) - 1)])
        duration_m = end_m - start_m

        if duration_m < min_duration_m:
            continue

        peak_slip = float(slip[s:e].min()) if slip[s:e].min() < 0 else float(slip[s:e].max())
        # For lockups peak is min (most negative), for wheelspin peak is max
        if np.mean(slip[s:e]) < 0:
            peak_slip = float(slip[s:e].min())
        else:
            peak_slip = float(slip[s:e].max())

        events.append({
            "start_m": round(start_m, 2),
            "end_m": round(end_m, 2),
            "duration_m": round(duration_m, 2),
            "peak_slip": round(peak_slip, 4),
            "severity": severity_fn(peak_slip),
        })

    return events


def _lockup_severity(peak_slip: float) -> str:
    """Classify lockup severity by peak negative slip."""
    abs_slip = abs(peak_slip)
    if abs_slip >= 0.5:
        return "severe"
    if abs_slip >= 0.3:
        return "moderate"
    return "light"


def _wheelspin_severity(peak_slip: float) -> str:
    """Classify wheelspin severity by peak positive slip."""
    if peak_slip >= 0.5:
        return "severe"
    if peak_slip >= 0.3:
        return "moderate"
    return "light"


# ---------------------------------------------------------------------------
# Lockup detection
# ---------------------------------------------------------------------------

def detect_lockups(
    distances: np.ndarray,
    slip_ratios: dict,
    threshold: float = -0.15,
    min_duration_m: float = 2.0,
) -> list[dict]:
    """Detect lockup events where slip ratio drops below *threshold*.

    Parameters
    ----------
    distances : np.ndarray
        Monotonically increasing distance array (m).
    slip_ratios : dict
        Per-corner slip arrays from :func:`compute_slip_ratios`.
    threshold : float
        Negative slip value below which a lockup is detected.
    min_duration_m : float
        Minimum event length in metres to report.

    Returns
    -------
    list[dict]
        Each event: ``{corner, start_m, end_m, duration_m, peak_slip, severity}``.
    """
    distances = np.asarray(distances, dtype=float)
    events: list[dict] = []

    for corner, slip in slip_ratios.items():
        slip = np.asarray(slip, dtype=float)
        if len(slip) != len(distances):
            continue
        mask = slip < threshold
        corner_events = _find_events(
            distances, slip, mask, min_duration_m, _lockup_severity,
        )
        for ev in corner_events:
            ev["corner"] = corner
        events.extend(corner_events)

    # Sort by distance
    events.sort(key=lambda e: e["start_m"])
    return events


# ---------------------------------------------------------------------------
# Wheelspin detection
# ---------------------------------------------------------------------------

def detect_wheelspin(
    distances: np.ndarray,
    slip_ratios: dict,
    threshold: float = 0.10,
    min_duration_m: float = 2.0,
) -> list[dict]:
    """Detect wheelspin events where slip ratio exceeds *threshold*.

    Parameters
    ----------
    distances : np.ndarray
        Monotonically increasing distance array (m).
    slip_ratios : dict
        Per-corner slip arrays from :func:`compute_slip_ratios`.
    threshold : float
        Positive slip value above which wheelspin is detected.
    min_duration_m : float
        Minimum event length in metres to report.

    Returns
    -------
    list[dict]
        Each event: ``{corner, start_m, end_m, duration_m, peak_slip, severity}``.
    """
    distances = np.asarray(distances, dtype=float)
    events: list[dict] = []

    for corner, slip in slip_ratios.items():
        slip = np.asarray(slip, dtype=float)
        if len(slip) != len(distances):
            continue
        mask = slip > threshold
        corner_events = _find_events(
            distances, slip, mask, min_duration_m, _wheelspin_severity,
        )
        for ev in corner_events:
            ev["corner"] = corner
        events.extend(corner_events)

    events.sort(key=lambda e: e["start_m"])
    return events


# ---------------------------------------------------------------------------
# Traction utilisation per corner
# ---------------------------------------------------------------------------

def analyze_traction_utilization(
    distances: np.ndarray,
    slip_ratios: dict,
    corners: list[dict],
) -> list[dict]:
    """Compute per-corner traction statistics.

    For each corner zone ``[entry_m, exit_m]``, compute mean and max
    absolute slip on every wheel, and produce a traction rating.

    Parameters
    ----------
    distances : np.ndarray
        Distance channel (m).
    slip_ratios : dict
        Per-wheel slip from :func:`compute_slip_ratios`.
    corners : list[dict]
        Each with ``corner_id``, ``entry_m``, ``apex_m``, ``exit_m``.

    Returns
    -------
    list[dict]
        ``{corner_id, mean_slip: {fl,fr,rl,rr}, max_slip: {fl,fr,rl,rr}, traction_rating}``
    """
    distances = np.asarray(distances, dtype=float)
    results: list[dict] = []

    for c in corners:
        entry = c.get("entry_m", 0.0)
        exit_ = c.get("exit_m", 0.0)
        mask = (distances >= entry) & (distances <= exit_)

        if mask.sum() == 0:
            results.append({
                "corner_id": c.get("corner_id"),
                "mean_slip": {},
                "max_slip": {},
                "traction_rating": "no_data",
            })
            continue

        mean_slip = {}
        max_slip = {}
        worst_mean = 0.0

        for wheel, slip_arr in slip_ratios.items():
            slip_arr = np.asarray(slip_arr, dtype=float)
            if len(slip_arr) != len(distances):
                continue
            zone = np.abs(slip_arr[mask])
            zone = zone[np.isfinite(zone)]
            if len(zone) == 0:
                mean_slip[wheel] = 0.0
                max_slip[wheel] = 0.0
            else:
                m = float(zone.mean())
                mean_slip[wheel] = round(m, 4)
                max_slip[wheel] = round(float(zone.max()), 4)
                worst_mean = max(worst_mean, m)

        if worst_mean < 0.05:
            rating = "excellent"
        elif worst_mean < 0.10:
            rating = "good"
        elif worst_mean < 0.20:
            rating = "marginal"
        else:
            rating = "poor"

        results.append({
            "corner_id": c.get("corner_id"),
            "mean_slip": mean_slip,
            "max_slip": max_slip,
            "traction_rating": rating,
        })

    return results


# ---------------------------------------------------------------------------
# Column helpers
# ---------------------------------------------------------------------------

_SLIP_COLS = {
    "fl": ["wheel_slip_fl", "Wheel Slip FL"],
    "fr": ["wheel_slip_fr", "Wheel Slip FR"],
    "rl": ["wheel_slip_rl", "Wheel Slip RL"],
    "rr": ["wheel_slip_rr", "Wheel Slip RR"],
}

_WHEEL_SPEED_COLS = {
    "fl": ["wheel_speed_fl", "Wheel Speed FL (m/s)"],
    "fr": ["wheel_speed_fr", "Wheel Speed FR (m/s)"],
    "rl": ["wheel_speed_rl", "Wheel Speed RL (m/s)"],
    "rr": ["wheel_speed_rr", "Wheel Speed RR (m/s)"],
}

_DISTANCE_COLS = ["distance_m", "Distance (m)"]
_SPEED_COLS = ["speed_mps", "Speed (m/s)"]


def _resolve_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


# ---------------------------------------------------------------------------
# Session-level master function
# ---------------------------------------------------------------------------

def analyze_slip_session(
    resampled_laps: dict,
    corners: list[dict] | None = None,
) -> dict:
    """Run all slip analyses across a session.

    Parameters
    ----------
    resampled_laps : dict
        ``{lap_number: pd.DataFrame}``  Each DataFrame should contain
        either pre-computed slip columns or wheel-speed + vehicle-speed
        columns, plus a distance channel.
    corners : list[dict] | None
        Corner descriptors with ``corner_id``, ``entry_m``, ``exit_m``.

    Returns
    -------
    dict
        ``{has_slip_data, lockups, wheelspin, per_corner, summary}``
    """
    result: dict = {
        "has_slip_data": False,
        "lockups": [],
        "wheelspin": [],
        "per_corner": [],
        "summary": {},
    }

    if not resampled_laps:
        return result

    first_df = next(iter(resampled_laps.values()))
    dist_col = _resolve_col(first_df, _DISTANCE_COLS)
    if dist_col is None:
        return result

    # Try pre-computed slip columns first
    slip_cols = {pos: _resolve_col(first_df, cands) for pos, cands in _SLIP_COLS.items()}
    has_precomputed = all(slip_cols.values())

    # Otherwise try to compute from wheel speeds
    ws_cols = {pos: _resolve_col(first_df, cands) for pos, cands in _WHEEL_SPEED_COLS.items()}
    speed_col = _resolve_col(first_df, _SPEED_COLS)
    has_raw = all(ws_cols.values()) and speed_col is not None

    if not has_precomputed and not has_raw:
        return result

    result["has_slip_data"] = True
    total_lockups: list[dict] = []
    total_wheelspin: list[dict] = []

    for lap_num, df in sorted(resampled_laps.items()):
        distances = df[dist_col].values

        if has_precomputed:
            slip_ratios = {
                pos: df[col].fillna(0.0).values
                for pos, col in slip_cols.items()
            }
        else:
            slip_ratios = compute_slip_ratios(
                df[ws_cols["fl"]].fillna(0.0).values,
                df[ws_cols["fr"]].fillna(0.0).values,
                df[ws_cols["rl"]].fillna(0.0).values,
                df[ws_cols["rr"]].fillna(0.0).values,
                df[speed_col].fillna(0.0).values,
            )

        lockups = detect_lockups(distances, slip_ratios)
        for ev in lockups:
            ev["lap"] = lap_num
        total_lockups.extend(lockups)

        wheelspin = detect_wheelspin(distances, slip_ratios)
        for ev in wheelspin:
            ev["lap"] = lap_num
        total_wheelspin.extend(wheelspin)

    result["lockups"] = total_lockups
    result["wheelspin"] = total_wheelspin

    # Per-corner analysis on first lap (representative)
    if corners:
        first_lap_df = next(iter(resampled_laps.values()))
        distances = first_lap_df[dist_col].values
        if has_precomputed:
            slip_ratios = {
                pos: first_lap_df[col].fillna(0.0).values
                for pos, col in slip_cols.items()
            }
        else:
            slip_ratios = compute_slip_ratios(
                first_lap_df[ws_cols["fl"]].fillna(0.0).values,
                first_lap_df[ws_cols["fr"]].fillna(0.0).values,
                first_lap_df[ws_cols["rl"]].fillna(0.0).values,
                first_lap_df[ws_cols["rr"]].fillna(0.0).values,
                first_lap_df[speed_col].fillna(0.0).values,
            )
        result["per_corner"] = analyze_traction_utilization(
            distances, slip_ratios, corners,
        )

    result["summary"] = {
        "total_lockups": len(total_lockups),
        "total_wheelspin": len(total_wheelspin),
        "severe_events": len(
            [e for e in total_lockups + total_wheelspin if e.get("severity") == "severe"]
        ),
    }

    return result
