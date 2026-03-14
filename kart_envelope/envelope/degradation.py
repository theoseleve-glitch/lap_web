"""
degradation.py
--------------
Track tire grip degradation across a session by computing per-window
capability metrics and fitting a degradation trend.

Uses only speed + ax/ay data (Level 1 — GPS + accelerometer).

The core idea: split laps into windows (e.g., laps 1-5, 6-10, 11-15)
and compute the 95th-percentile lateral/traction/braking capability in
each window.  A declining trend = tire degradation.  A rising trend =
tire warm-up (early laps) or track rubbering in.

Outputs:
  - Per-window grip metrics
  - Degradation rate (grip loss per lap, as fraction)
  - Phase classification: warm-up / peak / degradation / stable
  - Coaching advice for tire management
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.ingest.columns import COL_ACCEL_LAT, COL_ACCEL_LONG, COL_SPEED

logger = logging.getLogger(__name__)

_G = 9.80665


@dataclass
class GripWindow:
    """Grip metrics for a window of consecutive laps."""
    window_id: int
    lap_start: int
    lap_end: int
    n_laps: int
    ay_p95: float       # 95th percentile |lateral accel| [m/s²]
    ax_drive_p95: float  # 95th percentile traction accel [m/s²]
    ax_brake_p95: float  # 95th percentile |braking decel| [m/s²]
    gg_p90: float        # 90th percentile combined G-G utilization
    avg_lap_time_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "lap_range": f"{self.lap_start}-{self.lap_end}",
            "n_laps": self.n_laps,
            "ay_p95": round(self.ay_p95, 3),
            "ax_drive_p95": round(self.ax_drive_p95, 3),
            "ax_brake_p95": round(self.ax_brake_p95, 3),
            "gg_p90": round(self.gg_p90, 3),
            "avg_lap_time_s": round(self.avg_lap_time_s, 3),
        }


@dataclass
class DegradationAnalysis:
    """Session-level tire degradation analysis.

    Attributes
    ----------
    windows : list[GripWindow]
        Per-window grip metrics.
    degradation_rate_per_lap : float
        Fractional grip loss per lap (e.g., -0.005 = 0.5% loss/lap).
        Negative = degradation. Positive = improvement (warm-up).
    peak_window : int
        Window ID where peak grip was observed.
    phase : str
        Session phase classification:
        ``"stable"`` — grip variation < 3% across session.
        ``"warm_up_then_stable"`` — first window lower, then stable.
        ``"degradation"`` — clear declining trend after peak.
        ``"warm_up_then_degradation"`` — rises then falls.
    coaching_hint : str
        Tire management coaching advice.
    total_grip_change_pct : float
        Total grip change from peak to final window [%].
    """
    windows: list[GripWindow] = field(default_factory=list)
    degradation_rate_per_lap: float = 0.0
    peak_window: int = 0
    phase: str = "stable"
    coaching_hint: str = ""
    total_grip_change_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [w.to_dict() for w in self.windows],
            "degradation_rate_per_lap": round(self.degradation_rate_per_lap, 5),
            "peak_window": self.peak_window,
            "phase": self.phase,
            "coaching_hint": self.coaching_hint,
            "total_grip_change_pct": round(self.total_grip_change_pct, 2),
        }


def analyze_degradation(
    resampled_laps: dict[int, pd.DataFrame],
    window_size: int = 5,
    min_windows: int = 2,
    lap_times: dict[int, float] | None = None,
) -> DegradationAnalysis:
    """Analyze tire degradation across a session.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        ``{lap_number: resampled_df}`` with canonical columns.
    window_size : int
        Number of laps per analysis window.
    min_windows : int
        Minimum windows required for trend analysis.
    lap_times : dict[int, float] | None
        Optional ``{lap_number: lap_time_s}`` for lap time tracking.

    Returns
    -------
    DegradationAnalysis
    """
    if len(resampled_laps) < window_size:
        return DegradationAnalysis(
            phase="insufficient_data",
            coaching_hint="Not enough laps for degradation analysis.",
        )

    sorted_laps = sorted(resampled_laps.keys())
    n_laps = len(sorted_laps)

    # Build overlapping windows with stride = window_size // 2
    stride = max(window_size // 2, 1)
    windows: list[GripWindow] = []
    win_id = 0

    i = 0
    while i + window_size <= n_laps:
        win_id += 1
        win_laps = sorted_laps[i : i + window_size]
        win_dfs = [resampled_laps[ln] for ln in win_laps]

        gw = _compute_window_metrics(
            window_id=win_id,
            lap_nums=win_laps,
            lap_dfs=win_dfs,
            lap_times=lap_times,
        )
        if gw is not None:
            windows.append(gw)

        i += stride

    # Handle remaining laps if they form at least half a window
    if i < n_laps and (n_laps - i) >= max(window_size // 2, 2):
        win_id += 1
        win_laps = sorted_laps[i:]
        win_dfs = [resampled_laps[ln] for ln in win_laps]
        gw = _compute_window_metrics(
            window_id=win_id,
            lap_nums=win_laps,
            lap_dfs=win_dfs,
            lap_times=lap_times,
        )
        if gw is not None:
            windows.append(gw)

    if len(windows) < min_windows:
        return DegradationAnalysis(
            windows=windows,
            phase="insufficient_data",
            coaching_hint="Not enough valid windows for trend analysis.",
        )

    # Analyze grip trend using ay_p95 as primary metric
    ay_values = np.array([w.ay_p95 for w in windows])
    peak_idx = int(np.argmax(ay_values))
    peak_ay = float(ay_values[peak_idx])

    # Degradation rate: linear fit from peak to end
    if peak_idx < len(windows) - 1 and peak_ay > 0:
        post_peak = ay_values[peak_idx:]
        x = np.arange(len(post_peak)) * stride
        if len(x) >= 2:
            slope = float(np.polyfit(x, post_peak, 1)[0])
            deg_rate = slope / peak_ay  # fractional per lap
        else:
            deg_rate = 0.0
    else:
        deg_rate = 0.0

    final_ay = float(ay_values[-1])
    total_change_pct = ((final_ay - peak_ay) / peak_ay * 100) if peak_ay > 0 else 0.0

    phase = _classify_phase(ay_values, peak_idx)
    hint = _degradation_hint(phase, deg_rate, total_change_pct, len(sorted_laps))

    return DegradationAnalysis(
        windows=windows,
        degradation_rate_per_lap=deg_rate,
        peak_window=peak_idx + 1,
        phase=phase,
        coaching_hint=hint,
        total_grip_change_pct=total_change_pct,
    )


def _compute_window_metrics(
    window_id: int,
    lap_nums: list[int],
    lap_dfs: list[pd.DataFrame],
    lap_times: dict[int, float] | None,
) -> GripWindow | None:
    """Compute grip metrics for a window of laps."""
    v_all, ax_all, ay_all = [], [], []

    for df in lap_dfs:
        if COL_SPEED not in df.columns:
            continue
        v = pd.to_numeric(df.get(COL_SPEED), errors="coerce").to_numpy(dtype=float)
        ax = (pd.to_numeric(df.get(COL_ACCEL_LONG), errors="coerce").to_numpy(dtype=float)
              if COL_ACCEL_LONG in df.columns else np.zeros_like(v))
        ay = (pd.to_numeric(df.get(COL_ACCEL_LAT), errors="coerce").to_numpy(dtype=float)
              if COL_ACCEL_LAT in df.columns else np.zeros_like(v))

        valid = np.isfinite(v) & np.isfinite(ax) & np.isfinite(ay) & (v > 1.0)
        v_all.append(v[valid])
        ax_all.append(ax[valid])
        ay_all.append(ay[valid])

    if not v_all:
        return None

    v_cat = np.concatenate(v_all)
    ax_cat = np.concatenate(ax_all)
    ay_cat = np.concatenate(ay_all)

    if len(v_cat) < 50:
        return None

    ay_abs = np.abs(ay_cat)
    ax_pos = ax_cat[ax_cat > 0.1]
    ax_neg = np.abs(ax_cat[ax_cat < -0.1])

    ay_p95 = float(np.percentile(ay_abs, 95))
    ax_drive_p95 = float(np.percentile(ax_pos, 95)) if len(ax_pos) >= 10 else 0.0
    ax_brake_p95 = float(np.percentile(ax_neg, 95)) if len(ax_neg) >= 10 else 0.0

    # Combined G-G utilization (using max observed as reference)
    ay_max = max(ay_p95, 0.1)
    ax_max = max(max(ax_drive_p95, ax_brake_p95), 0.1)
    gg = np.sqrt((np.abs(ax_cat) / ax_max) ** 2 + (ay_abs / ay_max) ** 2)
    gg_p90 = float(np.percentile(gg[np.isfinite(gg)], 90))

    avg_lt = 0.0
    if lap_times:
        lts = [lap_times[ln] for ln in lap_nums if ln in lap_times]
        avg_lt = float(np.mean(lts)) if lts else 0.0

    return GripWindow(
        window_id=window_id,
        lap_start=int(lap_nums[0]),
        lap_end=int(lap_nums[-1]),
        n_laps=len(lap_nums),
        ay_p95=ay_p95,
        ax_drive_p95=ax_drive_p95,
        ax_brake_p95=ax_brake_p95,
        gg_p90=gg_p90,
        avg_lap_time_s=avg_lt,
    )


def _classify_phase(
    ay_values: np.ndarray,
    peak_idx: int,
) -> str:
    """Classify the grip evolution phase pattern."""
    n = len(ay_values)
    if n < 2:
        return "stable"

    peak = float(ay_values[peak_idx])
    if peak <= 0:
        return "stable"

    # Relative values
    rel = ay_values / peak

    # Check stability: all within 3% of peak
    if float(np.max(np.abs(rel - 1.0))) < 0.03:
        return "stable"

    first_rel = float(rel[0])
    last_rel = float(rel[-1])
    warm_up = peak_idx > 0 and first_rel < 0.96
    degradation = last_rel < 0.96 and peak_idx < n - 1

    if warm_up and degradation:
        return "warm_up_then_degradation"
    if warm_up:
        return "warm_up_then_stable"
    if degradation:
        return "degradation"
    return "stable"


def _degradation_hint(
    phase: str,
    deg_rate: float,
    total_change_pct: float,
    total_laps: int,
) -> str:
    """Generate tire management coaching hint."""
    if phase == "stable":
        return (
            "Tire grip remained stable throughout the session. "
            "No tire management concerns."
        )

    if phase == "warm_up_then_stable":
        return (
            "Tires needed warm-up in the first few laps, then stabilized. "
            "Consider a more aggressive warm-up routine (weaving, brake "
            "heating) to reach peak grip sooner."
        )

    deg_per_lap_pct = abs(deg_rate * 100)

    if phase == "degradation":
        if deg_per_lap_pct > 1.0:
            return (
                f"Significant tire degradation: {deg_per_lap_pct:.1f}%/lap, "
                f"{abs(total_change_pct):.1f}% total loss over {total_laps} laps. "
                f"Reduce aggression in the first third of the stint to preserve "
                f"grip for the final laps. Smooth inputs extend tire life."
            )
        return (
            f"Mild tire degradation: {deg_per_lap_pct:.1f}%/lap, "
            f"{abs(total_change_pct):.1f}% total. "
            f"Monitor grip feel in the final laps and adjust braking "
            f"points 1-2m earlier as grip fades."
        )

    # warm_up_then_degradation
    return (
        f"Tires warmed up then degraded ({abs(total_change_pct):.1f}% from peak, "
        f"{deg_per_lap_pct:.1f}%/lap). "
        f"Your peak grip window is limited — use the early laps to learn "
        f"the track, then push during the grip peak (mid-stint). "
        f"Ease off in the final third to avoid sliding."
    )
