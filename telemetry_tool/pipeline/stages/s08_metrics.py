"""
Stage 08 -- Per-Lap Metrics, Consistency, Robustness, Condition Tracking,
            Weather, Tyre Degradation, Invalid/Incomplete/Anomalous Lap
            Detection, and Best-Lap Selection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Steps 08-08j: compute per-lap features, flag bad laps, select the best
representative lap for downstream physics and scoring stages.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from pipeline.helpers import (
    _COL_LAP,
    _COL_SPEED,
    compute_robustness_metrics,
    lazy_import,
)

logger = logging.getLogger(__name__)


# ── Step 08: Per-lap metrics ─────────────────────────────────────────


def run_compute_metrics(
    resampled_laps: dict[int, pd.DataFrame],
) -> tuple[list[dict[str, Any]], list[float]]:
    """Step 08: Compute per-lap metrics.

    For each lap compute lap time, speed profile features, acceleration
    features, and line length.

    Returns
    -------
    (lap_metrics, lap_times) : tuple
        *lap_metrics* is a list of dicts (one per lap).
        *lap_times* is a parallel list of lap-time floats.

    Raises
    ------
    ImportError
        If the ``features`` module is unavailable.
    """
    feat_mod = lazy_import("features")
    if feat_mod is None:
        raise ImportError("features module unavailable")

    all_metrics: list[dict[str, Any]] = []
    all_times: list[float] = []

    for ln in sorted(resampled_laps.keys()):
        rlap = resampled_laps[ln]
        m: dict[str, Any] = {"lap_number": ln}
        m.update(feat_mod.compute_lap_time(rlap))
        m.update(feat_mod.compute_speed_profile_features(rlap))
        m.update(feat_mod.compute_accel_features(rlap))
        m.update(feat_mod.compute_line_length(rlap))
        all_metrics.append(m)
        lt = m.get("lap_time_s", float("nan"))
        all_times.append(float(lt) if lt is not None else float("nan"))

    return all_metrics, all_times


# ── Step 08b: Consistency ────────────────────────────────────────────


def run_consistency(lap_times: list[float]) -> dict[str, Any]:
    """Step 08b: Compute consistency metrics from lap times.

    Returns an empty dict if the ``features`` module is unavailable.
    """
    feat_mod = lazy_import("features")
    if feat_mod is None:
        return {}
    return feat_mod.compute_consistency_metrics(lap_times)


# ── Step 08d: Condition tracking ─────────────────────────────────────


def run_condition_tracking(
    lap_metrics: list[dict[str, Any]],
    lap_times: list[float],
    *,
    meta: Optional[dict[str, Any]] = None,
    csv_path: Optional[str] = None,
    context: Any = None,
    output_dir: Optional[str] = None,
    driver_tag: str = "",
) -> tuple[Optional[pd.DataFrame], Optional[dict[int, int]]]:
    """Step 08d: Condition tracking.

    Detect grip / track-condition changes across the stint using
    telemetry-derived indicators.  Optionally merge manual condition
    markers from *meta* and persist phases to *output_dir*.

    Returns
    -------
    (phases_df, lap_to_phase) : tuple
        *phases_df* is a DataFrame of condition phases (or ``None``).
        *lap_to_phase* maps lap numbers to phase IDs (or ``None``).
    """
    ct_mod = lazy_import("condition_tracking")
    if ct_mod is None:
        logger.info("condition_tracking module absent; skipping.")
        return None, None

    if not lap_metrics:
        return None, None

    if meta is None:
        meta = {}

    lm_df = pd.DataFrame(lap_metrics)
    indicators = ct_mod.compute_grip_indicators(lm_df)

    # Use combined detection (z-score + trend) if available
    if hasattr(ct_mod, "detect_condition_changes_combined"):
        changes = ct_mod.detect_condition_changes_combined(
            indicators, lap_times=lap_times,
        )
    else:
        changes = ct_mod.detect_condition_changes(indicators)

    # Merge manual condition markers (--condition-change CLI flag)
    manual_cc = meta.get("manual_condition_changes")
    if manual_cc and hasattr(ct_mod, "merge_manual_changes"):
        changes = ct_mod.merge_manual_changes(changes, manual_cc)
        logger.info("Merged %d manual condition change(s).", len(manual_cc))

    phases_df = ct_mod.build_condition_phases(lm_df, changes)

    # Label phases if context available
    if context is not None and hasattr(context, "baseline_track_state"):
        weather = getattr(context, "weather", None)
        phases_df = ct_mod.label_phases(
            phases_df, context.baseline_track_state, weather,
        )

    # Build lap-to-phase mapping
    lap_to_phase: dict[int, int] = {}
    if (
        "phase_id" in phases_df.columns
        and "lap_start" in phases_df.columns
        and "lap_end" in phases_df.columns
    ):
        for _, row in phases_df.iterrows():
            pid = int(row["phase_id"])
            for ln in range(int(row["lap_start"]), int(row["lap_end"]) + 1):
                lap_to_phase[ln] = pid

    # Persist phases CSV
    if output_dir is not None:
        try:
            _dtag_suffix = f"_{driver_tag}" if driver_tag else ""
            phases_path = Path(output_dir) / f"condition_phases{_dtag_suffix}.csv"
            phases_path.parent.mkdir(parents=True, exist_ok=True)
            phases_df.to_csv(phases_path, index=False)
            logger.info("Saved condition phases to %s", phases_path)
        except Exception as exc:
            logger.warning("Could not save phases: %s", exc)

    return phases_df, lap_to_phase


# ── Step 08d2: Track evolution rate ──────────────────────────────────


def run_track_evolution(
    phases_df: Optional[pd.DataFrame],
    lap_metrics: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Step 08d2: Compute track evolution rate from condition phases.

    Returns a dict with ``total_evolution_pct`` and ``grip_trend``, or
    ``None`` if prerequisites are missing.
    """
    ct_mod = lazy_import("condition_tracking")
    if ct_mod is None or not hasattr(ct_mod, "compute_track_evolution_rate"):
        return None
    if phases_df is None or phases_df.empty:
        return None
    if not lap_metrics:
        return None

    lm_df = pd.DataFrame(lap_metrics)
    return ct_mod.compute_track_evolution_rate(phases_df, lm_df)


# ── Step 08e (weather): Weather timeline ─────────────────────────────


def run_weather_timeline(
    csv_path: Optional[str],
    meta: Optional[dict[str, Any]],
    summary: dict[str, Any],
    lap_times: list[float],
    *,
    conn: Any = None,
) -> Optional[pd.DataFrame]:
    """Step 08e: Build per-lap weather timeline via meteo API.

    Requires a session datetime (from CSV filename or *meta*), track
    coordinates from the DB, and the ``weather_timeline`` +
    ``meteo_service`` modules.

    Returns a DataFrame with per-lap weather data or ``None``.
    """
    wt_mod = lazy_import("weather_timeline")
    ms_mod = lazy_import("meteo_service")
    if wt_mod is None or ms_mod is None:
        return None

    if meta is None:
        meta = {}

    # Resolve session datetime
    session_dt = wt_mod.parse_session_datetime(csv_path) if csv_path else None
    if session_dt is None:
        dt_str = meta.get("session_datetime") or meta.get("date")
        if dt_str:
            try:
                session_dt = datetime.fromisoformat(str(dt_str))
            except (ValueError, TypeError):
                pass
    if session_dt is None:
        logger.info("No session datetime available; skipping weather timeline")
        return None

    # Get track coordinates from DB
    track_id = summary.get("track_id")
    if not track_id or conn is None:
        return None

    try:
        track_row = conn.execute(
            "SELECT start_lat, start_lon FROM tracks WHERE track_id = ?",
            (track_id,),
        ).fetchone()
    except Exception:
        track_row = None

    if not track_row or not track_row["start_lat"]:
        return None

    lat, lon = track_row["start_lat"], track_row["start_lon"]

    # Fetch hourly weather
    hourly = ms_mod.fetch_historical_weather(
        lat, lon, session_dt.strftime("%Y-%m-%d"),
    )
    if "error" in hourly:
        logger.warning("Weather API error: %s", hourly.get("error"))
        return None

    # Build per-lap timestamps from cumulative lap times
    lap_ts: list[float] = []
    cumulative = 0.0
    for lt in lap_times:
        lap_ts.append(cumulative)
        cumulative += lt
    if not lap_ts:
        return None

    return wt_mod.build_weather_timeline(hourly, lap_ts, session_dt)


# ── Step 08d3: Tyre degradation / grip evolution ─────────────────────


def run_tyre_degradation(
    resampled_laps: dict[int, pd.DataFrame],
    lap_times: list[float],
) -> Optional[dict[str, Any]]:
    """Step 08d3: Compute tyre/grip degradation from telemetry.

    Returns a dict with grip evolution metrics or ``None``.
    """
    td_mod = lazy_import("tyre_degradation")
    if td_mod is None:
        return None
    if not resampled_laps or not lap_times:
        return None

    evo = td_mod.compute_grip_evolution(resampled_laps, lap_times)
    return evo.to_dict()


# ── Step 08e (laps): Invalid lap detection ───────────────────────────


def run_invalid_lap_detection(
    lap_times: list[float],
    resampled_laps: dict[int, pd.DataFrame],
    *,
    meta: Optional[dict[str, Any]] = None,
) -> tuple[set[int], Optional[dict[str, Any]]]:
    """Step 08e: Identify invalid laps (outlier times, manual exclusion).

    Returns
    -------
    (invalid_lap_set, analysis_dict) : tuple
        *invalid_lap_set* is the set of lap numbers flagged as invalid.
        *analysis_dict* is the full result dict from the trimming module.
    """
    trim_mod = lazy_import("session_trimming")
    if trim_mod is None or not hasattr(trim_mod, "identify_invalid_laps"):
        return set(), None
    if not lap_times:
        return set(), None

    if meta is None:
        meta = {}

    sorted_keys = sorted(resampled_laps.keys())
    exclude = meta.get("exclude_laps")

    result = trim_mod.identify_invalid_laps(
        lap_times, lap_keys=sorted_keys, exclude_laps=exclude,
    )
    invalid_set = result.get("invalid_laps", set()) if result else set()
    return invalid_set, result


# ── Step 08e2: Best-N% lap selection ─────────────────────────────────


def run_best_n_selection(
    lap_times: list[float],
    resampled_laps: dict[int, pd.DataFrame],
    invalid_lap_set: set[int],
) -> Optional[list[int]]:
    """Step 08e2: Select the best N% of valid laps for theoretical envelope.

    Filters out *invalid_lap_set* first, requires at least 3 valid laps.

    Returns a list of indices into the sorted lap keys, or ``None``.
    """
    trim_mod = lazy_import("session_trimming")
    if trim_mod is None or not hasattr(trim_mod, "select_best_n_percent_laps"):
        return None
    if not lap_times:
        return None

    sorted_keys = sorted(resampled_laps.keys())
    valid_keys = [k for k in sorted_keys if k not in invalid_lap_set]
    valid_lt = [lap_times[sorted_keys.index(k)] for k in valid_keys]

    if len(valid_lt) < 3:
        return None

    best_keys = trim_mod.select_best_n_percent_laps(
        valid_lt, lap_keys=valid_keys, best_pct=30.0, min_laps=3,
    )
    # Convert selected lap keys to indices into sorted_keys list
    return [sorted_keys.index(k) for k in best_keys if k in sorted_keys]


# ── Step 08f: Incomplete lap detection ───────────────────────────────


def run_incomplete_lap_detection(
    trimmed_df: Optional[pd.DataFrame],
) -> tuple[set[int], Optional[dict[str, Any]]]:
    """Step 08f: Identify incomplete laps (distance-based).

    Detects laps that are too short (pit-in, pauses, session-end
    fragments) compared to the median lap distance.

    Returns
    -------
    (incomplete_lap_set, analysis_dict) : tuple
    """
    trim_mod = lazy_import("session_trimming")
    if trim_mod is None or not hasattr(trim_mod, "identify_incomplete_laps"):
        return set(), None
    if trimmed_df is None or trimmed_df.empty:
        return set(), None

    result = trim_mod.identify_incomplete_laps(trimmed_df)
    incomplete_set = result.get("incomplete_laps", set()) if result else set()
    return incomplete_set, result


# ── Step 08g: Anomalous lap detection ────────────────────────────────


def run_anomalous_lap_detection(
    trimmed_df: Optional[pd.DataFrame],
    already_excluded: set[int],
) -> tuple[set[int], Optional[dict[str, Any]]]:
    """Step 08g: Identify anomalous laps (distance band + rolling-mean time).

    Laps already in *already_excluded* are skipped during detection.

    Returns
    -------
    (anomalous_lap_set, analysis_dict) : tuple
    """
    trim_mod = lazy_import("session_trimming")
    if trim_mod is None or not hasattr(trim_mod, "identify_anomalous_laps"):
        return set(), None
    if trimmed_df is None or trimmed_df.empty:
        return set(), None

    result = trim_mod.identify_anomalous_laps(
        trimmed_df, excluded_laps=already_excluded,
    )
    anomalous_set = result.get("flagged_laps", set()) if result else set()
    return anomalous_set, result


# ── Best-lap selection ───────────────────────────────────────────────


def select_best_lap(
    resampled_laps: dict[int, pd.DataFrame],
    lap_times: list[float],
    excluded_laps: set[int],
    invalid_lap_set: set[int],
) -> tuple[Optional[int], Optional[pd.DataFrame], list[tuple[int, float]]]:
    """Select best lap excluding invalid/incomplete/anomalous/deviated laps.

    Uses a three-tier fallback strategy:
    1. Exclude all *excluded_laps* (strictest).
    2. Exclude only *invalid_lap_set* (less strict).
    3. Use any lap with a finite time (last resort).

    Returns
    -------
    (best_lap_key, best_lap_df, valid_times) : tuple
        *best_lap_key* is the lap number of the best lap (or ``None``).
        *best_lap_df* is the corresponding DataFrame (or ``None``).
        *valid_times* is the list of ``(lap_key, time)`` pairs used.
    """
    sorted_keys = sorted(resampled_laps.keys())

    # Tier 1: exclude all flagged laps
    valid_times = [
        (k, t)
        for k, t in zip(sorted_keys, lap_times)
        if math.isfinite(t) and k not in excluded_laps
    ]

    # Tier 2: fallback to only invalid_lap_set excluded
    if not valid_times:
        valid_times = [
            (k, t)
            for k, t in zip(sorted_keys, lap_times)
            if math.isfinite(t) and k not in invalid_lap_set
        ]

    # Tier 3: last resort -- any finite time
    if not valid_times:
        valid_times = [
            (k, t)
            for k, t in zip(sorted_keys, lap_times)
            if math.isfinite(t)
        ]

    if not valid_times:
        return None, None, []

    best_lap_key = min(valid_times, key=lambda x: x[1])[0]
    best_lap_df = resampled_laps.get(best_lap_key)
    return best_lap_key, best_lap_df, valid_times


# ── Build clean data ─────────────────────────────────────────────────


def build_clean_data(
    resampled_laps: dict[int, pd.DataFrame],
    lap_times: list[float],
    lap_metrics: list[dict[str, Any]],
    excluded_laps: set[int],
) -> tuple[dict[int, pd.DataFrame], list[float], list[dict[str, Any]]]:
    """Build clean data structures with excluded laps removed.

    Filters *resampled_laps*, *lap_times*, and *lap_metrics* to remove
    all laps in *excluded_laps*.

    Returns
    -------
    (clean_resampled, clean_lap_times, clean_lap_metrics) : tuple
    """
    sorted_keys = sorted(resampled_laps.keys())

    clean_resampled = {
        k: v for k, v in resampled_laps.items()
        if k not in excluded_laps
    }

    clean_lap_times = [
        t for k, t in zip(sorted_keys, lap_times)
        if k not in excluded_laps and math.isfinite(t)
    ]

    clean_lap_metrics = [
        m for m in lap_metrics
        if m.get("lap_number") not in excluded_laps
    ]

    return clean_resampled, clean_lap_times, clean_lap_metrics
