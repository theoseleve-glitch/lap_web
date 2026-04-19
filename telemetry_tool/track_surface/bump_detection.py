"""
track_surface/bump_detection.py
-------------------------------
Surface bump detection from per-wheel suspension deflection data.

Detects bumps, dips, and transitions by high-pass filtering shock
deflection channels and finding peaks above a configurable threshold.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from track_surface.frenet import FrenetFrame

logger = logging.getLogger(__name__)

_WHEEL_LABELS = ["fl", "fr", "rl", "rr"]
_DEFL_CHANNELS = [f"shock_defl_{w}" for w in _WHEEL_LABELS]
_VEL_CHANNELS = [f"shock_vel_{w}" for w in _WHEEL_LABELS]

# Wheels on each side for lateral offset estimation
_LEFT_WHEELS = {"fl", "rl"}
_RIGHT_WHEELS = {"fr", "rr"}
_FRONT_WHEELS = {"fl", "fr"}
_REAR_WHEELS = {"rl", "rr"}


@dataclass
class SurfaceBump:
    """A detected surface irregularity."""

    s_position: float           # distance along track (m)
    n_estimated: float          # lateral offset estimate (m)
    severity: float             # 0-1 severity score
    bump_type: str              # "bump" | "dip" | "transition"
    affected_wheels: list[str]  # e.g. ["fl", "fr"]

    def to_dict(self) -> dict:
        return {
            "s_position": round(self.s_position, 1),
            "n_estimated": round(self.n_estimated, 2),
            "severity": round(self.severity, 3),
            "bump_type": self.bump_type,
            "affected_wheels": self.affected_wheels,
        }


def _highpass_filter(signal: np.ndarray, cutoff_samples: int = 20) -> np.ndarray:
    """Simple high-pass via subtraction of a running mean.

    Removes steady-state ride height, leaving only transient bumps.
    """
    if len(signal) < cutoff_samples:
        return signal - np.mean(signal)
    kernel = np.ones(cutoff_samples) / cutoff_samples
    padded = np.pad(signal, cutoff_samples, mode="reflect")
    low_pass = np.convolve(padded, kernel, mode="valid")
    # Align: convolve 'valid' shortens by (kernel_len - 1)
    low_pass = low_pass[:len(signal)]
    return signal - low_pass


def _find_peaks_above(arr: np.ndarray, threshold: float) -> list[int]:
    """Find indices where |arr| exceeds threshold (local maxima)."""
    peaks: list[int] = []
    n = len(arr)
    if n < 3:
        return peaks
    for i in range(1, n - 1):
        val = abs(arr[i])
        if val >= threshold and val >= abs(arr[i - 1]) and val >= abs(arr[i + 1]):
            peaks.append(i)
    return peaks


def _get_distance(df: pd.DataFrame) -> np.ndarray | None:
    """Extract or compute a distance array from the DataFrame."""
    for col in ("distance_m", "Distance (m)"):
        if col not in df.columns:
            continue
        raw = pd.to_numeric(df[col], errors="coerce")
        if raw.notna().sum() > 0:
            return raw.values

    # Fall back: integrate speed
    for col in ("speed_mps", "Speed (m/s)"):
        if col not in df.columns:
            continue
        spd = pd.to_numeric(df[col], errors="coerce")
        if spd.notna().sum() > 0:
            dt = 0.01  # assume 100 Hz default
            if "time_s" in df.columns:
                t = pd.to_numeric(df["time_s"], errors="coerce").values
                dt_arr = np.diff(t)
                dt = float(np.nanmedian(dt_arr)) if len(dt_arr) > 0 else 0.01
            return np.cumsum(np.nan_to_num(spd.values) * dt)
    return None


def _get_xy(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray] | None:
    """Extract (x, y) position arrays from the DataFrame."""
    for xc, yc in [
        ("pos_x_m", "pos_y_m"),
        ("x_m", "y_m"),
    ]:
        if xc not in df.columns or yc not in df.columns:
            continue
        xv = pd.to_numeric(df[xc], errors="coerce")
        yv = pd.to_numeric(df[yc], errors="coerce")
        if xv.notna().sum() > 0 and yv.notna().sum() > 0:
            return xv.values, yv.values
    return None


def _classify_bump(
    affected: list[str],
    raw_value: float,
) -> str:
    """Classify bump type from which wheels triggered and sign."""
    fronts = set(affected) & _FRONT_WHEELS
    rears = set(affected) & _REAR_WHEELS
    if fronts and rears:
        return "transition"  # full-width feature (speed bump / ridge)
    if raw_value < 0:
        return "dip"
    return "bump"


def _estimate_n(affected: list[str], track_half_width: float = 4.0) -> float:
    """Estimate lateral offset from which wheels triggered.

    Left wheels -> positive n, right wheels -> negative n.
    Both sides -> centerline (0).
    """
    left_count = len(set(affected) & _LEFT_WHEELS)
    right_count = len(set(affected) & _RIGHT_WHEELS)
    if left_count > 0 and right_count > 0:
        return 0.0
    if left_count > 0:
        return track_half_width * 0.5
    if right_count > 0:
        return -track_half_width * 0.5
    return 0.0


def detect_bumps_from_suspension(
    df: pd.DataFrame,
    frenet: FrenetFrame,
    threshold_mm: float = 3.0,
) -> list[SurfaceBump]:
    """Detect surface bumps from per-wheel shock deflection channels.

    Available channels (Tier 5, may be absent):
    - shock_defl_fl/fr/rl/rr (mm)
    - shock_vel_fl/fr/rl/rr (m/s)

    Also needs: pos_x_m/x_m, pos_y_m/y_m for Frenet projection,
    and distance_m or speed_mps for localization.

    Returns list of SurfaceBump sorted by s_position.
    Returns empty list if shock channels not available.
    """
    # Check which deflection channels are present
    available: dict[str, np.ndarray] = {}
    for ch in _DEFL_CHANNELS:
        if ch not in df.columns:
            continue
        raw = pd.to_numeric(df[ch], errors="coerce")
        if raw.notna().sum() > 10:
            vals = np.nan_to_num(raw.values, nan=0.0)
            available[ch] = vals

    if not available:
        return []

    # Get distance for s-position
    dist = _get_distance(df)
    if dist is None:
        return []

    # Optionally get (x, y) for Frenet projection
    xy = _get_xy(df)

    # High-pass filter each channel and find peaks
    # Map: sample_index -> list of (wheel_label, raw_filtered_value)
    peak_map: dict[int, list[tuple[str, float]]] = {}

    max_defl = 0.0
    for ch_name, vals in available.items():
        wheel = ch_name.replace("shock_defl_", "")
        filtered = _highpass_filter(vals)
        max_defl = max(max_defl, float(np.max(np.abs(filtered))))
        peaks = _find_peaks_above(filtered, threshold_mm)
        for idx in peaks:
            peak_map.setdefault(idx, []).append((wheel, float(filtered[idx])))

    if not peak_map or max_defl < 1e-9:
        return []

    # Merge nearby peaks (within 5 samples)
    sorted_indices = sorted(peak_map.keys())
    merged: list[tuple[int, list[tuple[str, float]]]] = []
    i = 0
    while i < len(sorted_indices):
        group_idx = sorted_indices[i]
        group_wheels = list(peak_map[group_idx])
        j = i + 1
        while j < len(sorted_indices) and sorted_indices[j] - group_idx <= 5:
            group_wheels.extend(peak_map[sorted_indices[j]])
            j += 1
        merged.append((group_idx, group_wheels))
        i = j

    # Convert to SurfaceBump objects
    bumps: list[SurfaceBump] = []
    for sample_idx, wheel_hits in merged:
        affected_wheels = sorted(set(w for w, _ in wheel_hits))
        raw_vals = [v for _, v in wheel_hits]
        mean_val = float(np.mean(raw_vals))
        peak_val = float(np.max(np.abs(raw_vals)))

        severity = min(peak_val / max_defl, 1.0)

        # Get s position
        s_pos = float(dist[min(sample_idx, len(dist) - 1)])

        # If we have xy, project through Frenet for better s,n
        n_est = _estimate_n(affected_wheels)
        if xy is not None:
            xv, yv = xy
            idx = min(sample_idx, len(xv) - 1)
            if np.isfinite(xv[idx]) and np.isfinite(yv[idx]):
                s_arr, n_arr = frenet.xy_to_sn(
                    np.array([xv[idx]]), np.array([yv[idx]]),
                )
                s_pos = float(s_arr[0])
                # Blend Frenet n with wheel-side estimate
                n_est = float(n_arr[0])

        bump_type = _classify_bump(affected_wheels, mean_val)

        bumps.append(SurfaceBump(
            s_position=s_pos,
            n_estimated=n_est,
            severity=severity,
            bump_type=bump_type,
            affected_wheels=affected_wheels,
        ))

    bumps.sort(key=lambda b: b.s_position)
    return bumps
