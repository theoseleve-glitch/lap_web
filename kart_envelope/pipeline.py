"""
pipeline.py
-----------
End-to-end orchestrator for the kart-envelope analysis pipeline.

Provides two top-level functions:

- ``analyze_session`` — full analysis of a single session CSV.
- ``train_library`` — build / update envelope library from multiple sessions.

Every step is wrapped in ``_safe_step`` for graceful degradation.
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Callable, TypeVar

import numpy as np

from kart_envelope.coaching.cause_ranking import (
    generate_coaching_text,
    rank_time_loss_causes,
)
from kart_envelope.coaching.corner_coaching import (
    analyze_corner_performance,
    detect_corners_from_curvature,
)
from kart_envelope.coaching.delta_analysis import compute_delta_map
from kart_envelope.config import KartEnvelopeConfig, default_config, load_config
from kart_envelope.envelope.capability import (
    CapabilityEnvelope,
    train_capability_envelope,
)
from kart_envelope.inference.conditions import classify_conditions
from kart_envelope.inference.session_scalars import SessionScalars, infer_session_scalars
from kart_envelope.ingest.columns import normalize_columns
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.ingest.parser import parse_session_csv, parse_session_csv_raw
from kart_envelope.output.csv_tables import write_corner_table, write_delta_map
from kart_envelope.output.json_summary import build_session_summary, write_session_summary
from kart_envelope.processing.cleaning import clean_and_derive
from kart_envelope.processing.lap_splitting import compute_lap_times, split_and_select_laps
from kart_envelope.processing.outlier_filter import mad_filter_accel
from kart_envelope.processing.resampler import resample_laps_by_ds
from kart_envelope.solver.min_time import TheoreticalResult, compute_theoretical_lap
from kart_envelope.solver.record_cal import RecordCalibration, calibrate_to_record
from kart_envelope.track.detection import detect_or_register_track
from kart_envelope.track.geometry import TrackGeometry, build_track_geometry

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _safe_step(name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> tuple[T | None, str | None]:
    """Execute *fn* and return ``(result, None)`` or ``(None, error_msg)``."""
    try:
        result = fn(*args, **kwargs)
        logger.info("Step [%s] — OK", name)
        return result, None
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        logger.warning("Step [%s] — FAILED: %s\n%s", name, msg, traceback.format_exc())
        return None, msg


# ---------------------------------------------------------------------------
# analyze_session
# ---------------------------------------------------------------------------

def analyze_session(
    csv_path: Path,
    metadata: SessionMetadata,
    config: KartEnvelopeConfig | None = None,
    models_dir: Path = Path("models"),
    tracks_dir: Path = Path("tracks"),
    output_dir: Path = Path("outputs"),
) -> dict[str, Any]:
    """Full single-session analysis pipeline.

    Returns a summary dict with all intermediate results.
    """
    if config is None:
        config = default_config()

    ctx: dict[str, Any] = {"errors": []}

    # 1. Parse CSV — single read returning both raw and normalised DataFrames.
    #    Eliminates the previous double-read that loaded the file twice
    #    (once for normalised names, once for raw names for cleaning).
    result, err = _safe_step("parse_csv", parse_session_csv_raw, csv_path)
    if result is None:
        ctx["errors"].append(f"parse: {err}")
        return ctx
    raw_rc, _normalised = result

    # 2. Clean and derive channels (raw RaceChrono column names)
    cleaned, err = _safe_step("clean_derive", clean_and_derive, raw_rc, config)
    if cleaned is None:
        ctx["errors"].append(f"clean: {err}")
        return ctx

    # 3. Normalise column names (after cleaning with raw names)
    df = normalize_columns(cleaned)

    # 4. Split into laps
    laps, err = _safe_step("split_laps", split_and_select_laps, df, config)
    if laps is None:
        ctx["errors"].append(f"laps: {err}")
        return ctx

    ctx["n_clean_laps"] = len(laps)

    # 5. Resample
    resampled, err = _safe_step("resample", resample_laps_by_ds, laps, config)
    if resampled is None:
        ctx["errors"].append(f"resample: {err}")
        return ctx

    # 6. Outlier filter
    filtered, _ = _safe_step("outlier_filter", mad_filter_accel, resampled, config)
    if filtered is None:
        filtered = resampled

    # 7. Build track geometry
    geometry, err = _safe_step("track_geometry", build_track_geometry,
                                filtered, config, metadata.track_name or "")
    if geometry is None:
        ctx["errors"].append(f"geometry: {err}")
        return ctx

    # 8. Detect / register track
    # When metadata provides a track name, use it directly (avoid fingerprint
    # mismatches that create duplicate IDs like CKS_2, CKS_3, etc.)
    if metadata.track_name:
        track_id = metadata.track_name
        logger.info("Step [track_detect] — using metadata track name: %s", track_id)
        geometry.track_id = track_id
    else:
        track_id, _ = _safe_step("track_detect", detect_or_register_track,
                                  raw_rc, geometry, tracks_dir)
        if track_id is None:
            track_id = "unknown"
    ctx["track_id"] = track_id

    # 9. Load or build envelope
    kart_id = metadata.kart_id
    envelope_path = models_dir / track_id / kart_id / "envelope.json"
    envelope: CapabilityEnvelope | None = None
    if envelope_path.exists():
        envelope, _ = _safe_step("load_envelope", CapabilityEnvelope.load, envelope_path)

    if envelope is None:
        # Fall back to single-session envelope
        logger.info("No saved envelope for (%s, %s); training from this session.",
                      track_id, kart_id)
        envelope, err = _safe_step("train_envelope_single",
                                    train_capability_envelope,
                                    [filtered], config, track_id, kart_id)
    if envelope is None:
        ctx["errors"].append(f"envelope: {err}")
        return ctx

    ctx["envelope"] = envelope.to_dict()

    # 10. Infer session scalars
    scalars, _ = _safe_step("infer_scalars", infer_session_scalars,
                             filtered, envelope, config)
    if scalars is None:
        scalars = SessionScalars()

    # 11. Classify conditions
    cond, _ = _safe_step("classify_conditions", classify_conditions, scalars)
    if cond:
        scalars.condition_label = cond
    ctx["session_scalars"] = {
        "mu": scalars.mu_session, "p": scalars.p_session,
        "b": scalars.b_session, "condition": scalars.condition_label,
    }

    # 12. Compute theoretical lap
    theoretical, err = _safe_step("theoretical_lap", compute_theoretical_lap,
                                   geometry, envelope, scalars, config)
    if theoretical is None:
        ctx["errors"].append(f"solver: {err}")
        return ctx

    ctx["theoretical_lap_time_s"] = theoretical.lap_time_s

    # 13. Record calibration (if provided)
    record_cal: RecordCalibration | None = None
    if metadata.track_record_s is not None and metadata.track_record_s > 0:
        record_cal, _ = _safe_step(
            "record_cal", calibrate_to_record,
            geometry, envelope, metadata.track_record_s, config,
            theoretical.lap_time_s,
        )

    # 14. Find best lap (use filtered dict — incomplete laps already removed by splitting)
    lap_times = compute_lap_times(filtered)
    best_lap_num = min(lap_times, key=lap_times.get) if lap_times else 0
    best_lap_df = filtered.get(best_lap_num)

    # 15. Delta map
    delta_map = None
    if best_lap_df is not None:
        delta_map, _ = _safe_step("delta_map", compute_delta_map,
                                   best_lap_df, theoretical)

    # 16. Corner detection + coaching
    corners, _ = _safe_step("detect_corners", detect_corners_from_curvature,
                             geometry.curvature_1pm, geometry.distance_m)
    if corners is None:
        corners = []

    corner_perfs = []
    if best_lap_df is not None and corners:
        corner_perfs_r, _ = _safe_step("corner_perf", analyze_corner_performance,
                                        best_lap_df, theoretical, corners)
        if corner_perfs_r:
            corner_perfs = corner_perfs_r

    # 17. Rank causes + coaching text
    causes = rank_time_loss_causes(corner_perfs, top_n=config.coaching_top_corners)
    coaching_text = generate_coaching_text(causes, scalars)
    ctx["coaching_text"] = coaching_text

    # 18. Write outputs
    session_id = Path(metadata.session_file).stem
    out_dir = output_dir / session_id
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = build_session_summary(
        metadata, scalars, theoretical, corner_perfs, causes,
        lap_times, best_lap_num, record_cal, coaching_text,
    )
    write_session_summary(summary, out_dir / "session_summary.json")

    if delta_map is not None:
        write_delta_map(delta_map, out_dir / "delta_map.csv")

    if corner_perfs:
        write_corner_table(corner_perfs, out_dir / "corner_table.csv")

    ctx["output_dir"] = str(out_dir)
    logger.info("Session analysis complete. Outputs in %s", out_dir)
    return ctx


# ---------------------------------------------------------------------------
# train_library
# ---------------------------------------------------------------------------

def train_library(
    session_files: list[tuple[Path, SessionMetadata]],
    config: KartEnvelopeConfig | None = None,
    models_dir: Path = Path("models"),
    tracks_dir: Path = Path("tracks"),
) -> dict[str, Any]:
    """Train / update the envelope library from multiple sessions.

    Groups sessions by (track, kart) and trains one envelope per group.

    Returns a summary dict.
    """
    if config is None:
        config = default_config()

    # Process each session into resampled laps
    session_data: dict[tuple[str, str], list[dict[int, Any]]] = {}  # (track, kart) -> list of resampled lap dicts
    track_geometries: dict[str, TrackGeometry] = {}

    for csv_path, meta in session_files:
        logger.info("Processing %s ...", csv_path.name)

        # Single-read: get both raw (for cleaning) and normalised DataFrames.
        result, err = _safe_step(f"read:{csv_path.name}", parse_session_csv_raw, csv_path)
        if result is None:
            continue
        raw, _normalised = result

        cleaned, err = _safe_step(f"clean:{csv_path.name}", clean_and_derive, raw, config)
        if cleaned is None:
            continue

        df = normalize_columns(cleaned)

        laps, err = _safe_step(f"split:{csv_path.name}", split_and_select_laps, df, config)
        if laps is None:
            continue

        resampled, err = _safe_step(f"resample:{csv_path.name}", resample_laps_by_ds, laps, config)
        if resampled is None:
            continue

        filtered, _ = _safe_step(f"outlier:{csv_path.name}", mad_filter_accel, resampled, config)
        if filtered is None:
            filtered = resampled

        # Build geometry
        track_name = meta.track_name or "unknown"
        if track_name not in track_geometries:
            geom, _ = _safe_step(f"geom:{csv_path.name}", build_track_geometry,
                                  filtered, config, track_name)
            if geom:
                track_geometries[track_name] = geom

        key = (track_name, meta.kart_id)
        session_data.setdefault(key, []).append(filtered)

    # Train envelopes per (track, kart)
    results: dict[str, Any] = {"envelopes": {}}
    for (track_name, kart_id), sessions in session_data.items():
        logger.info("Training envelope for (%s, %s) with %d sessions.",
                      track_name, kart_id, len(sessions))
        envelope, err = _safe_step(
            f"train:{track_name}/{kart_id}",
            train_capability_envelope,
            sessions, config, track_name, kart_id,
        )
        if envelope is None:
            continue

        env_path = models_dir / track_name / kart_id / "envelope.json"
        envelope.save(env_path)
        results["envelopes"][f"{track_name}/{kart_id}"] = {
            "path": str(env_path),
            "n_sessions": envelope.n_sessions,
            "n_laps": envelope.n_laps,
            "p_combined": envelope.p_combined,
        }

    # Save track geometries
    for track_name, geom in track_geometries.items():
        geom_dir = tracks_dir / track_name
        geom.save(geom_dir / "geometry.json")

    logger.info("Library training complete: %d envelopes.", len(results["envelopes"]))
    return results
