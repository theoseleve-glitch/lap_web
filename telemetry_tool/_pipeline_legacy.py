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

from pipeline_status import (
    PipelineState,
    PipelineStatus,
    StepState,
    StepStatus,
    compute_pipeline_version_string,
    get_model_version,
    now_epoch,
    now_monotonic,
)
from provenance.run_context import build_provenance

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================================

# Column-name constants (mirrors upstream)

# ============================================================================


_COL_LAP:   Final[str] = "Lap #"
_COL_TIME:  Final[str] = "Time (s)"
_COL_SPEED: Final[str] = "Speed (m/s)"
_COL_DIST:  Final[str] = "Distance (m)"


# -- Column discovery engine (replaces _RAW_TO_INTERNAL) --
# Import is placed here at module level for clarity; the actual discovery
# runs lazily during the pipeline orchestrator.
try:
    from telemetry_tool.column_discovery import apply_discovery, discover_columns
except ImportError:
    from column_discovery import apply_discovery, discover_columns


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
                "s_start": cn.get("s_start"),
                "s_end": cn.get("s_end"),
                "s_apex": cn.get("s_apex", apex_m),
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
    progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
    stop_after_corners: bool = False,
    resume_from_step8: bool = False,
    preloaded_resampled_laps: Optional[dict] = None,
    preloaded_corners: Optional[list] = None,
    filter_profile_name: Optional[str] = None,
    vehicle_overrides: Optional[dict[str, Any]] = None,
    deterministic: bool = False,
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
    # Derive session date from telemetry CSV headers if not user-provided
    if not meta.get("date"):
        try:
            wt = _import("weather_timeline")
            if wt and hasattr(wt, "parse_session_datetime"):
                _dt = wt.parse_session_datetime(csv_path)
                if _dt:
                    meta["date"] = _dt.strftime("%Y-%m-%d")
                    meta["session_datetime"] = _dt.isoformat()
        except Exception:
            pass  # Best-effort; fall through to now()
    meta.setdefault("date",         datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # --- Resolve filter profile ---
    _resolved_filter_profile = None
    try:
        from telemetry_tool.filter_profile import resolve_filter_profile as _resolve_fp
        _resolved_filter_profile = _resolve_fp(
            filter_profile_name,
            track_id=meta.get("track_id"),
            session_type=meta.get("session_type"),
        )
        logger.info("Filter profile resolved: %s", _resolved_filter_profile.profile_name)
    except Exception as _fp_exc:
        logger.debug("Filter profile resolution skipped: %s", _fp_exc)

    # --- Driver-tag file suffix (multi-driver namespacing)

    _dtag_suffix = f"_{driver_tag}" if driver_tag else ""

    # ── Pipeline status tracker ─────────────────────────────
    _pipeline_status = PipelineStatus(
        pipeline_version=compute_pipeline_version_string(),
        model_version=get_model_version(),
    )

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
        # Weather timeline (step 08e)
        "weather_timeline":      None,
        # Filter + vehicle override metadata
        "filter_config":         (
            _resolved_filter_profile.to_dict()
            if _resolved_filter_profile else None
        ),
        "vehicle_overrides":     vehicle_overrides,
    }

    # ── Stage progress tracking ─────────────────────────────
    _STAGE_MAP: list[tuple[str, str]] = [
        ("01_ingest",           "Ingesting CSV"),
        ("02_filter",           "GPS Filtering"),
        ("03_derived_channels", "Derived Channels"),
        ("04_trim_session",     "Session Trim"),
        ("05_detect_track",     "Track Detection"),
        ("06_segment_laps",     "Lap Segmentation"),
        ("06b_detect_corners",  "Corner Detection"),
        ("08_compute_metrics",  "Computing Metrics"),
        ("09a_reference_line",  "Reference Line"),
        ("09_compute_deltas",   "Physics Models"),
        ("10_theoretical",      "Theoretical Lap"),
        ("11_build_features",   "Feature Engineering"),
        ("13_score_session",    "Scoring"),
        ("15_persist_db",       "Saving Results"),
    ]
    _STAGE_TOTAL = len(_STAGE_MAP)
    _STAGE_LOOKUP = {name: (i + 1, label) for i, (name, label) in enumerate(_STAGE_MAP)}

    def _fire_progress(step_name: str, status: str = "done") -> None:
        if progress_callback and step_name in _STAGE_LOOKUP:
            idx, label = _STAGE_LOOKUP[step_name]
            try:
                progress_callback(idx, _STAGE_TOTAL, label, status)
            except Exception:
                pass  # Never let progress reporting crash the pipeline

    # Phase-tracking state (populated by step 08d)

    phases_df: Optional[pd.DataFrame] = None
    lap_to_phase: Optional[dict[int, int]] = None

    def _record(step: str, result: Any, error: Optional[str]) -> Any:
        """Book-keep step outcome; return *result* for chaining.

        Automatically picks up the :class:`StepStatus` left by the most
        recent ``_safe_step`` call and feeds it to ``_pipeline_status``.
        """
        global _last_step_status  # noqa: PLW0603
        if error is None:
            summary["steps_ok"].append(step)
        else:
            summary["steps_failed"].append(step)
            summary["errors"][step] = error
        if _last_step_status is not None:
            _pipeline_status.record_step(_last_step_status)
            _last_step_status = None
        return result

    # Column discovery result — populated during Phase 1 (ingest),
    # used lazily at the theoretical engine step.
    _channel_discovery = None

    # Initialise variables used in both Phase 1 and the tail of the function
    raw_df: Optional[pd.DataFrame] = None

    # ── Phase 1 vs Resume branching ────────────────────────
    if resume_from_step8:
        # Resume path: skip stages 1-7, use preloaded intermediate data
        if preloaded_resampled_laps is None:
            logger.error("resume_from_step8=True but no preloaded_resampled_laps")
            return summary
        resampled_laps = preloaded_resampled_laps
        corners = preloaded_corners or []
        track_id = meta.get("track_id", "unknown_track")
        # Reconstruct trimmed_df from resampled laps so that steps 08f-08h
        # (incomplete/anomalous/deviation detection) can run during resume.
        # Without this, trimmed_df=None causes all validation steps to bail.
        if resampled_laps:
            trimmed_df = pd.concat(
                [resampled_laps[k] for k in sorted(resampled_laps.keys())
                 if resampled_laps[k] is not None and not resampled_laps[k].empty],
                ignore_index=True,
            )
        else:
            trimmed_df = None
        summary.update({
            "resampled_laps": resampled_laps,
            "corners": corners,
            "track_id": track_id,
        })
    else:
        # ── Phase 1: Stages 1-7 ──────────────────────────

        # STEP 1 --  Ingest

        #
        io_mod = _import("io_racechrono")

        def _ingest() -> pd.DataFrame:
            # Try adapter registry first (handles all formats).
            try:
                from telemetry_tool.adapters import parse_file as _parse_file
                _df, _adapter = _parse_file(csv_path, progress_cb=progress_callback)
                summary["source_format"] = _adapter.FORMAT_NAME
                summary["available_channels"] = _adapter.available_channels()
                summary["data_tier"] = _adapter.data_tier()
                summary["source_metadata"] = _adapter.metadata()
                return _df
            except (ValueError, ImportError):
                pass

            # Fallback to original RaceChrono reader.
            if io_mod is None:
                raise ImportError("No adapter matched and io_racechrono unavailable")
            return io_mod.read_racechrono_csv(csv_path)

        raw_df, err = _safe_step("01_ingest", _ingest)
        _record("01_ingest", raw_df, err)
        _fire_progress("01_ingest")
        summary["raw_df"] = None  # Not consumed downstream; avoid holding ~8 GB

        if raw_df is None:
            logger.error("Ingest failed --  cannot continue.")
            _pipeline_status.mark_failed()
            _pipeline_status.finalize()
            summary["pipeline"] = _pipeline_status.to_dict()
            return summary

        # -- Adapter compatibility: reverse canonical → RaceChrono names --
        # The adapter registry renames columns to canonical names, but
        # downstream modules still expect raw RaceChrono column names.
        # Reverse-map the essential columns so the pipeline works with both.
        _CANONICAL_TO_RAW: dict[str, str] = {
            "time_s": "Time (s)", "speed_mps": "Speed (m/s)",
            "distance_m": "Distance (m)", "lap_number": "Lap #",
            "lat_deg": "Latitude (deg)", "lon_deg": "Longitude (deg)",
            "altitude_m": "Altitude (m)", "heading_deg": "Bearing (deg)",
            "satellites": "Satellites", "accuracy_m": "Accuracy (m)",
        }
        _reverse = {k: v for k, v in _CANONICAL_TO_RAW.items()
                    if k in raw_df.columns and v not in raw_df.columns}
        if _reverse:
            raw_df = raw_df.rename(columns=_reverse)
            logger.info("Reversed canonical→RaceChrono names: %s", list(_reverse.values()))

        # -- Step: Column discovery --
        # Run discovery on the raw DataFrame to classify channels, detect
        # units, and build the rename map.  The result is stored in the
        # summary for downstream reporting.  Renaming is NOT applied here
        # because upstream modules (gps_filtering, derived_channels,
        # session_trimming, track_detection, resampling, corner_detection)
        # still expect raw RaceChrono column names.  The rename map is
        # applied lazily per-lap at the theoretical engine step.
        try:
            _channel_discovery = discover_columns(raw_df)
            summary["channel_discovery"] = _channel_discovery.to_dict()
            logger.info(
                "Column discovery: %d channels (%d custom), format=%s",
                len(_channel_discovery.channels),
                len(_channel_discovery.custom_channels),
                _channel_discovery.format,
            )
        except Exception as exc:
            logger.warning("Column discovery failed: %s — raw names preserved", exc)

        # STEP 2 --  Filter (GPS quality)

        #
        gps_mod = _import("gps_filtering")

        def _filter() -> pd.DataFrame:
            if gps_mod is None:
                logger.info("GPS filtering skipped (module absent).")
                return raw_df
            return gps_mod.filter_gps_quality(
                raw_df,
                filter_profile=_resolved_filter_profile,
            )

        filtered_df, err = _safe_step("02_filter", _filter)
        _record("02_filter", filtered_df, err)
        _fire_progress("02_filter")
        if filtered_df is None:
            filtered_df = raw_df
        summary["filtered_df"] = None  # Not consumed downstream; avoid holding ~8 GB
        raw_df = None  # Allow GC of ingest DataFrame

        # STEP 2.5 -- Sensor fusion (EKF)
        #
        _fusion_mod = _import("fusion_ekf")

        def _fusion():
            if _fusion_mod is None:
                logger.info("fusion_ekf module absent; skipping sensor fusion.")
                return filtered_df, None
            return _fusion_mod.run_sensor_fusion(filtered_df)

        _fusion_result, err = _safe_step("02b_sensor_fusion", _fusion)
        _record("02b_sensor_fusion", _fusion_result, err)
        _fire_progress("02b_sensor_fusion")
        if _fusion_result is not None:
            filtered_df, _fusion_meta = _fusion_result
            summary["sensor_fusion"] = _fusion_meta.to_dict() if hasattr(_fusion_meta, "to_dict") else _fusion_meta
        else:
            _fusion_meta = None
            summary["sensor_fusion"] = None

        # STEP 3 --  Derived channels

        #
        dc_mod = _import("derived_channels")

        def _derived() -> pd.DataFrame:
            if dc_mod is None:
                logger.info("Derived channels skipped (module absent).")
                return filtered_df

            # Grade quality check + elevation profile
            _grade_status = "grade_unavailable"
            _do_slope_correct = False
            if hasattr(dc_mod, "compute_elevation_profile_with_quality"):
                try:
                    _grade_series, _grade_status = dc_mod.compute_elevation_profile_with_quality(filtered_df)
                    if _grade_status == "grade_used":
                        filtered_df[dc_mod.OUT_GRADE_PCT] = _grade_series.values
                        _do_slope_correct = True
                    elif _grade_status == "grade_low_confidence":
                        filtered_df[dc_mod.OUT_GRADE_PCT] = _grade_series.values
                        # Still compute grade but don't use for correction
                except Exception as _ge:
                    logger.warning("Grade estimation failed: %s", _ge)
            summary["grade_status"] = _grade_status

            df = dc_mod.compute_longitudinal_accel(
                filtered_df, correct_for_slope=_do_slope_correct)
            df = dc_mod.compute_lateral_accel_from_xy(df)
            df = dc_mod.compute_yaw_rate_from_heading(df)
            return df

        enriched_df, err = _safe_step("03_derived_channels", _derived)
        _record("03_derived_channels", enriched_df, err)
        _fire_progress("03_derived_channels")
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
        _fire_progress("04_trim_session")
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
        _fire_progress("05_detect_track")
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
            # Support both RaceChrono raw name and canonical adapter name
            _lap_col_name = _COL_LAP
            if _COL_LAP not in trimmed_df.columns:
                if "lap_number" in trimmed_df.columns:
                    _lap_col_name = "lap_number"
                else:
                    raise PipelineError(f"Column {_COL_LAP!r} missing.")
            lap_col = pd.to_numeric(trimmed_df[_lap_col_name], errors="coerce")
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
        _fire_progress("06_segment_laps")
        summary["lap_dict"] = lap_dict

        if lap_dict is None or len(lap_dict) == 0:
            logger.error("No laps --  returning partial summary.")
            return summary

        # -- Safety net: validate & repair distance data before resampling
        lap_dict = validate_lap_consistency(lap_dict)

        # STEP 6.5 -- Distance integrity preflight
        #
        _di_mod = _import("distance_integrity")

        def _distance_integrity():
            if _di_mod is None:
                logger.info("distance_integrity module absent; skipping preflight.")
                return lap_dict, None
            return _di_mod.run_distance_integrity(lap_dict)

        _di_result, err = _safe_step("06b_distance_integrity", _distance_integrity)
        _record("06b_distance_integrity", _di_result, err)
        _fire_progress("06b_distance_integrity")
        if _di_result is not None:
            lap_dict, _distance_quality = _di_result
            summary["distance_quality"] = _distance_quality.to_dict() if hasattr(_distance_quality, "to_dict") else _distance_quality
        else:
            _distance_quality = None
            summary["distance_quality"] = None

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
        _fire_progress("06b_detect_corners")
        summary["corners"] = corners or []

        # Classify corner types + detect compounds + setup corners
        try:
            if corners and resampled_laps:
                first_key = sorted(resampled_laps.keys())[0]
                if hasattr(corner_mod, "classify_corner_types"):
                    corner_mod.classify_corner_types(corners, resampled_laps[first_key])
                if hasattr(corner_mod, "detect_compound_corners"):
                    compound_groups = corner_mod.detect_compound_corners(corners, resampled_laps[first_key])
                    summary["compound_corners_raw"] = compound_groups
                if hasattr(corner_mod, "identify_setup_corners"):
                    corner_mod.identify_setup_corners(corners, resampled_laps[first_key])
        except Exception:
            logger.debug("Corner taxonomy/compound/setup failed", exc_info=True)

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

        # ── Early return for SaaS split-pipeline (stop after corner detection) ──
        if stop_after_corners:
            layout = None
            if resampled_laps:
                _best_key = sorted(resampled_laps.keys())[0]
                layout = _extract_track_layout_for_picker(
                    resampled_laps[_best_key], corners or []
                )
                if layout and track_id:
                    layout["track_id"] = track_id
            summary["track_layout"] = layout
            summary["resampled_laps"] = resampled_laps
            return summary

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
    _fire_progress("08_compute_metrics")
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

    # -- 08e: Weather timeline (per-lap weather interpolation) --

    weather_timeline: "pd.DataFrame | None" = None

    def _weather_timeline():
        wt_mod = _import("weather_timeline")
        ms_mod = _import("meteo_service")
        if wt_mod is None or ms_mod is None:
            return None

        # Try to get session datetime
        session_dt = wt_mod.parse_session_datetime(csv_path)
        if session_dt is None:
            # Check user-provided datetime from web form
            _dt_str = meta.get("session_datetime") or meta.get("date")
            if _dt_str:
                try:
                    session_dt = datetime.fromisoformat(str(_dt_str))
                except (ValueError, TypeError):
                    pass
        if session_dt is None:
            logger.info("No session datetime available; skipping weather timeline")
            return None

        # Get track coordinates
        _tid = summary.get("track_id")
        if not _tid or not conn:
            return None
        try:
            _track_row = conn.execute(
                "SELECT start_lat, start_lon FROM tracks WHERE track_id = ?",
                (_tid,)
            ).fetchone()
        except Exception:
            _track_row = None
        if not _track_row or not _track_row["start_lat"]:
            return None

        lat, lon = _track_row["start_lat"], _track_row["start_lon"]

        # Fetch hourly weather
        hourly = ms_mod.fetch_historical_weather(
            lat, lon, session_dt.strftime("%Y-%m-%d"),
        )
        if "error" in hourly:
            logger.warning("Weather API error: %s", hourly.get("error"))
            return None

        # Build per-lap timestamps from lap_times
        _lap_ts: list[float] = []
        cumulative = 0.0
        for lt in (summary.get("lap_times") or []):
            _lap_ts.append(cumulative)
            cumulative += lt
        if not _lap_ts:
            return None

        return wt_mod.build_weather_timeline(hourly, _lap_ts, session_dt)

    weather_tl, err = _safe_step("08e_weather_timeline", _weather_timeline)
    _record("08e_weather_timeline", weather_tl, err)
    if weather_tl is not None and not weather_tl.empty:
        weather_timeline = weather_tl
        logger.info("Weather timeline: %d laps enriched", len(weather_tl))
    summary["weather_timeline"] = weather_timeline

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
        # Pass all known-bad laps as exclude set if the function supports it
        # (deviated_lap_set and joker_lap_set aren't populated yet at this point)

        import inspect
        sig = inspect.signature(ref_line_mod.compute_reference_line)
        if "exclude_laps" in sig.parameters:
            _pre_excl = invalid_lap_set | incomplete_lap_set | anomalous_lap_set
            return ref_line_mod.compute_reference_line(
                resampled_laps, exclude_laps=_pre_excl or None,
            )
        return ref_line_mod.compute_reference_line(resampled_laps)

    reference_line, err = _safe_step("09a_reference_line", _reference_line)
    _record("09a_reference_line", reference_line, err)
    _fire_progress("09a_reference_line")
    summary["reference_line"] = reference_line

    # STEP 09a2 -- Track boundaries (after reference line)

    track_boundaries = None

    def _track_boundaries():
        rl_mod = _import("reference_line")
        if rl_mod is None or not hasattr(rl_mod, "estimate_track_boundaries"):
            return None
        if reference_line is None or not resampled_laps:
            return None
        return rl_mod.estimate_track_boundaries(resampled_laps, reference_line)

    track_boundaries, err = _safe_step("09a2_track_boundaries", _track_boundaries)
    _record("09a2_track_boundaries", track_boundaries, err)
    if track_boundaries is not None:
        summary["track_boundaries"] = track_boundaries.to_dict() if hasattr(track_boundaries, "to_dict") else track_boundaries

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

    # ── Build clean data for ALL downstream analysis ──
    # Excluded laps (invalid, incomplete, anomalous, deviated, joker) must
    # not distort scoring, physics models, or data-quality assessment.
    # Every analysis step from here forward uses these filtered structures.
    sorted_keys = sorted(resampled_laps.keys())
    _clean_resampled = {
        k: v for k, v in resampled_laps.items()
        if k not in excluded_laps
    }
    _clean_lap_times = [
        t for k, t in zip(sorted_keys, lap_times)
        if k not in excluded_laps and math.isfinite(t)
    ]
    _clean_lap_metrics = [
        m for m in lap_metrics
        if m.get("lap_number") not in excluded_laps
    ]

    # ── 08i — Recompute consistency & robustness with excluded laps removed ──
    #
    # Steps 08b/08c computed these metrics *before* invalid/incomplete/anomalous
    # laps were identified.  Recompute using only valid lap times so the
    # scoring system receives clean data.

    if excluded_laps:
        logger.info(
            "Excluded %d lap(s) — all downstream analysis uses %d clean laps "
            "(of %d total).",
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
    _fire_progress("09_compute_deltas")
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
        return fric_mod.build_friction_model(_clean_resampled or resampled_laps)

    friction_circle, err = _safe_step("09c_friction_model", _friction)
    _record("09c_friction_model", friction_circle, err)
    summary["friction_model"] = friction_circle

    # -- 09d: Vehicle classification and parameter estimation

    def _vehicle_class() -> Any:
        if veh_mod is None:
            raise ImportError("vehicle_model unavailable")
        if friction_circle is None:
            raise ValueError("No friction model from step 09c")
        return veh_mod.classify_vehicle(
            friction_circle, _clean_lap_metrics or lap_metrics,
        )

    vehicle_params, err = _safe_step("09d_vehicle_model", _vehicle_class)
    _record("09d_vehicle_model", vehicle_params, err)

    # Apply user vehicle overrides if provided
    if vehicle_params is not None and vehicle_overrides:
        _vo = vehicle_overrides
        if _vo.get("mass_kg") is not None:
            vehicle_params.estimated_mass_kg = float(_vo["mass_kg"])
            vehicle_params.classification_reasons.append("mass overridden by user")
            logger.info("Vehicle mass overridden: %.1f kg", _vo["mass_kg"])
        if _vo.get("power_kw") is not None:
            logger.info("Vehicle power override noted: %.1f kW", _vo["power_kw"])
        if _vo.get("drag_model") is not None:
            logger.info("Drag model override: %s", _vo["drag_model"])

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
        _fc = -1.0
        _sf = summary.get("sensor_fusion")
        if isinstance(_sf, dict):
            _fc = _sf.get("confidence", -1.0)
        return dq_mod.score_data_quality(
            _clean_resampled or resampled_laps,
            _clean_lap_times or lap_times,
            fusion_confidence=_fc,
        )

    data_quality_rpt, err = _safe_step("09e_data_quality", _data_quality)
    _record("09e_data_quality", data_quality_rpt, err)
    summary["data_quality"] = data_quality_rpt

    # -- 09f: Progressive physics analysis (tier 2+) --

    _data_tier = summary.get("data_tier", 1)
    _progressive_physics: dict[str, Any] = {}

    def _progressive_physics_step() -> dict[str, Any]:
        results: dict[str, Any] = {}
        _laps_to_analyze = _clean_resampled or resampled_laps
        _corners = summary.get("corners") or []

        if _data_tier >= 2 and _laps_to_analyze:
            try:
                from telemetry_tool.physics import controls_physics
                per_lap_controls: dict[int, list[dict]] = {}
                for ln in sorted(_laps_to_analyze.keys()):
                    lap_df = _laps_to_analyze[ln]
                    analysis = controls_physics.analyze_corners_with_controls(
                        lap_df, _corners,
                    )
                    per_lap_controls[ln] = analysis
                results["controls_analysis"] = per_lap_controls
                logger.info(
                    "Tier 2 controls physics: analysed %d laps.",
                    len(per_lap_controls),
                )
            except Exception as _cp_exc:
                logger.warning("Controls physics failed: %s", _cp_exc)

        if _data_tier >= 3 and _laps_to_analyze:
            # Tire thermal analysis
            try:
                from telemetry_tool.physics import tire_thermal
                tire_result = tire_thermal.analyze_tire_session(
                    _laps_to_analyze, _corners,
                )
                results["tire_thermal"] = tire_result
                logger.info("Tier 3 tire thermal analysis complete.")
            except Exception as _tt_exc:
                logger.warning("Tire thermal analysis failed: %s", _tt_exc)

            # Wheel slip analysis
            try:
                from telemetry_tool.physics import slip_model
                slip_result = slip_model.analyze_slip_session(
                    _laps_to_analyze, _corners,
                )
                results["slip_analysis"] = slip_result
                logger.info("Tier 3 slip analysis complete.")
            except Exception as _sl_exc:
                logger.warning("Slip analysis failed: %s", _sl_exc)

            # Fuel analysis
            try:
                from telemetry_tool.physics import fuel_model
                _fuel_levels = []
                for ln in sorted(_laps_to_analyze.keys()):
                    _ldf = _laps_to_analyze[ln]
                    for _fc in ("fuel_kg", "fuel_remaining_kg", "FuelLevel"):
                        if _fc in _ldf.columns and _ldf[_fc].notna().any():
                            _fuel_levels.append(float(_ldf[_fc].iloc[-1]))
                            break
                if _fuel_levels and len(_fuel_levels) >= 2:
                    fuel_result = fuel_model.analyze_fuel_session(
                        lap_times[:len(_fuel_levels)], _fuel_levels,
                    )
                    results["fuel_analysis"] = fuel_result
                    logger.info("Tier 3 fuel analysis complete.")
            except Exception as _fu_exc:
                logger.warning("Fuel analysis failed: %s", _fu_exc)

        return results

    _progressive_physics, err = _safe_step(
        "09f_progressive_physics", _progressive_physics_step,
    )
    _record("09f_progressive_physics", _progressive_physics, err)
    summary["progressive_physics"] = _progressive_physics or {}

    # ====================================================================
    # STEP 09g -- Traffic detection + Lap inclusion policy
    # ====================================================================

    _td_mod = _import("traffic_detection")
    _li_mod = _import("lap_inclusion")

    def _traffic_and_inclusion():
        _traffic_result_inner = None
        _inclusion_policy_inner = None

        if _td_mod is not None and resampled_laps:
            _traffic_result_inner = _td_mod.run_traffic_detection(
                resampled_laps, summary.get("corners"),
            )

        if _li_mod is not None:
            if _traffic_result_inner is not None:
                _inclusion_policy_inner = _li_mod.build_inclusion_policy(
                    resampled_laps,
                    lap_times,
                    _traffic_result_inner,
                    distance_quality=summary.get("distance_quality"),
                )
            else:
                from traffic_detection import TrafficResult
                empty_traffic = TrafficResult([], [], {k: 0.0 for k in resampled_laps}, 0)
                _inclusion_policy_inner = _li_mod.build_inclusion_policy(
                    resampled_laps, lap_times, empty_traffic,
                    distance_quality=summary.get("distance_quality"),
                )

        return _traffic_result_inner, _inclusion_policy_inner

    _traffic_incl, err = _safe_step("09g_traffic_inclusion", _traffic_and_inclusion)
    _record("09g_traffic_inclusion", _traffic_incl, err)
    _fire_progress("09g_traffic_inclusion")

    _traffic_result = None
    _inclusion_policy = None
    if _traffic_incl is not None:
        _traffic_result, _inclusion_policy = _traffic_incl
    if _traffic_result is not None:
        summary["traffic"] = _traffic_result.to_dict()
    else:
        summary["traffic"] = None
    if _inclusion_policy is not None:
        summary["lap_inclusion"] = _inclusion_policy.to_dict()
    else:
        summary["lap_inclusion"] = None

    # ====================================================================
    # STEP 09h -- Condition clustering
    # ====================================================================

    _cc_mod = _import("condition_clustering")
    _clustering_result = None

    def _condition_clustering():
        if _cc_mod is None or not resampled_laps:
            return None
        _traffic_scores = {}
        if _traffic_result is not None:
            _traffic_scores = _traffic_result.per_lap_score
        _learning = None
        if _inclusion_policy is not None:
            _learning = _inclusion_policy.learning_laps
        return _cc_mod.cluster_laps(
            resampled_laps, lap_times, _traffic_scores,
            learning_laps=_learning,
        )

    _clustering_raw, err = _safe_step("09h_condition_clustering", _condition_clustering)
    _record("09h_condition_clustering", _clustering_raw, err)
    _fire_progress("09h_condition_clustering")

    if _clustering_raw is not None:
        _clustering_result = _clustering_raw
        summary["clustering"] = _clustering_result.to_dict()
    else:
        summary["clustering"] = None

    # ====================================================================
    # STEP 09i -- Grip map + friction envelope
    # ====================================================================

    _gm_mod = _import("grip_map")
    _fe_mod = _import("friction_envelope")
    _grip_map = None
    _friction_envelope_result = None

    def _compute_grip_map():
        if _gm_mod is None or not resampled_laps:
            return None
        _learning = None
        if _inclusion_policy is not None:
            _learning = _inclusion_policy.learning_laps
        return _gm_mod.compute_grip_map(
            resampled_laps,
            curvature_profile=curvature_profile,
            learning_laps=_learning,
        )

    _grip_raw, err = _safe_step("09i_grip_map", _compute_grip_map)
    _record("09i_grip_map", _grip_raw, err)
    _fire_progress("09i_grip_map")

    if _grip_raw is not None:
        _grip_map = _grip_raw
        summary["grip_map"] = _grip_map.to_dict()
    else:
        summary["grip_map"] = None

    def _compute_friction_envelope():
        if _fe_mod is None or not resampled_laps:
            return None
        _learning = None
        if _inclusion_policy is not None:
            _learning = _inclusion_policy.learning_laps
        return _fe_mod.compute_friction_envelope(
            resampled_laps,
            learning_laps=_learning,
        )

    _fe_raw, err = _safe_step("09i_friction_envelope", _compute_friction_envelope)
    _record("09i_friction_envelope", _fe_raw, err)

    if _fe_raw is not None:
        _friction_envelope_result = _fe_raw
        summary["friction_envelope"] = _friction_envelope_result.to_dict()
    else:
        summary["friction_envelope"] = None

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
    _corner_coaching: list[dict[str, Any]] | None = None
    _delta_map: pd.DataFrame | None = None
    _session_scalars: dict[str, Any] | None = None

    _laps_for_theo_ref = [None]  # mutable container to capture laps_for_theo from nested function

    def _theoretical() -> pd.DataFrame:
        nonlocal _sim_method, _sim_result
        nonlocal _corner_coaching, _delta_map, _session_scalars

        # Best driver time for sanity checking

        best_driver_time = float("inf")
        if valid_times:
            best_driver_time = min(t for _, t in valid_times)

        # -- Priority 0: kart_envelope solver via adapter --
        try:
            from theoretical_adapter import compute_theoretical_via_envelope
            adapter_result = compute_theoretical_via_envelope(
                resampled_laps,
                curvature_profile,
                vehicle_params,
                data_quality_rpt,
                best_driver_time_s=(
                    best_driver_time
                    if math.isfinite(best_driver_time) else None
                ),
            )
            _sim_method = adapter_result.method
            _sim_result = adapter_result.theoretical_result
            _corner_coaching = adapter_result.corner_coaching
            _delta_map = adapter_result.delta_map
            if adapter_result.session_scalars is not None:
                sc = adapter_result.session_scalars
                _session_scalars = {
                    "mu": round(sc.mu_session, 4),
                    "p": round(sc.p_session, 4),
                    "b": round(sc.b_session, 4),
                    "confidence": round(sc.confidence, 4),
                    "condition_label": sc.condition_label,
                }
            logger.info(
                "kart_envelope solver [%s]: %.2fs (driver best %.2fs).",
                adapter_result.method,
                adapter_result.theoretical_result.lap_time_s
                if adapter_result.theoretical_result else float("nan"),
                best_driver_time,
            )
            return adapter_result.theoretical_df
        except Exception as exc:
            logger.warning(
                "kart_envelope adapter failed: %s — falling back to "
                "legacy engines.", exc,
            )

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
                    grip_map=_grip_map,
                    friction_envelope=_friction_envelope_result,
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
            if _channel_discovery is not None:
                laps_list = [
                    apply_discovery(resampled_laps[k], _channel_discovery)
                    for k in sorted_keys
                ]
            else:
                laps_list = [resampled_laps[k] for k in sorted_keys]

            # Pre-filter to best-N% laps if available (tighter envelope).
            # Also exclude any laps flagged after best-N% was computed
            # (incomplete, anomalous, deviated, joker) for consistency.

            if best_n_lap_indices:
                laps_for_theo = [laps_list[i] for i in best_n_lap_indices
                                 if i < len(laps_list)
                                 and sorted_keys[i] not in excluded_laps]
                keys_for_theo = [sorted_keys[i] for i in best_n_lap_indices
                                 if i < len(sorted_keys)
                                 and sorted_keys[i] not in excluded_laps]
                logger.info(
                    "Theoretical envelope: using %d best-N%% laps "
                    "(out of %d total).",
                    len(laps_for_theo), len(laps_list),
                )
            else:
                laps_for_theo = laps_list
                keys_for_theo = sorted_keys

            # Filter by inclusion policy (if available)
            if _inclusion_policy is not None and hasattr(_inclusion_policy, 'learning_laps'):
                _learning_set = set(_inclusion_policy.learning_laps)
                _filtered = [
                    (lap, key) for lap, key in zip(laps_for_theo, keys_for_theo)
                    if key in _learning_set
                ]
                if len(_filtered) >= 3:
                    laps_for_theo = [x[0] for x in _filtered]
                    keys_for_theo = [x[1] for x in _filtered]
                    logger.info(
                        "Theoretical envelope: filtered to %d learning laps "
                        "(excluded %d by inclusion policy).",
                        len(laps_for_theo),
                        len(sorted_keys) - len(laps_for_theo),
                    )
                else:
                    logger.warning(
                        "Inclusion policy leaves only %d laps — using all %d.",
                        len(_filtered), len(laps_for_theo),
                    )

            # Filter by selected cluster (if available)
            if _clustering_result is not None and not _clustering_result.fallback:
                _selected = [
                    c for c in _clustering_result.clusters
                    if c.cluster_id == _clustering_result.selected_cluster_id
                ]
                if _selected:
                    _cluster_laps = set(_selected[0].lap_numbers)
                    _cluster_filtered = [
                        (lap, key) for lap, key in zip(laps_for_theo, keys_for_theo)
                        if key in _cluster_laps
                    ]
                    if len(_cluster_filtered) >= 3:
                        laps_for_theo = [x[0] for x in _cluster_filtered]
                        keys_for_theo = [x[1] for x in _cluster_filtered]
                        logger.info(
                            "Theoretical envelope: filtered to %d laps from "
                            "cluster %d (purity=%.2f).",
                            len(laps_for_theo),
                            _clustering_result.selected_cluster_id,
                            _clustering_result.purity_score,
                        )
                    else:
                        logger.warning(
                            "Cluster filtering leaves only %d laps — "
                            "using all %d learning laps.",
                            len(_cluster_filtered), len(laps_for_theo),
                        )

            # Adaptive percentile from data quality

            speed_pct = 98.0
            accel_pct = 99.0
            if data_quality_rpt is not None:
                speed_pct = data_quality_rpt.recommended_speed_percentile
                accel_pct = data_quality_rpt.recommended_accel_percentile

            # Traffic masks from inclusion policy (if available)
            _traffic_masks = (
                _inclusion_policy.traffic_masks
                if _inclusion_policy is not None
                   and hasattr(_inclusion_policy, 'traffic_masks')
                else None
            )

            # Use phase-aware version if available

            if hasattr(theo_mod, 'build_theoretical_lap_phase_aware') and phases_df is not None:
                _sim_method = "percentile_envelope_phase_aware"
                _laps_for_theo_ref[0] = laps_for_theo
                return theo_mod.build_theoretical_lap_phase_aware(
                    laps_for_theo, phases_df=phases_df,
                    lap_to_phase=lap_to_phase,
                    n_points=n_resample_points,
                    lap_keys=keys_for_theo,
                    speed_percentile=speed_pct,
                    accel_percentile=accel_pct,
                    masks=_traffic_masks,
                )

            _sim_method = "percentile_envelope"
            _laps_for_theo_ref[0] = laps_for_theo
            # Try adaptive percentile first, fall back to default

            try:
                return theo_mod.build_theoretical_lap(
                    laps_for_theo, n_points=n_resample_points,
                    speed_percentile=speed_pct,
                    accel_percentile=accel_pct,
                    masks=_traffic_masks,
                )
            except TypeError:
                # Older theoretical_engine without percentile/masks kwargs

                return theo_mod.build_theoretical_lap(
                    laps_for_theo, n_points=n_resample_points,
                )

        raise ImportError(
            "No simulation method available: both lap_simulation and "
            "theoretical_engine are unavailable."
        )

    # Gate: skip theoretical if distance quality is degraded
    if _distance_quality is not None and hasattr(_distance_quality, 'gate_advanced') and _distance_quality.gate_advanced:
        logger.warning("Theoretical lap SKIPPED: distance quality gate active (status=%s).",
                       getattr(_distance_quality, 'status', 'unknown'))
        theoretical_lap = None
        err = "distance_quality_gate"
        _record("10_theoretical", None, err)
        _fire_progress("10_theoretical")
        summary["theoretical_lap"] = None
    else:
        theoretical_lap, err = _safe_step("10_theoretical", _theoretical)
        _record("10_theoretical", theoretical_lap, err)
        _fire_progress("10_theoretical")
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

    # ── 10b-i½: Theoretical plausibility cross-validation ──
    _plausibility = None

    def _compute_plausibility():
        if theoretical_lap is None or theo_mod is None:
            return None
        if not hasattr(theo_mod, "split_laps_train_holdout"):
            return None
        if not hasattr(theo_mod, "compute_theoretical_plausibility"):
            return None

        _laps = _laps_for_theo_ref[0]
        if _laps is None or len(_laps) < 4:
            return None

        _, holdout, _ = theo_mod.split_laps_train_holdout(_laps)
        if not holdout:
            return None

        return theo_mod.compute_theoretical_plausibility(
            theoretical_lap, holdout,
        )

    _plausibility, err = _safe_step("10b_plausibility", _compute_plausibility)
    _record("10b_plausibility", _plausibility, err)

    if _plausibility is not None and theo_metrics is not None:
        theo_metrics["plausibility"] = _plausibility.to_dict()
        summary["theoretical_metrics"] = theo_metrics

    # ── 10b-ii: Attach confidence assessment ──
    _conf_mod = _import("confidence")

    def _compute_confidence():
        if _conf_mod is None:
            return None

        # Gather inputs
        n_learn = 0
        if _inclusion_policy is not None:
            n_learn = len(_inclusion_policy.learning_laps)
        else:
            n_learn = len(resampled_laps)

        dq_conf = 0.5
        if data_quality_rpt is not None:
            dq_conf = data_quality_rpt.overall_confidence

        dist_status = "good"
        dq = summary.get("distance_quality")
        if dq and isinstance(dq, dict):
            dist_status = dq.get("status", "good")
        elif _distance_quality is not None and hasattr(_distance_quality, 'status'):
            dist_status = _distance_quality.status

        c_purity = 1.0
        if _clustering_result is not None:
            c_purity = _clustering_result.purity_score

        # Channel coverage from data quality or compute
        ch_cov = 0.5
        if data_quality_rpt is not None:
            # Use accel_quality as proxy for coverage
            ch_cov = max(data_quality_rpt.gps_quality, data_quality_rpt.accel_quality)

        solver = _sim_method or "percentile_envelope"

        curv_rel = 0.5
        cq = summary.get("curvature_quality")
        if cq and isinstance(cq, dict):
            curv_rel = cq.get("quality_score", 0.5)

        fuse_conf = -1.0
        sf = summary.get("sensor_fusion")
        if sf and isinstance(sf, dict):
            fuse_conf = sf.get("confidence", -1.0)

        return _conf_mod.compute_confidence(
            n_learning_laps=n_learn,
            data_quality_confidence=dq_conf,
            distance_quality_status=dist_status,
            cluster_purity=c_purity,
            channel_coverage=ch_cov,
            solver_method=solver,
            curvature_reliability=curv_rel,
            fusion_confidence=fuse_conf,
        )

    _confidence, err = _safe_step("10b_confidence", _compute_confidence)
    _record("10b_confidence", _confidence, err)

    if _confidence is not None and theo_metrics is not None:
        conf_dict = _confidence.to_dict()
        # Inject plausibility penalty if overfit suspected
        if _plausibility is not None and _plausibility.overfit_suspected:
            reasons = conf_dict.get("confidence_reasons", [])
            reasons.insert(0, "overfit_suspected: theoretical may be unreachable")
            conf_dict["confidence_reasons"] = reasons
            # Apply penalty
            raw_score = conf_dict.get("confidence_score", 100)
            penalized = int(raw_score * _plausibility.plausibility_score)
            conf_dict["confidence_score"] = max(0, penalized)
            # Recompute level
            if penalized >= 75:
                conf_dict["confidence_level"] = "high"
            elif penalized >= 45:
                conf_dict["confidence_level"] = "medium"
            else:
                conf_dict["confidence_level"] = "low"
        theo_metrics["confidence"] = conf_dict
        summary["theoretical_metrics"] = theo_metrics

    # ── 10b-iii: Unified optimal solver (feature flag) ──
    _opt_mod = _import("optimal_solver")

    def _compute_optimal_v2():
        import os as _os
        if _opt_mod is None:
            return None
        if _os.environ.get("OPTIMAL_V2", "0") not in ("1", "true", "yes"):
            return None
        if theoretical_lap is None:
            return None

        # Build OptimalCaps from whichever path produced the theoretical lap
        caps = None

        # Try percentile envelope caps (most common path)
        if theo_mod is not None and resampled_laps:
            try:
                curv_arr = np.zeros(len(theoretical_lap))
                if curvature_profile is not None and "curvature_1pm" in curvature_profile.columns:
                    cp_dist = curvature_profile["distance_m"].values
                    cp_curv = curvature_profile["curvature_1pm"].values
                    theo_dist = theoretical_lap["distance_m"].values
                    curv_arr = np.interp(theo_dist, cp_dist, cp_curv)

                laps_list = [resampled_laps[k] for k in sorted(resampled_laps.keys())]
                if hasattr(theo_mod, "caps_from_percentile_envelope"):
                    caps = theo_mod.caps_from_percentile_envelope(
                        laps_list, curv_arr,
                        speed_percentile=speed_pct,
                    )
            except Exception as exc:
                logger.debug("caps_from_percentile_envelope failed: %s", exc)

        if caps is None:
            return None

        # Apply grip map override
        if _grip_map is not None and not _grip_map.is_global_fallback and caps.mu is None:
            mu_arr = np.array([
                _grip_map.mu_at(float(d), "p95") for d in caps.distance_m
            ])
            caps.mu = mu_arr

        # Try solve with uncertainty bands first
        result_with_bands = None
        if hasattr(theo_mod, "caps_from_percentile_envelope_with_bands"):
            try:
                caps_nom, caps_low, caps_high = theo_mod.caps_from_percentile_envelope_with_bands(
                    laps_list, curv_arr,
                    speed_percentile=speed_pct,
                )
                # Apply grip map to all three
                for c in (caps_nom, caps_low, caps_high):
                    if _grip_map is not None and not _grip_map.is_global_fallback and c.mu is None:
                        c.mu = np.array([
                            _grip_map.mu_at(float(d), "p95") for d in c.distance_m
                        ])
                result_with_bands = _opt_mod.solve_optimal_speed_with_bands(
                    caps_nom, caps_low, caps_high,
                )
            except Exception as exc:
                logger.debug("solve_optimal_speed_with_bands failed: %s", exc)

        if result_with_bands is not None:
            return result_with_bands

        return _opt_mod.solve_optimal_speed(caps)

    _optimal_result, err = _safe_step("10b_optimal_v2", _compute_optimal_v2)
    _record("10b_optimal_v2", _optimal_result, err)

    if _optimal_result is not None:
        summary["optimal_v2"] = _optimal_result.to_dict()

        # Corner saturation
        if corners and hasattr(_opt_mod, "compute_corner_saturation"):
            try:
                corner_dicts = [c if isinstance(c, dict) else c.to_dict()
                                for c in corners]
                sats = _opt_mod.compute_corner_saturation(_optimal_result, corner_dicts)
                summary["optimal_v2"]["corner_saturation"] = [s.to_dict() for s in sats]
            except Exception:
                logger.debug("Corner saturation failed", exc_info=True)

        # Corner coaching labels
        _ca_mod = _import("corner_analysis")
        if _ca_mod is not None and corners and hasattr(_ca_mod, "compute_corner_coaching_labels"):
            try:
                corner_dicts = [c if isinstance(c, dict) else c.to_dict()
                                for c in corners]
                coaching_labels = _ca_mod.compute_corner_coaching_labels(
                    corners=corner_dicts,
                    limiting_factors=_optimal_result.limiting_factor,
                    distance_m=_optimal_result.distance_m,
                    lap_length_m=float(_optimal_result.distance_m[-1]),
                )
                summary["optimal_v2"]["corner_coaching_labels"] = coaching_labels
            except Exception:
                logger.debug("Corner coaching labels failed", exc_info=True)

    summary["corner_coaching"] = _corner_coaching
    summary["delta_map"] = _delta_map
    summary["session_scalars"] = _session_scalars

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

    # If kart_envelope didn't provide corner coaching (Priority 0 failed)
    # but step 10c produced corner performances, use those as corner
    # coaching data so insert_theoretical_data persists them to the DB.
    if _corner_coaching is None and corner_performances:
        summary["corner_coaching"] = corner_performances

    # -- 10c-ii: Corner Timeline detection (event-based) --

    corner_timelines: list[dict[str, Any]] = []

    def _corner_timelines():
        ca_mod = _import("corner_analysis")
        if ca_mod is None or not hasattr(ca_mod, "detect_corner_events"):
            return None
        if not corners or best_lap_df is None:
            return None

        dq = summary.get("data_quality")
        dq_score = getattr(dq, "overall_confidence", 1.0) if dq else 1.0

        theo_df = None
        theo_result = summary.get("theoretical_lap")
        if theo_result is not None and isinstance(theo_result, pd.DataFrame):
            theo_df = theo_result

        timelines = []
        for c in corners:
            try:
                tl = ca_mod.detect_corner_events(c, best_lap_df, theo_df, dq_score)
                if theo_df is not None and hasattr(ca_mod, "compute_segment_losses"):
                    ca_mod.compute_segment_losses(tl, best_lap_df, theo_df)
                if hasattr(ca_mod, "detect_corner_mistakes"):
                    tl.mistakes = ca_mod.detect_corner_mistakes(tl, best_lap_df, c)
                timelines.append(tl)
            except Exception:
                logger.debug("Corner timeline failed for corner %s", c.get("corner_id"), exc_info=True)

        # Multi-lap stability
        if hasattr(ca_mod, "compute_event_stability") and resampled_laps:
            all_dfs = [
                resampled_laps[k] for k in sorted(resampled_laps.keys())
                if k not in excluded_laps and resampled_laps[k] is not None and len(resampled_laps[k]) >= 10
            ]
            if len(all_dfs) >= 3:
                try:
                    stability = ca_mod.compute_event_stability(corners, all_dfs, dq_score)
                    for tl in timelines:
                        cid_stab = stability.get(tl.corner_id, {})
                        tl.mrp_stability_std_m = cid_stab.get("MRP", 0.0)
                        tl.event_stability = cid_stab
                except Exception:
                    logger.debug("Event stability failed", exc_info=True)

        return [tl.to_dict() for tl in timelines]

    tl_result, tl_err = _safe_step("10c_corner_timelines", _corner_timelines)
    _record("10c_corner_timelines", tl_result, tl_err)
    if tl_result is not None:
        corner_timelines = tl_result
        logger.info("Corner timelines: %d corners with events", len(tl_result))
    summary["corner_timelines"] = corner_timelines

    # -- 10c-iii: Advanced corner intelligence --

    def _advanced_corner_intelligence():
        ca_mod = _import("corner_analysis")
        feat_mod = _import("features")
        if ca_mod is None:
            return None
        if not corner_timelines or best_lap_df is None:
            return None

        dq = summary.get("data_quality")
        dq_score = getattr(dq, "overall_confidence", 1.0) if dq else 1.0

        result = {}

        # Rebuild CornerTimeline objects from dicts for functions that need them
        tl_objects = []
        for tl_dict in corner_timelines:
            events = []
            for ed in tl_dict.get("events", []):
                events.append(ca_mod.CornerEvent(
                    ed["event_type"], ed["s_position"], ed["confidence"],
                    ed["source_channel"], ed["value"], ed["available"],
                ))
            tl_obj = ca_mod.CornerTimeline(
                corner_id=tl_dict["corner_id"], events=events,
                segment_losses_s=tl_dict.get("segment_losses_s", {}),
                segment_confidences=tl_dict.get("segment_confidences", {}),
                mistakes=tl_dict.get("mistakes", []),
                mrp_strength=tl_dict.get("mrp_strength", 0),
                mrp_stability_std_m=tl_dict.get("mrp_stability_std_m", 0),
                event_stability=tl_dict.get("event_stability", {}),
            )
            tl_objects.append(tl_obj)

        # Brake release + coupling per corner
        brake_release_data = []
        coupling_data = []
        for tl_obj, c in zip(tl_objects, corners):
            try:
                if hasattr(ca_mod, "compute_brake_release_metrics"):
                    br = ca_mod.compute_brake_release_metrics(tl_obj, best_lap_df, c, dq_score)
                    if br is not None:
                        brake_release_data.append({"corner_id": c.get("corner_id"), **br.to_dict()})
            except Exception:
                pass
            try:
                if hasattr(ca_mod, "compute_brake_yaw_coupling"):
                    coup = ca_mod.compute_brake_yaw_coupling(tl_obj, best_lap_df, c, dq_score)
                    if coup is not None:
                        coupling_data.append({"corner_id": c.get("corner_id"), **coup.to_dict()})
            except Exception:
                pass

        result["brake_release"] = brake_release_data
        result["brake_yaw_coupling"] = coupling_data

        # Corner targets (needs theoretical)
        theo_df = summary.get("theoretical_lap")
        if theo_df is not None and isinstance(theo_df, pd.DataFrame) and hasattr(ca_mod, "compute_corner_targets"):
            targets_data = []
            for tl_obj, c in zip(tl_objects, corners):
                try:
                    theo_tl = ca_mod.detect_corner_events(c, theo_df, data_quality=dq_score)
                    tgt = ca_mod.compute_corner_targets(c, tl_obj, theo_tl, theo_df, best_lap_df, dq_score)
                    if tgt is not None:
                        if hasattr(ca_mod, "validate_corner_targets"):
                            ca_mod.validate_corner_targets(tgt, c)
                        targets_data.append(tgt.to_dict())
                except Exception:
                    pass
            result["corner_targets"] = targets_data

        # Compound metrics
        compound_groups = summary.get("compound_corners_raw", [])
        if compound_groups and corner_performances and hasattr(ca_mod, "compute_compound_metrics"):
            # Rebuild CornerPerformance objects
            perf_objs = []
            for cp in corner_performances:
                if isinstance(cp, dict):
                    perf_objs.append(ca_mod.CornerPerformance(
                        corner_id=cp.get("corner_id", 0),
                        s_start=cp.get("s_start", 0),
                        s_end=cp.get("s_end", 0),
                        time_loss_s=cp.get("time_loss_s", 0),
                    ))
                else:
                    perf_objs.append(cp)

            compound_data = []
            for cg in compound_groups:
                try:
                    cm = ca_mod.compute_compound_metrics(cg, perf_objs, corners)
                    if cm is not None:
                        compound_data.append(cm.to_dict())
                except Exception:
                    pass
            result["compound_metrics"] = compound_data

        # Risk scores
        if hasattr(ca_mod, "compute_corner_risk") and resampled_laps:
            all_dfs = [
                resampled_laps[k] for k in sorted(resampled_laps.keys())
                if k not in excluded_laps and resampled_laps[k] is not None and len(resampled_laps[k]) >= 10
            ]
            risk_data = []
            for tl_obj, c in zip(tl_objects, corners):
                try:
                    risk = ca_mod.compute_corner_risk(tl_obj, all_dfs, c, dq_score)
                    risk_data.append(risk.to_dict())
                except Exception:
                    pass
            result["corner_risk_scores"] = risk_data

        # Driver style
        if feat_mod is not None and hasattr(feat_mod, "compute_driver_style"):
            try:
                style = feat_mod.compute_driver_style(corner_performances, data_quality=dq_score)
                result["driver_style"] = style.to_dict()
            except Exception:
                pass

        return result

    aci_result, aci_err = _safe_step("10c_advanced_corner_intelligence", _advanced_corner_intelligence)
    _record("10c_advanced_corner_intelligence", aci_result, aci_err)
    if aci_result is not None:
        summary["advanced_corner_intelligence"] = aci_result
        logger.info("Advanced corner intelligence computed")

    # STEP 10e -- Endurance analytics

    def _endurance_analytics():
        sa_mod = _import("stint_analysis")
        if sa_mod is None or not hasattr(sa_mod, "generate_team_coaching"):
            return None
        result = {}
        stint_data = summary.get("stint_analysis", {})
        stint_metrics = stint_data.get("stint_metrics", []) if isinstance(stint_data, dict) else []
        if stint_metrics:
            team_coaching = sa_mod.generate_team_coaching(stint_metrics)
            result["team_coaching"] = team_coaching
        return result if result else None

    endurance_result, err = _safe_step("10e_endurance", _endurance_analytics)
    _record("10e_endurance", endurance_result, err)
    if endurance_result is not None:
        summary["endurance"] = endurance_result

    # STEP 10f -- Raceline optimizer (gated by enable_raceline_optimizer)

    _enable_raceline = config.get("enable_raceline_optimizer", False) if config else False
    if _enable_raceline and track_boundaries is not None and reference_line is not None:
        def _raceline_optimize():
            rl_mod = _import("raceline_optimizer")
            if rl_mod is None:
                return None
            ref_dict = {
                "distance_m": reference_line[_COL_DIST].values if isinstance(reference_line, pd.DataFrame) else np.array([]),
                "curvature": curvature_profile.get("curvature", np.array([])) if isinstance(curvature_profile, dict) else np.array([]),
            }
            bounds_dict = track_boundaries.to_dict() if hasattr(track_boundaries, "to_dict") else track_boundaries
            _friction_val = corrected_friction if corrected_friction else 1.2
            friction = {"mu": _friction_val if isinstance(_friction_val, (int, float)) else 1.2}
            return rl_mod.optimize_corner_lines(
                corners or [], ref_dict, bounds_dict, friction,
            )

        raceline_result, err = _safe_step("10f_raceline", _raceline_optimize)
        _record("10f_raceline", raceline_result, err)
        if raceline_result is not None:
            summary["raceline_optimization"] = raceline_result.to_dict() if hasattr(raceline_result, "to_dict") else raceline_result

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
    _fire_progress("11_build_features")
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
                weather_timeline=weather_timeline,
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
            corner_coaching=_corner_coaching,
            progressive_physics=summary.get("progressive_physics"),
        )

    score_result, err = _safe_step("13_score_session", _score)
    _record("13_score_session", score_result, err)
    _fire_progress("13_score_session")
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

    if _distance_quality is not None and hasattr(_distance_quality, 'gate_advanced') and _distance_quality.gate_advanced:
        logger.warning("Coaching guide SKIPPED: distance quality gate active.")
        cg_result = None
        _record("13b_coaching_guide", None, "distance_quality_gate")
    else:
        cg_result, err = _safe_step("13b_coaching_guide", _coaching_guide)
        _record("13b_coaching_guide", cg_result, err)
    if cg_result:
        coaching_guide = cg_result
        n_focus = len(cg_result.get("focus_areas", []))
        logger.info("Coaching guide: %d focus areas", n_focus)
    summary["coaching_guide"] = coaching_guide

    # STEP 13c -- Coaching V2 (evidence-based, confidence-gated)

    def _coaching_v2():
        ca_mod = _import("corner_analysis")
        if ca_mod is None or not hasattr(ca_mod, "generate_coaching_v2"):
            return None
        if not corner_performances:
            return None
        return ca_mod.generate_coaching_v2(
            corner_performances,
            corner_timelines=corner_timelines,
            corners=corners,
            data_quality=dq_score,
        )

    # Gate on distance quality (same as coaching_guide)
    if _distance_quality is not None and hasattr(_distance_quality, 'gate_advanced') and _distance_quality.gate_advanced:
        _record("13c_coaching_v2", None, "distance_quality_gate")
    else:
        cv2_result, err = _safe_step("13c_coaching_v2", _coaching_v2)
        _record("13c_coaching_v2", cv2_result, err)
        if cv2_result is not None:
            summary["coaching_v2"] = cv2_result.to_dict() if hasattr(cv2_result, "to_dict") else cv2_result

    # STEP 13d -- Drills + practice plan

    def _practice_plan():
        drills_mod = _import("drills")
        if drills_mod is None or not hasattr(drills_mod, "generate_practice_plan"):
            return None
        cv2 = summary.get("coaching_v2")
        if not cv2:
            return None
        available_channels = list(enriched_df.columns) if enriched_df is not None else []
        return drills_mod.generate_practice_plan(cv2, available_channels)

    plan_result, err = _safe_step("13d_practice_plan", _practice_plan)
    _record("13d_practice_plan", plan_result, err)
    if plan_result is not None:
        plan_dict = plan_result.to_dict() if hasattr(plan_result, "to_dict") else plan_result
        prov = summary.get("provenance", {})
        if prov:
            plan_dict["provenance_ref"] = {
                "analysis_run_id": prov.get("analysis_run_id"),
                "pipeline_version": prov.get("pipeline_version"),
            }
        summary["practice_plan"] = plan_dict

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

        # Enrich corner_performances with advanced intelligence data for HTML report
        _enriched_corner_perfs = corner_performances
        if corner_performances and corners:
            try:
                aci = summary.get("advanced_corner_intelligence", {})
                risk_scores = aci.get("corner_risk_scores", [])
                risk_map = {r.get("corner_id"): r.get("risk_index", 0) for r in risk_scores}
                tl_data = summary.get("corner_timelines", [])
                tl_map = {t.get("corner_id") if isinstance(t, dict) else getattr(t, "corner_id", None): t for t in tl_data}
                corner_type_map = {c.get("corner_id", i): c.get("corner_type", "") for i, c in enumerate(corners)}
                compound_map = {c.get("corner_id", i): c.get("compound_id") for i, c in enumerate(corners)}
                setup_map = {c.get("corner_id", i): c.get("is_setup_corner", False) for i, c in enumerate(corners)}
                br_data = aci.get("brake_release_metrics", [])
                br_map = {b.get("corner_id"): b for b in br_data} if br_data else {}

                enriched = []
                for p in corner_performances:
                    d = p.to_dict() if hasattr(p, "to_dict") else dict(p) if isinstance(p, dict) else {"corner_id": 0}
                    cid = d.get("corner_id", 0)
                    d["corner_type"] = corner_type_map.get(cid, "")
                    d["risk_index"] = risk_map.get(cid, 0.0)
                    d["compound_id"] = compound_map.get(cid)
                    d["is_setup_corner"] = setup_map.get(cid, False)
                    d["brake_release"] = br_map.get(cid, {})
                    tl = tl_map.get(cid)
                    if tl:
                        d["timeline"] = tl if isinstance(tl, dict) else (tl.to_dict() if hasattr(tl, "to_dict") else {})
                    enriched.append(d)
                _enriched_corner_perfs = enriched
            except Exception:
                logger.debug("Corner perf enrichment failed, using raw data", exc_info=True)

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
                corner_performances=_enriched_corner_perfs,
                grip_evolution=grip_evolution_result,
                data_quality=data_quality_rpt,
                theoretical_result=_sim_result,
                weather_timeline=weather_timeline,
                distance_quality=summary.get("distance_quality"),
                traffic=summary.get("traffic"),
                lap_inclusion=summary.get("lap_inclusion"),
                theoretical_metrics=summary.get("theoretical_metrics"),
                grip_map=summary.get("grip_map"),
                driver_style=summary.get("driver_style"),
                coaching_v2=summary.get("coaching_v2"),
                practice_plan=summary.get("practice_plan"),
                endurance=summary.get("endurance"),
                track_boundaries=summary.get("track_boundaries"),
                raceline_optimization=summary.get("raceline_optimization"),
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
        # Skip when running under PostgreSQL — Celery finalize handles persistence.
        import os as _os
        if _os.environ.get("USE_PG", "0") == "1":
            logger.info("Skipping SQLite persist (USE_PG=1; Celery handles DB persistence).")
            return None
        try:
            from web.db import get_db_connection, init_db, set_default_db_path
            from web.models import (
                insert_condition_markers,
                insert_condition_phases,
                insert_driver_progression,
                insert_driving_style_features,
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
                # Auto-set track condition reference if first for this condition.
                try:
                    from web.models import auto_set_track_reference
                    _cond = auto_set_track_reference(conn, session_id)
                    if _cond:
                        logger.info("Set %s reference line for track from session %s.",
                                    _cond, session_id)
                except Exception as _ref_auto_err:
                    logger.debug("Auto-set track reference skipped: %s", _ref_auto_err)
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
                    _theo_t = theo_metrics.get("best_s")
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

            # ── Persist weather timeline to session_weather_laps ──────
            if weather_timeline is not None and not weather_timeline.empty:
                try:
                    for _, _wrow in weather_timeline.iterrows():
                        conn.execute(
                            "INSERT OR IGNORE INTO session_weather_laps "
                            "(session_id, lap_number, timestamp, air_temp_c, "
                            "humidity_pct, wind_speed_mps, wind_dir_deg, "
                            "rain_mm, cloud_cover_pct, weather_code, "
                            "grip_score, track_state, track_temp_est_c) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                session_id, int(_wrow["lap_number"]),
                                _wrow.get("timestamp"), _wrow.get("air_temp_c"),
                                _wrow.get("humidity_pct"), _wrow.get("wind_speed_mps"),
                                _wrow.get("wind_dir_deg"), _wrow.get("rain_mm"),
                                _wrow.get("cloud_cover_pct"), _wrow.get("weather_code"),
                                _wrow.get("grip_score"), _wrow.get("track_state"),
                                _wrow.get("track_temp_est_c"),
                            ),
                        )
                    logger.info("Saved weather timeline for %d laps",
                                len(weather_timeline))
                except Exception as _wt_err:
                    logger.warning("Failed to persist weather timeline: %s",
                                   _wt_err)

        # with conn: auto-commits on success, rolls back on exception
        logger.info("Persisted session %s to SQLite.", session_id)
        return session_id

    db_session_id, err = _safe_step("15_persist_db", _persist_to_db)
    _record("15_persist_db", db_session_id, err)
    _fire_progress("15_persist_db")
    summary["db_session_id"] = db_session_id

    # Final summary — build pipeline status report

    #
    n_ok     = len(summary["steps_ok"])
    n_fail   = len(summary["steps_failed"])

    # If ingest failed (pipeline cannot produce any result), mark as failed.
    if raw_df is None and not resume_from_step8:
        _pipeline_status.mark_failed()

    _pipeline_status.finalize()
    summary["pipeline"] = _pipeline_status.to_dict()

    # ── Provenance ─────────────────────────────────────────────────
    try:
        _training_data_hash = None
        _laps = _laps_for_theo_ref[0]
        if _laps and len(_laps) > 0:
            try:
                from provenance.fingerprint import compute_data_fingerprint as _cdf
                _training_data_hash = _cdf(pd.concat(_laps, ignore_index=True))
            except Exception:
                pass

        _provenance_record = build_provenance(
            input_df=raw_df if raw_df is not None else pd.DataFrame(),
            config=meta,
            method_used="telemetry_tool_v2",
            file_path=str(csv_path) if csv_path else None,
            pipeline_version=_pipeline_status.pipeline_version,
            model_version=_pipeline_status.model_version,
            deterministic=deterministic,
            training_data_hash=_training_data_hash,
        )
        summary["provenance"] = _provenance_record.to_dict()

        # Attach lightweight provenance ref to sub-outputs
        _prov_ref = {
            "analysis_run_id": _provenance_record.analysis_run_id,
            "pipeline_version": _provenance_record.pipeline_version,
        }
        if summary.get("coaching_guide") and isinstance(summary["coaching_guide"], dict):
            summary["coaching_guide"]["provenance_ref"] = _prov_ref

        # ── Write provenance to table (silently skipped if table missing) ──
        if db_session_id is not None:
            try:
                import os as _prov_os

                from provenance.persistence import insert_provenance
                if _prov_os.environ.get("USE_PG", "0") != "1":
                    from web.db import get_db_connection as _prov_get_conn
                    _prov_conn = _prov_get_conn()
                    _wid = None
                    try:
                        from flask import g
                        _wid = getattr(g, "workspace_id", None)
                    except (ImportError, RuntimeError):
                        pass
                    insert_provenance(
                        _prov_conn, _provenance_record,
                        session_id=str(db_session_id),
                        workspace_id=_wid,
                    )
            except Exception as _prov_db_err:
                logger.debug("Provenance table write skipped: %s", _prov_db_err)
    except Exception as _prov_err:
        logger.debug("Provenance generation skipped: %s", _prov_err)

    score_str = (
        f"{score_result['total_score']:.1f}/{score_result['grade']}"
        if score_result else "n/a"
    )
    _degraded_tag = (
        f"  DEGRADED=[{', '.join(_pipeline_status.degraded_steps)}]"
        if _pipeline_status.degraded else ""
    )
    logger.info(
        "Pipeline complete: %d/%d steps OK  track=%s  laps=%d  score=%s  "
        "version=%s%s",
        n_ok, n_ok + n_fail, track_id,
        len(resampled_laps) if resampled_laps else 0,
        score_str,
        _pipeline_status.pipeline_version,
        _degraded_tag,
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