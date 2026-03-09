"""
pipeline.helpers
~~~~~~~~~~~~~~~~
Shared utilities for the pipeline package: safe-step wrapper,
dynamic import, error class, column constants, and metric helpers.
"""
from __future__ import annotations

import logging
import math
import traceback
from typing import Any, Callable, Final, Optional, TypeVar

import numpy as np
import pandas as pd

from pipeline_status import (
    StepState,
    StepStatus,
    now_epoch,
    now_monotonic,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Column-name constants (mirrors upstream) ──────────────────────

_COL_LAP:   Final[str] = "Lap #"
_COL_TIME:  Final[str] = "Time (s)"
_COL_SPEED: Final[str] = "Speed (m/s)"
_COL_DIST:  Final[str] = "Distance (m)"


# ── Dynamic import helper ─────────────────────────────────────────

def lazy_import(module_name: str) -> Any:
    """Import *module_name*; return ``None`` if unavailable."""
    try:
        import importlib
        return importlib.import_module(module_name)
    except ImportError as exc:
        logger.warning("Module %r unavailable: %s", module_name, exc)
        return None


# ── Pipeline error ────────────────────────────────────────────────

class PipelineError(Exception):
    """Raised internally when a pipeline step fails."""


# ── Safe-step wrapper ─────────────────────────────────────────────

_last_step_status: Optional[StepStatus] = None
"""Module-level slot used by ``run_full_analysis`` closures.

``_safe_step`` writes the most recent :class:`StepStatus` here;
``_record`` reads and clears it so the pipeline status tracker
stays in sync without requiring changes to every call-site.
"""


def _safe_step(
    step_name: str,
    fn: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> tuple[Optional[T], Optional[str]]:
    """
    Execute *fn*.  Return ``(result, None)`` on success, or
    ``(None, error_msg)`` on failure.  Never raises.

    Side-effect: stores a :class:`StepStatus` in the module-level
    ``_last_step_status`` slot for ``_record`` to pick up.
    """
    global _last_step_status  # noqa: PLW0603
    t_start_epoch = now_epoch()
    t_start = now_monotonic()
    try:
        result = fn(*args, **kwargs)
        duration_ms = (now_monotonic() - t_start) * 1000
        logger.info("Step [%s] --  OK  (%.0f ms)", step_name, duration_ms)
        _last_step_status = StepStatus(
            name=step_name,
            status=StepState.OK,
            started_at=t_start_epoch,
            duration_ms=duration_ms,
        )
        return result, None
    except Exception as exc:
        duration_ms = (now_monotonic() - t_start) * 1000
        tb = traceback.format_exc()
        msg = f"{type(exc).__name__}: {exc}"
        logger.warning("Step [%s] --  FAILED: %s  (%.0f ms)", step_name, msg, duration_ms)
        logger.debug("Step [%s] traceback:\n%s", step_name, tb)
        _last_step_status = StepStatus(
            name=step_name,
            status=StepState.FAIL,
            started_at=t_start_epoch,
            duration_ms=duration_ms,
            message_code=type(exc).__name__,
            message=str(exc)[:200],
        )
        return None, msg


def get_and_clear_last_step_status() -> Optional[StepStatus]:
    """Return the last step status and clear the slot."""
    global _last_step_status  # noqa: PLW0603
    status = _last_step_status
    _last_step_status = None
    return status


# ── Lap distance validation & repair ──────────────────────────────

def validate_lap_consistency(
    lap_dict: dict[int, pd.DataFrame],
    *,
    min_distance_m: float = 50.0,
    max_speed_mps: float = 120.0,
) -> dict[int, pd.DataFrame]:
    """Validate and repair per-lap distance data.

    For each lap check that:
    - Distance column exists and is monotonically increasing.
    - Total distance is above *min_distance_m*.
    - No speed exceeds *max_speed_mps* (sanity check).

    Returns the (possibly repaired) *lap_dict*.
    """
    dist_col: Optional[str] = None
    sample_df = next(iter(lap_dict.values()))
    for candidate in (_COL_DIST, "distance_m", "dist_m"):
        if candidate in sample_df.columns:
            dist_col = candidate
            break
    if dist_col is None:
        return lap_dict

    repaired: dict[int, pd.DataFrame] = {}
    for ln, df in lap_dict.items():
        if dist_col not in df.columns:
            repaired[ln] = df
            continue

        dist = pd.to_numeric(df[dist_col], errors="coerce")

        # Repair non-monotonic distance by forward-fill
        if not dist.is_monotonic_increasing:
            dist = dist.cummax()
            df = df.copy()
            df[dist_col] = dist

        total_dist = float(dist.iloc[-1] - dist.iloc[0]) if len(dist) > 1 else 0.0
        if total_dist < min_distance_m:
            logger.debug("Lap %d: distance %.1f m < %.1f m threshold — kept but flagged.", ln, total_dist, min_distance_m)

        repaired[ln] = df

    return repaired


# ── Robustness metrics ────────────────────────────────────────────

def compute_robustness_metrics(
    resampled_laps: dict[int, pd.DataFrame],
    lap_times: list[float],
    *,
    early_frac: float = 0.33,
    late_frac: float = 0.33,
) -> dict[str, Any]:
    """Compute early-vs-late stint metrics for robustness scoring."""
    n = len(lap_times)
    if n < 3:
        return {}

    valid_times = [t for t in lap_times if isinstance(t, (int, float)) and math.isfinite(t) and t > 0]
    if len(valid_times) < 3:
        return {}

    n_early = max(1, int(n * early_frac))
    n_late  = max(1, int(n * late_frac))
    early = valid_times[:n_early]
    late  = valid_times[-n_late:]

    mean_early = float(np.mean(early))
    mean_late  = float(np.mean(late))
    std_early  = float(np.std(early))  if len(early) > 1 else 0.0
    std_late   = float(np.std(late))   if len(late) > 1 else 0.0

    drift = mean_late - mean_early
    drift_pct = (drift / mean_early * 100) if mean_early > 0 else 0.0

    # Speed consistency across distance bins
    speed_col = _COL_SPEED
    all_stds: list[float] = []
    for ln in sorted(resampled_laps.keys()):
        rlap = resampled_laps[ln]
        if speed_col in rlap.columns:
            s = pd.to_numeric(rlap[speed_col], errors="coerce").dropna()
            if len(s) > 10:
                all_stds.append(float(s.std()))

    return {
        "mean_early_s":      round(mean_early, 4),
        "mean_late_s":       round(mean_late, 4),
        "std_early_s":       round(std_early, 4),
        "std_late_s":        round(std_late, 4),
        "drift_s":           round(drift, 4),
        "drift_pct":         round(drift_pct, 2),
        "n_early":           n_early,
        "n_late":            n_late,
        "speed_std_mean":    round(float(np.mean(all_stds)), 4) if all_stds else None,
    }


# ── Theoretical metrics extraction ────────────────────────────────

def theoretical_metrics_from_lap(
    theoretical_lap: pd.DataFrame,
    *,
    simulation_method: str = "unknown",
    sim_result: Any = None,
    data_quality: Any = None,
) -> dict[str, Any]:
    """Extract scalar metrics from a theoretical lap DataFrame."""
    speed_col = None
    for c in (_COL_SPEED, "speed_mps", "Speed (m/s)"):
        if c in theoretical_lap.columns:
            speed_col = c
            break

    time_col = None
    for c in (_COL_TIME, "time_s", "Time (s)"):
        if c in theoretical_lap.columns:
            time_col = c
            break

    dist_col = None
    for c in (_COL_DIST, "distance_m", "Distance (m)"):
        if c in theoretical_lap.columns:
            dist_col = c
            break

    metrics: dict[str, Any] = {"method": simulation_method}

    if time_col is not None:
        times = pd.to_numeric(theoretical_lap[time_col], errors="coerce").dropna()
        if len(times) > 0:
            metrics["best_s"] = float(times.iloc[-1] - times.iloc[0])
    if speed_col is not None:
        speeds = pd.to_numeric(theoretical_lap[speed_col], errors="coerce").dropna()
        if len(speeds) > 0:
            metrics["max_speed_mps"] = float(speeds.max())
            metrics["avg_speed_mps"] = float(speeds.mean())
            metrics["min_speed_mps"] = float(speeds.min())

    if sim_result is not None:
        if hasattr(sim_result, "lap_time_s"):
            metrics["best_s"] = float(sim_result.lap_time_s)
        if hasattr(sim_result, "max_speed_mps"):
            metrics["max_speed_mps"] = float(sim_result.max_speed_mps)
        if hasattr(sim_result, "method"):
            metrics["method"] = sim_result.method
        if hasattr(sim_result, "diagnostics"):
            metrics["diagnostics"] = sim_result.diagnostics

    if data_quality is not None:
        metrics["data_quality_confidence"] = getattr(data_quality, "overall_confidence", None)

    return metrics


# ── Track layout extraction for corner picker ─────────────────────

def extract_track_layout_for_picker(
    best_lap_df: pd.DataFrame,
    corners: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Build a lightweight track layout dict for the corner picker UI."""
    lat_col = lon_col = dist_col = None
    for c in ("Latitude (deg)", "lat_deg", "latitude"):
        if c in best_lap_df.columns:
            lat_col = c
            break
    for c in ("Longitude (deg)", "lon_deg", "longitude"):
        if c in best_lap_df.columns:
            lon_col = c
            break
    for c in (_COL_DIST, "distance_m", "dist_m"):
        if c in best_lap_df.columns:
            dist_col = c
            break

    if lat_col is None or lon_col is None:
        return None

    lat = pd.to_numeric(best_lap_df[lat_col], errors="coerce").values
    lon = pd.to_numeric(best_lap_df[lon_col], errors="coerce").values
    dist_arr = (
        pd.to_numeric(best_lap_df[dist_col], errors="coerce").values
        if dist_col else np.arange(len(lat), dtype=float)
    )

    # Downsample for UI (max ~500 points)
    step = max(1, len(lat) // 500)
    return {
        "lat": lat[::step].tolist(),
        "lon": lon[::step].tolist(),
        "distance_m": dist_arr[::step].tolist(),
        "corners": corners,
        "n_points": len(lat),
    }
