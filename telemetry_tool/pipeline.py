"""
pipeline.py -- -
End-to-end analysis orchestrator for motorsport telemetry.

Wires every upstream module into a single deterministic pipeline with
graceful degradation --  each step that fails is logged and skipped so
downstream steps receive the best partial result available.

Flow (14+ stages)
~~~~~~~~~~~~~~~~
 1  Ingest                io_racechrono.read_racechrono_csv
 2  Filter                gps_filtering.filter_gps_quality
 3  Derived channels      derived_channels.compute_*
 4  Trim session          session_trimming.trim_session
 5  Detect track          track_detection.register_or_match_track
 6  Detect corners        corner_detection.detect_corners
 7  Normalise / resample  resampling.resample_all_laps
 8  Compute metrics       features.compute_*
 9  Compute deltas        deltas.classify_time_loss_cause
 9a Reference line        reference_line.compute_reference_line
 9b Curvature profile     reference_line.compute_curvature_profile
 9c Friction model        friction_model.build_friction_model
 9d Vehicle model         vehicle_model.classify_vehicle
 9e Data quality          data_quality.score_data_quality
10  Theoretical lap       physics simulation -> adaptive percentile fallback
11  Build feature dataset feature_builder.build_feature_dataset
12  Train / update ML     ml_engine + anomaly_detection
13  Score session         scoring.score_session
14  Generate report       reporting_html + reporting_pdf + driver_profile


Design principles
~~~~~~~~~~~~~~~~~
- **Pure logic, zero console I/O.**  All diagnostics go through ``logging``.
- Each step wrapped in ``_safe_step()`` --  failures produce a warning + ``None``.
- Returns a single ``dict`` carrying every intermediate artefact.
- Deterministic: identical inputs -- ... --  identical outputs.
"""

from __future__ import annotations

import logging
import math
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Final, Optional, TypeVar

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================================

# Column-name constants (mirrors upstream)

# ============================================================================


_COL_LAP:   Final[str] = "Lap #"
_COL_TIME:  Final[str] = "Time (s)"
_COL_SPEED: Final[str] = "Speed (m/s)"
_COL_DIST:  Final[str] = "Distance (m)"


# -- -

# Raw -- ... --  internal column-name mapping.

#

# Upstream modules (io_racechrono, resampling, derived_channels) keep the

# original RaceChrono header names throughout.  The theoretical engine and

# feature schema expect snake_case internal names.

# This map bridges the gap; it is applied lazily just before any module

# that requires internal names.

# -- -

_RAW_TO_INTERNAL: Final[dict[str, str]] = {
    "Distance (m)":                           "distance_m",
    "Speed (m/s)":                            "speed_mps",
    "Speed (m/s) *calc":                      "speed_mps",
    "Longitudinal acceleration (G) *calc":    "accel_long_mps2",
    "Longitudinal acceleration (m/s²)":             "accel_long_mps2",
    "accel_long":                             "accel_long_mps2",
    "accel_long_g":                           "accel_long_mps2",
    "Lateral acceleration (G) *calc":         "accel_lat_mps2",
    "Lateral acceleration (m/s²)":                  "accel_lat_mps2",
    "accel_lat":                              "accel_lat_mps2",
    "Time (s)":                               "time_s",
    "Lap #":                                  "lap_number",
}


def _map_to_internal_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a copy of *df* with raw RaceChrono column names replaced by the
    internal snake_case names expected by downstream modules such as
    ``theoretical_engine`` and ``feature_builder``.

    Only columns present in ``_RAW_TO_INTERNAL`` are renamed; unrecognised
    columns pass through unchanged.  If an internal name already exists in
    *df* (e.g. from a previous mapping pass) the raw candidate is skipped
    to avoid collisions.
    """
    rename: dict[str, str] = {}
    claimed: set[str] = set()

    for raw_name, internal_name in _RAW_TO_INTERNAL.items():
        if internal_name in claimed:
            continue  # first raw match wins for each internal name
        if raw_name in df.columns and internal_name not in df.columns:
            rename[raw_name] = internal_name
            claimed.add(internal_name)

    if rename:
        df = df.rename(columns=rename)
    return df


# -- -

# Lap distance validation & repair --  "safety net" for raw data

# -- -


def validate_lap_consistency(
    lap_dict: dict[int, pd.DataFrame],
    *,
    dist_col: str = "Distance (m)",
    max_gap_m: float = 100.0,
) -> dict[int, pd.DataFrame]:
    """
    Validate and auto-repair per-lap distance data.

    Checks performed (per lap):

    1. **Negative distance jumps** --  a monotonically decreasing sample
       indicates a GPS glitch.  Repaired by linear interpolation with
       its neighbours.
    2. **Large distance gaps** --  consecutive samples separated by more
       than *max_gap_m* indicate a sensor dropout.  Filled via linear
       interpolation.
    3. **Lap-relative reset** --  the distance column is shifted so every
       lap starts at 0.0 m, guaranteeing that the theoretical engine
       sees comparable distance axes even when the raw CSV uses
       cumulative session distance.

    Parameters -- lap_dict:
        ``{lap_number: DataFrame}`` as produced by the segmentation step.
    dist_col:
        Name of the distance column.
    max_gap_m:
        Maximum allowed inter-sample distance jump before repair.

    Returns -- -
    dict[int, pd.DataFrame]
        Same shape, with repaired copies (originals never mutated).
    """
    repaired: dict[int, pd.DataFrame] = {}

    for lap_num, df in lap_dict.items():
        if dist_col not in df.columns:
            repaired[lap_num] = df
            continue

        df = df.copy()
        d = pd.to_numeric(df[dist_col], errors="coerce").values.astype(float)
        repairs = 0

        # -- Repair 1: negative distance jumps
        diffs = np.diff(d)
        neg_idxs = np.where(diffs < 0)[0]
        for idx in neg_idxs:
            lo = d[idx]
            hi_idx = min(idx + 2, len(d) - 1)
            d[idx + 1] = (lo + d[hi_idx]) / 2.0
            repairs += 1

        # -- Repair 2: large distance gaps
        diffs = np.diff(d)
        gap_idxs = np.where(diffs > max_gap_m)[0]
        for idx in gap_idxs:
            hi_idx = min(idx + 2, len(d) - 1)
            d[idx + 1] = (d[idx] + d[hi_idx]) / 2.0
            repairs += 1

        # -- Repair 3: make lap-relative (start at 0.0 m)
        d_start = d[0] if np.isfinite(d[0]) else 0.0
        if abs(d_start) > 0.5:
            d -= d_start

        df[dist_col] = d

        if repairs > 0:
            logger.info(
                "Lap %d: auto-repaired %d distance anomal%s.",
                lap_num, repairs, "y" if repairs == 1 else "ies",
            )
        repaired[lap_num] = df

    return repaired


# ============================================================================

# Lazy imports --  tolerate missing optional modules at runtime.

# ============================================================================


def _import(module_name: str) -> Any:
    """Import *module_name*; return ``None`` if unavailable."""
    try:
        import importlib
        return importlib.import_module(module_name)
    except ImportError as exc:
        logger.warning("Module %r unavailable: %s", module_name, exc)
        return None


# ============================================================================

# Safe-step wrapper

# ============================================================================


class PipelineError(Exception):
    """Raised internally when a pipeline step fails."""


def _safe_step(
    step_name: str,
    fn: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> tuple[Optional[T], Optional[str]]:
    """
    Execute *fn*.  Return ``(result, None)`` on success, or
    ``(None, error_msg)`` on failure.  Never raises.
    """
    try:
        result = fn(*args, **kwargs)
        logger.info("Step [%s] --  OK", step_name)
        return result, None
    except Exception as exc:
        tb = traceback.format_exc()
        msg = f"{type(exc).__name__}: {exc}"
        logger.warning("Step [%s] --  FAILED: %s", step_name, msg)
        logger.debug("Step [%s] traceback:\n%s", step_name, tb)
        return None, msg


# ============================================================================

# Helpers --  metrics that upstream modules don't provide directly

# ============================================================================


def _compute_robustness_metrics(
    resampled_laps: dict[int, pd.DataFrame],
    lap_times: list[float],
    *,
    early_frac: float = 0.33,
    late_frac: float = 0.33,
) -> dict[str, Any]:
    """
    Compute early-vs-late stint metrics for robustness scoring.

    Returns ``early_mean_s``, ``late_mean_s``, ``early_yaw_var``,
    ``late_yaw_var``.
    """
    valid = np.array([t for t in lap_times if math.isfinite(t)])
    n = len(valid)
    n_early = max(1, int(n * early_frac))
    n_late  = max(1, int(n * late_frac))

    early_mean = float(np.mean(valid[:n_early]))  if n > 0 else float("nan")
    late_mean  = float(np.mean(valid[-n_late:]))   if n > 0 else float("nan")

    sorted_keys = sorted(resampled_laps.keys())
    early_keys  = sorted_keys[:n_early]
    late_keys   = sorted_keys[-n_late:] if len(sorted_keys) > n_late else sorted_keys

    _YAW_COLS = ("yaw_rate_dps", "Yaw rate (deg/s)")

    def _yaw_var(keys: list[int]) -> float:
        variances: list[float] = []
        for k in keys:
            df = resampled_laps.get(k)
            if df is None:
                continue
            col = next((c for c in _YAW_COLS if c in df.columns), None)
            if col is None:
                continue
            arr = pd.to_numeric(df[col], errors="coerce").dropna().values
            if len(arr) > 1:
                variances.append(float(np.var(arr)))
        return float(np.mean(variances)) if variances else float("nan")

    def _rnd(v: float) -> float:
        return round(v, 4) if math.isfinite(v) else float("nan")

    return {
        "early_mean_s":  _rnd(early_mean),
        "late_mean_s":   _rnd(late_mean),
        "early_yaw_var": _rnd(_yaw_var(early_keys)),
        "late_yaw_var":  _rnd(_yaw_var(late_keys)),
    }


def _theoretical_metrics_from_lap(
    theo_lap: pd.DataFrame,
    *,
    simulation_method: str = "percentile_envelope",
    sim_result: Any = None,
    data_quality: Any = None,
) -> dict[str, Any]:
    """
    Extract the metrics ``scoring.score_session`` needs from a theoretical
    lap DataFrame (speed-envelope integration for ``best_s``, etc.).

    Extended to also report the simulation method used, cornering-limited
    fraction (when physics simulation was used), and data quality confidence.
    """
    dist_col  = "distance_m"       if "distance_m"   in theo_lap.columns else _COL_DIST
    speed_col = "v_env_mps"        if "v_env_mps"    in theo_lap.columns else _COL_SPEED
    accel_col = "accel_max_mps2"
    brake_col = "brake_max_mps2"

    dist  = pd.to_numeric(theo_lap.get(dist_col,  pd.Series(dtype=float)), errors="coerce")
    speed = pd.to_numeric(theo_lap.get(speed_col, pd.Series(dtype=float)), errors="coerce").dropna()

    best_s = float("nan")
    if len(dist.dropna()) > 1 and len(speed) > 1:
        d_vals = dist.dropna().values
        s_vals = speed.values[:len(d_vals)]
        mask   = (s_vals > 0) & np.isfinite(s_vals) & np.isfinite(d_vals)
        if mask.sum() > 1:
            ds   = np.diff(d_vals[mask])
            invv = 1.0 / s_vals[mask]
            dt   = 0.5 * (invv[:-1] + invv[1:]) * np.abs(ds)
            best_s = float(np.sum(dt))

    def _col_max(col: str) -> float:
        if col in theo_lap.columns:
            vals = pd.to_numeric(theo_lap[col], errors="coerce").dropna()
            return float(vals.max()) if len(vals) > 0 else float("nan")
        return float("nan")

    def _rnd(v: float) -> float:
        return round(v, 4) if math.isfinite(v) else float("nan")

    result: dict[str, Any] = {
        "best_s":           _rnd(best_s),
        "speed_mean_mps":   _rnd(float(speed.mean())) if len(speed) > 0 else float("nan"),
        "accel_max_mps2":   _rnd(_col_max(accel_col)),
        "braking_max_mps2": _rnd(_col_max(brake_col)),
        # New fields for physics pipeline

        "simulation_method":          simulation_method,
        "cornering_limited_fraction": 0.0,
        "confidence":                 0.5,
    }

    # Enrich from physics simulation result

    if sim_result is not None:
        try:
            cl = sim_result.cornering_limited
            if hasattr(cl, 'mean'):
                result["cornering_limited_fraction"] = round(float(cl.mean()), 4)
            # Use the simulation's own lap time as best_s if physics method

            if simulation_method in ("physics", "hybrid") and hasattr(sim_result, 'lap_time_s'):
                result["best_s"] = _rnd(sim_result.lap_time_s)
        except Exception:
            pass  # sim_result doesn't have expected attrs

    # Enrich from data quality report

    if data_quality is not None:
        try:
            result["confidence"] = round(
                float(data_quality.overall_confidence), 4,
            )
        except Exception:
            pass  # data_quality doesn't have expected attrs

    return result


# ============================================================================

# Public API

# ============================================================================


def _extract_track_layout_for_picker(
    best_df: pd.DataFrame,
    corners: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Build track layout data for the mid-analysis corner picker.

    Returns a dict with GPS outline + corner positions suitable for
    Canvas rendering in the browser.
    """
    import bisect

    # Find column names (resampled data uses RaceChrono naming)
    lat_col = lon_col = dist_col = spd_col = None
    for c in best_df.columns:
        cl = c.lower()
        if "latitude" in cl and "deg" in cl:
            lat_col = c
        elif "longitude" in cl and "deg" in cl:
            lon_col = c
        elif cl in ("distance_m", "distance", "distance (m)"):
            dist_col = c
        elif cl in ("speed_mps", "speed (m/s)", "speed"):
            spd_col = c

    if lat_col is None or lon_col is None:
        return None

    lats = best_df[lat_col].tolist()
    lons = best_df[lon_col].tolist()

    if dist_col and dist_col in best_df.columns:
        dists = best_df[dist_col].tolist()
    elif hasattr(best_df.index, "name") and best_df.index.name == "distance_m":
        dists = best_df.index.tolist()
    else:
        dists = list(range(len(best_df)))

    speeds = best_df[spd_col].tolist() if spd_col else [0.0] * len(best_df)

    # Map each corner's apex to lat/lon via distance bisect
    corner_positions = []
    for cn in corners:
        apex_m = cn.get("s_apex", (cn.get("s_start", 0) + cn.get("s_end", 0)) / 2)
        idx = bisect.bisect_left(dists, apex_m)
        idx = min(idx, len(dists) - 1)
        if idx < len(lats) and lats[idx] is not None:
            corner_positions.append({
                "corner_id": cn["corner_id"],
                "direction": cn.get("direction", ""),
                "lat": lats[idx],
                "lon": lons[idx],
                "dist_m": apex_m,
            })

    return {
        "latitudes": lats,
        "longitudes": lons,
        "distances": dists,
        "speeds": speeds,
        "corners": corner_positions,
    }


def run_full_analysis(
    csv_path: str | Path,
    session_meta: dict[str, Any],
    *,
    enable_ml: bool = True,
    enable_report: bool = True,
    output_dir: Optional[str | Path] = None,
    n_resample_points: int = 1000,
    lap_range: Optional[tuple[int, int]] = None,
    context: Any = None,
    driver_tag: Optional[str] = None,
    corner_callback: Optional[Any] = None,
    joker_callback: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Orchestrate the full telemetry analysis pipeline.

    Parameters -- csv_path:
        Path to a RaceChrono CSV export.
    session_meta:
        Dict with optional keys:
            ``session_id`` -- ... --  str
            ``session_type`` -- ... --  ``"practice"`` | ``"qualifying"`` | ``"race"``
            ``track_state`` -- ... --  ``"dry"`` | ``"wet"`` | ``"damp"``
            ``driver_name`` -- ... --  str
            ``track_id`` -- ... --  str  (auto-detected if absent)
            ``date`` -- ... --  str  (ISO-8601; defaults to today)
    enable_ml:
        Run ML training / anomaly detection.  Default ``True``.
    enable_report:
        Generate HTML + PDF reports.  Default ``True``.
    output_dir:
        Root for report files.  ``None`` -- ... --  ``Results/{date}_{track}/``.
    n_resample_points:
        Distance-grid resolution per lap.  Default 1 000.
    lap_range:
        ``(first_lap, last_lap)`` inclusive filter.  ``None`` -- ... --  all laps.

    Returns -- -
    dict
        ``csv_path``, ``session_meta``, ``output_dir``,
        ``raw_df``, ``filtered_df``, ``enriched_df``,
        ``trimmed_df``, ``trim_report``,
        ``track_match``, ``track_id``,
        ``lap_dict``, ``resampled_laps``, ``corners``,
        ``lap_metrics``, ``lap_times``, ``consistency_metrics``,
        ``robustness_metrics``, ``best_lap``, ``best_lap_key``,
        ``delta_segments``, ``segment_losses``,
        ``reference_line``, ``curvature_profile``,
        ``friction_model``, ``vehicle_params``, ``data_quality``,
        ``theoretical_lap``, ``theoretical_metrics``,
        ``feature_df``, ``ml_results``, ``anomaly_results``,
        ``score_result``, ``driver_profile``,
        ``html_path``, ``pdf_path``,
        ``steps_ok``, ``steps_failed``, ``errors``
    """
    csv_path = Path(csv_path)

    # --- Normalise session metadata with sensible defaults -
    meta = dict(session_meta)
    meta.setdefault("session_type", "practice")
    meta.setdefault("track_state",  "dry")
    meta.setdefault("driver_name",  "Unknown")
    meta.setdefault("session_id",   csv_path.stem)
    # Honour user-provided session_date from the web form
    if meta.get("session_date") and not meta.get("date"):
        meta["date"] = meta["session_date"]
    meta.setdefault("date",         datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # --- Driver-tag file suffix (multi-driver namespacing)

    _dtag_suffix = f"_{driver_tag}" if driver_tag else ""

    summary: dict[str, Any] = {
        "csv_path":             str(csv_path),
        "session_meta":         meta,
        "steps_ok":             [],
        "steps_failed":         [],
        "errors":               {},
        # Pre-populate every key so early returns always have a full schema.

        "raw_df":               None,
        "filtered_df":          None,
        "enriched_df":          None,
        "trimmed_df":           None,
        "trim_report":          {},
        "track_match":          None,
        "track_id":             meta.get("track_id", "unknown_track"),
        "lap_dict":             None,
        "resampled_laps":       None,
        "corners":              [],
        "lap_metrics":          [],
        "lap_times":            [],
        "consistency_metrics":  {},
        "robustness_metrics":   {},
        "best_lap":             None,
        "best_lap_key":         None,
        "delta_segments":       [],
        "segment_losses":       [],
        "theoretical_lap":      None,
        "theoretical_metrics":  {},
        "feature_df":           None,
        "ml_results":           {},
        "anomaly_results":      {},
        "score_result":         None,
        "driver_profile":       None,
        "html_path":            None,
        "pdf_path":             None,
        "output_dir":           None,
        "phases_df":            None,
        "lap_to_phase":         None,
        "adaptation_score":     None,
        "track_evolution":     None,
        "grip_evolution":      None,
        "corner_performances": None,
        "coaching_guide":      None,
        # Physics pipeline intermediates (steps 09a–09e)

        "reference_line":       None,
        "curvature_profile":    None,
        "friction_model":       None,
        "vehicle_params":       None,
        "data_quality":         None,
        # Joker lap detection (step 08j)
        "joker_detection_result": None,
        "joker_lap_number":      None,
    }

    # Phase-tracking state (populated by step 08d)

    phases_df: Optional[pd.DataFrame] = None
    lap_to_phase: Optional[dict[int, int]] = None

    def _record(step: str, result: Any, error: Optional[str]) -> Any:
        """Book-keep step outcome; return *result* for chaining."""
        if error is None:
            summary["steps_ok"].append(step)
        else:
            summary["steps_failed"].append(step)
            summary["errors"][step] = error
        return result

    # STEP 1 --  Ingest

    #
    io_mod = _import("io_racechrono")

    def _ingest() -> pd.DataFrame:
        if io_mod is None:
            raise ImportError("io_racechrono unavailable")
        return io_mod.read_racechrono_csv(csv_path)

    raw_df, err = _safe_step("01_ingest", _ingest)
    _record("01_ingest", raw_df, err)
    summary["raw_df"] = None  # Not consumed downstream; avoid holding ~8 GB

    if raw_df is None:
        logger.error("Ingest failed --  cannot continue.")
        return summary

    # STEP 2 --  Filter (GPS quality)

    #
    gps_mod = _import("gps_filtering")

    def _filter() -> pd.DataFrame:
        if gps_mod is None:
            logger.info("GPS filtering skipped (module absent).")
            return raw_df
        return gps_mod.filter_gps_quality(raw_df)

    filtered_df, err = _safe_step("02_filter", _filter)
    _record("02_filter", filtered_df, err)
    if filtered_df is None:
        filtered_df = raw_df
    summary["filtered_df"] = None  # Not consumed downstream; avoid holding ~8 GB
    del raw_df  # Allow GC of ingest DataFrame

    # STEP 3 --  Derived channels

    #
    dc_mod = _import("derived_channels")

    def _derived() -> pd.DataFrame:
        # Work directly on filtered_df to avoid a full copy (~8 GB for 10 GB
        # CSV files).  The local var is not used after this step.
        if dc_mod is None:
            logger.info("Derived channels skipped (module absent).")
            return filtered_df
        df = dc_mod.compute_longitudinal_accel(filtered_df)
        df = dc_mod.compute_lateral_accel_from_xy(df)
        df = dc_mod.compute_yaw_rate_from_heading(df)
        return df

    enriched_df, err = _safe_step("03_derived_channels", _derived)
    _record("03_derived_channels", enriched_df, err)
    if enriched_df is None:
        enriched_df = filtered_df
    summary["enriched_df"] = None  # Not consumed downstream; avoid holding ~8 GB
    del filtered_df  # Allow GC

    # STEP 4 --  Trim session (remove outlaps, waiting periods)

    #
    trim_mod = _import("session_trimming")

    def _trim() -> tuple[pd.DataFrame, dict[str, Any]]:
        if trim_mod is None:
            return enriched_df, {"note": "session_trimming absent"}
        return trim_mod.trim_session(
            enriched_df,
            session_type=session_meta.get("session_type", "practice"),
        )

    trim_result, err = _safe_step("04_trim_session", _trim)
    _record("04_trim_session", trim_result, err)
    if trim_result is not None:
        trimmed_df, trim_report = trim_result
    else:
        trimmed_df, trim_report = enriched_df, {}
    del enriched_df  # Allow GC
    summary["trimmed_df"]  = trimmed_df
    summary["trim_report"] = trim_report

    # STEP 5 --  Detect track

    #
    track_mod = _import("track_detection")

    def _detect_track() -> tuple[Any, str]:
        if track_mod is None:
            return None, meta.get("track_id", "unknown_track")
        # Use user-provided track_name if available, else fall back to track_id.
        _tn = meta.get("track_name") or meta.get("track_id", "Unknown Track")
        match, _ = track_mod.register_or_match_track(
            trimmed_df, track_name=_tn,
        )
        return match, match.track_id

    track_result, err = _safe_step("05_detect_track", _detect_track)
    _record("05_detect_track", track_result, err)
    if track_result is not None:
        track_match, track_id = track_result
    else:
        track_match, track_id = None, meta.get("track_id", "unknown_track")
    meta["track_id"] = track_id
    summary["track_match"] = (
        track_match.to_dict()
        if track_match and hasattr(track_match, "to_dict")
        else None
    )
    summary["track_id"] = track_id

    # --- Persist SessionContext if provided -- -

    if context is not None:
        context.track_id = track_id
        try:
            from session_context import save_session_context
            if output_dir is not None:
                _ctx_path = Path(output_dir) / f"session_context{_dtag_suffix}.json"
                _ctx_path.parent.mkdir(parents=True, exist_ok=True)
                save_session_context(context, _ctx_path)
        except Exception as _ctx_exc:
            logger.warning("Could not persist session context: %s", _ctx_exc)

    # STEP 6 --  Segment laps into individual DataFrames

    #
    def _segment_laps() -> dict[int, pd.DataFrame]:
        if _COL_LAP not in trimmed_df.columns:
            raise PipelineError(f"Column {_COL_LAP!r} missing.")
        lap_col = pd.to_numeric(trimmed_df[_COL_LAP], errors="coerce")
        laps: dict[int, pd.DataFrame] = {}
        for lap_num, grp in trimmed_df.groupby(lap_col, sort=True):
            ln = int(lap_num)
            if lap_range is not None and not (lap_range[0] <= ln <= lap_range[1]):
                continue
            laps[ln] = grp.reset_index(drop=True)
        if not laps:
            raise PipelineError("No laps after segmentation / range filter.")
        return laps

    lap_dict, err = _safe_step("06_segment_laps", _segment_laps)
    _record("06_segment_laps", lap_dict, err)
    summary["lap_dict"] = lap_dict

    if lap_dict is None or len(lap_dict) == 0:
        logger.error("No laps --  returning partial summary.")
        return summary

    # -- Safety net: validate & repair distance data before resampling
    lap_dict = validate_lap_consistency(lap_dict)

    # STEP 7 --  Normalise (resample to uniform distance grid)

    #
    resamp_mod = _import("resampling")

    def _resample() -> dict[int, pd.DataFrame]:
        if resamp_mod is None:
            raise ImportError("resampling unavailable")
        return resamp_mod.resample_all_laps(lap_dict, n_points=n_resample_points)

    resampled_laps, err = _safe_step("07_normalise", _resample)
    _record("07_normalise", resampled_laps, err)
    summary["resampled_laps"] = resampled_laps

    if resampled_laps is None or len(resampled_laps) == 0:
        logger.error("Resampling failed --  returning partial summary.")
        return summary

    # STEP 6b --  Detect corners (requires resampled data, hence after 7)

    #
    corner_mod = _import("corner_detection")

    def _detect_corners() -> list[dict[str, Any]]:
        if corner_mod is None:
            return []
        first_key = sorted(resampled_laps.keys())[0]
        return corner_mod.detect_corners(resampled_laps[first_key])

    corners, err = _safe_step("06b_detect_corners", _detect_corners)
    _record("06b_detect_corners", corners, err)
    summary["corners"] = corners or []

    # ── Corner callback: notify caller with track layout for corner picker ──
    # The picker allows clicking anywhere on the track, so we show it even
    # when auto-detection found no corners (they are just reference guides).
    if corner_callback and resampled_laps:
        try:
            _best_key = sorted(resampled_laps.keys())[0]
            _best_df = resampled_laps[_best_key]
            _layout = _extract_track_layout_for_picker(_best_df, corners or [])
            if _layout:
                _layout["track_id"] = track_id
                corner_callback(_layout)
        except Exception as _cb_exc:
            logger.warning("Corner callback failed: %s", _cb_exc)

    # STEP 8 --  Compute per-lap metrics

    #
    feat_mod = _import("features")

    def _compute_metrics() -> tuple[list[dict[str, Any]], list[float]]:
        if feat_mod is None:
            raise ImportError("features unavailable")
        all_metrics: list[dict[str, Any]] = []
        all_times:   list[float]          = []
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

    metrics_res, err = _safe_step("08_compute_metrics", _compute_metrics)
    _record("08_compute_metrics", metrics_res, err)
    if metrics_res is not None:
        lap_metrics, lap_times = metrics_res
    else:
        lap_metrics, lap_times = [], []
    summary["lap_metrics"] = lap_metrics
    summary["lap_times"]   = lap_times

    # Consistency (companion to step 8)

    def _consistency() -> dict[str, Any]:
        if feat_mod is None:
            return {}
        return feat_mod.compute_consistency_metrics(lap_times)

    consistency, err = _safe_step("08b_consistency", _consistency)
    _record("08b_consistency", consistency, err)
    summary["consistency_metrics"] = consistency or {}

    # Robustness (companion to step 8)

    robustness, err = _safe_step(
        "08c_robustness",
        _compute_robustness_metrics, resampled_laps, lap_times,
    )
    _record("08c_robustness", robustness, err)
    summary["robustness_metrics"] = robustness or {}

    # \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

    # STEP 08d \u2014 Condition tracking (optional, requires context)

    # \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

    ct_mod = _import("condition_tracking")

    def _condition_tracking() -> tuple[Optional[pd.DataFrame], Optional[dict[int, int]]]:
        if ct_mod is None:
            logger.info("condition_tracking module absent; skipping.")
            return None, None
        if not lap_metrics:
            return None, None

        lm_df = pd.DataFrame(lap_metrics)
        indicators = ct_mod.compute_grip_indicators(lm_df)

        # Use combined detection (z-score + trend) if available
        if hasattr(ct_mod, 'detect_condition_changes_combined'):
            changes = ct_mod.detect_condition_changes_combined(
                indicators, lap_times=lap_times,
            )
        else:
            changes = ct_mod.detect_condition_changes(indicators)

        # Merge manual condition markers (Phase 2: --condition-change)
        _manual_cc = meta.get("manual_condition_changes")
        if _manual_cc and hasattr(ct_mod, 'merge_manual_changes'):
            changes = ct_mod.merge_manual_changes(changes, _manual_cc)
            logger.info("Merged %d manual condition change(s).", len(_manual_cc))

        p_df = ct_mod.build_condition_phases(lm_df, changes)

        # Label phases if context available

        if context is not None and hasattr(context, 'baseline_track_state'):
            weather = getattr(context, 'weather', None)
            p_df = ct_mod.label_phases(p_df, context.baseline_track_state, weather)

        # Build lap-to-phase mapping

        l2p: dict[int, int] = {}
        if "phase_id" in p_df.columns and "lap_start" in p_df.columns and "lap_end" in p_df.columns:
            for _, row in p_df.iterrows():
                pid = int(row["phase_id"])
                for ln in range(int(row["lap_start"]), int(row["lap_end"]) + 1):
                    l2p[ln] = pid

        # Persist phases

        if output_dir is not None:
            try:
                _phases_path = Path(output_dir) / f"condition_phases{_dtag_suffix}.csv"
                _phases_path.parent.mkdir(parents=True, exist_ok=True)
                p_df.to_csv(_phases_path, index=False)
                logger.info("Saved condition phases to %s", _phases_path)
            except Exception as _pex:
                logger.warning("Could not save phases: %s", _pex)

        return p_df, l2p

    ct_result, err = _safe_step("08d_condition_tracking", _condition_tracking)
    _record("08d_condition_tracking", ct_result, err)
    if ct_result is not None:
        phases_df, lap_to_phase = ct_result
    summary["phases_df"] = phases_df
    summary["lap_to_phase"] = lap_to_phase

    # -- 08d2: Track evolution rate (requires phases) -- -

    track_evolution: "dict[str, Any] | None" = None

    def _track_evolution_rate():
        if ct_mod is None or not hasattr(ct_mod, 'compute_track_evolution_rate'):
            return None
        if phases_df is None or phases_df.empty:
            return None
        if not lap_metrics:
            return None
        lm_df = pd.DataFrame(lap_metrics)
        return ct_mod.compute_track_evolution_rate(phases_df, lm_df)

    evo_result, err = _safe_step("08d2_track_evolution", _track_evolution_rate)
    _record("08d2_track_evolution", evo_result, err)
    if evo_result is not None:
        track_evolution = evo_result
        logger.info(
            "Track evolution: %.1f%% (%s)",
            evo_result.get("total_evolution_pct", 0.0),
            evo_result.get("grip_trend", "unknown"),
        )
    summary["track_evolution"] = track_evolution

    # -- 08d3: Tyre degradation / grip evolution (from telemetry)

    grip_evolution_result = None

    def _tyre_degradation():
        td_mod = _import("tyre_degradation")
        if td_mod is None:
            return None
        if not resampled_laps or not lap_times:
            return None
        evo = td_mod.compute_grip_evolution(resampled_laps, lap_times)
        return evo.to_dict()

    td_result, err = _safe_step("08d3_tyre_degradation", _tyre_degradation)
    _record("08d3_tyre_degradation", td_result, err)
    if td_result is not None:
        grip_evolution_result = td_result
        direction = td_result.get("grip_direction", "unknown")
        drop = td_result.get("estimated_grip_drop_pct", 0.0)
        evo_pct = td_result.get("track_evolution_pct", 0.0)
        if direction == "improving":
            logger.info(
                "Grip evolution: track IMPROVING by %.1f%% "
                "(not tyre degradation)",
                evo_pct,
            )
        elif direction == "degrading":
            logger.info(
                "Grip evolution: tyre DEGRADATION %.1f%%",
                drop,
            )
        else:
            logger.info(
                "Grip evolution: %s (drop=%.1f%%, evo=%.1f%%)",
                direction, drop, evo_pct,
            )
    summary["grip_evolution"] = grip_evolution_result

    # -- 08e: Invalid-lap detection and best-N% selection --
    invalid_lap_set: set = set()

    best_n_lap_indices: "list[int] | None" = None

    def _invalid_lap_detection():
        trim_mod = _import("session_trimming")
        if trim_mod is None or not hasattr(trim_mod, "identify_invalid_laps"):
            return None
        if not lap_times:
            return None
        sorted_keys = sorted(resampled_laps.keys())
        # Support manual exclusion from JSON config

        _exclude = meta.get("exclude_laps")
        return trim_mod.identify_invalid_laps(
            lap_times, lap_keys=sorted_keys,
            exclude_laps=_exclude,
        )

    invalid_result, err = _safe_step("08e_invalid_laps", _invalid_lap_detection)
    _record("08e_invalid_laps", invalid_result, err)
    if invalid_result is not None:
        invalid_lap_set = invalid_result.get("invalid_laps", set())
        summary["invalid_lap_analysis"] = {
            k: v for k, v in invalid_result.items() if k != "reason"
        }
        if invalid_lap_set:
            logger.info(
                "Flagged %d invalid lap(s): %s",
                len(invalid_lap_set), sorted(invalid_lap_set),
            )

    # Select best-N% of valid laps for theoretical envelope

    def _best_n_selection():
        trim_mod = _import("session_trimming")
        if trim_mod is None or not hasattr(trim_mod, "select_best_n_percent_laps"):
            return None
        if not lap_times:
            return None
        sorted_keys = sorted(resampled_laps.keys())
        # Filter out invalid laps first

        valid_keys = [k for k in sorted_keys if k not in invalid_lap_set]
        valid_lt = [lap_times[sorted_keys.index(k)] for k in valid_keys]
        if len(valid_lt) < 3:
            return None
        best_keys = trim_mod.select_best_n_percent_laps(
            valid_lt, lap_keys=valid_keys, best_pct=30.0, min_laps=3,
        )
        # Convert selected lap keys to indices into sorted_keys list

        return [sorted_keys.index(k) for k in best_keys if k in sorted_keys]

    best_n_result, err = _safe_step("08e2_best_n_laps", _best_n_selection)
    _record("08e2_best_n_laps", best_n_result, err)
    if best_n_result is not None:
        best_n_lap_indices = best_n_result
        logger.info(
            "Best-N%% lap indices for theoretical: %d indices.",
            len(best_n_lap_indices),
        )

    # Best-lap identification (needed by steps 9, 14)

    # IMPORTANT: Exclude invalid laps AND incomplete laps (pit-in, pauses,

    # short inlaps at end of session) from best-lap selection.  Without

    # this, a short inlap fragment can be mistakenly chosen as "best".

    best_lap_key: Optional[int] = None
    best_lap_df:  Optional[pd.DataFrame] = None

    # -- 08f: Incomplete-lap detection (distance-based) -- -

    incomplete_lap_set: set = set()

    def _incomplete_lap_detection():
        trim_mod = _import("session_trimming")
        if trim_mod is None or not hasattr(trim_mod, "identify_incomplete_laps"):
            return None
        if trimmed_df is None or trimmed_df.empty:
            return None
        return trim_mod.identify_incomplete_laps(trimmed_df)

    incomplete_result, err = _safe_step("08f_incomplete_laps", _incomplete_lap_detection)
    _record("08f_incomplete_laps", incomplete_result, err)
    if incomplete_result is not None:
        incomplete_lap_set = incomplete_result.get("incomplete_laps", set())
        summary["incomplete_lap_analysis"] = {
            k: v for k, v in incomplete_result.items() if k != "reason"
        }
        if incomplete_lap_set:
            logger.info(
                "Flagged %d incomplete lap(s): %s  (reasons: %s)",
                len(incomplete_lap_set), sorted(incomplete_lap_set),
                {k: v for k, v in incomplete_result.get("reason", {}).items()},
            )

    # -- 08g: Anomalous-lap filtering (distance band + rolling-mean time) -- -

    anomalous_lap_set: set = set()

    def _anomalous_lap_detection():
        trim_mod = _import("session_trimming")
        if trim_mod is None or not hasattr(trim_mod, "identify_anomalous_laps"):
            return None
        if trimmed_df is None or trimmed_df.empty:
            return None
        already_excluded = invalid_lap_set | incomplete_lap_set
        return trim_mod.identify_anomalous_laps(
            trimmed_df, excluded_laps=already_excluded,
        )

    anomalous_result, err = _safe_step("08g_anomalous_laps", _anomalous_lap_detection)
    _record("08g_anomalous_laps", anomalous_result, err)
    if anomalous_result is not None:
        anomalous_lap_set = anomalous_result.get("flagged_laps", set())
        summary["anomalous_lap_analysis"] = {
            k: v for k, v in anomalous_result.items() if k != "reason"
        }
        if anomalous_lap_set:
            logger.info(
                "Flagged %d anomalous lap(s): %s",
                len(anomalous_lap_set), sorted(anomalous_lap_set),
            )

    deviated_lap_set: set = set()
    # NOTE: Step 08h (line deviation detection) is deferred to after step 09a
    # because it requires the reference_line computed in 09a.
    # The excluded_laps computation and best-lap selection are deferred to
    # after step 08h so that deviated_lap_set is populated.

    corner_performances: "list[dict[str, Any]] | None" = None
    # NOTE: Corner analysis moved to step 10c (after theoretical lap).

    # ====================================================================

    # STEPS 09a-09e -- Physics pipeline (reference line, friction model,

    #                  vehicle classification, data quality)

    # ====================================================================

    # These build the inputs needed for the physics-based theoretical lap

    # simulation.  Each is independently wrapped in _safe_step so a failure

    # in one does not block the rest -- the cascading step 10 falls back to

    # the original percentile envelope if any prerequisite is missing.


    ref_line_mod = _import("reference_line")
    fric_mod     = _import("friction_model")
    veh_mod      = _import("vehicle_model")
    dq_mod       = _import("data_quality")
    sim_mod      = _import("lap_simulation")

    # Intermediate state (populated by 09a-09e, consumed by step 10)

    reference_line:    Optional[pd.DataFrame] = None
    curvature_profile: Optional[pd.DataFrame] = None
    friction_circle:   Any = None   # FrictionCircle
    vehicle_params:    Any = None   # VehicleParameters
    data_quality_rpt:  Any = None   # DataQualityReport

    # -- 09a: Reference line from resampled laps -- -

    def _reference_line() -> pd.DataFrame:
        if ref_line_mod is None:
            raise ImportError("reference_line unavailable")
        # Pass invalid laps as exclude set if the function supports it

        import inspect
        sig = inspect.signature(ref_line_mod.compute_reference_line)
        if "exclude_laps" in sig.parameters:
            return ref_line_mod.compute_reference_line(
                resampled_laps, exclude_laps=invalid_lap_set or None,
            )
        return ref_line_mod.compute_reference_line(resampled_laps)

    reference_line, err = _safe_step("09a_reference_line", _reference_line)
    _record("09a_reference_line", reference_line, err)
    summary["reference_line"] = reference_line

    # -- 08h: Line deviation detection (deferred from earlier — needs reference_line)

    def _line_deviation_detection():
        trim_mod = _import("session_trimming")
        if trim_mod is None or not hasattr(trim_mod, "identify_line_deviations"):
            return None
        if not resampled_laps or reference_line is None:
            return None
        already_excluded = invalid_lap_set | incomplete_lap_set | anomalous_lap_set
        return trim_mod.identify_line_deviations(
            resampled_laps, reference_line,
            excluded_laps=already_excluded,
        )

    deviation_result, err = _safe_step("08h_line_deviations", _line_deviation_detection)
    _record("08h_line_deviations", deviation_result, err)
    if deviation_result is not None:
        deviated_lap_set = deviation_result.get("deviated_laps", set())
        summary["line_deviation_analysis"] = {
            k: v for k, v in deviation_result.items() if k != "reason"
        }
        if deviated_lap_set:
            logger.info(
                "Flagged %d deviated lap(s): %s",
                len(deviated_lap_set), sorted(deviated_lap_set),
            )

    # ── 08j — Joker lap detection ──────────────────────────────────────────
    #
    # Only runs if the user checked "Enable Joker Lap Detection" in the
    # session info form (session_meta["enable_joker"]).  When a
    # joker_callback is provided (web mode), it blocks the pipeline until
    # the user confirms or rejects the candidate.

    joker_lap_set: set = set()

    def _joker_detection():
        # Check the session-level opt-in flag first.
        enable_joker = session_meta.get("enable_joker", False)
        if not enable_joker:
            return None  # User didn't check the box — skip detection.

        # Look up track config from DB for expected deltas (optional tuning).
        expected_dist = None
        expected_time = None
        try:
            from web.db import get_db_connection
            conn = get_db_connection()
            row = conn.execute(
                "SELECT joker_distance_delta_m, joker_time_delta_s "
                "FROM tracks WHERE track_id = :tid",
                {"tid": track_id},
            ).fetchone()
            if row:
                expected_dist = row["joker_distance_delta_m"]
                expected_time = row["joker_time_delta_s"]
        except Exception:
            pass  # CLI mode or DB not available.

        from kart_envelope.processing.joker_detection import (
            detect_joker_lap,
        )
        already_excluded = (
            invalid_lap_set | incomplete_lap_set
            | anomalous_lap_set | deviated_lap_set
        )
        result = detect_joker_lap(
            lap_metrics,
            lap_times,
            expected_distance_delta_m=expected_dist,
            expected_time_delta_s=expected_time,
            excluded_laps=already_excluded,
        )
        return result

    joker_result, err = _safe_step("08j_joker_detection", _joker_detection)
    _record("08j_joker_detection", joker_result, err)

    if joker_result is not None and joker_result.candidate_lap is not None:
        summary["joker_detection_result"] = {
            "candidate_lap": joker_result.candidate_lap,
            "confidence": joker_result.confidence,
            "all_distances": joker_result.all_distances,
            "median_distance": joker_result.median_distance,
            "delta_from_median": joker_result.delta_from_median,
            "all_times": joker_result.all_times,
            "median_time": joker_result.median_time,
            "time_delta_from_median": joker_result.time_delta_from_median,
            "reason": joker_result.reason,
        }
        confirmed_lap = None
        if joker_callback is not None:
            # Web mode — block pipeline until user confirms/rejects.
            confirmed_lap = joker_callback(joker_result)
        elif joker_result.confidence >= 0.7:
            # CLI/batch mode — auto-accept high-confidence candidates.
            confirmed_lap = joker_result.candidate_lap
            logger.info(
                "Auto-accepted joker lap %d (confidence %.2f, CLI mode).",
                confirmed_lap, joker_result.confidence,
            )

        if confirmed_lap is not None:
            joker_lap_set.add(confirmed_lap)
            summary["joker_lap_number"] = confirmed_lap
            logger.info("Joker lap confirmed: lap %d.", confirmed_lap)
        else:
            # User rejected or timed out — treat candidate as invalid.
            candidate = joker_result.candidate_lap
            invalid_lap_set.add(candidate)
            logger.info(
                "Joker lap rejected/timed out: lap %d added to invalid set.",
                candidate,
            )

    # Combine all exclusion sets for best-lap selection
    # (placed after 08j so joker_lap_set is populated)

    excluded_laps = (
        invalid_lap_set | incomplete_lap_set
        | anomalous_lap_set | deviated_lap_set
        | joker_lap_set
    )

    valid_times = [
        (k, t) for k, t in zip(sorted(resampled_laps.keys()), lap_times)
        if math.isfinite(t) and k not in excluded_laps
    ]
    if not valid_times:
        # Fallback: try with only invalid_lap_set excluded (less strict)

        valid_times = [
            (k, t) for k, t in zip(sorted(resampled_laps.keys()), lap_times)
            if math.isfinite(t) and k not in invalid_lap_set
        ]
    if not valid_times:
        # Last resort: use any finite time

        valid_times = [
            (k, t) for k, t in zip(sorted(resampled_laps.keys()), lap_times)
            if math.isfinite(t)
        ]
    if valid_times:
        best_lap_key = min(valid_times, key=lambda x: x[1])[0]
        best_lap_df  = resampled_laps.get(best_lap_key)
        logger.info(
            "Best lap selected: lap %d (%.3f s), "
            "excluded %d invalid + %d incomplete + %d deviated + %d joker lap(s).",
            best_lap_key, min(valid_times, key=lambda x: x[1])[1],
            len(invalid_lap_set), len(incomplete_lap_set),
            len(deviated_lap_set), len(joker_lap_set),
        )
    summary["best_lap"]     = best_lap_df
    summary["best_lap_key"] = best_lap_key

    # ── 08i — Recompute consistency & robustness with excluded laps removed ──
    #
    # Steps 08b/08c computed these metrics *before* invalid/incomplete/anomalous
    # laps were identified.  That means flagged laps (e.g. short inlaps, track
    # cuts, paused laps) were inflating CV%, skewing early/late stint averages,
    # and corrupting the robustness score.  We now recompute using only valid
    # lap times so the scoring system receives clean data.

    if excluded_laps:
        sorted_keys = sorted(resampled_laps.keys())
        _clean_lap_times = [
            t for k, t in zip(sorted_keys, lap_times)
            if k not in excluded_laps and math.isfinite(t)
        ]
        _clean_resampled = {
            k: v for k, v in resampled_laps.items()
            if k not in excluded_laps
        }
        logger.info(
            "Recomputing consistency/robustness after excluding %d lap(s) "
            "(kept %d of %d).",
            len(excluded_laps), len(_clean_lap_times), len(lap_times),
        )

        def _consistency_clean() -> dict[str, Any]:
            if feat_mod is None:
                return {}
            return feat_mod.compute_consistency_metrics(_clean_lap_times)

        consistency_v2, err = _safe_step(
            "08i_consistency_clean", _consistency_clean,
        )
        if consistency_v2:
            consistency = consistency_v2
            summary["consistency_metrics"] = consistency

        robustness_v2, err = _safe_step(
            "08i_robustness_clean",
            _compute_robustness_metrics, _clean_resampled, _clean_lap_times,
        )
        if robustness_v2:
            robustness = robustness_v2
            summary["robustness_metrics"] = robustness

    # STEP 9 --  Compute deltas (each lap vs best lap)

    #
    delta_mod = _import("deltas")

    def _compute_deltas() -> tuple[list[dict[str, Any]], list[list[float]]]:
        if delta_mod is None:
            raise ImportError("deltas unavailable")
        if best_lap_df is None or len(valid_times) < 2:
            return [], []

        ref = best_lap_df
        all_segs:   list[dict[str, Any]] = []
        all_losses: list[list[float]]    = []

        for ln in sorted(resampled_laps.keys()):
            # Skip excluded laps — they should not appear in the
            # delta heatmap (same logic that already excludes them
            # from best-lap selection and scoring).
            if ln in excluded_laps:
                continue

            cmp = resampled_laps[ln]
            if ln == best_lap_key:
                try:
                    curve = delta_mod.compute_delta_curve(ref, ref)
                    segs  = delta_mod.segment_time_loss(curve)
                    all_losses.append([s.get("time_loss_ms", 0.0) for s in segs])
                except Exception:
                    all_losses.append([0.0] * 20)
                continue
            try:
                causes = delta_mod.classify_time_loss_cause(ref, cmp)
                all_segs.extend(causes)
                all_losses.append([s.get("time_loss_ms", 0.0) for s in causes])
            except Exception as exc:
                logger.debug("Delta for lap %d failed: %s", ln, exc)
                all_losses.append([0.0] * 20)

        return all_segs, all_losses

    delta_res, err = _safe_step("09_compute_deltas", _compute_deltas)
    _record("09_compute_deltas", delta_res, err)
    if delta_res is not None:
        delta_segments, segment_losses = delta_res
    else:
        delta_segments, segment_losses = [], []
    summary["delta_segments"] = delta_segments
    summary["segment_losses"] = segment_losses

    # -- 09b: Curvature profile from reference line
    def _curvature() -> pd.DataFrame:
        if ref_line_mod is None:
            raise ImportError("reference_line unavailable")
        if reference_line is None:
            raise ValueError("No reference line from step 09a")
        return ref_line_mod.compute_curvature_profile(reference_line)

    curvature_profile, err = _safe_step("09b_curvature_profile", _curvature)
    _record("09b_curvature_profile", curvature_profile, err)
    summary["curvature_profile"] = curvature_profile

    # -- 09c: Friction model from telemetry

    def _friction() -> Any:
        if fric_mod is None:
            raise ImportError("friction_model unavailable")
        return fric_mod.build_friction_model(resampled_laps)

    friction_circle, err = _safe_step("09c_friction_model", _friction)
    _record("09c_friction_model", friction_circle, err)
    summary["friction_model"] = friction_circle

    # -- 09d: Vehicle classification and parameter estimation

    def _vehicle_class() -> Any:
        if veh_mod is None:
            raise ImportError("vehicle_model unavailable")
        if friction_circle is None:
            raise ValueError("No friction model from step 09c")
        return veh_mod.classify_vehicle(friction_circle, lap_metrics)

    vehicle_params, err = _safe_step("09d_vehicle_model", _vehicle_class)
    _record("09d_vehicle_model", vehicle_params, err)
    summary["vehicle_params"] = vehicle_params

    # -- 09d2: Kart traction correction -- # If the vehicle is classified as a kart, the friction model's traction

    # values are likely too conservative due to GPS noise.  Apply a traction

    # floor so the physics sim produces reasonable lap times.

    def _kart_traction_fix() -> Any:
        if friction_circle is None or vehicle_params is None:
            return friction_circle
        if fric_mod is None:
            return friction_circle
        if not hasattr(vehicle_params, 'vehicle_class'):
            return friction_circle
        vc = vehicle_params.vehicle_class
        # Check for kart class (handle both enum and string)

        is_kart = (hasattr(vc, 'value') and vc.value == "kart") or str(vc) == "kart"
        if not is_kart:
            return friction_circle
        if hasattr(fric_mod, 'apply_kart_traction_floor'):
            logger.info("Applying kart traction floor correction.")
            return fric_mod.apply_kart_traction_floor(friction_circle, floor_g=0.35)
        return friction_circle

    corrected_friction, err = _safe_step("09d2_kart_traction_fix", _kart_traction_fix)
    _record("09d2_kart_traction_fix", corrected_friction, err)
    if corrected_friction is not None:
        friction_circle = corrected_friction
        summary["friction_model"] = friction_circle

    # -- 09e: Data quality assessment

    def _data_quality() -> Any:
        if dq_mod is None:
            raise ImportError("data_quality unavailable")
        return dq_mod.score_data_quality(resampled_laps, lap_times)

    data_quality_rpt, err = _safe_step("09e_data_quality", _data_quality)
    _record("09e_data_quality", data_quality_rpt, err)
    summary["data_quality"] = data_quality_rpt

    # ====================================================================

    # STEP 10 -- Theoretical lap (cascading: physics -> percentile)

    # ====================================================================

    # Priority 1: Physics-based point-mass simulation using curvature

    #             profile + friction model + vehicle parameters.

    # Priority 2: Adaptive percentile envelope (original method) with

    #             data-quality-adjusted percentile.

    # Priority 3: Raw percentile envelope (hardcoded p98).

    #

    # The simulation method chosen is recorded in theoretical_metrics so

    # downstream consumers (scoring, debrief) know the provenance.


    theo_mod = _import("theoretical_engine")

    # Track which method succeeded

    _sim_method: str = "none"
    _sim_result: Any = None   # TheoreticalLapResult (if physics used)

    def _theoretical() -> pd.DataFrame:
        nonlocal _sim_method, _sim_result

        # Best driver time for sanity checking

        best_driver_time = float("inf")
        if valid_times:
            best_driver_time = min(t for _, t in valid_times)

        # -- Priority 1: Hybrid physics simulation (telemetry-fitted
        #    vehicle model + forward-backward solver, with internal
        #    fallback to friction-only physics then percentile envelope).
        if sim_mod is not None:
            try:
                # Extract grade profile if elevation data exists
                grade_prof = None
                if curvature_profile is not None and "grade" in curvature_profile.columns:
                    grade_vals = curvature_profile["grade"].values
                    if np.isfinite(grade_vals).sum() > 10:
                        grade_prof = grade_vals

                # Vehicle-specific physics parameters
                rr   = vehicle_params.rolling_resistance_est if vehicle_params else 0.015
                aero = vehicle_params.aero_drag_factor_est   if vehicle_params else 0.0

                # Adaptive speed percentile from data quality
                sp_pct = 98.0
                if data_quality_rpt is not None:
                    sp_pct = data_quality_rpt.recommended_speed_percentile

                result = sim_mod.simulate_with_fallback(
                    resampled_laps,
                    curvature_profile,
                    friction_circle,
                    driver_best_time_s=(
                        best_driver_time
                        if math.isfinite(best_driver_time) else None
                    ),
                    grade_profile=grade_prof,
                    rolling_resistance=rr,
                    aero_drag_factor=aero,
                    speed_percentile=sp_pct,
                )

                _sim_method = result.method   # "hybrid", "physics", or "percentile_envelope"
                _sim_result = result
                logger.info(
                    "Simulation [%s]: %.2fs (driver best %.2fs, "
                    "ratio %.1f%%).",
                    result.method, result.lap_time_s,
                    best_driver_time,
                    (result.lap_time_s / best_driver_time * 100
                     if math.isfinite(best_driver_time) and best_driver_time > 0
                     else float("nan")),
                )
                return sim_mod.result_to_theoretical_df(result)

            except Exception as exc:
                logger.warning(
                    "Simulation (with fallback) failed: %s — "
                    "falling back to percentile envelope via "
                    "theoretical_engine.", exc,
                )

        # -- Priority 2: Adaptive percentile envelope

        if theo_mod is not None:
            sorted_keys = sorted(resampled_laps.keys())
            laps_list = [
                _map_to_internal_names(resampled_laps[k])
                for k in sorted_keys
            ]

            # Pre-filter to best-N% laps if available (tighter envelope)

            if best_n_lap_indices:
                laps_for_theo = [laps_list[i] for i in best_n_lap_indices
                                 if i < len(laps_list)]
                keys_for_theo = [sorted_keys[i] for i in best_n_lap_indices
                                 if i < len(sorted_keys)]
                logger.info(
                    "Theoretical envelope: using %d best-N%% laps "
                    "(out of %d total).",
                    len(laps_for_theo), len(laps_list),
                )
            else:
                laps_for_theo = laps_list
                keys_for_theo = sorted_keys

            # Adaptive percentile from data quality

            speed_pct = 98.0
            accel_pct = 99.0
            if data_quality_rpt is not None:
                speed_pct = data_quality_rpt.recommended_speed_percentile
                accel_pct = data_quality_rpt.recommended_accel_percentile

            # Use phase-aware version if available

            if hasattr(theo_mod, 'build_theoretical_lap_phase_aware') and phases_df is not None:
                _sim_method = "percentile_envelope_phase_aware"
                return theo_mod.build_theoretical_lap_phase_aware(
                    laps_for_theo, phases_df=phases_df,
                    lap_to_phase=lap_to_phase,
                    n_points=n_resample_points,
                    lap_keys=keys_for_theo,
                    speed_percentile=speed_pct,
                    accel_percentile=accel_pct,
                )

            _sim_method = "percentile_envelope"
            # Try adaptive percentile first, fall back to default

            try:
                return theo_mod.build_theoretical_lap(
                    laps_for_theo, n_points=n_resample_points,
                    speed_percentile=speed_pct,
                    accel_percentile=accel_pct,
                )
            except TypeError:
                # Older theoretical_engine without percentile kwargs

                return theo_mod.build_theoretical_lap(
                    laps_for_theo, n_points=n_resample_points,
                )

        raise ImportError(
            "No simulation method available: both lap_simulation and "
            "theoretical_engine are unavailable."
        )

    theoretical_lap, err = _safe_step("10_theoretical", _theoretical)
    _record("10_theoretical", theoretical_lap, err)
    summary["theoretical_lap"] = theoretical_lap

    def _compute_theo_metrics() -> dict[str, Any]:
        if theoretical_lap is None:
            raise ValueError("No theoretical lap from step 10 -- cannot compute metrics.")
        return _theoretical_metrics_from_lap(
            theoretical_lap,
            simulation_method=_sim_method,
            sim_result=_sim_result,
            data_quality=data_quality_rpt,
        )

    theo_metrics, err = _safe_step(
        "10b_theoretical_metrics",
        _compute_theo_metrics,
    )
    _record("10b_theoretical_metrics", theo_metrics, err)
    theo_metrics = theo_metrics or {}
    summary["theoretical_metrics"] = theo_metrics

    # -- 10c: Corner analysis (requires corners + theoretical + friction) --

    def _corner_analysis():
        ca_mod = _import("corner_analysis")
        if ca_mod is None:
            return None
        if not corners or not resampled_laps or best_lap_df is None:
            return None
        # Need theoretical lap and friction model

        theo_result = summary.get("theoretical_lap")
        friction = summary.get("friction_model")
        if theo_result is None:
            return None
        perfs = ca_mod.analyze_corners(
            corners, best_lap_df, theo_result, friction,
        )
        return [p.to_dict() for p in perfs]

    ca_result, err = _safe_step("10c_corner_analysis", _corner_analysis)
    _record("10c_corner_analysis", ca_result, err)
    if ca_result is not None:
        corner_performances = ca_result
        n_corners = len(ca_result)
        total_loss = sum(cp.get("time_loss_s", 0) for cp in ca_result)
        logger.info(
            "Corner analysis: %d corners, total time loss %.3f s",
            n_corners, total_loss,
        )
    summary["corner_performances"] = corner_performances

    # STEP 10d -- Per-lap corner metrics (for DB storage & dashboard)

    per_lap_corner_metrics: list[dict[str, Any]] = []

    def _per_lap_corner_metrics():
        """Analyze every valid lap against detected corners."""
        ca_mod = _import("corner_analysis")
        if ca_mod is None:
            return []
        if not corners or not resampled_laps:
            return []

        theo_result = summary.get("theoretical_lap")
        friction = summary.get("friction_model")

        results = []
        sorted_keys = sorted(resampled_laps.keys())

        for lap_num in sorted_keys:
            if lap_num in excluded_laps:
                continue
            lap_df = resampled_laps[lap_num]
            if lap_df is None or len(lap_df) < 10:
                continue

            try:
                perfs = ca_mod.analyze_corners(
                    corners, lap_df, theo_result, friction,
                )
                for perf in perfs:
                    d = perf.to_dict() if hasattr(perf, "to_dict") else dict(perf)
                    d["lap_number"] = int(lap_num)
                    # Convert time_loss_s to time_loss_ms for DB
                    tl = d.get("time_loss_s", 0.0)
                    d["time_loss_ms"] = round(float(tl or 0) * 1000, 1)
                    # Map field names to corner_metrics columns
                    d["entry_speed_mps"] = d.get("actual_entry_speed_mps")
                    d["apex_speed_mps"] = d.get("actual_apex_speed_mps")
                    d["exit_speed_mps"] = d.get("actual_exit_speed_mps")
                    d["brake_point_m"] = d.get("braking_point_actual_m")
                    d["grip_utilization"] = d.get("grip_utilisation_pct")
                    if d.get("grip_utilization"):
                        d["grip_utilization"] = d["grip_utilization"] / 100.0

                    # Extract throttle_onset, brake_intensity, exit_accel
                    # from raw telemetry in the corner region
                    try:
                        s_start = d.get("s_start", 0)
                        s_end = d.get("s_end", 0)
                        dist_col = None
                        spd_col = None
                        accel_col = None
                        for c in ["Distance (m)", "distance_m", "dist_m"]:
                            if c in lap_df.columns:
                                dist_col = c
                                break
                        for c in ["Speed (m/s)", "speed_mps"]:
                            if c in lap_df.columns:
                                spd_col = c
                                break
                        for c in ["accel_long_mps2", "Accel_long_G",
                                  "accel_long_g",
                                  "Longitudinal acceleration (G) *calc",
                                  "Acceleration (m/s²)", "accel_mps2"]:
                            if c in lap_df.columns:
                                accel_col = c
                                break

                        if dist_col and spd_col:
                            dist_arr = pd.to_numeric(
                                lap_df[dist_col], errors="coerce"
                            ).values
                            spd_arr = pd.to_numeric(
                                lap_df[spd_col], errors="coerce"
                            ).values

                            # Find apex index (min speed in corner)
                            mask = (dist_arr >= s_start) & (dist_arr <= s_end)
                            corner_idx = np.where(mask)[0]
                            if len(corner_idx) > 2:
                                corner_spd = spd_arr[corner_idx]
                                apex_local = np.nanargmin(corner_spd)
                                apex_idx = corner_idx[apex_local]

                                # Throttle onset: first distance after apex
                                # where speed increases sustained for 3+ pts
                                onset_m = None
                                for k in range(apex_idx + 1,
                                               min(apex_idx + 50,
                                                   len(spd_arr) - 2)):
                                    if (spd_arr[k] > spd_arr[apex_idx] + 0.5
                                            and spd_arr[k + 1] > spd_arr[k]):
                                        onset_m = float(dist_arr[k])
                                        break
                                if onset_m is not None:
                                    d["throttle_onset_m"] = onset_m

                                # Exit acceleration (avg accel in exit half)
                                exit_start = corner_idx[len(corner_idx) // 2]
                                exit_end = corner_idx[-1]
                                if exit_end > exit_start + 1:
                                    exit_spds = spd_arr[exit_start:exit_end + 1]
                                    exit_dists = dist_arr[exit_start:exit_end + 1]
                                    dd = np.diff(exit_dists)
                                    dv = np.diff(exit_spds)
                                    valid_dd = dd > 0.01
                                    if np.any(valid_dd):
                                        accels = dv[valid_dd] * exit_spds[
                                            :-1][valid_dd] / dd[valid_dd]
                                        pos_acc = accels[accels > 0]
                                        if len(pos_acc) > 0:
                                            d["exit_accel_mps2"] = round(
                                                float(np.mean(pos_acc)), 3
                                            )

                            # Brake intensity (peak deceleration before corner)
                            if accel_col:
                                accel_arr = pd.to_numeric(
                                    lap_df[accel_col], errors="coerce"
                                ).values
                                # Look 50m before corner entry
                                pre_mask = ((dist_arr >= s_start - 50)
                                            & (dist_arr < s_start))
                                pre_idx = np.where(pre_mask)[0]
                                if len(pre_idx) > 0:
                                    pre_accel = accel_arr[pre_idx]
                                    valid = pre_accel[np.isfinite(pre_accel)]
                                    if len(valid) > 0:
                                        d["brake_intensity"] = round(
                                            float(np.min(valid)), 3
                                        )
                    except Exception:
                        pass  # Non-critical enrichment

                    results.append(d)
            except Exception as exc:
                logger.debug("Corner analysis for lap %s: %s", lap_num, exc)
                continue

        return results

    _plcm_result, err = _safe_step("10d_per_lap_corners", _per_lap_corner_metrics)
    _record("10d_per_lap_corners", _plcm_result, err)
    if _plcm_result:
        per_lap_corner_metrics = _plcm_result
        logger.info(
            "Per-lap corner metrics: %d entries across %d laps",
            len(per_lap_corner_metrics),
            len(set(m["lap_number"] for m in per_lap_corner_metrics)),
        )
    summary["per_lap_corner_metrics"] = per_lap_corner_metrics

    # STEP 11 --  Build feature dataset

    #
    fb_mod = _import("feature_builder")

    def _build_features() -> pd.DataFrame:
        if fb_mod is None:
            raise ImportError("feature_builder unavailable")
        lap_df = pd.DataFrame(lap_metrics)
        seg_df: Optional[pd.DataFrame] = None
        if delta_segments:
            flat_rows: list[dict[str, Any]] = []
            for seg in delta_segments:
                row = dict(seg)
                cd = seg.get("cause_details")
                if isinstance(cd, dict):
                    row.update(cd)
                flat_rows.append(row)
            if flat_rows:
                seg_df = pd.DataFrame(flat_rows)
        metadata = {
            "track_id":    track_id,
            "track_state": meta.get("track_state", "dry"),
            "driver_name": meta.get("driver_name", "Unknown"),
            "session_id":  meta.get("session_id", ""),
        }
        return fb_mod.build_feature_dataset(
            lap_df, seg_df, metadata,
            context=context, lap_to_phase=lap_to_phase,
        )

    feature_df, err = _safe_step("11_build_features", _build_features)
    _record("11_build_features", feature_df, err)
    summary["feature_df"] = feature_df

    # STEP 12 --  Train / update ML + anomaly detection

    ml_results:      dict[str, Any] = {}
    anomaly_results: dict[str, Any] = {}

    if enable_ml and feature_df is not None and len(feature_df) > 0:
        ml_mod = _import("ml_engine")
        ad_mod = _import("anomaly_detection")

        def _ml_train() -> dict[str, Any]:
            res: dict[str, Any] = {}
            if ml_mod is None or len(feature_df) < 10:
                res["skipped"] = "insufficient data or module absent"
                return res
            try:
                res["global_model"] = ml_mod.train_global_model(feature_df)
            except Exception as exc:
                res["global_model_error"] = str(exc)
            try:
                driver = meta.get("driver_name", "Unknown")
                res["driver_model"] = ml_mod.train_driver_model(feature_df, driver)
            except Exception as exc:
                res["driver_model_error"] = str(exc)
            return res

        ml_results, err = _safe_step("12a_ml_train", _ml_train)
        _record("12a_ml_train", ml_results, err)
        ml_results = ml_results or {}

        def _anomaly() -> dict[str, Any]:
            if ad_mod is None:
                return {"skipped": "anomaly_detection absent"}
            model = ad_mod.train_anomaly_model(feature_df)
            detections = ad_mod.detect_anomalies(model, feature_df)
            return {
                "condition_keys": list(model.condition_models.keys()),
                "detections":     detections,
                "n_anomalies":    sum(1 for d in detections if d.get("anomaly_flag")),
            }

        anomaly_results, err = _safe_step("12b_anomaly_detection", _anomaly)
        _record("12b_anomaly_detection", anomaly_results, err)
        anomaly_results = anomaly_results or {}

    summary["ml_results"]      = ml_results
    summary["anomaly_results"] = anomaly_results

    # STEP 13 --  Score session

    #
    score_mod = _import("scoring")

    def _score() -> dict[str, Any]:
        if score_mod is None:
            raise ImportError("scoring unavailable")
        m: dict[str, Any] = {}
        if consistency:
            m.update(consistency)
        if robustness:
            m.update(robustness)
        if lap_metrics:
            # Filter out excluded laps from execution metrics so that
            # invalid/incomplete laps don't distort speed/accel averages.
            _valid_metrics = [
                lm for lm in lap_metrics
                if lm.get("lap_number") not in excluded_laps
            ]
            _src = _valid_metrics if _valid_metrics else lap_metrics
            speeds = [lm.get("speed_mean_mps", float("nan")) for lm in _src]
            accels = [lm.get("accel_max_mps2", float("nan")) for lm in _src]
            brakes = [lm.get("braking_max_mps2", float("nan")) for lm in _src]
            m["speed_mean_mps"]   = float(np.nanmean(speeds))  if speeds else float("nan")
            m["accel_max_mps2"]   = float(np.nanmax(accels))   if accels else float("nan")
            m["braking_max_mps2"] = float(np.nanmax(brakes))   if brakes else float("nan")
        # Use phase-aware scoring if available

        if hasattr(score_mod, 'score_session_phase_aware'):
            return score_mod.score_session_phase_aware(
                m, theo_metrics, meta.get("session_type", "practice"),
                context=context, phases_df=phases_df,
                lap_to_phase=lap_to_phase,
                lap_metrics=lap_metrics,
                track_evolution=track_evolution,
                corner_performances=corner_performances,
            )
        # Detect wet from context for non-phase-aware fallback

        _is_wet = False
        if context is not None:
            _ts = getattr(context, "baseline_track_state", None)
            if _ts is not None:
                _sv = _ts.value if hasattr(_ts, "value") else str(_ts)
                _is_wet = _sv.lower() in ("wet", "full_wet", "damp", "drying", "greasy")
        return score_mod.score_session(
            m, theo_metrics, meta.get("session_type", "practice"),
            is_wet=_is_wet,
        )

    score_result, err = _safe_step("13_score_session", _score)
    _record("13_score_session", score_result, err)
    summary["score_result"] = score_result

    # STEP 14 --  Generate report (driver profile + HTML + PDF)

    # 14a. Driver profile

    dp_mod = _import("driver_profile")

    def _driver_profile() -> dict[str, Any]:
        if dp_mod is None:
            raise ImportError("driver_profile unavailable")
        sess_data: dict[str, Any] = {
            "metrics":             {**(consistency or {}), **(robustness or {})},
            "theoretical_metrics": theo_metrics,
            "resampled_laps":      list(resampled_laps.values()),
            "score_result":        score_result or {},
            "session_id":          meta.get("session_id"),
            "session_date":        meta.get("date"),
        }
        if lap_metrics:
            sess_data["metrics"].update(lap_metrics[0])
        return dp_mod.generate_driver_profile(
            meta.get("driver_name", "Unknown"), [sess_data],
            context=context, phases_df=phases_df,
            lap_to_phase=lap_to_phase, lap_metrics=lap_metrics,
        )

    driver_profile, err = _safe_step("14a_driver_profile", _driver_profile)
    _record("14a_driver_profile", driver_profile, err)
    summary["driver_profile"] = driver_profile

    # STEP 14a2 -- Driving style features (Phase 3)

    ds_mod = _import("driving_style")
    driving_style_result: "dict[str, Any] | None" = None

    def _driving_style() -> "dict[str, Any] | None":
        if ds_mod is None:
            return None
        if not resampled_laps:
            return None
        return ds_mod.compute_driving_style(
            resampled_laps,
            lap_metrics=lap_metrics,
            corners=corners,
            corner_performances=corner_performances,
            theoretical_metrics=theo_metrics,
            per_lap_corner_metrics=per_lap_corner_metrics,
        )

    driving_style_result, err = _safe_step("14a2_driving_style", _driving_style)
    _record("14a2_driving_style", driving_style_result, err)
    summary["driving_style"] = driving_style_result

    # 14b + 14c. HTML + PDF

    # STEP 13b -- Generate coaching guide

    coaching_guide: "dict[str, Any] | None" = None

    def _coaching_guide():
        de_mod = _import("debrief_engine")
        if de_mod is None or not hasattr(de_mod, "generate_coaching_guide"):
            return None
        return de_mod.generate_coaching_guide(
            corner_performances=corner_performances,
            lap_metrics=lap_metrics,
            score_result=score_result,
            track_evolution=track_evolution,
            session_type=meta.get("session_type", "practice"),
        )

    cg_result, err = _safe_step("13b_coaching_guide", _coaching_guide)
    _record("13b_coaching_guide", cg_result, err)
    if cg_result:
        coaching_guide = cg_result
        n_focus = len(cg_result.get("focus_areas", []))
        logger.info("Coaching guide: %d focus areas", n_focus)
    summary["coaching_guide"] = coaching_guide

    html_path: Optional[Path] = None
    pdf_path:  Optional[Path] = None

    if enable_report:
        if output_dir is not None:
            out_dir = Path(output_dir)
        else:
            date_str = meta.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            out_dir = Path("Results") / f"{date_str}_{track_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        summary["output_dir"] = str(out_dir)

        rpt_html = _import("reporting_html")
        rpt_pdf  = _import("reporting_pdf")

        def _html_report() -> Path:
            if rpt_html is None:
                raise ImportError("reporting_html unavailable")
            return rpt_html.generate_report(
                score_result=score_result,
                theoretical_lap=theoretical_lap,
                best_lap=best_lap_df,
                delta_segments=delta_segments[:20] if delta_segments else None,
                lap_times=lap_times,
                segment_losses=segment_losses,
                driver_profiles=[driver_profile] if driver_profile else None,
                session_meta=meta,
                context=context,
                phases_df=phases_df,
                output_path=out_dir / f"index{_dtag_suffix}.html",
                coaching_guide=coaching_guide,
                # Physics data for G-G diagram, grip chart, corner table

                resampled_laps=resampled_laps,
                friction_circle=friction_circle,
                corner_performances=corner_performances,
                grip_evolution=grip_evolution_result,
                data_quality=data_quality_rpt,
                theoretical_result=_sim_result,
            )

        html_path, err = _safe_step("14b_html_report", _html_report)
        _record("14b_html_report", html_path, err)

        def _pdf_report() -> Optional[Path]:
            if rpt_pdf is None or html_path is None:
                return None
            return rpt_pdf.generate_pdf_from_html(
                html_path, out_dir / f"session_report{_dtag_suffix}.pdf",
            )

        pdf_path, err = _safe_step("14c_pdf_report", _pdf_report)
        _record("14c_pdf_report", pdf_path, err)

    summary["html_path"] = str(html_path) if html_path else None
    summary["pdf_path"]  = str(pdf_path)  if pdf_path  else None

    # STEP 15 --  Persist to SQLite database (optional, graceful degradation)

    def _persist_to_db() -> Optional[str]:
        """Save pipeline results to SQLite.  Returns session_id or None."""
        try:
            from web.db import get_db_connection, init_db, set_default_db_path
            from web.models import (
                insert_condition_markers,
                insert_condition_phases,
                insert_driving_style_features,
                insert_driver_progression,
                insert_gps_traces,
                insert_laps,
                insert_reference_line,
                insert_score_details,
                insert_theoretical_data,
                upsert_driver,
                upsert_driver_profile,
                upsert_session,
                upsert_track,
            )
        except ImportError:
            logger.debug("Web layer not available; skipping DB persistence.")
            return None

        try:
            from path_manager import get_db_path
            db_path = get_db_path()
        except (ImportError, AttributeError):
            db_path = Path(__file__).resolve().parent / "telemetry.db"

        set_default_db_path(db_path)
        init_db(db_path)
        conn = get_db_connection()

        # Use ``with conn:`` for atomic commit/rollback -- if any
        # unhandled exception propagates, all changes are rolled back.
        with conn:
            driver_name = meta.get("driver_name", "Driver_1")
            driver_id = upsert_driver(conn, driver_name)

            # Ensure track exists in DB before inserting session (FK constraint).
            _tid = summary.get("track_id")
            if _tid:
                _track_entry = None
                # Prefer full fingerprint from tracks.json (has bbox, start coords).
                try:
                    from track_detection import load_track_database
                    for _te in load_track_database():
                        if _te.get("track_id") == _tid:
                            _track_entry = _te
                            break
                except Exception:
                    pass

                if _track_entry is None:
                    # Fall back to whatever the pipeline match result provides.
                    _tm = summary.get("track_match")
                    _track_entry = {
                        "track_id":   _tid,
                        "track_name": (_tm or {}).get("track_name", _tid),
                        "fingerprint": {
                            "lap_length_m": (_tm or {}).get("lap_length_m", 0.0),
                            "bbox": {},
                            "start_lat": None,
                            "start_lon": None,
                            "sample_count": None,
                            "lap_count": None,
                        },
                    }
                upsert_track(conn, _track_entry)

            session_id = upsert_session(conn, summary, driver_id)
            insert_laps(conn, session_id, summary)
            insert_gps_traces(conn, session_id, summary)
            insert_score_details(conn, session_id, summary)
            insert_condition_phases(conn, session_id, summary)

            # Phase 4: theoretical data + reference line
            try:
                insert_theoretical_data(conn, session_id, summary)
                logger.info("Persisted theoretical data for session %s.", session_id)
            except Exception as _theo_err:
                logger.warning("Theoretical data persistence FAILED: %s", _theo_err,
                               exc_info=True)
            try:
                insert_reference_line(conn, session_id, summary)
                logger.info("Persisted reference line for session %s.", session_id)
            except Exception as _ref_err:
                logger.warning("Reference line persistence FAILED: %s", _ref_err,
                               exc_info=True)

            # Persist per-lap corner metrics (Phase 7)
            try:
                from web.models import insert_corner_metrics
                _cm_count = insert_corner_metrics(conn, session_id, summary)
                if _cm_count > 0:
                    logger.info("Persisted %d corner metrics for session %s.",
                                _cm_count, session_id)
            except Exception as _cm_err:
                logger.warning("Corner metrics persistence skipped: %s", _cm_err)

            # Persist manual condition markers (Phase 2)
            _manual_cc = meta.get("manual_condition_changes")
            if _manual_cc:
                insert_condition_markers(conn, session_id, _manual_cc)

            # Enrich score_result with historical context (Phase 2)
            try:
                from cross_session import enrich_with_historical
                _best_s = summary.get("score_result", {}).get("best_s") or None
                if _best_s is None and summary.get("score_result"):
                    _best_s = summary["score_result"].get("metrics", {}).get("best_s")
                if score_result and track_id:
                    enriched = enrich_with_historical(
                        conn, session_id, track_id, driver_id, score_result,
                    )
                    summary["score_result"] = enriched
                    logger.info("Enriched score with historical context.")
            except (ImportError, Exception) as _h_err:
                logger.warning("Historical enrichment skipped: %s", _h_err)

            # ── Phase 3: Persist driving style features ──────────────
            if driving_style_result:
                try:
                    insert_driving_style_features(
                        conn, driver_id, session_id, driving_style_result,
                    )
                    logger.info("Persisted driving style: %s",
                                driving_style_result.get("style_label"))
                except Exception as _ds_err:
                    logger.warning("Driving style persistence skipped: %s", _ds_err)

            # ── Phase 3: Persist driver progression snapshot ─────────
            try:
                # Compute progression metrics from current session data
                _lap_times = summary.get("lap_times") or []
                _valid_lt = [t for t in _lap_times
                             if t and isinstance(t, (int, float))
                             and math.isfinite(t) and t > 0]
                _n_laps = len(_valid_lt)
                _best_s = min(_valid_lt) if _valid_lt else None
                _mean_s = sum(_valid_lt) / _n_laps if _n_laps > 0 else None

                # Pace delta: best - theoretical (positive = slower)
                _pace_delta = None
                if _best_s and theo_metrics:
                    _theo_t = theo_metrics.get("theoretical_time_s")
                    if _theo_t and isinstance(_theo_t, (int, float)):
                        _pace_delta = _best_s - _theo_t

                # Consistency: CV% of valid lap times
                _cv_pct = None
                if _n_laps >= 3:
                    _std = float(np.std(_valid_lt))
                    _cv_pct = (_std / _mean_s * 100.0) if _mean_s else None

                # Style indices from driving_style_result
                _aggression = None
                _smoothness = None
                if driving_style_result:
                    _feat = driving_style_result.get("features", {})
                    _aggression = _feat.get("turn_in_aggressiveness")
                    _smoothness = _feat.get("smoothness_composite")

                _total_score = None
                if score_result:
                    _total_score = score_result.get("total_score")

                _prog_data = {
                    "session_date": session_id[:10],
                    "track_id":     track_id,
                    "pace_delta_s": _pace_delta,
                    "consistency_cv_pct": _cv_pct,
                    "aggression_index":   _aggression,
                    "smoothness_index":   _smoothness,
                    "total_score":        _total_score,
                    "n_laps":             _n_laps,
                }
                insert_driver_progression(conn, driver_id, session_id, _prog_data)
                logger.info("Persisted driver progression for session %s.", session_id)
            except Exception as _prog_err:
                logger.warning("Driver progression persistence skipped: %s", _prog_err)

            # ── Phase 3: Update driver profile computed fields ───────
            try:
                # Aggregate across all progression rows for this driver
                _all_prog = conn.execute(
                    "SELECT pace_delta_s, consistency_cv_pct, aggression_index, "
                    "smoothness_index, total_score, n_laps "
                    "FROM driver_progression WHERE driver_id = ?",
                    (driver_id,),
                ).fetchall()

                if _all_prog:
                    _deltas = [r[0] for r in _all_prog if r[0] is not None]
                    _cvs    = [r[1] for r in _all_prog if r[1] is not None]
                    _aggs   = [r[2] for r in _all_prog if r[2] is not None]
                    _smos   = [r[3] for r in _all_prog if r[3] is not None]
                    _total_laps = sum(r[5] for r in _all_prog if r[5])
                    _total_sess = len(_all_prog)

                    # Trend: compare mean score of last 3 vs first 3
                    _scores = [r[4] for r in _all_prog if r[4] is not None]
                    _trend = "stable"
                    if len(_scores) >= 4:
                        _early = np.mean(_scores[:3])
                        _late  = np.mean(_scores[-3:])
                        if _late > _early * 1.05:
                            _trend = "improving"
                        elif _late < _early * 0.95:
                            _trend = "declining"

                    # Best-ever time across all sessions
                    _best_row = conn.execute(
                        "SELECT best_lap_time_s, track_id FROM sessions "
                        "WHERE driver_id = ? AND best_lap_time_s IS NOT NULL "
                        "ORDER BY best_lap_time_s ASC LIMIT 1",
                        (driver_id,),
                    ).fetchone()

                    _profile_data = {
                        "pace_delta_mean_s":  float(np.mean(_deltas)) if _deltas else None,
                        "consistency_rating": float(np.mean(_cvs)) if _cvs else None,
                        "aggression_index":   float(np.mean(_aggs)) if _aggs else None,
                        "smoothness_index":   float(np.mean(_smos)) if _smos else None,
                        "improvement_trend":  _trend,
                        "total_sessions":     _total_sess,
                        "total_laps":         _total_laps,
                        "best_ever_time_s":   _best_row[0] if _best_row else None,
                        "best_ever_track_id": _best_row[1] if _best_row else None,
                    }
                    upsert_driver_profile(conn, driver_id, _profile_data)
                    logger.info("Updated driver profile (sessions=%d, laps=%d).",
                                _total_sess, _total_laps)
            except Exception as _prof_err:
                logger.warning("Driver profile update skipped: %s", _prof_err)

        # with conn: auto-commits on success, rolls back on exception
        logger.info("Persisted session %s to SQLite.", session_id)
        return session_id

    db_session_id, err = _safe_step("15_persist_db", _persist_to_db)
    _record("15_persist_db", db_session_id, err)
    summary["db_session_id"] = db_session_id

    # Final summary

    #
    n_ok     = len(summary["steps_ok"])
    n_fail   = len(summary["steps_failed"])
    score_str = (
        f"{score_result['total_score']:.1f}/{score_result['grade']}"
        if score_result else "n/a"
    )
    logger.info(
        "Pipeline complete: %d/%d steps OK  track=%s  laps=%d  score=%s",
        n_ok, n_ok + n_fail, track_id,
        len(resampled_laps) if resampled_laps else 0,
        score_str,
    )
    return summary


# ============================================================================

# Inline tests

# ============================================================================


def _run_tests() -> None:
    """Self-contained test suite --  run with ``python pipeline.py``."""

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn: Any) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Test 1 --  _safe_step success -- -

    def t_safe_ok() -> None:
        r, e = _safe_step("t", lambda: 42)
        assert r == 42 and e is None

    _test("safe_step_ok", t_safe_ok)

    # -- Test 2 --  _safe_step failure -- -

    def t_safe_fail() -> None:
        def _boom() -> None:
            raise ValueError("boom")
        r, e = _safe_step("t", _boom)
        assert r is None and "boom" in e

    _test("safe_step_fail", t_safe_fail)

    # -- Test 3 --  robustness metrics normal

    def t_robustness() -> None:
        rng = np.random.default_rng(42)
        laps: dict[int, pd.DataFrame] = {}
        times: list[float] = []
        for i in range(1, 11):
            d = np.linspace(0, 4500, 500)
            s = 30 + 10 * np.sin(d / 700) + rng.normal(0, 0.5, 500)
            y = rng.normal(0, 5, 500) * (1.5 if i > 7 else 1.0)
            laps[i] = pd.DataFrame({
                "Distance (m)": d, "Speed (m/s)": s, "yaw_rate_dps": y,
            })
            times.append(4500 / max(float(s.mean()), 1) + (0.5 if i > 7 else 0))

        r = _compute_robustness_metrics(laps, times)
        assert all(k in r for k in ("early_mean_s", "late_mean_s",
                                     "early_yaw_var", "late_yaw_var"))
        assert all(math.isfinite(v) for v in r.values())
        assert r["late_yaw_var"] > r["early_yaw_var"]

    _test("robustness_metrics", t_robustness)

    # -- Test 4 --  robustness empty data

    def t_robustness_empty() -> None:
        r = _compute_robustness_metrics({}, [])
        assert math.isnan(r["early_mean_s"])

    _test("robustness_empty", t_robustness_empty)

    # -- Test 5 --  theoretical metrics extraction -- -

    def t_theo_metrics() -> None:
        d = np.linspace(0, 4500, 1000)
        s = 35 + 10 * np.sin(2 * np.pi * d / 4500)
        theo = pd.DataFrame({
            "distance_m": d, "v_env_mps": s,
            "accel_max_mps2": np.full(1000, 8.0),
            "brake_max_mps2": np.full(1000, 12.0),
        })
        m = _theoretical_metrics_from_lap(theo)
        assert math.isfinite(m["best_s"]) and m["best_s"] > 0
        assert m["accel_max_mps2"] == 8.0

    _test("theoretical_metrics", t_theo_metrics)

    # -- Test 6 --  theoretical metrics minimal data -- -

    def t_theo_minimal() -> None:
        m = _theoretical_metrics_from_lap(
            pd.DataFrame({"distance_m": [0], "v_env_mps": [30]}),
        )
        assert math.isnan(m["best_s"])

    _test("theoretical_metrics_minimal", t_theo_minimal)

    # -- Test 7 --  missing CSV returns partial summary

    def t_missing_csv() -> None:
        r = run_full_analysis(
            "/nonexistent.csv", {"driver_name": "Test"},
            enable_ml=False, enable_report=False,
        )
        assert isinstance(r, dict)
        assert "01_ingest" in r["steps_failed"]
        assert r["raw_df"] is None

    _test("missing_csv", t_missing_csv)

    # -- Test 8 --  session_meta defaults

    def t_meta_defaults() -> None:
        r = run_full_analysis(
            "/x.csv", {}, enable_ml=False, enable_report=False,
        )
        m = r["session_meta"]
        assert m["session_type"] == "practice"
        assert m["track_state"]  == "dry"
        assert m["driver_name"]  == "Unknown"
        assert "date" in m

    _test("meta_defaults", t_meta_defaults)

    # -- Test 9 --  summary always has required keys -- -

    def t_summary_keys() -> None:
        r = run_full_analysis(
            "/x.csv", {}, enable_ml=False, enable_report=False,
        )
        for key in ("csv_path", "session_meta", "steps_ok",
                     "steps_failed", "errors", "raw_df"):
            assert key in r, f"Missing key: {key}"

    _test("summary_keys", t_summary_keys)

    # -- Test 10 --  _import missing returns None

    def t_import_missing() -> None:
        assert _import("nonexistent_xyz_123") is None

    _test("import_missing", t_import_missing)

    # -- Test 11 --  _import real module works -- -

    def t_import_real() -> None:
        mod = _import("math")
        assert mod is not None and hasattr(mod, "pi")

    _test("import_real", t_import_real)

    # -- Test 12 --  PipelineError is catchable

    def t_pipeline_error() -> None:
        try:
            raise PipelineError("test")
        except PipelineError:
            pass

    _test("pipeline_error", t_pipeline_error)

    # -- Test 13 --  lap_range=None does not crash -- -

    def t_lap_range_none() -> None:
        r = run_full_analysis(
            "/x.csv", {}, enable_ml=False, enable_report=False,
            lap_range=None,
        )
        assert isinstance(r, dict)

    _test("lap_range_none", t_lap_range_none)

    # -- Test 14 --  lap_range with value does not crash -- -

    def t_lap_range_set() -> None:
        r = run_full_analysis(
            "/x.csv", {}, enable_ml=False, enable_report=False,
            lap_range=(3, 10),
        )
        assert isinstance(r, dict)

    _test("lap_range_set", t_lap_range_set)

    # -- Test 15 --  enable_ml=False skips ML steps

    def t_ml_skipped() -> None:
        r = run_full_analysis(
            "/x.csv", {}, enable_ml=False, enable_report=False,
        )
        assert r["ml_results"] == {}
        assert r["anomaly_results"] == {}

    _test("ml_skipped", t_ml_skipped)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nPipeline Tests: {len(passed)}/{total} passed [{status}]")
    for name in passed:
        print(f"  \u2713 {name}")
    for name, tb in failed:
        print(f"  \u2717 {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()