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

import concurrent.futures
import csv
import json
import logging
import os
import re
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, TypeVar

import numpy as np
import pandas as pd

from kart_envelope.coaching.cause_ranking import (
    generate_coaching_text,
    rank_time_loss_causes,
)
from kart_envelope.coaching.corner_coaching import (
    analyze_corner_performance,
    detect_corners_from_curvature,
)
from kart_envelope.coaching.delta_analysis import compute_delta_map
from kart_envelope.coaching.driver_diagnostics import analyze_driver_dynamics
from kart_envelope.config import KartEnvelopeConfig, default_config, load_config
from kart_envelope.envelope.capability import (
    CapabilityEnvelope,
    train_capability_envelope,
)
from kart_envelope.envelope.grip_map import resolve_grip_scale_profile
from kart_envelope.envelope.tire_stack import (
    apply_tire_runtime_to_envelope,
    build_tire_runtime_meta,
)
from kart_envelope.inference.bundle_v2 import (
    build_lap_feature_frame,
    estimate_optimal_speed_profile,
    resolve_bundle_path,
    run_bundle_inference,
)
from kart_envelope.inference.calibration import build_calibration_report
from kart_envelope.inference.conditions import classify_conditions
from kart_envelope.inference.policy import build_policy_attribution, select_driver_policy
from kart_envelope.inference.session_scalars import SessionScalars, infer_session_scalars
from kart_envelope.inference.validation import build_validation_report
from kart_envelope.ingest.acd_parser import enrich_metadata_from_acd
from kart_envelope.ingest.columns import (
    COL_ACCEL_LAT,
    COL_ACCEL_LONG,
    COL_SPEED,
    COL_YAW_RATE,
    normalize_columns,
)
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.ingest.parser import parse_session_csv, parse_session_csv_raw
from kart_envelope.optimizer.sensitivity import (
    SensitivityRuntimeContext,
    optimize_corner_sensitivity,
    prepare_sensitivity_runtime,
)
from kart_envelope.output.csv_tables import (
    write_corner_recommendations,
    write_corner_sensitivity_table,
    write_corner_table,
    write_corner_whatif_matrix,
    write_delta_map,
    write_driver_diagnostics,
    write_ideal_lap_profile,
    write_sector_summary,
)
from kart_envelope.output.json_summary import build_session_summary, write_session_summary
from kart_envelope.processing.cleaning import clean_and_derive
from kart_envelope.processing.lap_splitting import compute_lap_times, split_and_select_laps
from kart_envelope.processing.outlier_filter import mad_filter_accel
from kart_envelope.processing.resampler import resample_laps_by_ds
from kart_envelope.solver.aero import build_aero_runtime
from kart_envelope.solver.load_transfer_fe import resolve_load_transfer_scale_profile
from kart_envelope.solver.min_time import TheoreticalResult, compute_theoretical_lap
from kart_envelope.solver.powertrain import build_powertrain_runtime
from kart_envelope.solver.record_cal import RecordCalibration, calibrate_to_record
from kart_envelope.solver.vehicle_surrogate import (
    apply_vehicle_dynamics_to_envelope,
    build_vehicle_dynamics_meta,
)
from kart_envelope.tiering import (
    PRODUCT_TIER_B2B_BASIC,
    PRODUCT_TIER_B2B_PREMIUM,
    evaluate_domain_gate,
    resolve_product_tier,
    validate_sensor_contract,
)
from kart_envelope.track.detection import detect_or_register_track
from kart_envelope.track.geometry import TrackGeometry, build_track_geometry
from kart_envelope.track.lidar_profile import resolve_track_surface_profile

try:
    from provenance.run_context import build_provenance as _build_provenance
except ImportError:
    _build_provenance = None

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
# Runtime helpers
# ---------------------------------------------------------------------------

def _apply_fast_inference_overrides(
    config: KartEnvelopeConfig,
    optimize_all_laps: bool,
) -> tuple[KartEnvelopeConfig, bool]:
    """Reduce expensive search dimensions for low-latency inference."""
    if not config.fast_inference_mode:
        return config, optimize_all_laps

    cfg = replace(
        config,
        sensitivity_grid_size=max(3, int(config.fast_inference_grid_size)),
        sensitivity_apex_grid_size=max(1, min(int(config.sensitivity_apex_grid_size), 3)),
        sensitivity_line_grid_size=max(1, min(int(config.sensitivity_line_grid_size), 3)),
        sensitivity_force_grid_size=max(1, int(config.fast_inference_force_grid_size)),
        sensitivity_consistency_iterations=max(1, int(config.fast_inference_consistency_iterations)),
        sensitivity_ml_enable=(
            False if config.fast_inference_disable_ml else bool(config.sensitivity_ml_enable)
        ),
    )
    if cfg.fast_inference_skip_all_laps:
        optimize_all_laps = False
    logger.info(
        "Fast inference mode enabled: grid=%d apex_grid=%d line_grid=%d force_grid=%d consistency=%d ml=%s all_laps=%s",
        cfg.sensitivity_grid_size,
        cfg.sensitivity_apex_grid_size,
        cfg.sensitivity_line_grid_size,
        cfg.sensitivity_force_grid_size,
        cfg.sensitivity_consistency_iterations,
        cfg.sensitivity_ml_enable,
        optimize_all_laps,
    )
    return cfg, optimize_all_laps


def _try_load_cached_session_result(
    csv_path: Path,
    out_dir: Path,
    config: KartEnvelopeConfig,
) -> dict[str, Any] | None:
    if not config.reuse_cached_session_outputs:
        return None

    summary_path = out_dir / "session_summary.json"
    if not summary_path.exists():
        return None

    try:
        src_mtime = float(csv_path.stat().st_mtime)
        out_mtime = float(summary_path.stat().st_mtime)
    except OSError:
        return None

    grace = float(max(config.cache_staleness_grace_s, 0.0))
    if out_mtime + grace < src_mtime:
        return None

    try:
        with open(summary_path, encoding="utf-8") as fh:
            summary = json.load(fh)
    except Exception as exc:
        logger.warning("Failed reading cached summary %s: %s", summary_path, exc)
        return None

    ctx: dict[str, Any] = {"errors": [], "cached": True, "output_dir": str(out_dir)}
    scalars = summary.get("session_scalars", {}) if isinstance(summary, dict) else {}
    if isinstance(scalars, dict):
        ctx["session_scalars"] = {
            "mu": float(scalars.get("mu_session") or 0.0),
            "p": float(scalars.get("p_session") or 0.0),
            "b": float(scalars.get("b_session") or 0.0),
            "condition": str(scalars.get("condition_label") or ""),
        }
    theo = summary.get("theoretical", {}) if isinstance(summary, dict) else {}
    if isinstance(theo, dict) and "lap_time_s" in theo:
        try:
            ctx["theoretical_lap_time_s"] = float(theo["lap_time_s"])
        except (TypeError, ValueError):
            pass
    sens = summary.get("sensitivity", {}) if isinstance(summary, dict) else {}
    if isinstance(sens, dict):
        for src, dst in (
            ("ideal_lap_time_s", "ideal_lap_time_s"),
            ("total_gain_s", "ideal_gain_s"),
            ("ml_enabled", "sensitivity_ml_enabled"),
            ("ml_training_rows", "sensitivity_ml_training_rows"),
            ("ml_used_corners", "sensitivity_ml_used_corners"),
        ):
            if src in sens:
                ctx[dst] = sens.get(src)
        recs = sens.get("recommendations")
        if isinstance(recs, list):
            ctx["sensitivity_top_recommendations"] = recs

    all_opt = summary.get("all_lap_optimal", {}) if isinstance(summary, dict) else {}
    if isinstance(all_opt, dict):
        try:
            ctx["all_lap_optimal_count"] = int(all_opt.get("n_laps", 0))
        except (TypeError, ValueError):
            pass
    if isinstance(summary, dict):
        if "model_version" in summary:
            ctx["model_version"] = summary.get("model_version")
        if "physics_stack_version" in summary:
            ctx["physics_stack_version"] = summary.get("physics_stack_version")
        if isinstance(summary.get("quality_metrics"), dict):
            ctx["quality_metrics"] = summary["quality_metrics"]
        if isinstance(summary.get("confidence_gate"), dict):
            ctx["confidence_gate"] = summary["confidence_gate"]
        for key in (
            "solver_meta",
            "tire_meta",
            "vehicle_meta",
            "powertrain_meta",
            "tier_meta",
            "sensor_validation_meta",
            "domain_gate_meta",
            "track_surface_meta",
            "grip_map_meta",
            "load_transfer_meta",
            "aero_meta",
            "transmission_meta",
            "optimization_meta",
            "policy_meta",
            "validation_meta",
            "calibration_meta",
        ):
            if isinstance(summary.get(key), dict):
                ctx[key] = summary[key]
        if isinstance(summary.get("optimal_v2"), dict):
            opt2 = summary["optimal_v2"]
            if "predicted_optimal_lap_s" in opt2:
                ctx["bundle_v2_optimal_lap_time_s"] = opt2.get("predicted_optimal_lap_s")
            if "predicted_total_gain_s" in opt2:
                ctx["bundle_v2_total_gain_s"] = opt2.get("predicted_total_gain_s")

    logger.info("Using cached outputs from %s", summary_path)
    return ctx


def _compute_quality_metrics(
    filtered_laps: dict[int, pd.DataFrame],
    scalars: SessionScalars,
    config: KartEnvelopeConfig,
) -> dict[str, float]:
    if not filtered_laps:
        return {
            "speed_coverage": 0.0,
            "accel_coverage": 0.0,
            "yaw_coverage": 0.0,
            "lap_count": 0.0,
            "score": 0.0,
        }

    total_rows = 0
    speed_ok = 0
    accel_ok = 0
    yaw_ok = 0
    for lap_df in filtered_laps.values():
        n = int(len(lap_df))
        if n <= 0:
            continue
        total_rows += n

        if COL_SPEED in lap_df.columns:
            speed_ok += int(pd.to_numeric(lap_df[COL_SPEED], errors="coerce").notna().sum())
        if COL_ACCEL_LONG in lap_df.columns and COL_ACCEL_LAT in lap_df.columns:
            ax_ok = pd.to_numeric(lap_df[COL_ACCEL_LONG], errors="coerce").notna()
            ay_ok = pd.to_numeric(lap_df[COL_ACCEL_LAT], errors="coerce").notna()
            accel_ok += int((ax_ok & ay_ok).sum())
        elif COL_ACCEL_LONG in lap_df.columns:
            accel_ok += int(pd.to_numeric(lap_df[COL_ACCEL_LONG], errors="coerce").notna().sum())
        elif COL_ACCEL_LAT in lap_df.columns:
            accel_ok += int(pd.to_numeric(lap_df[COL_ACCEL_LAT], errors="coerce").notna().sum())

        if COL_YAW_RATE in lap_df.columns:
            yaw_ok += int(pd.to_numeric(lap_df[COL_YAW_RATE], errors="coerce").notna().sum())

    denom = max(total_rows, 1)
    speed_cov = float(speed_ok / denom)
    accel_cov = float(accel_ok / denom)
    yaw_cov = float(yaw_ok / denom)
    lap_count = float(len(filtered_laps))
    confidence = float(np.clip(scalars.confidence, 0.0, 1.0))

    speed_norm = np.clip(speed_cov / max(config.quality_min_speed_coverage, 1e-6), 0.0, 1.0)
    accel_norm = np.clip(accel_cov / max(config.quality_min_accel_coverage, 1e-6), 0.0, 1.0)
    yaw_norm = np.clip(yaw_cov / max(config.quality_min_yaw_coverage, 1e-6), 0.0, 1.0)
    laps_norm = np.clip(lap_count / max(float(config.quality_min_laps_for_ml), 1.0), 0.0, 1.0)
    score = float(np.clip(
        0.30 * speed_norm +
        0.25 * accel_norm +
        0.15 * yaw_norm +
        0.20 * confidence +
        0.10 * laps_norm,
        0.0,
        1.0,
    ))

    return {
        "speed_coverage": round(speed_cov, 4),
        "accel_coverage": round(accel_cov, 4),
        "yaw_coverage": round(yaw_cov, 4),
        "lap_count": round(lap_count, 4),
        "score": round(score, 4),
    }


def _apply_confidence_gate(
    config: KartEnvelopeConfig,
    quality_metrics: dict[str, float],
    scalars: SessionScalars,
) -> tuple[KartEnvelopeConfig, dict[str, Any]]:
    gate = {
        "enabled": bool(config.confidence_gate_enable),
        "active": False,
        "threshold": float(config.confidence_gate_threshold),
        "reason": "",
        "pre_ml_enabled": bool(config.sensitivity_ml_enable),
        "post_ml_enabled": bool(config.sensitivity_ml_enable),
        "force_gain_scale": 1.0,
    }
    if not config.confidence_gate_enable:
        return config, gate

    conf = float(np.clip(scalars.confidence, 0.0, 1.0))
    quality = float(np.clip(quality_metrics.get("score", 0.0), 0.0, 1.0))
    trigger = min(conf, quality) < float(config.confidence_gate_threshold)
    if not trigger:
        return config, gate

    scale = float(np.clip(config.confidence_gate_force_gain_scale, 0.4, 1.0))
    new_cfg = replace(
        config,
        sensitivity_lat_force_gain=float(config.sensitivity_lat_force_gain) * scale,
        sensitivity_brake_force_gain=float(config.sensitivity_brake_force_gain) * scale,
        sensitivity_ml_enable=(
            False if config.confidence_gate_disable_ml else bool(config.sensitivity_ml_enable)
        ),
    )
    gate["active"] = True
    gate["reason"] = (
        f"confidence={conf:.3f}, quality={quality:.3f}, "
        f"threshold={config.confidence_gate_threshold:.3f}"
    )
    gate["post_ml_enabled"] = bool(new_cfg.sensitivity_ml_enable)
    gate["force_gain_scale"] = scale
    return new_cfg, gate


def _augment_reliability_with_drift(
    reliability: dict[str, Any],
    metadata: SessionMetadata,
    config: KartEnvelopeConfig,
) -> dict[str, Any]:
    rel = dict(reliability or {})
    rel.setdefault("drift_detected", False)
    rel.setdefault("drift_sigma", 0.0)
    rel.setdefault("drift_reference_n", 0)

    if not config.drift_detection_enable:
        return rel

    hist_path_s = config.reliability_history_csv
    if not hist_path_s:
        return rel

    hist_path = Path(hist_path_s)
    if not hist_path.is_absolute():
        hist_path = Path.cwd() / hist_path
    if not hist_path.exists():
        return rel

    try:
        hist_df = pd.read_csv(hist_path)
    except Exception as exc:
        logger.warning("Failed reading reliability history %s: %s", hist_path, exc)
        return rel
    if hist_df.empty:
        return rel

    for col, value in (
        ("track_name", metadata.track_name),
        ("kart_id", metadata.kart_id),
        ("condition_label", metadata.condition_label),
    ):
        if col in hist_df.columns and value:
            hist_df = hist_df[hist_df[col].astype(str).str.lower() == str(value).lower()]
    if hist_df.empty:
        return rel

    metric_col = "gain_pct" if "gain_pct" in hist_df.columns else None
    if metric_col is None and "gain_s" in hist_df.columns and "actual_lap_time_s" in hist_df.columns:
        denom = pd.to_numeric(hist_df["actual_lap_time_s"], errors="coerce").replace(0.0, np.nan)
        hist_df = hist_df.assign(_gain_pct=100.0 * pd.to_numeric(hist_df["gain_s"], errors="coerce") / denom)
        metric_col = "_gain_pct"
    if metric_col is None:
        return rel

    vals = pd.to_numeric(hist_df[metric_col], errors="coerce").dropna().to_numpy(dtype=float)
    if len(vals) < int(max(config.drift_detection_history_min_sessions, 1)):
        rel["drift_reference_n"] = int(len(vals))
        return rel

    mu = float(np.nanmean(vals))
    sigma = float(np.nanstd(vals))
    sigma = max(sigma, 1e-3)
    current = float(rel.get("gain_pct", 0.0))
    drift_sigma = abs(current - mu) / sigma
    drift_flag = bool(drift_sigma >= float(config.drift_detection_sigma_threshold))

    rel["drift_reference_n"] = int(len(vals))
    rel["drift_mean_gain_pct"] = round(mu, 4)
    rel["drift_sigma_gain_pct"] = round(sigma, 4)
    rel["drift_sigma"] = round(float(drift_sigma), 4)
    rel["drift_detected"] = drift_flag

    if drift_flag and config.drift_retrain_trigger_file:
        _append_retrain_trigger(
            path=Path(config.drift_retrain_trigger_file),
            metadata=metadata,
            drift_sigma=float(drift_sigma),
            current_gain_pct=current,
            reference_mean_pct=mu,
            auto_retrain=bool(config.auto_retrain_on_drift),
        )
    return rel


def _append_retrain_trigger(
    path: Path,
    metadata: SessionMetadata,
    drift_sigma: float,
    current_gain_pct: float,
    reference_mean_pct: float,
    auto_retrain: bool,
) -> None:
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "session_file": metadata.session_file,
        "track_name": metadata.track_name,
        "kart_id": metadata.kart_id,
        "condition_label": metadata.condition_label,
        "drift_sigma": round(float(drift_sigma), 4),
        "current_gain_pct": round(float(current_gain_pct), 4),
        "reference_mean_gain_pct": round(float(reference_mean_pct), 4),
        "auto_retrain": bool(auto_retrain),
    }

    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, list):
                existing = [r for r in raw if isinstance(r, dict)]
        except Exception:
            existing = []
    existing.append(payload)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(existing[-200:], fh, indent=2)


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
    optimize_all_laps: bool = False,
) -> dict[str, Any]:
    """Full single-session analysis pipeline.

    Returns a summary dict with all intermediate results.
    """
    if config is None:
        config = default_config()
    resolved_tier = resolve_product_tier(config.product_tier, metadata.product_tier)
    metadata.product_tier = resolved_tier
    config = replace(config, product_tier=resolved_tier)
    config = replace(
        config,
        sensitivity_target_lap_time_s=_resolve_session_target_lap_time(
            config=config,
            metadata=metadata,
        ),
    )
    config, optimize_all_laps = _apply_fast_inference_overrides(config, optimize_all_laps)
    cached = _try_load_cached_session_result(
        csv_path=csv_path,
        out_dir=output_dir / Path(metadata.session_file).stem,
        config=config,
    )
    if cached is not None:
        return cached

    ctx: dict[str, Any] = {
        "errors": [],
        "model_version": str(config.model_version),
        "physics_stack_version": str(config.physics_stack_version),
        "tier_meta": {
            "product_tier": resolved_tier,
            "deployment_mode": "single_tier_container",
        },
    }

    # 0. Enrich metadata with ACD engine/kart data when available.
    acd_data, _ = _safe_step(
        "acd_enrich",
        enrich_metadata_from_acd,
        metadata,
        csv_path=csv_path,
    )
    if acd_data is not None:
        ctx["acd_engine"] = acd_data.to_dict()

    # 1. Parse CSV - single read returning both raw and normalised DataFrames.
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

    # 3b. Tiered sensor-contract validation.
    sensor_validation = validate_sensor_contract(
        set(df.columns),
        tier=resolved_tier,
        strict=bool(config.tier_enforce_sensor_contract and not config.tier_allow_sensor_fallback),
    )
    if not metadata.sensor_profile:
        metadata.sensor_profile = sensor_validation.inferred_sensor_profile
    ctx["sensor_validation_meta"] = sensor_validation.to_dict()
    if not sensor_validation.passed and bool(config.tier_enforce_sensor_contract):
        ctx["errors"].append(f"sensor_contract: {sensor_validation.reason}")
        return ctx

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

    domain_gate = evaluate_domain_gate(
        tier=resolved_tier,
        track_name=track_id or metadata.track_name,
        kart_id=metadata.kart_id,
        layout_id=metadata.layout_id,
        whitelist_tracks_csv=config.b2b_whitelist_track_ids,
        whitelist_karts_csv=config.b2b_whitelist_kart_ids,
        whitelist_layouts_csv=config.b2b_whitelist_layout_ids,
        soft_gate_enable=bool(config.domain_soft_gate_enable),
    )
    ctx["domain_gate_meta"] = domain_gate.to_dict()
    if domain_gate.soft_gate_triggered:
        ctx["errors"].append(f"domain_soft_gate: {domain_gate.reason}")
    if (resolved_tier in {PRODUCT_TIER_B2B_BASIC, PRODUCT_TIER_B2B_PREMIUM}) and (
        not domain_gate.in_domain and not domain_gate.soft_gate_triggered
    ):
        ctx["errors"].append(f"domain_gate: {domain_gate.reason}")
        return ctx

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
    quality_metrics = _compute_quality_metrics(filtered, scalars, config)
    if domain_gate.soft_gate_triggered:
        quality_metrics = dict(quality_metrics)
        base_score = float(np.clip(quality_metrics.get("score", 0.0), 0.0, 1.0))
        quality_metrics["score_pre_domain_penalty"] = round(base_score, 4)
        quality_metrics["score"] = round(float(np.clip(base_score * 0.75, 0.0, 1.0)), 4)
        quality_metrics["domain_penalty_applied"] = True
    ctx["quality_metrics"] = quality_metrics
    sensitivity_cfg, confidence_gate = _apply_confidence_gate(config, quality_metrics, scalars)
    ctx["confidence_gate"] = confidence_gate

    # Pre-compute best lap for fallback asset resolvers.
    lap_times = compute_lap_times(filtered)
    best_lap_num = min(lap_times, key=lap_times.get) if lap_times else 0
    best_lap_df = filtered.get(best_lap_num)

    # Cycle-B asset interfaces with fallback behavior.
    track_surface_meta: dict[str, Any] = {}
    grip_map_meta: dict[str, Any] = {}
    load_transfer_meta: dict[str, Any] = {}
    lat_profile = np.ones(len(geometry.distance_m), dtype=float)
    drv_profile = np.ones(len(geometry.distance_m), dtype=float)
    brk_profile = np.ones(len(geometry.distance_m), dtype=float)

    surface_res, _ = _safe_step(
        "track_surface_profile",
        resolve_track_surface_profile,
        geometry,
        metadata,
        config,
        fallback_df=best_lap_df,
        tracks_dir=tracks_dir,
    )
    if surface_res is not None:
        _surface_elev, _surface_bank, surface_meta_obj = surface_res
        track_surface_meta = surface_meta_obj.to_dict()
    ctx["track_surface_meta"] = track_surface_meta

    grip_res, _ = _safe_step(
        "grip_map_profile",
        resolve_grip_scale_profile,
        geometry,
        metadata,
        config,
        fallback_df=best_lap_df,
        tracks_dir=tracks_dir,
    )
    if grip_res is not None:
        grip_scale, grip_meta_obj = grip_res
        g = np.asarray(grip_scale, dtype=float)
        lat_profile = np.clip(lat_profile * g, 0.65, 1.20)
        drv_profile = np.clip(drv_profile * g, 0.65, 1.20)
        brk_profile = np.clip(brk_profile * g, 0.65, 1.20)
        grip_map_meta = grip_meta_obj.to_dict()
    ctx["grip_map_meta"] = grip_map_meta

    lt_res, _ = _safe_step(
        "load_transfer_profile",
        resolve_load_transfer_scale_profile,
        geometry,
        metadata,
        config,
        fallback_df=best_lap_df,
        tracks_dir=tracks_dir,
    )
    if lt_res is not None:
        lt_lat, lt_drv, lt_brk, lt_meta_obj = lt_res
        lat_profile = np.clip(lat_profile * np.asarray(lt_lat, dtype=float), 0.65, 1.25)
        drv_profile = np.clip(drv_profile * np.asarray(lt_drv, dtype=float), 0.65, 1.25)
        brk_profile = np.clip(brk_profile * np.asarray(lt_brk, dtype=float), 0.65, 1.25)
        load_transfer_meta = lt_meta_obj.to_dict()
    ctx["load_transfer_meta"] = load_transfer_meta

    # 11b. Cycle-A tire/vehicle/powertrain runtime stack.
    tire_meta, _ = _safe_step(
        "tire_runtime",
        build_tire_runtime_meta,
        filtered,
        metadata,
        scalars,
        config,
    )
    vehicle_meta, _ = _safe_step(
        "vehicle_runtime",
        build_vehicle_dynamics_meta,
        filtered,
        geometry,
        config,
    )
    runtime_envelope = envelope
    if tire_meta is not None:
        runtime_envelope = apply_tire_runtime_to_envelope(runtime_envelope, tire_meta)
        ctx["tire_meta"] = tire_meta.to_dict()
    else:
        ctx["tire_meta"] = {}
    if vehicle_meta is not None:
        runtime_envelope = apply_vehicle_dynamics_to_envelope(runtime_envelope, vehicle_meta)
        ctx["vehicle_meta"] = vehicle_meta.to_dict()
    else:
        ctx["vehicle_meta"] = {}
    powertrain_runtime = build_powertrain_runtime(
        metadata,
        config,
        acd_engine=ctx.get("acd_engine"),
    )
    aero_runtime = build_aero_runtime(
        metadata,
        config,
        condition_label=scalars.condition_label,
    )
    ctx["powertrain_meta"] = powertrain_runtime.to_dict()
    ctx["transmission_meta"] = powertrain_runtime.transmission_meta()
    ctx["aero_meta"] = aero_runtime.to_dict()

    # 12. Compute theoretical lap
    theoretical, err = _safe_step(
        "theoretical_lap",
        compute_theoretical_lap,
        geometry,
        runtime_envelope,
        scalars,
        config,
        metadata,
        ctx.get("acd_engine"),
        powertrain_runtime=powertrain_runtime,
        aero_runtime=aero_runtime,
        lateral_scale_profile=lat_profile,
        drive_scale_profile=drv_profile,
        brake_scale_profile=brk_profile,
    )
    if theoretical is None:
        ctx["errors"].append(f"solver: {err}")
        return ctx

    ctx["theoretical_lap_time_s"] = theoretical.lap_time_s
    ctx["solver_meta"] = dict(theoretical.solver_diagnostics or {})
    ctx["optimization_meta"] = {
        "runtime_online_slowdown_budget": float(config.runtime_online_slowdown_budget),
        "product_tier": resolved_tier,
        "sensor_profile": str(metadata.sensor_profile or ""),
        "domain_soft_gate_triggered": bool(domain_gate.soft_gate_triggered),
        "solver_backend_requested": str(config.solver_backend),
        "solver_backend_used": str(theoretical.solver_backend),
        "ocp_mesh_mode": str(config.solver_ocp_mesh_mode),
        "fallback_to_qss_enabled": bool(config.solver_backend_fallback_to_qss),
        "track_surface_source": str(track_surface_meta.get("source", "disabled")),
        "grip_map_source": str(grip_map_meta.get("source", "disabled")),
        "load_transfer_source": str(load_transfer_meta.get("source", "disabled")),
        "profile_lateral_scale_mean": float(np.nanmean(lat_profile)) if len(lat_profile) else 1.0,
        "profile_drive_scale_mean": float(np.nanmean(drv_profile)) if len(drv_profile) else 1.0,
        "profile_brake_scale_mean": float(np.nanmean(brk_profile)) if len(brk_profile) else 1.0,
    }

    # 13. Record calibration (if provided)
    record_cal: RecordCalibration | None = None
    if metadata.track_record_s is not None and metadata.track_record_s > 0:
        record_cal, _ = _safe_step(
            "record_cal", calibrate_to_record,
            geometry, runtime_envelope, metadata.track_record_s, config,
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

    # 16b. Driver behavior diagnostics (ML + dynamics)
    driver_diagnostics = None
    if best_lap_df is not None:
        driver_diagnostics, _ = _safe_step(
            "driver_diagnostics",
            analyze_driver_dynamics,
            filtered,
            best_lap_df,
            geometry,
            envelope,
            scalars,
            metadata,
            corners,
            config,
        )
        if driver_diagnostics is not None:
            ctx["driver_diagnostics"] = driver_diagnostics.to_dict()

    # 17. Rank causes + coaching text
    causes = rank_time_loss_causes(corner_perfs, top_n=config.coaching_top_corners)
    coaching_text = generate_coaching_text(causes, scalars)
    if driver_diagnostics is not None and driver_diagnostics.findings:
        coaching_text = (
            coaching_text
            + "\n\nDynamics ML diagnostics:\n"
            + driver_diagnostics.to_text(max_items=4)
        )
    ctx["coaching_text"] = coaching_text

    # 17b. Corner sensitivity sweep + ideal-lap assembly
    sensitivity_result = None
    sensitivity_runtime_context: SensitivityRuntimeContext | None = None
    if sensitivity_cfg.sensitivity_enable and best_lap_df is not None and corners:
        sensitivity_runtime_context, _ = _safe_step(
            "corner_sensitivity_prepare",
            prepare_sensitivity_runtime,
            filtered,
            geometry,
            runtime_envelope,
            scalars,
            metadata,
            corners,
            sensitivity_cfg,
        )
        sensitivity_result, _ = _safe_step(
            "corner_sensitivity",
            optimize_corner_sensitivity,
            best_lap_df,
            filtered,
            geometry,
            runtime_envelope,
            scalars,
            metadata,
            corners,
            sensitivity_cfg,
            runtime_context=sensitivity_runtime_context,
        )
        if sensitivity_result is not None:
            reliability = dict(sensitivity_result.reliability or {})
            reliability["quality_score"] = float(quality_metrics.get("score", 0.0))
            reliability["quality_speed_coverage"] = float(quality_metrics.get("speed_coverage", 0.0))
            reliability["quality_accel_coverage"] = float(quality_metrics.get("accel_coverage", 0.0))
            reliability["confidence_gate_active"] = bool(confidence_gate.get("active", False))
            reliability["confidence_gate_reason"] = str(confidence_gate.get("reason", ""))
            reliability = _augment_reliability_with_drift(
                reliability=reliability,
                metadata=metadata,
                config=sensitivity_cfg,
            )
            sensitivity_result.reliability = reliability
            ctx["ideal_lap_time_s"] = sensitivity_result.ideal_lap_time_s
            ctx["ideal_gain_s"] = sensitivity_result.total_gain_s
            ctx["sensitivity_ml_enabled"] = sensitivity_result.ml_enabled
            ctx["sensitivity_ml_training_rows"] = sensitivity_result.ml_training_rows
            ctx["sensitivity_ml_used_corners"] = sensitivity_result.ml_used_corners
            ctx["sensitivity_top_recommendations"] = [
                r.to_dict() for r in sensitivity_result.recommendations
            ]

    # 17bb. Bundle v2 fast inference (offline-trained student models).
    bundle_v2_result = None
    bundle_v2_source = "disabled"
    bundle_v2_dir: Path | None = None
    if config.bundle_v2_enable:
        lookup_track = track_id
        lookup_kart = metadata.kart_id
        if domain_gate.soft_gate_triggered:
            lookup_track = "_global"
            lookup_kart = "_global"
        bundle_v2_dir, bundle_v2_source = resolve_bundle_path(
            lookup_track,
            lookup_kart,
            config,
            product_tier=resolved_tier,
            force_global=bool(domain_gate.soft_gate_triggered),
        )
        ctx["bundle_v2_source"] = bundle_v2_source
        if bundle_v2_dir is not None:
            lap_feat = build_lap_feature_frame(
                filtered_laps=filtered,
                lap_times=lap_times,
                metadata=metadata,
                scalars=scalars,
                quality_metrics=quality_metrics,
                product_tier=resolved_tier,
            )
            if len(lap_feat) >= int(max(1, config.bundle_v2_min_laps)):
                bundle_v2_result, bundle_v2_err = _safe_step(
                    "bundle_v2_infer",
                    run_bundle_inference,
                    bundle_v2_dir,
                    lap_feat,
                    config=config,
                    product_tier=resolved_tier,
                )
                if bundle_v2_result is None and bundle_v2_err:
                    ctx["errors"].append(f"bundle_v2: {bundle_v2_err}")
            else:
                logger.info(
                    "Skipping bundle_v2 inference: only %d lap rows (< %d).",
                    len(lap_feat),
                    int(max(1, config.bundle_v2_min_laps)),
                )
        elif not config.bundle_v2_use_legacy_fallback:
            ctx["errors"].append("bundle_v2: bundle not found and legacy fallback disabled")
            return ctx

    policy_selection = select_driver_policy(
        config=config,
        quality_score=float(quality_metrics.get("score", 0.0)),
        bundle_dir=bundle_v2_dir,
    )
    ctx["policy_meta"] = policy_selection.to_dict()

    if bundle_v2_result is not None:
        for row in bundle_v2_result.lap_rows:
            row["policy"] = policy_selection.selected_policy
            row["policy_confidence"] = round(float(policy_selection.confidence), 4)
            row["policy_source"] = policy_selection.source
        ctx["bundle_v2_optimal_lap_time_s"] = bundle_v2_result.predicted_optimal_lap_s
        ctx["bundle_v2_total_gain_s"] = bundle_v2_result.predicted_total_gain_s

    # 17c. Optional per-lap optimal sweep (all clean laps)
    all_lap_optimal_rows: list[dict[str, Any]] = []
    if (
        optimize_all_laps
        and sensitivity_cfg.sensitivity_enable
        and corners
        and filtered
    ):
        all_lap_optimal_rows = _compute_all_lap_optimal_rows(
            filtered=filtered,
            lap_times=lap_times,
            geometry=geometry,
            envelope=runtime_envelope,
            scalars=scalars,
            metadata=metadata,
            corners=corners,
            config=sensitivity_cfg,
            precomputed_best=sensitivity_result,
            best_lap_num=best_lap_num,
            runtime_context=sensitivity_runtime_context,
        )
        ctx["all_lap_optimal_count"] = len(all_lap_optimal_rows)

    if all_lap_optimal_rows:
        attr = {
            int(r["lap_number"]): r
            for r in build_policy_attribution(
                lap_numbers=[int(row["lap_number"]) for row in all_lap_optimal_rows],
                selection=policy_selection,
            )
        }
        for row in all_lap_optimal_rows:
            row.update(attr.get(int(row["lap_number"]), {}))

    calibration_meta = build_calibration_report(
        metadata=metadata,
        config=config,
        lap_times=lap_times,
        scalars=scalars,
        quality_metrics=quality_metrics,
        sensitivity_result=sensitivity_result,
        bundle_v2_result=bundle_v2_result,
    )
    validation_meta = build_validation_report(
        config=config,
        lap_times=lap_times,
        quality_metrics=quality_metrics,
        calibration_report=calibration_meta,
        all_lap_optimal_rows=all_lap_optimal_rows,
        bundle_lap_rows=(bundle_v2_result.lap_rows if bundle_v2_result is not None else None),
    )
    ctx["calibration_meta"] = calibration_meta
    ctx["validation_meta"] = validation_meta

    # 18. Write outputs
    session_id = Path(metadata.session_file).stem
    out_dir = output_dir / session_id
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = build_session_summary(
        metadata, scalars, theoretical, corner_perfs, causes,
        lap_times, best_lap_num, record_cal, coaching_text,
        driver_diagnostics=(
            driver_diagnostics.to_dict()
            if driver_diagnostics is not None
            else None
        ),
        acd_engine=ctx.get("acd_engine"),
    )
    summary["version"] = "2.2"
    summary["model_version"] = str(config.model_version)
    summary["physics_stack_version"] = str(config.physics_stack_version)
    solver_meta = dict(theoretical.solver_diagnostics or {})
    solver_meta.setdefault("requested_backend", str(config.solver_backend))
    solver_meta.setdefault("used_backend", str(theoretical.solver_backend))
    summary["solver_meta"] = solver_meta
    summary["tire_meta"] = ctx.get("tire_meta", {})
    summary["vehicle_meta"] = ctx.get("vehicle_meta", {})
    summary["powertrain_meta"] = ctx.get("powertrain_meta", {})
    summary["tier_meta"] = ctx.get("tier_meta", {})
    summary["sensor_validation_meta"] = ctx.get("sensor_validation_meta", {})
    summary["domain_gate_meta"] = ctx.get("domain_gate_meta", {})
    summary["track_surface_meta"] = ctx.get("track_surface_meta", {})
    summary["grip_map_meta"] = ctx.get("grip_map_meta", {})
    summary["load_transfer_meta"] = ctx.get("load_transfer_meta", {})
    summary["aero_meta"] = ctx.get("aero_meta", {})
    summary["transmission_meta"] = ctx.get("transmission_meta", {})
    summary["optimization_meta"] = ctx.get("optimization_meta", {})
    summary["policy_meta"] = policy_selection.to_dict()
    summary["calibration_meta"] = calibration_meta
    summary["validation_meta"] = validation_meta
    if sensitivity_result is not None:
        summary["sensitivity"] = sensitivity_result.to_dict()
    summary["quality_metrics"] = quality_metrics
    summary["confidence_gate"] = confidence_gate
    if bundle_v2_result is not None:
        summary["model_bundle_v2"] = {
            "bundle_path": str(bundle_v2_dir) if bundle_v2_dir is not None else "",
            "resolution_source": bundle_v2_source,
            "method": bundle_v2_result.method,
            "model_confidence": round(float(bundle_v2_result.model_confidence), 4),
            "product_tier": bundle_v2_result.product_tier,
            "tier_schema_used": bundle_v2_result.tier_schema_used,
            "policy_selection": policy_selection.selected_policy,
        }
        summary["optimal_v2"] = {
            "best_actual_lap_s": round(float(bundle_v2_result.best_actual_lap_s), 4),
            "predicted_optimal_lap_s": round(float(bundle_v2_result.predicted_optimal_lap_s), 4),
            "predicted_total_gain_s": round(float(bundle_v2_result.predicted_total_gain_s), 4),
            "n_laps": int(bundle_v2_result.n_laps),
            "lap_rows_csv": "all_laps_optimal_v2.csv",
        }
        summary["diagnostics_v2"] = bundle_v2_result.diagnostics_summary
        summary["uncertainty_v2"] = {
            "low_s": (
                round(float(bundle_v2_result.uncertainty_low_s), 4)
                if bundle_v2_result.uncertainty_low_s is not None
                else None
            ),
            "high_s": (
                round(float(bundle_v2_result.uncertainty_high_s), 4)
                if bundle_v2_result.uncertainty_high_s is not None
                else None
            ),
        }
        summary["calibration_v2"] = bundle_v2_result.calibration_summary
    if all_lap_optimal_rows:
        summary["all_lap_optimal"] = {
            "n_laps": len(all_lap_optimal_rows),
            "best_gain_s": round(
                max(float(r["gain_s"]) for r in all_lap_optimal_rows),
                4,
            ),
            "mean_gain_s": round(
                float(np.mean([float(r["gain_s"]) for r in all_lap_optimal_rows])),
                4,
            ),
        }
    # ── Provenance ──────────────────────────────────────────────
    if _build_provenance is not None:
        try:
            _first_lap_df = next(iter(filtered.values())) if filtered else pd.DataFrame()
            _provenance_record = _build_provenance(
                input_df=_first_lap_df,
                config={
                    "model_version": str(config.model_version),
                    "solver_backend": str(config.solver_backend),
                    "physics_stack_version": str(config.physics_stack_version),
                },
                method_used="kart_envelope_v2.2",
                file_path=str(metadata.session_file) if metadata and hasattr(metadata, "session_file") else None,
                pipeline_version=summary.get("version", "2.2"),
                model_version=str(config.model_version),
                solver_version=str(theoretical.solver_backend) if theoretical and hasattr(theoretical, "solver_backend") else None,
            )
            summary["provenance"] = _provenance_record.to_dict()
        except Exception as _prov_err:
            logging.getLogger(__name__).debug("Provenance generation skipped: %s", _prov_err)

    write_session_summary(summary, out_dir / "session_summary.json")

    if delta_map is not None:
        write_delta_map(delta_map, out_dir / "delta_map.csv")

    if corner_perfs:
        write_corner_table(corner_perfs, out_dir / "corner_table.csv")

    if driver_diagnostics is not None:
        write_driver_diagnostics(
            [f.to_dict() for f in driver_diagnostics.findings],
            out_dir / "driver_diagnostics_findings.csv",
        )
        write_driver_diagnostics(
            driver_diagnostics.lap_metrics,
            out_dir / "driver_diagnostics_laps.csv",
        )
        write_driver_diagnostics(
            driver_diagnostics.corner_metrics,
            out_dir / "driver_diagnostics_corners.csv",
        )

    if sensitivity_result is not None:
        write_corner_sensitivity_table(
            sensitivity_result.candidate_rows,
            out_dir / "corner_sensitivity.csv",
        )
        write_corner_whatif_matrix(
            sensitivity_result.candidate_rows,
            out_dir / "corner_whatif_matrix.csv",
        )
        write_corner_recommendations(
            [r.to_dict() for r in sensitivity_result.recommendations],
            out_dir / "corner_recommendations.csv",
        )
        write_ideal_lap_profile(
            sensitivity_result.distance_m,
            sensitivity_result.baseline_speed_mps,
            sensitivity_result.ideal_speed_mps,
            out_dir / "ideal_lap_profile.csv",
        )
        write_sector_summary(
            sensitivity_result.sector_rows,
            out_dir / "sector_summary.csv",
        )

    if all_lap_optimal_rows:
        pd.DataFrame(all_lap_optimal_rows).to_csv(
            out_dir / "all_laps_optimal.csv",
            index=False,
        )
    if bundle_v2_result is not None:
        pd.DataFrame(bundle_v2_result.lap_rows).to_csv(
            out_dir / "all_laps_optimal_v2.csv",
            index=False,
        )

    if sensitivity_result is not None and best_lap_num in lap_times:
        _write_web_optimal_vs_best_outputs(
            out_dir=out_dir,
            session_id=session_id,
            best_lap_num=int(best_lap_num),
            best_lap_time_s=float(lap_times[best_lap_num]),
            sensitivity_result=sensitivity_result,
            target_lap_time_s=sensitivity_cfg.sensitivity_target_lap_time_s,
            solver_meta=summary.get("solver_meta", {}),
            tier_meta=summary.get("tier_meta", {}),
            sensor_validation_meta=summary.get("sensor_validation_meta", {}),
            domain_gate_meta=summary.get("domain_gate_meta", {}),
            policy_meta=summary.get("policy_meta", {}),
            validation_meta=summary.get("validation_meta", {}),
            track_surface_meta=summary.get("track_surface_meta", {}),
            grip_map_meta=summary.get("grip_map_meta", {}),
            load_transfer_meta=summary.get("load_transfer_meta", {}),
            aero_meta=summary.get("aero_meta", {}),
            transmission_meta=summary.get("transmission_meta", {}),
            optimization_meta=summary.get("optimization_meta", {}),
        )
    if bundle_v2_result is not None:
        _write_web_optimal_vs_best_outputs_v2(
            out_dir=out_dir,
            session_id=session_id,
            best_lap_num=int(best_lap_num),
            best_lap_time_s=float(lap_times.get(best_lap_num, bundle_v2_result.best_actual_lap_s)),
            bundle_v2_result=bundle_v2_result,
            distance=(
                np.asarray(sensitivity_result.distance_m, dtype=float)
                if sensitivity_result is not None
                else np.asarray(geometry.distance_m, dtype=float)
            ),
            baseline_speed=(
                np.asarray(sensitivity_result.baseline_speed_mps, dtype=float)
                if sensitivity_result is not None
                else _best_lap_speed_on_distance(best_lap_df, np.asarray(geometry.distance_m, dtype=float))
            ),
            target_lap_time_s=sensitivity_cfg.sensitivity_target_lap_time_s,
            sensitivity_result=sensitivity_result,
            corners=list(corners or []),
            smoothing_enable=bool(sensitivity_cfg.optimal_profile_smoothing_enable),
            smoothing_window_m=float(sensitivity_cfg.optimal_profile_smoothing_window_m),
            smoothing_passes=int(sensitivity_cfg.optimal_profile_smoothing_passes),
            smoothing_preserve_lap_time=bool(sensitivity_cfg.optimal_profile_smoothing_preserve_lap_time),
            solver_meta=summary.get("solver_meta", {}),
            tier_meta=summary.get("tier_meta", {}),
            sensor_validation_meta=summary.get("sensor_validation_meta", {}),
            domain_gate_meta=summary.get("domain_gate_meta", {}),
            policy_meta=summary.get("policy_meta", {}),
            validation_meta=summary.get("validation_meta", {}),
            track_surface_meta=summary.get("track_surface_meta", {}),
            grip_map_meta=summary.get("grip_map_meta", {}),
            load_transfer_meta=summary.get("load_transfer_meta", {}),
            aero_meta=summary.get("aero_meta", {}),
            transmission_meta=summary.get("transmission_meta", {}),
            optimization_meta=summary.get("optimization_meta", {}),
        )

    ctx["output_dir"] = str(out_dir)
    logger.info("Session analysis complete. Outputs in %s", out_dir)
    return ctx


def _resolve_session_target_lap_time(
    config: KartEnvelopeConfig,
    metadata: SessionMetadata,
) -> float | None:
    """
    Resolve sensitivity target lap time for this session.

    Rule:
    - If a track record exists, use the slower of:
      1) configured target (if any), and
      2) track record.
      This keeps the user-provided floor (e.g. 43.4 s) while avoiding
      applying that same value to much longer tracks.
    - If no track record exists, keep configured target as-is.
    """
    cfg_target = config.sensitivity_target_lap_time_s

    table_target = _lookup_condition_target_lap_time(config, metadata)
    if table_target is not None:
        return table_target

    rec = getattr(metadata, "track_record_s", None)
    if rec is None or rec <= 0:
        return cfg_target
    if cfg_target is None:
        return float(rec)
    return float(max(float(cfg_target), float(rec)))


def _lookup_condition_target_lap_time(
    config: KartEnvelopeConfig,
    metadata: SessionMetadata,
) -> float | None:
    """Lookup explicit target from data/condition_targets.csv (track + condition)."""
    path_s = getattr(config, "sensitivity_condition_targets_csv", None)
    if not path_s:
        return None

    path = Path(path_s)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return None

    targets = _load_condition_targets(path)
    if not targets:
        return None

    track = _norm_key(metadata.track_name)
    cond = _norm_condition(metadata.condition_label)
    if not track or not cond:
        return None

    exact = targets.get((track, cond))
    if exact is not None:
        return float(exact)

    # Optional fallback for dry sessions if only "ideal dry" is provided.
    if cond == "dry":
        ideal_dry = targets.get((track, "ideal dry"))
        if ideal_dry is not None:
            return float(ideal_dry)
    return None


def _load_condition_targets(path: Path) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(2048)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(fh, dialect=dialect)
            for row in reader:
                track = _norm_key(row.get("track"))
                cond = _norm_condition(row.get("condition"))
                raw_target = row.get("target_lap_s")
                target = _parse_target_time_seconds(raw_target)
                if not track or not cond or target is None or target <= 0:
                    continue
                out[(track, cond)] = float(target)
    except Exception as exc:
        logger.warning("Failed reading condition target file %s: %s", path, exc)
        return {}
    return out


def _norm_key(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _norm_condition(value: Any) -> str:
    s = _norm_key(value).replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    aliases = {
        "idealdry": "ideal dry",
        "ideal dry": "ideal dry",
    }
    return aliases.get(s, s)


def _parse_target_time_seconds(value: Any) -> float | None:
    """Parse flexible target formats (seconds or minute/second strings)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            out = float(value)
            return out if out > 0 else None
        except (TypeError, ValueError):
            return None

    s = str(value).strip().lower()
    if not s:
        return None

    s = s.replace(" ", "")
    s = s.replace(",", ".")
    s = s.replace("'", ":").replace('"', ":")

    # mm:ss:ms
    if re.fullmatch(r"\d+:\d{1,2}:\d{1,3}", s):
        mm_s, ss_s, ms_s = s.split(":")
        mm = int(mm_s)
        ss = int(ss_s)
        if ss >= 60:
            return None
        ms = int(ms_s)
        return float(mm * 60 + ss + (ms / (10 ** len(ms_s))))

    # mm:ss(.sss)
    if re.fullmatch(r"\d+:\d{1,2}(\.\d+)?", s):
        mm_s, sec_s = s.split(":")
        mm = int(mm_s)
        sec = float(sec_s)
        if sec >= 60:
            return None
        return float(mm * 60 + sec)

    # mm.ss.mmm (or compact typo form like 1.134.4 -> 1:13.44)
    if re.fullmatch(r"\d+\.\d{1,3}\.\d{1,3}", s):
        mm_s, ss_s, frac_s = s.split(".")
        mm = int(mm_s)
        if len(ss_s) <= 2:
            ss = int(ss_s)
            frac_digits = frac_s
        else:
            ss = int(ss_s[:2])
            frac_digits = ss_s[2:] + frac_s
        if ss < 60:
            frac = int(frac_digits) / (10 ** len(frac_digits)) if frac_digits else 0.0
            return float(mm * 60 + ss + frac)

    # Plain seconds.
    try:
        out = float(s)
        return out if out > 0 else None
    except ValueError:
        return None


def _compute_all_lap_optimal_rows(
    filtered: dict[int, pd.DataFrame],
    lap_times: dict[int, float],
    geometry: TrackGeometry,
    envelope: CapabilityEnvelope,
    scalars: SessionScalars,
    metadata: SessionMetadata,
    corners: list[dict[str, Any]],
    config: KartEnvelopeConfig,
    precomputed_best: Any | None = None,
    best_lap_num: int | None = None,
    runtime_context: SensitivityRuntimeContext | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    batch_cfg = replace(
        config,
        sensitivity_two_stage_search=False,
        sensitivity_grid_size=max(5, min(int(config.sensitivity_grid_size), 7)),
        sensitivity_apex_grid_size=1,
        sensitivity_line_grid_size=1,
        sensitivity_force_grid_size=max(3, min(int(config.sensitivity_force_grid_size), 3)),
        sensitivity_consistency_iterations=max(1, min(int(config.sensitivity_consistency_iterations), 2)),
        sensitivity_target_grid_size=max(3, min(int(config.sensitivity_target_grid_size), 5)),
        sensitivity_top_recommendations=max(1, min(int(config.sensitivity_top_recommendations), 2)),
        sensitivity_target_lap_time_s=None,
    )
    batch_runtime_context, _ = _safe_step(
        "corner_sensitivity_prepare_all_laps",
        prepare_sensitivity_runtime,
        filtered,
        geometry,
        envelope,
        scalars,
        metadata,
        corners,
        batch_cfg,
    )
    lap_numbers = sorted(filtered.keys())

    def _row_from_result(lap_num: int, lap_result: Any) -> dict[str, Any]:
        baseline_time = float(lap_times.get(lap_num, lap_result.baseline_lap_time_s))
        optimal_time = float(lap_result.ideal_lap_time_s)
        gain_s = max(0.0, baseline_time - optimal_time)
        gain_pct = (100.0 * gain_s / baseline_time) if baseline_time > 1e-9 else 0.0
        return {
            "lap_number": int(lap_num),
            "actual_lap_time_s": round(baseline_time, 4),
            "optimal_lap_time_s": round(optimal_time, 4),
            "gain_s": round(gain_s, 4),
            "gain_pct": round(gain_pct, 4),
            "accepted_count": int(lap_result.accepted_count),
            "evaluated_count": int(lap_result.evaluated_count),
            "target_status": lap_result.target_status,
            "target_gap_s": (
                round(float(lap_result.target_gap_s), 4)
                if lap_result.target_gap_s is not None
                else None
            ),
            "target_force_scale": round(float(lap_result.target_force_scale), 4),
            "ml_enabled": bool(lap_result.ml_enabled),
            "ml_training_rows": int(lap_result.ml_training_rows),
            "ml_used_corners": int(lap_result.ml_used_corners),
            "envelope_source": lap_result.envelope_source,
        }

    def _run_lap(lap_num: int) -> dict[str, Any] | None:
        lap_df = filtered.get(lap_num)
        if lap_df is None or len(lap_df) < 20:
            return None

        lap_result = None
        if precomputed_best is not None and best_lap_num is not None and int(lap_num) == int(best_lap_num):
            lap_result = precomputed_best
        elif best_lap_num is not None and int(lap_num) == int(best_lap_num):
            lap_result, _ = _safe_step(
                f"corner_sensitivity_lap_{lap_num}",
                optimize_corner_sensitivity,
                lap_df,
                filtered,
                geometry,
                envelope,
                scalars,
                metadata,
                corners,
                config,
                runtime_context=runtime_context,
            )
        else:
            lap_result, _ = _safe_step(
                f"corner_sensitivity_lap_{lap_num}",
                optimize_corner_sensitivity,
                lap_df,
                filtered,
                geometry,
                envelope,
                scalars,
                metadata,
                corners,
                batch_cfg,
                runtime_context=batch_runtime_context,
            )
        if lap_result is None:
            return None
        return _row_from_result(lap_num, lap_result)

    use_parallel = bool(config.sensitivity_parallel_laps) and len(lap_numbers) > 1
    if use_parallel:
        workers = int(config.sensitivity_parallel_workers)
        if workers <= 0:
            workers = max(1, min(8, (os.cpu_count() or 1)))
        logger.info("All-lap optimal: parallel mode with %d worker(s).", workers)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            fut_map = {ex.submit(_run_lap, lap_num): lap_num for lap_num in lap_numbers}
            for fut in concurrent.futures.as_completed(fut_map):
                lap_num = fut_map[fut]
                try:
                    row = fut.result()
                except Exception as exc:
                    logger.warning("All-lap optimal failed for lap %s: %s", lap_num, exc)
                    continue
                if row is not None:
                    rows.append(row)
        rows.sort(key=lambda r: int(r["lap_number"]))
    else:
        for lap_num in lap_numbers:
            row = _run_lap(lap_num)
            if row is not None:
                rows.append(row)
    return rows


def _write_web_optimal_vs_best_outputs(
    out_dir: Path,
    session_id: str,
    best_lap_num: int,
    best_lap_time_s: float,
    sensitivity_result: Any,
    target_lap_time_s: float | None,
    solver_meta: dict[str, Any] | None = None,
    tier_meta: dict[str, Any] | None = None,
    sensor_validation_meta: dict[str, Any] | None = None,
    domain_gate_meta: dict[str, Any] | None = None,
    policy_meta: dict[str, Any] | None = None,
    validation_meta: dict[str, Any] | None = None,
    track_surface_meta: dict[str, Any] | None = None,
    grip_map_meta: dict[str, Any] | None = None,
    load_transfer_meta: dict[str, Any] | None = None,
    aero_meta: dict[str, Any] | None = None,
    transmission_meta: dict[str, Any] | None = None,
    optimization_meta: dict[str, Any] | None = None,
) -> None:
    distance = np.asarray(sensitivity_result.distance_m, dtype=float)
    baseline_speed = np.asarray(sensitivity_result.baseline_speed_mps, dtype=float)
    ideal_speed = np.asarray(sensitivity_result.ideal_speed_mps, dtype=float)
    if len(distance) == 0:
        return

    profile_path = out_dir / "web_optimal_vs_best_profile.csv"
    profile_df = pd.DataFrame({
        "distance_m": distance,
        "best_speed_mps": baseline_speed,
        "optimal_speed_mps": ideal_speed,
        "speed_delta_mps": ideal_speed - baseline_speed,
    })
    profile_df.to_csv(profile_path, index=False)

    optimal_lap_time_s = float(sensitivity_result.ideal_lap_time_s)
    gain_s = max(0.0, float(best_lap_time_s) - optimal_lap_time_s)
    gain_pct_vs_optimal = 100.0 * gain_s / optimal_lap_time_s if optimal_lap_time_s > 1e-9 else 0.0
    method = "sensitivity_ml_rollout" if sensitivity_result.ml_enabled else "sensitivity_rollout"

    summary = {
        "session_id": session_id,
        "best_lap_number": int(best_lap_num),
        "best_lap_time_s": round(float(best_lap_time_s), 4),
        "optimal_lap_time_s": round(optimal_lap_time_s, 4),
        "time_gain_s": round(gain_s, 4),
        "gain_pct_vs_optimal": round(gain_pct_vs_optimal, 4),
        "simulation_method": method,
        "profile_points": int(len(distance)),
        "profile_csv": str(profile_path).replace("\\", "/"),
        "view_url": f"http://127.0.0.1:5000/visualize/{session_id}",
        "api_speed_trace": f"/api/session/{session_id}/speed_trace",
        "api_theoretical": f"/api/session/{session_id}/theoretical",
        "target_status": sensitivity_result.target_status,
        "target_lap_time_s": (
            round(float(target_lap_time_s), 4)
            if target_lap_time_s is not None
            else None
        ),
        "uncertainty_lap_time_low_s": (
            round(float(sensitivity_result.uncertainty_lap_time_low_s), 4)
            if getattr(sensitivity_result, "uncertainty_lap_time_low_s", None) is not None
            else None
        ),
        "uncertainty_lap_time_high_s": (
            round(float(sensitivity_result.uncertainty_lap_time_high_s), 4)
            if getattr(sensitivity_result, "uncertainty_lap_time_high_s", None) is not None
            else None
        ),
        "reliability": getattr(sensitivity_result, "reliability", {}) or {},
        "solver_meta": solver_meta or {},
        "tier_meta": tier_meta or {},
        "sensor_validation_meta": sensor_validation_meta or {},
        "domain_gate_meta": domain_gate_meta or {},
        "policy_meta": policy_meta or {},
        "validation_meta": validation_meta or {},
        "track_surface_meta": track_surface_meta or {},
        "grip_map_meta": grip_map_meta or {},
        "load_transfer_meta": load_transfer_meta or {},
        "aero_meta": aero_meta or {},
        "transmission_meta": transmission_meta or {},
        "optimization_meta": optimization_meta or {},
    }
    with open(out_dir / "web_optimal_vs_best_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)


def _best_lap_speed_on_distance(best_lap_df: pd.DataFrame | None, distance: np.ndarray) -> np.ndarray:
    if best_lap_df is None or len(distance) == 0:
        return np.full_like(distance, 0.5, dtype=float)
    if "distance_m" not in best_lap_df.columns or "speed_mps" not in best_lap_df.columns:
        return np.full_like(distance, 0.5, dtype=float)
    s = pd.to_numeric(best_lap_df["distance_m"], errors="coerce").to_numpy(dtype=float)
    v = pd.to_numeric(best_lap_df["speed_mps"], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(s) & np.isfinite(v)
    if np.sum(mask) < 2:
        return np.full_like(distance, 0.5, dtype=float)
    s = s[mask]
    v = v[mask]
    order = np.argsort(s)
    s = s[order]
    v = v[order]
    s, keep = np.unique(s, return_index=True)
    v = v[keep]
    return np.interp(distance, s, v, left=float(v[0]), right=float(v[-1]))


def _write_web_optimal_vs_best_outputs_v2(
    out_dir: Path,
    session_id: str,
    best_lap_num: int,
    best_lap_time_s: float,
    bundle_v2_result: Any,
    distance: np.ndarray,
    baseline_speed: np.ndarray,
    target_lap_time_s: float | None = None,
    sensitivity_result: Any | None = None,
    corners: list[dict[str, Any]] | None = None,
    smoothing_enable: bool = True,
    smoothing_window_m: float = 5.0,
    smoothing_passes: int = 2,
    smoothing_preserve_lap_time: bool = True,
    solver_meta: dict[str, Any] | None = None,
    tier_meta: dict[str, Any] | None = None,
    sensor_validation_meta: dict[str, Any] | None = None,
    domain_gate_meta: dict[str, Any] | None = None,
    policy_meta: dict[str, Any] | None = None,
    validation_meta: dict[str, Any] | None = None,
    track_surface_meta: dict[str, Any] | None = None,
    grip_map_meta: dict[str, Any] | None = None,
    load_transfer_meta: dict[str, Any] | None = None,
    aero_meta: dict[str, Any] | None = None,
    transmission_meta: dict[str, Any] | None = None,
    optimization_meta: dict[str, Any] | None = None,
) -> None:
    distance = np.asarray(distance, dtype=float)
    baseline_speed = np.asarray(baseline_speed, dtype=float)
    if len(distance) == 0 or len(baseline_speed) == 0:
        return
    if len(baseline_speed) != len(distance):
        baseline_speed = np.interp(
            distance,
            np.linspace(float(distance[0]), float(distance[-1]), len(baseline_speed)),
            baseline_speed,
        )
    sensitivity_template = None
    corner_recommendations: list[dict[str, Any]] = []
    if sensitivity_result is not None:
        try:
            sensitivity_template = np.asarray(
                getattr(sensitivity_result, "ideal_speed_mps", []),
                dtype=float,
            )
        except Exception:
            sensitivity_template = None
        recs = getattr(sensitivity_result, "recommendations", None)
        if isinstance(recs, list):
            for rec in recs:
                if hasattr(rec, "to_dict"):
                    try:
                        corner_recommendations.append(dict(rec.to_dict()))
                    except Exception:
                        continue
                elif isinstance(rec, dict):
                    corner_recommendations.append(dict(rec))
    model_optimal_lap_time_s = float(bundle_v2_result.predicted_optimal_lap_s)
    profile_optimal_lap_time_s = float(model_optimal_lap_time_s)
    if target_lap_time_s is not None and np.isfinite(float(target_lap_time_s)) and float(target_lap_time_s) > 0:
        profile_optimal_lap_time_s = min(profile_optimal_lap_time_s, float(target_lap_time_s))
    target_override_applied = profile_optimal_lap_time_s < model_optimal_lap_time_s - 1e-6

    optimal_speed = estimate_optimal_speed_profile(
        baseline_speed_mps=baseline_speed,
        best_actual_lap_s=float(best_lap_time_s),
        predicted_optimal_lap_s=float(profile_optimal_lap_time_s),
        distance_m=distance,
        sensitivity_template_speed_mps=sensitivity_template,
        corner_recommendations=corner_recommendations,
        corners=list(corners or []),
        smoothing_enable=bool(smoothing_enable),
        smoothing_window_m=float(smoothing_window_m),
        smoothing_passes=int(smoothing_passes),
        smoothing_preserve_lap_time=bool(smoothing_preserve_lap_time),
    )

    profile_path = out_dir / "web_optimal_vs_best_profile_v2.csv"
    pd.DataFrame({
        "distance_m": distance,
        "best_speed_mps": baseline_speed,
        "optimal_speed_mps": optimal_speed,
        "speed_delta_mps": optimal_speed - baseline_speed,
    }).to_csv(profile_path, index=False)

    optimal_lap_time_s = float(profile_optimal_lap_time_s)
    gain_s = max(0.0, float(best_lap_time_s) - optimal_lap_time_s)
    gain_pct_vs_optimal = 100.0 * gain_s / optimal_lap_time_s if optimal_lap_time_s > 1e-9 else 0.0
    summary = {
        "session_id": session_id,
        "best_lap_number": int(best_lap_num),
        "best_lap_time_s": round(float(best_lap_time_s), 4),
        "optimal_lap_time_s": round(optimal_lap_time_s, 4),
        "time_gain_s": round(gain_s, 4),
        "gain_pct_vs_optimal": round(gain_pct_vs_optimal, 4),
        "simulation_method": "bundle_v2_student",
        "profile_points": int(len(distance)),
        "profile_csv": str(profile_path).replace("\\", "/"),
        "view_url": f"http://127.0.0.1:5000/visualize/{session_id}",
        "api_speed_trace": f"/api/session/{session_id}/speed_trace",
        "api_theoretical": f"/api/session/{session_id}/theoretical",
        "model_predicted_optimal_lap_time_s": round(float(model_optimal_lap_time_s), 4),
        "target_lap_time_s": (
            round(float(target_lap_time_s), 4)
            if target_lap_time_s is not None and np.isfinite(float(target_lap_time_s))
            else None
        ),
        "target_override_applied": bool(target_override_applied),
        "model_confidence": round(float(bundle_v2_result.model_confidence), 4),
        "uncertainty_lap_time_low_s": (
            round(float(bundle_v2_result.uncertainty_low_s), 4)
            if bundle_v2_result.uncertainty_low_s is not None
            else None
        ),
        "uncertainty_lap_time_high_s": (
            round(float(bundle_v2_result.uncertainty_high_s), 4)
            if bundle_v2_result.uncertainty_high_s is not None
            else None
        ),
        "diagnostics_summary": bundle_v2_result.diagnostics_summary,
        "calibration_summary": bundle_v2_result.calibration_summary,
        "gate_summary": bundle_v2_result.gate_summary,
        "solver_meta": solver_meta or {},
        "tier_meta": tier_meta or {},
        "sensor_validation_meta": sensor_validation_meta or {},
        "domain_gate_meta": domain_gate_meta or {},
        "policy_meta": policy_meta or {},
        "validation_meta": validation_meta or {},
        "track_surface_meta": track_surface_meta or {},
        "grip_map_meta": grip_map_meta or {},
        "load_transfer_meta": load_transfer_meta or {},
        "aero_meta": aero_meta or {},
        "transmission_meta": transmission_meta or {},
        "optimization_meta": optimization_meta or {},
    }
    with open(out_dir / "web_optimal_vs_best_summary_v2.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)


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
