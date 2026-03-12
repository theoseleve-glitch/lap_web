"""
pipeline.orchestrator
~~~~~~~~~~~~~~~~~~~~~
Slimmed-down orchestrator for the 14-stage telemetry analysis pipeline.

Each stage's implementation lives in ``pipeline/stages/s*.py``.
This module wires them together, managing shared state via the
``summary`` dict and firing progress callbacks.

Design principles
~~~~~~~~~~~~~~~~~
- **Pure logic, zero console I/O.**  All diagnostics go through ``logging``.
- Each step wrapped in ``_safe_step()`` — failures produce a warning + ``None``.
- Returns a single ``dict`` carrying every intermediate artefact.
- Deterministic: identical inputs → identical outputs.
"""
from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from pipeline.helpers import (
    _COL_DIST,
    _COL_LAP,
    _COL_SPEED,
    PipelineError,
    _safe_step,
    compute_robustness_metrics,
    extract_track_layout_for_picker,
    get_and_clear_last_step_status,
    lazy_import,
    theoretical_metrics_from_lap,
    validate_lap_consistency,
)
from pipeline_status import (
    PipelineStatus,
    compute_pipeline_version_string,
    get_model_version,
)
from provenance.run_context import build_provenance

logger = logging.getLogger(__name__)

# Column discovery imports (lazy, with fallback)
try:
    from telemetry_tool.column_discovery import apply_discovery, discover_columns
except ImportError:
    try:
        from column_discovery import apply_discovery, discover_columns
    except ImportError:
        discover_columns = None
        apply_discovery = None


def _fetch_user_corners(conn, session_id: str) -> list[dict] | None:
    """Fetch user-placed corner definitions for a session.

    Returns [] on success with no rows, None when conn/session_id missing.
    """
    if conn is None or not session_id:
        return None
    cursor = conn.execute(
        "SELECT corner_index, s_entry, s_apex, s_exit, lat_entry, lon_entry, "
        "lat_apex, lon_apex, lat_exit, lon_exit FROM user_corners WHERE session_id = ?",
        (session_id,),
    )
    return [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]


def _build_corner_perfs_from_user_corners(
    user_corner_rows: list[dict],
    best_lap_df,
    sim_result,
    vehicle_class: str = "car",
) -> list[dict]:
    """Convert user corner rows to corner_perf dicts for V3 analyzers.

    Key mapping: s_entry->s_start, s_exit->s_end, corner_index->corner_id.
    """
    import numpy as np
    perfs = []
    for row in user_corner_rows:
        perf = {
            "corner_id": row["corner_index"],
            "s_start": row["s_entry"],
            "s_end": row["s_exit"],
            "s_apex": row["s_apex"],
            "braking_decel_mps2": 6.0,
            "cornering_accel_mps2": 5.0,
            "exit_accel_mps2": 3.0,
            "vehicle_class": vehicle_class,
        }
        # Try to extract actual values from best lap segment
        if best_lap_df is not None and "Distance (m)" in best_lap_df.columns:
            d = best_lap_df["Distance (m)"].values
            mask = (d >= row["s_entry"]) & (d <= row["s_exit"])
            if mask.sum() > 5:
                seg = best_lap_df[mask]
                if "accel_long_mps2" in seg.columns:
                    a_long = seg["accel_long_mps2"].values
                    braking = a_long[a_long < 0]
                    accel = a_long[a_long > 0]
                    if len(braking) > 0:
                        perf["braking_decel_mps2"] = abs(float(np.mean(braking)))
                    if len(accel) > 0:
                        perf["exit_accel_mps2"] = float(np.mean(accel))
                if "accel_lat_mps2" in seg.columns:
                    lat = np.abs(seg["accel_lat_mps2"].values)
                    if len(lat) > 0:
                        perf["cornering_accel_mps2"] = float(np.mean(lat))
        perfs.append(perf)
    return perfs


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

    Parameters
    ----------
    csv_path : Path to a RaceChrono CSV export.
    session_meta : Dict with session_id, session_type, track_state, driver_name, etc.
    enable_ml : Run ML training / anomaly detection.
    enable_report : Generate HTML + PDF reports.
    output_dir : Root for report files.
    n_resample_points : Distance-grid resolution per lap.
    lap_range : (first_lap, last_lap) inclusive filter.

    Returns
    -------
    dict with all intermediate artefacts and results.
    """
    csv_path = Path(csv_path)

    # ── Normalise session metadata ────────────────────────────────
    meta = dict(session_meta)
    meta.setdefault("session_type", "practice")
    meta.setdefault("track_state", "dry")
    meta.setdefault("driver_name", "Unknown")
    # ── Fetch driver experience for scoring ────────────────────────
    meta.setdefault("driver_total_laps", 0)
    try:
        from db.queries import SELECT_DRIVER_BY_NAME
        from web.db import get_db_connection as _get_exp_conn
        _exp_conn = _get_exp_conn()
        _drv_row = _exp_conn.execute(
            SELECT_DRIVER_BY_NAME, {"driver_name": meta["driver_name"]}
        ).fetchone()
        if _drv_row:
            _drv_id = _drv_row[0] if not isinstance(_drv_row, dict) else _drv_row.get("driver_id")
            _prof_row = _exp_conn.execute(
                "SELECT total_laps FROM driver_profiles WHERE driver_id = :driver_id",
                {"driver_id": _drv_id},
            ).fetchone()
            if _prof_row:
                meta["driver_total_laps"] = int(
                    (_prof_row[0] if not isinstance(_prof_row, dict) else _prof_row.get("total_laps", 0)) or 0
                )
    except Exception:
        pass  # Graceful fallback — new driver or no DB
    meta.setdefault("session_id", csv_path.stem)
    if meta.get("session_date") and not meta.get("date"):
        meta["date"] = meta["session_date"]
    if not meta.get("date"):
        try:
            wt = lazy_import("weather_timeline")
            if wt and hasattr(wt, "parse_session_datetime"):
                _dt = wt.parse_session_datetime(csv_path)
                if _dt:
                    meta["date"] = _dt.strftime("%Y-%m-%d")
                    meta["session_datetime"] = _dt.isoformat()
        except Exception:
            pass
    meta.setdefault("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # ── Resolve filter profile ────────────────────────────────────
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

    _dtag_suffix = f"_{driver_tag}" if driver_tag else ""

    # ── Pipeline status tracker ───────────────────────────────────
    _pipeline_status = PipelineStatus(
        pipeline_version=compute_pipeline_version_string(),
        model_version=get_model_version(),
    )

    # ── Pre-populate summary dict ─────────────────────────────────
    summary: dict[str, Any] = {
        "csv_path": str(csv_path),
        "session_meta": meta,
        "steps_ok": [],
        "steps_failed": [],
        "errors": {},
        "raw_df": None, "filtered_df": None, "enriched_df": None,
        "trimmed_df": None, "trim_report": {},
        "track_match": None,
        "track_id": meta.get("track_id", "unknown_track"),
        "lap_dict": None, "resampled_laps": None, "corners": [],
        "lap_metrics": [], "lap_times": [],
        "consistency_metrics": {}, "robustness_metrics": {},
        "best_lap": None, "best_lap_key": None,
        "delta_segments": [], "segment_losses": [],
        "theoretical_lap": None, "theoretical_metrics": {},
        "feature_df": None, "ml_results": {}, "anomaly_results": {},
        "score_result": None, "driver_profile": None,
        "html_path": None, "pdf_path": None, "output_dir": None,
        "phases_df": None, "lap_to_phase": None,
        "adaptation_score": None, "track_evolution": None,
        "grip_evolution": None, "corner_performances": None,
        "coaching_guide": None,
        "reference_line": None, "curvature_profile": None,
        "friction_model": None, "vehicle_params": None,
        "data_quality": None,
        "joker_detection_result": None, "joker_lap_number": None,
        "weather_timeline": None,
        "filter_config": (
            _resolved_filter_profile.to_dict()
            if _resolved_filter_profile else None
        ),
        "vehicle_overrides": vehicle_overrides,
    }

    # ── Stage progress tracking ───────────────────────────────────
    _STAGE_MAP: list[tuple[str, str]] = [
        ("01_ingest", "Ingesting CSV"),
        ("02_filter", "GPS Filtering"),
        ("03_derived_channels", "Derived Channels"),
        ("04_trim_session", "Session Trim"),
        ("05_detect_track", "Track Detection"),
        ("06_segment_laps", "Lap Segmentation"),
        ("06b_detect_corners", "Corner Detection"),
        ("08_compute_metrics", "Computing Metrics"),
        ("09a_reference_line", "Reference Line"),
        ("09_compute_deltas", "Physics Models"),
        ("10_theoretical", "Theoretical Lap"),
        ("11_build_features", "Feature Engineering"),
        ("13_score_session", "Scoring"),
        ("15_persist_db", "Saving Results"),
    ]
    _STAGE_TOTAL = len(_STAGE_MAP)
    _STAGE_LOOKUP = {name: (i + 1, label) for i, (name, label) in enumerate(_STAGE_MAP)}

    def _fire_progress(step_name: str, status: str = "done") -> None:
        if progress_callback and step_name in _STAGE_LOOKUP:
            idx, label = _STAGE_LOOKUP[step_name]
            try:
                progress_callback(idx, _STAGE_TOTAL, label, status)
            except Exception:
                pass

    phases_df: Optional[pd.DataFrame] = None
    lap_to_phase: Optional[dict[int, int]] = None

    def _record(step: str, result: Any, error: Optional[str]) -> Any:
        """Book-keep step outcome."""
        if error is None:
            summary["steps_ok"].append(step)
        else:
            summary["steps_failed"].append(step)
            summary["errors"][step] = error
        status = get_and_clear_last_step_status()
        if status is not None:
            _pipeline_status.record_step(status)
        return result

    _channel_discovery = None
    raw_df = None  # type: Optional[pd.DataFrame]

    # ══════════════════════════════════════════════════════════════
    # PHASE 1: Ingest through Corner Detection (steps 01-07)
    # ══════════════════════════════════════════════════════════════

    if resume_from_step8:
        raw_df = None  # not available when resuming
        if preloaded_resampled_laps is None:
            logger.error("resume_from_step8=True but no preloaded_resampled_laps")
            return summary
        resampled_laps = preloaded_resampled_laps
        corners = preloaded_corners or []
        track_id = meta.get("track_id", "unknown_track")
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
        # ── Import stage modules ──────────────────────────────────
        from pipeline.stages import (
            s01_ingest,
            s02_filter,
            s03_derived,
            s04_trim,
            s05_track,
            s06_segment,
            s07_resample,
        )

        # STEP 01 — Ingest
        def _ingest():
            return s01_ingest.run_ingest(csv_path, progress_callback=progress_callback)

        ingest_result, err = _safe_step("01_ingest", _ingest)
        _record("01_ingest", ingest_result, err)
        _fire_progress("01_ingest")

        if ingest_result is None:
            logger.error("Ingest failed — cannot continue.")
            _pipeline_status.mark_failed()
            _pipeline_status.finalize()
            summary["pipeline"] = _pipeline_status.to_dict()
            return summary

        raw_df, source_info = ingest_result
        summary["raw_df"] = None  # Don't hold ~8 GB
        for k in ("source_format", "available_channels", "data_tier",
                   "source_metadata", "channel_discovery"):
            if k in source_info:
                summary[k] = source_info[k]
        _channel_discovery = source_info.get("_channel_discovery")

        # STEP 02 — Filter + Sensor Fusion
        filtered_df, err = _safe_step(
            "02_filter", s02_filter.run_filter,
            raw_df, filter_profile=_resolved_filter_profile,
        )
        _record("02_filter", filtered_df, err)
        _fire_progress("02_filter")
        if filtered_df is None:
            filtered_df = raw_df
        summary["filtered_df"] = None
        raw_df = None

        fusion_result, err = _safe_step("02b_sensor_fusion", s02_filter.run_sensor_fusion, filtered_df)
        _record("02b_sensor_fusion", fusion_result, err)
        if fusion_result is not None:
            filtered_df, _fusion_meta = fusion_result
            summary["sensor_fusion"] = (
                _fusion_meta.to_dict() if hasattr(_fusion_meta, "to_dict") else _fusion_meta
            )
        else:
            summary["sensor_fusion"] = None

        # STEP 03 — Derived Channels
        derived_result, err = _safe_step(
            "03_derived_channels", s03_derived.run_derived_channels, filtered_df,
        )
        _record("03_derived_channels", derived_result, err)
        _fire_progress("03_derived_channels")
        if derived_result is not None:
            enriched_df, grade_status = derived_result
            summary["grade_status"] = grade_status
        else:
            enriched_df = filtered_df
            summary["grade_status"] = "grade_unavailable"
        summary["enriched_df"] = None
        del filtered_df

        # STEP 04 — Trim Session
        trim_result, err = _safe_step(
            "04_trim_session", s04_trim.run_trim,
            enriched_df, session_type=meta.get("session_type", "practice"),
        )
        _record("04_trim_session", trim_result, err)
        _fire_progress("04_trim_session")
        if trim_result is not None:
            trimmed_df, trim_report = trim_result
        else:
            trimmed_df, trim_report = enriched_df, {}
        del enriched_df
        summary["trimmed_df"] = trimmed_df
        summary["trim_report"] = trim_report

        # STEP 05 — Track Detection
        track_result, err = _safe_step(
            "05_detect_track", s05_track.run_track_detection,
            trimmed_df, meta, context=context, output_dir=output_dir,
            driver_tag=driver_tag,
        )
        _record("05_detect_track", track_result, err)
        _fire_progress("05_detect_track")
        if track_result is not None:
            track_match, track_id = track_result
        else:
            track_match, track_id = None, meta.get("track_id", "unknown_track")
        meta["track_id"] = track_id
        # track_match is a dict (from s05_track) or a MatchResult with .to_dict()
        if track_match and isinstance(track_match, dict):
            summary["track_match"] = track_match
        elif track_match and hasattr(track_match, "to_dict"):
            summary["track_match"] = track_match.to_dict()
        else:
            summary["track_match"] = None
        summary["track_id"] = track_id

        # STEP 06 — Segment Laps
        lap_dict, err = _safe_step(
            "06_segment_laps", s06_segment.run_segment_laps,
            trimmed_df, lap_range=lap_range,
        )
        _record("06_segment_laps", lap_dict, err)
        _fire_progress("06_segment_laps")
        summary["lap_dict"] = lap_dict

        if lap_dict is None or len(lap_dict) == 0:
            logger.error("No laps — returning partial summary.")
            return summary

        lap_dict = validate_lap_consistency(lap_dict)

        # STEP 06.5 — Distance Integrity
        di_result, err = _safe_step(
            "06b_distance_integrity", s06_segment.run_distance_integrity, lap_dict,
        )
        _record("06b_distance_integrity", di_result, err)
        if di_result is not None:
            lap_dict, _distance_quality = di_result
            summary["distance_quality"] = (
                _distance_quality.to_dict()
                if hasattr(_distance_quality, "to_dict") else _distance_quality
            )
        else:
            _distance_quality = None
            summary["distance_quality"] = None

        # STEP 07 — Resample
        resampled_laps, err = _safe_step(
            "07_normalise", s07_resample.run_resample,
            lap_dict, n_points=n_resample_points,
        )
        _record("07_normalise", resampled_laps, err)
        summary["resampled_laps"] = resampled_laps

        if resampled_laps is None or len(resampled_laps) == 0:
            logger.error("Resampling failed — returning partial summary.")
            return summary

        # STEP 06b — Corner Detection
        corners, err = _safe_step(
            "06b_detect_corners", s07_resample.run_corner_detection, resampled_laps,
        )
        _record("06b_detect_corners", corners, err)
        _fire_progress("06b_detect_corners")
        corners = corners or []
        summary["corners"] = corners

        # Corner classification
        corner_mod = lazy_import("corner_detection")
        if corner_mod:
            compound_groups = s07_resample.classify_corners(corners, resampled_laps, corner_mod)
            if compound_groups:
                summary["compound_corners_raw"] = compound_groups

        # Corner callback
        if corner_callback and resampled_laps:
            try:
                _best_key = sorted(resampled_laps.keys())[0]
                _layout = extract_track_layout_for_picker(
                    resampled_laps[_best_key], corners,
                )
                if _layout:
                    _layout["track_id"] = track_id
                    corner_callback(_layout)
            except Exception as _cb_exc:
                logger.warning("Corner callback failed: %s", _cb_exc)

        # Early return for split-pipeline
        if stop_after_corners:
            layout = None
            if resampled_laps:
                _best_key = sorted(resampled_laps.keys())[0]
                layout = extract_track_layout_for_picker(
                    resampled_laps[_best_key], corners,
                )
                if layout and track_id:
                    layout["track_id"] = track_id
            summary["track_layout"] = layout
            summary["resampled_laps"] = resampled_laps
            return summary

    # ══════════════════════════════════════════════════════════════
    # PHASE 2: Metrics & Validation (steps 08-08j)
    # ══════════════════════════════════════════════════════════════
    from pipeline.stages import s08_metrics

    # Step 08 — Per-lap metrics
    metrics_res, err = _safe_step("08_compute_metrics", s08_metrics.run_compute_metrics, resampled_laps)
    _record("08_compute_metrics", metrics_res, err)
    _fire_progress("08_compute_metrics")
    if metrics_res is not None:
        lap_metrics, lap_times = metrics_res
    else:
        lap_metrics, lap_times = [], []
    summary["lap_metrics"] = lap_metrics
    summary["lap_times"] = lap_times

    # Step 08b — Consistency
    consistency, err = _safe_step("08b_consistency", s08_metrics.run_consistency, lap_times)
    _record("08b_consistency", consistency, err)
    summary["consistency_metrics"] = consistency or {}

    # Step 08c — Robustness
    robustness, err = _safe_step(
        "08c_robustness", compute_robustness_metrics, resampled_laps, lap_times,
    )
    _record("08c_robustness", robustness, err)
    summary["robustness_metrics"] = robustness or {}

    # Step 08d — Condition tracking
    ct_result, err = _safe_step(
        "08d_condition_tracking", s08_metrics.run_condition_tracking,
        lap_metrics, lap_times, meta=meta, csv_path=csv_path,
        context=context, output_dir=output_dir, driver_tag=driver_tag,
    )
    _record("08d_condition_tracking", ct_result, err)
    if ct_result is not None:
        phases_df, lap_to_phase = ct_result
    summary["phases_df"] = phases_df
    summary["lap_to_phase"] = lap_to_phase

    # Step 08d2 — Track evolution
    evo_result, err = _safe_step("08d2_track_evolution", s08_metrics.run_track_evolution, phases_df, lap_metrics)
    _record("08d2_track_evolution", evo_result, err)
    track_evolution = evo_result
    summary["track_evolution"] = track_evolution

    # Step 08e — Weather timeline
    weather_tl, err = _safe_step(
        "08e_weather_timeline", s08_metrics.run_weather_timeline,
        csv_path, meta, summary, lap_times,
    )
    _record("08e_weather_timeline", weather_tl, err)
    weather_timeline = weather_tl if (weather_tl is not None and not weather_tl.empty) else None
    summary["weather_timeline"] = weather_timeline

    # Step 08d3 — Tyre degradation
    td_result, err = _safe_step("08d3_tyre_degradation", s08_metrics.run_tyre_degradation, resampled_laps, lap_times)
    _record("08d3_tyre_degradation", td_result, err)
    grip_evolution_result = td_result
    summary["grip_evolution"] = grip_evolution_result

    # Step 08e — Invalid laps
    invalid_result, err = _safe_step(
        "08e_invalid_laps", s08_metrics.run_invalid_lap_detection,
        lap_times, resampled_laps, meta=meta,
    )
    _record("08e_invalid_laps", invalid_result, err)
    invalid_lap_set = set()
    if invalid_result is not None:
        invalid_lap_set, inv_analysis = invalid_result
        summary["invalid_lap_analysis"] = inv_analysis

    # Step 08e2 — Best-N% selection
    best_n_result, err = _safe_step(
        "08e2_best_n_laps", s08_metrics.run_best_n_selection,
        lap_times, resampled_laps, invalid_lap_set,
    )
    _record("08e2_best_n_laps", best_n_result, err)
    best_n_lap_indices = best_n_result

    # Step 08f — Incomplete laps
    incomplete_result, err = _safe_step(
        "08f_incomplete_laps", s08_metrics.run_incomplete_lap_detection,
        trimmed_df if not resume_from_step8 else summary.get("trimmed_df"),
    )
    _record("08f_incomplete_laps", incomplete_result, err)
    incomplete_lap_set = set()
    if incomplete_result is not None:
        incomplete_lap_set, inc_analysis = incomplete_result
        summary["incomplete_lap_analysis"] = inc_analysis

    # Step 08g — Anomalous laps
    anomalous_result, err = _safe_step(
        "08g_anomalous_laps", s08_metrics.run_anomalous_lap_detection,
        trimmed_df if not resume_from_step8 else summary.get("trimmed_df"),
        invalid_lap_set | incomplete_lap_set,
    )
    _record("08g_anomalous_laps", anomalous_result, err)
    anomalous_lap_set = set()
    if anomalous_result is not None:
        anomalous_lap_set, anom_analysis = anomalous_result
        summary["anomalous_lap_analysis"] = anom_analysis

    deviated_lap_set: set = set()
    # NOTE: Step 08h deferred to after 09a (needs reference_line)

    corner_performances = None

    # ══════════════════════════════════════════════════════════════
    # PHASE 3: Physics Pipeline (steps 09a-09i)
    # ══════════════════════════════════════════════════════════════
    from pipeline.stages import s09_physics

    # Step 09a — Reference line
    _pre_excl = invalid_lap_set | incomplete_lap_set | anomalous_lap_set
    reference_line, err = _safe_step(
        "09a_reference_line", s09_physics.run_reference_line,
        resampled_laps, exclude_laps=_pre_excl or None,
    )
    _record("09a_reference_line", reference_line, err)
    _fire_progress("09a_reference_line")
    summary["reference_line"] = reference_line

    # Step 09a2 — Track boundaries
    track_boundaries, err = _safe_step(
        "09a2_track_boundaries", s09_physics.run_track_boundaries,
        resampled_laps, reference_line,
    )
    _record("09a2_track_boundaries", track_boundaries, err)
    if track_boundaries is not None:
        summary["track_boundaries"] = (
            track_boundaries.to_dict()
            if hasattr(track_boundaries, "to_dict") else track_boundaries
        )

    # Step 08h — Line deviation detection (deferred)
    deviation_result, err = _safe_step(
        "08h_line_deviations", s09_physics.run_line_deviation_detection,
        resampled_laps, reference_line,
        invalid_lap_set | incomplete_lap_set | anomalous_lap_set,
    )
    _record("08h_line_deviations", deviation_result, err)
    if deviation_result is not None:
        deviated_lap_set, dev_analysis = deviation_result
        summary["line_deviation_analysis"] = dev_analysis

    # Step 08j — Joker lap detection (opt-in only)
    # Only runs when the user enabled the joker checkbox at upload.
    # If a specific lap number was provided, use it directly;
    # otherwise auto-detect.
    joker_lap_set: set = set()
    joker_enabled = session_meta.get("joker_enabled", False)
    user_joker = session_meta.get("joker_lap_number")

    if joker_enabled and user_joker is not None:
        # User specified an exact joker lap — use it directly
        logger.info("Using user-specified joker lap: %s", user_joker)
        joker_lap_set = {user_joker}
        summary["joker_lap_number"] = user_joker
        summary["joker_detection_result"] = {
            "source": "user",
            "joker_laps": [user_joker],
        }
        _record("08j_joker_detection", summary["joker_detection_result"], None)
    elif joker_enabled:
        # User enabled joker but didn't specify which lap — auto-detect
        joker_result, err = _safe_step(
            "08j_joker_detection", s09_physics.run_joker_detection,
            session_meta, track_id, lap_metrics, lap_times,
            invalid_lap_set=invalid_lap_set,
            incomplete_lap_set=incomplete_lap_set,
            anomalous_lap_set=anomalous_lap_set,
            deviated_lap_set=deviated_lap_set,
            joker_callback=joker_callback,
        )
        _record("08j_joker_detection", joker_result, err)
        if joker_result is not None:
            joker_lap_set, joker_dict, invalid_additions = joker_result
            summary["joker_detection_result"] = joker_dict
            if joker_lap_set:
                summary["joker_lap_number"] = next(iter(joker_lap_set))
            invalid_lap_set |= invalid_additions
    else:
        # Joker not enabled — skip detection entirely
        _record("08j_joker_detection", None, None)

    # Combine exclusion sets
    excluded_laps = (
        invalid_lap_set | incomplete_lap_set
        | anomalous_lap_set | deviated_lap_set
        | joker_lap_set
    )

    # Best-lap selection
    best_lap_key, best_lap_df, valid_times = s08_metrics.select_best_lap(
        resampled_laps, lap_times, excluded_laps, invalid_lap_set,
    )
    summary["best_lap"] = best_lap_df
    summary["best_lap_key"] = best_lap_key

    # Build clean data
    _clean_resampled, _clean_lap_times, _clean_lap_metrics = s08_metrics.build_clean_data(
        resampled_laps, lap_times, lap_metrics, excluded_laps,
    )

    # Recompute consistency/robustness with clean data
    if excluded_laps:
        logger.info(
            "Excluded %d lap(s) — downstream uses %d clean laps (of %d total).",
            len(excluded_laps), len(_clean_lap_times), len(lap_times),
        )
        feat_mod = lazy_import("features")

        def _consistency_clean():
            if feat_mod is None:
                return {}
            return feat_mod.compute_consistency_metrics(_clean_lap_times)

        consistency_v2, err = _safe_step("08i_consistency_clean", _consistency_clean)
        if consistency_v2:
            consistency = consistency_v2
            summary["consistency_metrics"] = consistency

        robustness_v2, err = _safe_step(
            "08i_robustness_clean", compute_robustness_metrics,
            _clean_resampled, _clean_lap_times,
        )
        if robustness_v2:
            robustness = robustness_v2
            summary["robustness_metrics"] = robustness

    # Step 09 — Deltas
    delta_res, err = _safe_step(
        "09_compute_deltas", s09_physics.run_deltas,
        resampled_laps, best_lap_df, best_lap_key, excluded_laps, valid_times,
    )
    _record("09_compute_deltas", delta_res, err)
    _fire_progress("09_compute_deltas")
    if delta_res is not None:
        delta_segments, segment_losses = delta_res
    else:
        delta_segments, segment_losses = [], []
    summary["delta_segments"] = delta_segments
    summary["segment_losses"] = segment_losses

    # Step 09b — Curvature
    curvature_profile, err = _safe_step("09b_curvature_profile", s09_physics.run_curvature, reference_line)
    _record("09b_curvature_profile", curvature_profile, err)
    summary["curvature_profile"] = curvature_profile

    # Step 09c — Friction model
    friction_circle, err = _safe_step(
        "09c_friction_model", s09_physics.run_friction_model,
        _clean_resampled or resampled_laps,
    )
    _record("09c_friction_model", friction_circle, err)
    summary["friction_model"] = friction_circle

    # Step 09d — Vehicle model
    vehicle_result, err = _safe_step(
        "09d_vehicle_model", s09_physics.run_vehicle_model,
        friction_circle, _clean_lap_metrics or lap_metrics,
        vehicle_overrides=vehicle_overrides,
    )
    _record("09d_vehicle_model", vehicle_result, err)
    vehicle_params = vehicle_result
    corrected_friction = friction_circle
    if vehicle_result is not None and isinstance(vehicle_result, tuple):
        vehicle_params, corrected_friction = vehicle_result
        summary["friction_model"] = corrected_friction
    summary["vehicle_params"] = vehicle_params

    # Step 09e — Data quality
    _fc = -1.0
    _sf = summary.get("sensor_fusion")
    if isinstance(_sf, dict):
        _fc = _sf.get("confidence", -1.0)
    data_quality_rpt, err = _safe_step(
        "09e_data_quality", s09_physics.run_data_quality,
        _clean_resampled or resampled_laps,
        _clean_lap_times or lap_times,
        fusion_confidence=_fc,
    )
    _record("09e_data_quality", data_quality_rpt, err)
    summary["data_quality"] = data_quality_rpt

    # Step 09f — Progressive physics
    _data_tier = summary.get("data_tier", 1)
    _prog_result, err = _safe_step(
        "09f_progressive_physics", s09_physics.run_progressive_physics,
        _clean_resampled or resampled_laps,
        summary.get("corners") or [],
        _data_tier,
    )
    _record("09f_progressive_physics", _prog_result, err)
    summary["progressive_physics"] = _prog_result or {}

    # Step 09g — Traffic + inclusion
    _traffic_incl, err = _safe_step(
        "09g_traffic_inclusion", s09_physics.run_traffic_and_inclusion,
        resampled_laps, lap_times, summary.get("corners"),
        distance_quality=summary.get("distance_quality"),
    )
    _record("09g_traffic_inclusion", _traffic_incl, err)
    _fire_progress("09g_traffic_inclusion")
    _traffic_result = _inclusion_policy = None
    if _traffic_incl is not None:
        _traffic_result, _inclusion_policy = _traffic_incl
    summary["traffic"] = _traffic_result.to_dict() if _traffic_result else None
    summary["lap_inclusion"] = _inclusion_policy.to_dict() if _inclusion_policy else None

    # Step 09h — Condition clustering
    _clustering_raw, err = _safe_step(
        "09h_condition_clustering", s09_physics.run_condition_clustering,
        resampled_laps, lap_times,
        traffic_result=_traffic_result,
        inclusion_policy=_inclusion_policy,
    )
    _record("09h_condition_clustering", _clustering_raw, err)
    _fire_progress("09h_condition_clustering")
    _clustering_result = _clustering_raw
    summary["clustering"] = _clustering_result.to_dict() if _clustering_result else None

    # Step 09i — Grip map
    _grip_result, err = _safe_step(
        "09i_grip_map", s09_physics.run_grip_map,
        resampled_laps,
        inclusion_policy=_inclusion_policy,
        clustering_result=_clustering_result,
    )
    _record("09i_grip_map", _grip_result, err)
    _grip_map = _friction_envelope_result = None
    if _grip_result is not None:
        _grip_map, _friction_envelope_result = _grip_result
    summary["grip_map"] = _grip_map.to_dict() if _grip_map and hasattr(_grip_map, "to_dict") else None
    summary["friction_envelope"] = (
        _friction_envelope_result.to_dict()
        if _friction_envelope_result and hasattr(_friction_envelope_result, "to_dict") else None
    )

    # ══════════════════════════════════════════════════════════════
    # PHASE 4: Theoretical Lap + Corner Analysis (step 10)
    # ══════════════════════════════════════════════════════════════
    from pipeline.stages import s10_theoretical, s10b_corners

    # Gate: skip if distance quality is degraded
    _dq = summary.get("distance_quality")
    _dq_gated = (_dq is not None and hasattr(_dq, "gate_advanced") and _dq.gate_advanced)

    if _dq_gated:
        logger.warning("Theoretical lap SKIPPED: distance quality gate active.")
        theoretical_lap = None
        _record("10_theoretical", None, "distance_quality_gate")
        _fire_progress("10_theoretical")
        summary["theoretical_lap"] = None
        _sim_method = "none"
        _sim_result = None
        _corner_coaching = None
        _delta_map = None
        _session_scalars = None
        _laps_for_theo_ref = [None]
    else:
        theo_result, err = _safe_step(
            "10_theoretical", s10_theoretical.run_theoretical,
            resampled_laps, curvature_profile, corrected_friction or friction_circle,
            vehicle_params, data_quality_rpt, valid_times,
            channel_discovery=_channel_discovery,
            n_resample_points=n_resample_points,
            best_n_lap_indices=best_n_lap_indices,
            excluded_laps=excluded_laps,
            inclusion_policy=_inclusion_policy,
            clustering_result=_clustering_result,
            phases_df=phases_df,
            lap_to_phase=lap_to_phase,
            grip_map=_grip_map,
            friction_envelope=_friction_envelope_result,
            distance_quality=_dq,
        )
        _record("10_theoretical", theo_result, err)
        _fire_progress("10_theoretical")

        if theo_result is not None:
            # run_theoretical returns a 7-tuple:
            # (theo_df, sim_method, sim_result, corner_coaching,
            #  delta_map, session_scalars, laps_for_theo)
            (theoretical_lap, _sim_method, _sim_result,
             _corner_coaching, _delta_map, _session_scalars,
             _laps_for_theo) = theo_result
            _laps_for_theo_ref = [_laps_for_theo]
        else:
            theoretical_lap = None
            _sim_method = "none"
            _sim_result = None
            _corner_coaching = None
            _delta_map = None
            _session_scalars = None
            _laps_for_theo_ref = [None]
        summary["theoretical_lap"] = theoretical_lap

    # Theoretical metrics
    def _theo_metrics():
        if theoretical_lap is None:
            raise ValueError("No theoretical lap")
        return theoretical_metrics_from_lap(
            theoretical_lap, simulation_method=_sim_method,
            sim_result=_sim_result, data_quality=data_quality_rpt,
        )

    theo_metrics, err = _safe_step("10b_theoretical_metrics", _theo_metrics)
    _record("10b_theoretical_metrics", theo_metrics, err)
    theo_metrics = theo_metrics or {}
    summary["theoretical_metrics"] = theo_metrics

    summary["corner_coaching"] = _corner_coaching
    summary["delta_map"] = _delta_map
    summary["session_scalars"] = _session_scalars

    # Corner analysis (steps 10c-10f)
    ca_result, err = _safe_step(
        "10c_corner_analysis", s10b_corners.run_corner_analysis,
        corners, best_lap_df, theoretical_lap,
        summary.get("friction_model"), resampled_laps, excluded_laps,
    )
    _record("10c_corner_analysis", ca_result, err)
    if ca_result is not None:
        corner_performances = ca_result
    summary["corner_performances"] = corner_performances

    if _corner_coaching is None and corner_performances:
        summary["corner_coaching"] = corner_performances

    # Corner timelines
    dq_score = getattr(data_quality_rpt, "overall_confidence", 1.0) if data_quality_rpt else 1.0
    tl_result, err = _safe_step(
        "10c_corner_timelines", s10b_corners.run_corner_timelines,
        corners, best_lap_df, resampled_laps, excluded_laps,
        data_quality=data_quality_rpt, theoretical_lap=theoretical_lap,
    )
    _record("10c_corner_timelines", tl_result, err)
    corner_timelines = tl_result or []
    summary["corner_timelines"] = corner_timelines

    # Advanced corner intelligence
    aci_result, err = _safe_step(
        "10c_advanced_corner_intelligence",
        s10b_corners.run_advanced_corner_intelligence,
        corners, corner_timelines, corner_performances, best_lap_df,
        resampled_laps, excluded_laps,
        data_quality=data_quality_rpt, theoretical_lap=theoretical_lap,
        compound_corners_raw=summary.get("compound_corners_raw"),
    )
    _record("10c_advanced_corner_intelligence", aci_result, err)
    if aci_result:
        summary["advanced_corner_intelligence"] = aci_result

    # Per-lap corner metrics
    _plcm, err = _safe_step(
        "10d_per_lap_corners", s10b_corners.run_per_lap_corner_metrics,
        corners, resampled_laps, excluded_laps,
        theoretical_lap=theoretical_lap,
        friction_model=summary.get("friction_model"),
    )
    _record("10d_per_lap_corners", _plcm, err)
    per_lap_corner_metrics = _plcm or []
    summary["per_lap_corner_metrics"] = per_lap_corner_metrics

    # Endurance + Raceline
    endurance_r, err = _safe_step("10e_endurance", s10b_corners.run_endurance, summary)
    _record("10e_endurance", endurance_r, err)
    if endurance_r:
        summary["endurance"] = endurance_r

    config = meta  # Pipeline config is stored in meta
    _enable_raceline = config.get("enable_raceline_optimizer", False) if config else False
    if _enable_raceline and track_boundaries is not None and reference_line is not None:
        rl_result, err = _safe_step(
            "10f_raceline", s10b_corners.run_raceline_optimizer,
            corners, reference_line, curvature_profile, track_boundaries,
            corrected_friction or friction_circle,
        )
        _record("10f_raceline", rl_result, err)
        if rl_result:
            summary["raceline_optimization"] = (
                rl_result.to_dict() if hasattr(rl_result, "to_dict") else rl_result
            )

    # Step 10g — V2 corner coaching (user-defined corners + MRP + handling)
    _v2_conn = None
    try:
        from web.db import get_db_connection as _get_v2_conn
        _v2_conn = _get_v2_conn()
    except Exception:
        pass

    v2_sections, err = _safe_step(
        "10g_track_decomposition_v2", s10b_corners.run_track_decomposition_v2,
        best_lap_df, conn=_v2_conn, session_id=str(meta.get("session_id", "")),
        fallback_corners=corners,
    )
    _record("10g_track_decomposition_v2", v2_sections, err)

    _avail_cols = set(best_lap_df.columns) if best_lap_df is not None else None

    if v2_sections:
        summary["track_sections_v2"] = v2_sections

        # Step 10g2 — MRP detection on v2 sections
        v2_mrp, err = _safe_step(
            "10g2_mrp_detection_v2", s10b_corners.run_mrp_detection_v2,
            v2_sections, best_lap_df,
        )
        _record("10g2_mrp_detection_v2", v2_mrp, err)
        if v2_mrp:
            summary["mrp_events_v2"] = v2_mrp

        # Step 10g3 — Handling analysis on v2 sections
        v2_handling, err = _safe_step(
            "10g3_handling_v2", s10b_corners.run_handling_analysis_v2,
            v2_sections, best_lap_df, available_columns=_avail_cols,
        )
        _record("10g3_handling_v2", v2_handling, err)

        # Step 10g4 — Coaching on v2 sections
        v2_coaching, err = _safe_step(
            "10g4_coaching_v2", s10b_corners.run_coaching_v2,
            v2_sections, v2_mrp, v2_handling, best_lap_df,
            available_columns=_avail_cols,
        )
        _record("10g4_coaching_v2", v2_coaching, err)
        if v2_coaching:
            summary["corner_coaching_v2"] = v2_coaching
            logger.info(
                "V2 corner coaching: %d sections coached (%s user-defined)",
                len(v2_coaching),
                sum(1 for s in v2_sections if s.get("corner_type") == "user_defined"),
            )

    # ── Step S10h: Corner diagnosis grid ──────────────────────────
    user_corner_rows = None
    _ucr, _err = _safe_step(
        "S10h_fetch_user_corners",
        lambda: _fetch_user_corners(_v2_conn, str(meta.get("session_id", ""))),
    )
    _record("S10h_fetch_user_corners", _ucr, _err)
    if _ucr is not None:
        user_corner_rows = _ucr

    if user_corner_rows:
        from coaching.corner_diagnosis import classify_all_corners as _classify_corners

        corner_labels, _err = _safe_step(
            "S10h_corner_labels",
            lambda: _classify_corners(
                resampled_laps=resampled_laps,
                theoretical_lap=theoretical_lap,
                user_corners=user_corner_rows,
                vehicle_class=meta.get("vehicle_class", "car"),
                valid_lap_numbers=[k for k in resampled_laps if k not in excluded_laps],
                curvature_profile=curvature_profile,
                mrp_events=summary.get("mrp_events_v2"),
            ),
        )
        _record("S10h_corner_labels", corner_labels, _err)
        if corner_labels is not None:
            summary["corner_labels"] = corner_labels

    # ══════════════════════════════════════════════════════════════
    # PHASE 5: Features, ML, Scoring, Reports, Persist (steps 11-15)
    # ══════════════════════════════════════════════════════════════
    from pipeline.stages import s11_features, s12_ml, s13_scoring, s14_reports

    # Step 11 — Features
    feature_df, err = _safe_step(
        "11_build_features", s11_features.run_build_features,
        lap_metrics, delta_segments, track_id, meta,
        context=context, lap_to_phase=lap_to_phase,
    )
    _record("11_build_features", feature_df, err)
    _fire_progress("11_build_features")
    summary["feature_df"] = feature_df

    # Step 12 — ML
    ml_results: dict[str, Any] = {}
    anomaly_results: dict[str, Any] = {}
    if enable_ml and feature_df is not None and len(feature_df) > 0:
        ml_results, err = _safe_step("12a_ml_train", s12_ml.run_ml_training, feature_df, meta)
        _record("12a_ml_train", ml_results, err)
        ml_results = ml_results or {}

        anomaly_results, err = _safe_step("12b_anomaly_detection", s12_ml.run_anomaly_detection, feature_df)
        _record("12b_anomaly_detection", anomaly_results, err)
        anomaly_results = anomaly_results or {}
    summary["ml_results"] = ml_results
    summary["anomaly_results"] = anomaly_results

    # Step 13 — Score
    score_result, err = _safe_step(
        "13_score_session", s13_scoring.run_score,
        consistency, robustness, lap_metrics, excluded_laps, theo_metrics, meta,
        context=context, phases_df=phases_df, lap_to_phase=lap_to_phase,
        track_evolution=track_evolution, corner_performances=corner_performances,
        weather_timeline=weather_timeline, corner_coaching=_corner_coaching,
        progressive_physics=summary.get("progressive_physics"),
    )
    _record("13_score_session", score_result, err)
    _fire_progress("13_score_session")
    summary["score_result"] = score_result

    # Step 14 — Reports
    driver_profile, err = _safe_step(
        "14a_driver_profile", s14_reports.run_driver_profile,
        meta, consistency, robustness, theo_metrics, resampled_laps, score_result,
        lap_metrics, context=context, phases_df=phases_df, lap_to_phase=lap_to_phase,
    )
    _record("14a_driver_profile", driver_profile, err)
    summary["driver_profile"] = driver_profile

    driving_style_result, err = _safe_step(
        "14a2_driving_style", s14_reports.run_driving_style,
        resampled_laps, lap_metrics=lap_metrics, corners=corners,
        corner_performances=corner_performances, theo_metrics=theo_metrics,
        per_lap_corner_metrics=per_lap_corner_metrics,
    )
    _record("14a2_driving_style", driving_style_result, err)
    summary["driving_style"] = driving_style_result

    # Coaching
    if _dq_gated:
        _record("13b_coaching_guide", None, "distance_quality_gate")
        coaching_guide = None
    else:
        coaching_guide, err = _safe_step(
            "13b_coaching_guide", s13_scoring.run_coaching_guide,
            corner_performances, lap_metrics, score_result, track_evolution, meta,
            distance_quality=_dq,
        )
        _record("13b_coaching_guide", coaching_guide, err)
    summary["coaching_guide"] = coaching_guide

    # Coaching V2
    if _dq_gated:
        _record("13c_coaching_v2", None, "distance_quality_gate")
    else:
        cv2_result, err = _safe_step(
            "13c_coaching_v2", s13_scoring.run_coaching_v2,
            corner_performances, corner_timelines, corners,
            data_quality=dq_score, distance_quality=_dq,
        )
        _record("13c_coaching_v2", cv2_result, err)
        if cv2_result is not None:
            summary["coaching_v2"] = (
                cv2_result.to_dict() if hasattr(cv2_result, "to_dict") else cv2_result
            )

    # Practice plan
    plan_result, err = _safe_step(
        "13d_practice_plan", s13_scoring.run_practice_plan,
        summary.get("coaching_v2"),
        summary.get("enriched_df"),
    )
    _record("13d_practice_plan", plan_result, err)
    if plan_result is not None:
        plan_dict = plan_result.to_dict() if hasattr(plan_result, "to_dict") else plan_result
        summary["practice_plan"] = plan_dict

    # Build user-corner-based perfs for V3 if user corners available
    v3_corner_perfs = corner_performances  # default: auto-detected
    if user_corner_rows:
        _v3_perfs, _err = _safe_step(
            "S10h_build_v3_perfs",
            lambda: _build_corner_perfs_from_user_corners(
                user_corner_rows, best_lap_df, _sim_result,
                vehicle_class=meta.get("vehicle_class", "car"),
            ),
        )
        if _v3_perfs:
            v3_corner_perfs = _v3_perfs

    # ── Coaching V3 (feature-flagged, default ON) ──
    if os.environ.get("COACHING_V3", "1") != "0":
        from pipeline.stages import s13_coaching_v3

        _analyzer_bundle, err = _safe_step(
            "13e_analyzers", s13_coaching_v3.run_coaching_analyzers,
            corner_perfs=v3_corner_perfs,
            best_lap_df=best_lap_df,
            theoretical_result=_sim_result,
            friction_model=corrected_friction or friction_circle,
            resampled_laps=resampled_laps,
            available_columns=_avail_cols,
        )
        _record("13e_analyzers", _analyzer_bundle, err)

        _driver_history, err = _safe_step(
            "13f_multi_session", s13_coaching_v3.run_multi_session_lookup,
            driver_id=_drv_id if '_drv_id' in dir() else None,
            track_id=meta.get("track_id"),
            corner_ids=[c["corner_id"] for c in (v3_corner_perfs or [])],
        )
        _record("13f_multi_session", _driver_history, err)

        _coaching_v3, err = _safe_step(
            "13g_coaching_v3", s13_coaching_v3.run_enhanced_coaching,
            corner_perfs=v3_corner_perfs,
            coaching_v2=summary.get("coaching_v2"),
            scores=score_result,
            lap_metrics=summary.get("metrics"),
            driving_style=driving_style_result,
            analyzer_bundle=_analyzer_bundle,
            driver_history=_driver_history,
            vehicle_class=meta.get("vehicle_class", "car"),
            previous_goals=None,
        )
        _record("13g_coaching_v3", _coaching_v3, err)
        if _coaching_v3:
            summary["coaching_v3"] = _coaching_v3

        _safe_step(
            "13g2_persist_coaching", s13_coaching_v3.persist_coaching_v3,
            coaching_dict=_coaching_v3,
            analysis_json=summary.get("_analysis_json_blob", {}),
            conn=None,
            session_id=meta.get("session_id"),
            driver_id=_drv_id if '_drv_id' in dir() else None,
            track_id=meta.get("track_id"),
            corner_coaching=(_coaching_v3 or {}).get("corner_coaching"),
        )

    # ── Step 13h: Gamification — XP, streaks, achievements ─────
    import os as _gam_os
    if _gam_os.environ.get("GAMIFICATION", "1") != "0":
        try:
            from gamification.xp import award_session_xp
            from gamification.streaks import update_streak
            from gamification.achievements import check_achievements
            from gamification.queries import count_driver_sessions, get_driver_best_lap
            from scoring import evaluate_badges as _eval_badges

            _gam_wid = getattr(g, "workspace_id", 1) if "g" in dir() else 1
            _gam_driver = _drv_id if "_drv_id" in dir() else None
            _gam_sid = meta.get("session_id")
            _gam_date = meta.get("date", "")

            if _gam_driver and _v2_conn:
                _gam_badges = []
                if score_result:
                    try:
                        _gam_badges = _eval_badges(score_result)
                    except Exception:
                        pass

                _prev_best = get_driver_best_lap(_v2_conn, _gam_driver, _gam_wid)
                _cur_best = min(valid_times) if valid_times else None

                xp_result = award_session_xp(
                    _v2_conn, _gam_driver, _gam_wid, _gam_sid,
                    badges=_gam_badges,
                    previous_best_lap=_prev_best,
                    current_best_lap=_cur_best,
                )
                streak_result = update_streak(_v2_conn, _gam_driver, _gam_wid, _gam_date)
                _gam_count = count_driver_sessions(_v2_conn, _gam_driver, _gam_wid)

                new_achievements = check_achievements(
                    _v2_conn, _gam_driver, _gam_wid, _gam_sid,
                    context={
                        "session_count": _gam_count,
                        "badges": _gam_badges,
                        "streak": streak_result["current_streak"],
                        "is_personal_best": xp_result["xp_breakdown"].get("personal_best", 0) > 0,
                    },
                )

                summary["gamification"] = {
                    "xp_gained": xp_result["xp_gained"],
                    "new_total": xp_result["new_total"],
                    "old_level": xp_result["old_level"],
                    "new_level": xp_result["new_level"],
                    "leveled_up": xp_result["leveled_up"],
                    "current_streak": streak_result["current_streak"],
                    "new_achievements": [
                        {"key": a["key"], "label": a["label"],
                         "description": a["description"], "icon": a["icon"]}
                        for a in new_achievements
                    ],
                }
                logger.info(
                    "Gamification: driver=%s xp=+%d level=%d streak=%d achievements=%d",
                    _gam_driver, xp_result["xp_gained"], xp_result["new_level"],
                    streak_result["current_streak"], len(new_achievements),
                )
        except Exception:
            logger.warning("Gamification stage failed (non-fatal)", exc_info=True)

    # HTML + PDF reports
    html_path: Optional[Path] = None
    pdf_path: Optional[Path] = None

    if enable_report:
        if output_dir is not None:
            out_dir = Path(output_dir)
        else:
            date_str = meta.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            out_dir = Path("Results") / f"{date_str}_{track_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        summary["output_dir"] = str(out_dir)

        html_path, err = _safe_step(
            "14b_html_report", s14_reports.run_html_report,
            score_result, theoretical_lap, best_lap_df,
            delta_segments, lap_times, segment_losses,
            driver_profile, meta, out_dir, summary,
            driver_tag=driver_tag, context=context, phases_df=phases_df,
            resampled_laps=resampled_laps, friction_circle=corrected_friction or friction_circle,
            corner_performances=corner_performances,
            grip_evolution=grip_evolution_result,
            data_quality=data_quality_rpt,
            theoretical_result=_sim_result,
            weather_timeline=weather_timeline,
            corners=corners,
            track_boundaries=track_boundaries,
        )
        _record("14b_html_report", html_path, err)

        pdf_path, err = _safe_step(
            "14c_pdf_report", s14_reports.run_pdf_report,
            html_path, out_dir, driver_tag=driver_tag,
        )
        _record("14c_pdf_report", pdf_path, err)

    summary["html_path"] = str(html_path) if html_path else None
    summary["pdf_path"] = str(pdf_path) if pdf_path else None

    # Step 15 — Persist to DB
    from pipeline.stages import s15_persist

    db_session_id, err = _safe_step(
        "15_persist_db", s15_persist.run_persist_to_db,
        summary, meta, track_id,
        score_result=score_result,
        driving_style_result=driving_style_result,
        weather_timeline=weather_timeline,
        driver_tag=driver_tag,
    )
    _record("15_persist_db", db_session_id, err)
    _fire_progress("15_persist_db")
    summary["db_session_id"] = db_session_id

    # ══════════════════════════════════════════════════════════════
    # FINALIZE
    # ══════════════════════════════════════════════════════════════
    n_ok = len(summary["steps_ok"])
    n_fail = len(summary["steps_failed"])

    if raw_df is None and not resume_from_step8:
        _pipeline_status.mark_failed()

    _pipeline_status.finalize()
    summary["pipeline"] = _pipeline_status.to_dict()

    # Provenance
    try:
        _training_data_hash = None
        _laps = _laps_for_theo_ref[0] if _laps_for_theo_ref else None
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

        _prov_ref = {
            "analysis_run_id": _provenance_record.analysis_run_id,
            "pipeline_version": _provenance_record.pipeline_version,
        }
        if summary.get("coaching_guide") and isinstance(summary["coaching_guide"], dict):
            summary["coaching_guide"]["provenance_ref"] = _prov_ref

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
