"""
dataset_builder.py
------------------
Builds a canonical offline training dataset from existing per-session outputs.

This module is intentionally I/O focused: the heavy modeling is done in
``teacher_train.py`` and ``distill_student.py``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.ingest.metadata import SessionMetadata, parse_metadata
from kart_envelope.tiering import (
    PRODUCT_TIER_B2B_BASIC,
    PRODUCT_TIER_B2B_PREMIUM,
    PRODUCT_TIER_B2C,
    normalize_product_tier,
)

logger = logging.getLogger(__name__)


NUMERIC_FEATURE_COLUMNS: list[str] = [
    "actual_lap_time_s",
    "gain_pct",
    "accepted_count",
    "evaluated_count",
    "target_force_scale",
    "ml_training_rows",
    "ml_used_corners",
    "session_mu",
    "session_p",
    "session_b",
    "session_confidence",
    "quality_score",
    "quality_speed_coverage",
    "quality_accel_coverage",
    "quality_yaw_coverage",
    "driver_weight_kg",
    "kart_weight_kg",
    "engine_peak_power_kw",
    "engine_size_cc",
    "track_record_s",
    "speed_mean_mps",
    "speed_max_mps",
    "speed_std_mps",
    "brake_peak_mps2",
    "lat_peak_mps2",
    "yaw_std_dps",
    "heading_std_deg",
    "grade_abs_mean_pct",
    "bank_abs_mean_deg",
    "steering_abs_mean_deg",
    "steering_rate_std_degps",
    "steering_jerk_std_degps2",
    "throttle_mean_pct",
    "throttle_reapply_delay_s",
    "brake_peak_pct",
    "brake_onset_rate_pctps",
    "trail_brake_fraction",
    "countersteer_proxy",
]


CATEGORICAL_FEATURE_COLUMNS: list[str] = [
    "track_name",
    "kart_id",
    "kart_class",
    "condition_label",
    "layout_id",
    "product_tier",
    "sensor_profile",
    "domain_whitelist_id",
    "envelope_source",
    "target_status",
    "tire_type",
]


TARGET_COLUMNS: list[str] = [
    "optimal_lap_time_s",
    "gain_s",
]


DIAGNOSTIC_CODES: list[str] = [
    "underdriving",
    "overdriving",
    "underbraking",
    "overbraking",
    "coasting",
    "apex_timing",
    "line_inconsistency",
    "entry_hesitation",
    "yaw_countersteer_instability",
    "crest_banking_sensitivity",
    "poor_apex_exit_carry",
]


TIER_NUMERIC_MASKS: dict[str, set[str]] = {
    PRODUCT_TIER_B2C: {
        *NUMERIC_FEATURE_COLUMNS,
    },
    PRODUCT_TIER_B2B_BASIC: {
        *NUMERIC_FEATURE_COLUMNS,
    },
    PRODUCT_TIER_B2B_PREMIUM: {
        *NUMERIC_FEATURE_COLUMNS,
    },
}
# Premium-only control channels are excluded from B2C/B2B basic training.
for _tier in (PRODUCT_TIER_B2C, PRODUCT_TIER_B2B_BASIC):
    TIER_NUMERIC_MASKS[_tier].difference_update(
        {
            "steering_abs_mean_deg",
            "steering_rate_std_degps",
            "steering_jerk_std_degps2",
            "throttle_mean_pct",
            "throttle_reapply_delay_s",
            "brake_peak_pct",
            "brake_onset_rate_pctps",
            "trail_brake_fraction",
            "countersteer_proxy",
        }
    )

TIER_CATEGORICAL_MASKS: dict[str, set[str]] = {
    PRODUCT_TIER_B2C: set(CATEGORICAL_FEATURE_COLUMNS),
    PRODUCT_TIER_B2B_BASIC: set(CATEGORICAL_FEATURE_COLUMNS),
    PRODUCT_TIER_B2B_PREMIUM: set(CATEGORICAL_FEATURE_COLUMNS),
}


def build_training_dataset(
    metadata_path: Path,
    outputs_dir: Path,
    output_path: Path,
    *,
    min_rows: int = 1,
) -> pd.DataFrame:
    """
    Build and persist the offline dataset from existing output artifacts.

    Parameters
    ----------
    metadata_path:
        Session metadata file used to map session-level context.
    outputs_dir:
        Root outputs directory with per-session subfolders.
    output_path:
        Target dataset file path (.parquet preferred, CSV fallback).
    min_rows:
        Minimum row count required for successful output.
    """
    meta_rows = parse_metadata(metadata_path)
    rows: list[dict[str, Any]] = []
    for meta in meta_rows:
        rows.extend(_collect_session_rows(meta, outputs_dir))

    if not rows:
        raise ValueError("No dataset rows were collected from outputs.")

    df = pd.DataFrame(rows)
    df = _normalise_dataset(df)
    if len(df) < int(max(1, min_rows)):
        raise ValueError(f"Dataset too small ({len(df)} rows).")

    _write_dataset(df, output_path)
    logger.info("Offline dataset built: %d rows, %d cols -> %s", len(df), len(df.columns), output_path)
    return df


def load_training_dataset(path: Path) -> pd.DataFrame:
    """Load dataset from parquet/csv path."""
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".parquet":
        try:
            return pd.read_parquet(path)
        except Exception:
            csv_fallback = path.with_suffix(".csv")
            if csv_fallback.exists():
                return pd.read_csv(csv_fallback)
            raise
    return pd.read_csv(path)


def feature_columns(
    df: pd.DataFrame,
    *,
    product_tier: str | None = None,
) -> tuple[list[str], list[str]]:
    """Return available numeric and categorical feature columns for one tier."""
    tier = normalize_product_tier(product_tier)
    num_allowed = TIER_NUMERIC_MASKS.get(tier, set(NUMERIC_FEATURE_COLUMNS))
    cat_allowed = TIER_CATEGORICAL_MASKS.get(tier, set(CATEGORICAL_FEATURE_COLUMNS))
    num = [c for c in NUMERIC_FEATURE_COLUMNS if c in df.columns and c in num_allowed]
    cat = [c for c in CATEGORICAL_FEATURE_COLUMNS if c in df.columns and c in cat_allowed]
    return num, cat


def _collect_session_rows(meta: SessionMetadata, outputs_dir: Path) -> list[dict[str, Any]]:
    session_id = Path(meta.session_file).stem
    session_dir = outputs_dir / session_id
    lap_path = session_dir / "all_laps_optimal.csv"
    if not lap_path.exists():
        return []

    try:
        lap_df = pd.read_csv(lap_path)
    except Exception as exc:
        logger.warning("Failed reading %s: %s", lap_path, exc)
        return []
    if lap_df.empty:
        return []

    summary = _read_json(session_dir / "session_summary.json")
    session_scalars = summary.get("session_scalars", {}) if isinstance(summary, dict) else {}
    quality = summary.get("quality_metrics", {}) if isinstance(summary, dict) else {}
    sensitivity = summary.get("sensitivity", {}) if isinstance(summary, dict) else {}

    diag = _read_diagnostics(session_dir / "driver_diagnostics_findings.csv")
    primary_diag_code = _primary_diag_code(diag)

    rows: list[dict[str, Any]] = []
    for rec in lap_df.to_dict(orient="records"):
        row = {
            "session_id": session_id,
            "session_file": meta.session_file,
            "lap_number": _to_int(rec.get("lap_number"), default=0),
            "layout_id": meta.layout_id or "",
            "product_tier": normalize_product_tier(meta.product_tier),
            "sensor_profile": str(meta.sensor_profile or ""),
            "domain_whitelist_id": str(meta.domain_whitelist_id or ""),
            "track_name": rec.get("track_name") or meta.track_name or "",
            "kart_id": rec.get("kart_id") or meta.kart_id or "",
            "kart_class": meta.kart_class or "4t",
            "condition_label": rec.get("condition_label") or meta.condition_label or "",
            "tire_type": meta.tire_type or "slick",
            "driver_weight_kg": _to_float(meta.driver_weight_kg),
            "kart_weight_kg": _to_float(meta.kart_weight_kg),
            "engine_peak_power_kw": _resolve_engine_kw(meta),
            "engine_size_cc": _to_float(meta.engine_size_cc),
            "track_record_s": _to_float(meta.track_record_s),
            "actual_lap_time_s": _to_float(rec.get("actual_lap_time_s")),
            "optimal_lap_time_s": _to_float(rec.get("optimal_lap_time_s")),
            "gain_s": _to_float(rec.get("gain_s")),
            "gain_pct": _to_float(rec.get("gain_pct")),
            "accepted_count": _to_float(rec.get("accepted_count")),
            "evaluated_count": _to_float(rec.get("evaluated_count")),
            "target_force_scale": _to_float(rec.get("target_force_scale")),
            "ml_training_rows": _to_float(rec.get("ml_training_rows")),
            "ml_used_corners": _to_float(rec.get("ml_used_corners")),
            "target_status": rec.get("target_status") or "",
            "envelope_source": rec.get("envelope_source") or sensitivity.get("envelope_source") or "",
            "session_mu": _to_float(session_scalars.get("mu_session")),
            "session_p": _to_float(session_scalars.get("p_session")),
            "session_b": _to_float(session_scalars.get("b_session")),
            "session_confidence": _to_float(session_scalars.get("confidence")),
            "quality_score": _to_float(quality.get("score")),
            "quality_speed_coverage": _to_float(quality.get("speed_coverage")),
            "quality_accel_coverage": _to_float(quality.get("accel_coverage")),
            "quality_yaw_coverage": _to_float(quality.get("yaw_coverage")),
            "speed_mean_mps": _to_float(rec.get("speed_mean_mps")),
            "speed_max_mps": _to_float(rec.get("speed_max_mps")),
            "speed_std_mps": _to_float(rec.get("speed_std_mps")),
            "brake_peak_mps2": _to_float(rec.get("brake_peak_mps2")),
            "lat_peak_mps2": _to_float(rec.get("lat_peak_mps2")),
            "yaw_std_dps": _to_float(rec.get("yaw_std_dps")),
            "heading_std_deg": _to_float(rec.get("heading_std_deg")),
            "grade_abs_mean_pct": _to_float(rec.get("grade_abs_mean_pct")),
            "bank_abs_mean_deg": _to_float(rec.get("bank_abs_mean_deg")),
            "steering_abs_mean_deg": _to_float(rec.get("steering_abs_mean_deg")),
            "steering_rate_std_degps": _to_float(rec.get("steering_rate_std_degps")),
            "steering_jerk_std_degps2": _to_float(rec.get("steering_jerk_std_degps2")),
            "throttle_mean_pct": _to_float(rec.get("throttle_mean_pct")),
            "throttle_reapply_delay_s": _to_float(rec.get("throttle_reapply_delay_s")),
            "brake_peak_pct": _to_float(rec.get("brake_peak_pct")),
            "brake_onset_rate_pctps": _to_float(rec.get("brake_onset_rate_pctps")),
            "trail_brake_fraction": _to_float(rec.get("trail_brake_fraction")),
            "countersteer_proxy": _to_float(rec.get("countersteer_proxy")),
            "diag_primary_code": primary_diag_code,
        }
        if isinstance(summary, dict):
            drv = summary.get("driver_diagnostics", {})
            if isinstance(drv, dict):
                metrics = drv.get("metrics", {})
                if isinstance(metrics, dict):
                    # Fallbacks when per-lap control traces are unavailable.
                    row["countersteer_proxy"] = row["countersteer_proxy"] or _to_float(
                        metrics.get("countersteer_events_per_km")
                    )
                    row["trail_brake_fraction"] = row["trail_brake_fraction"] or _to_float(
                        metrics.get("coast_frac")
                    )
        for code in DIAGNOSTIC_CODES:
            row[f"diag_{code}"] = float(diag.get(code, 0.0))
        rows.append(row)
    return rows


def _normalise_dataset(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in NUMERIC_FEATURE_COLUMNS + TARGET_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in CATEGORICAL_FEATURE_COLUMNS + ["diag_primary_code", "session_id", "session_file"]:
        if col in out.columns:
            out[col] = out[col].fillna("").astype(str)

    # Keep only rows with valid targets.
    if "optimal_lap_time_s" in out.columns:
        out = out[np.isfinite(out["optimal_lap_time_s"])]
    if "gain_s" in out.columns:
        out = out[np.isfinite(out["gain_s"])]
        out["gain_s"] = np.maximum(out["gain_s"].astype(float), 0.0)
    out = out.reset_index(drop=True)
    return out


def _write_dataset(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".parquet":
        try:
            df.to_parquet(output_path, index=False)
            return
        except Exception as exc:
            logger.warning("Parquet write failed (%s), falling back to CSV.", exc)
            csv_path = output_path.with_suffix(".csv")
            df.to_csv(csv_path, index=False)
            return
    df.to_csv(output_path, index=False)


def _resolve_engine_kw(meta: SessionMetadata) -> float:
    kw = _to_float(meta.engine_peak_power_kw)
    if kw > 0:
        return kw
    hp = _to_float(meta.engine_peak_power_hp)
    if hp > 0:
        return hp * 0.745699872
    return 0.0


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _read_diagnostics(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    out: dict[str, float] = {}
    if "code" not in df.columns:
        return out
    for _, row in df.iterrows():
        code = str(row.get("code", "")).strip()
        if not code:
            continue
        out[code] = float(_to_float(row.get("score"), default=0.0))
    return out


def _primary_diag_code(diag: dict[str, float]) -> str:
    if not diag:
        return "clean"
    items = [(k, v) for k, v in diag.items() if np.isfinite(v)]
    if not items:
        return "clean"
    items.sort(key=lambda kv: kv[1], reverse=True)
    return str(items[0][0])


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not np.isfinite(out):
        return float(default)
    return float(out)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)
