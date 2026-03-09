"""
bundle_v2.py
------------
Fast online inference using offline-trained bundle_v2 artifacts.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.ingest.columns import (
    COL_ACCEL_LAT,
    COL_ACCEL_LONG,
    COL_BANK_ANGLE_DEG,
    COL_BRAKE_PCT,
    COL_GRADE_PCT,
    COL_HEADING,
    COL_SPEED,
    COL_STEERING_ANGLE_DEG,
    COL_THROTTLE_PCT,
    COL_TIME,
    COL_YAW_RATE,
)
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.tiering import PRODUCT_TIER_DEFAULT, normalize_product_tier

logger = logging.getLogger(__name__)

try:
    import joblib  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - compatibility fallback
    import pickle

    class _JoblibCompat:
        @staticmethod
        def dump(obj: object, path: Path | str) -> None:
            with open(path, "wb") as fh:
                pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)

        @staticmethod
        def load(path: Path | str) -> object:
            with open(path, "rb") as fh:
                return pickle.load(fh)

    joblib = _JoblibCompat()  # type: ignore[assignment]


@dataclass
class BundleV2SessionResult:
    """Session-level bundle_v2 predictions."""

    bundle_path: str
    bundle_track: str
    bundle_kart: str
    n_laps: int
    best_actual_lap_s: float
    predicted_optimal_lap_s: float
    predicted_total_gain_s: float
    product_tier: str = PRODUCT_TIER_DEFAULT
    tier_schema_used: str = "default"
    method: str = "bundle_v2_student"
    model_confidence: float = 0.0
    uncertainty_low_s: float | None = None
    uncertainty_high_s: float | None = None
    lap_rows: list[dict[str, Any]] = field(default_factory=list)
    diagnostics_summary: dict[str, Any] = field(default_factory=dict)
    gate_summary: dict[str, Any] = field(default_factory=dict)
    calibration_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_path": self.bundle_path,
            "bundle_track": self.bundle_track,
            "bundle_kart": self.bundle_kart,
            "product_tier": self.product_tier,
            "tier_schema_used": self.tier_schema_used,
            "n_laps": int(self.n_laps),
            "best_actual_lap_s": round(float(self.best_actual_lap_s), 4),
            "predicted_optimal_lap_s": round(float(self.predicted_optimal_lap_s), 4),
            "predicted_total_gain_s": round(float(self.predicted_total_gain_s), 4),
            "method": self.method,
            "model_confidence": round(float(self.model_confidence), 4),
            "uncertainty_low_s": (
                round(float(self.uncertainty_low_s), 4) if self.uncertainty_low_s is not None else None
            ),
            "uncertainty_high_s": (
                round(float(self.uncertainty_high_s), 4) if self.uncertainty_high_s is not None else None
            ),
            "lap_rows": self.lap_rows,
            "diagnostics_summary": self.diagnostics_summary,
            "gate_summary": self.gate_summary,
            "calibration_summary": self.calibration_summary,
        }


def resolve_bundle_path(
    track_name: str | None,
    kart_id: str | None,
    config: KartEnvelopeConfig,
    *,
    product_tier: str | None = None,
    force_global: bool = False,
) -> tuple[Path | None, str]:
    """Resolve best matching bundle directory with optional tier routing."""
    root = Path(config.bundle_v2_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    tier = normalize_product_tier(product_tier or getattr(config, "product_tier", None))
    track = _safe_key(track_name)
    kart = _safe_key(kart_id)

    candidates: list[tuple[str, Path]] = []
    use_tier_subdirs = bool(getattr(config, "bundle_v2_tier_subdirs", False))

    if use_tier_subdirs:
        tier_root = root / tier
        if not force_global:
            if track and kart:
                candidates.append(("tier_exact", tier_root / track / kart / "bundle_v2"))
            if kart:
                candidates.append(("tier_kart_global_track", tier_root / "_global" / kart / "bundle_v2"))
            if track:
                candidates.append(("tier_track_global_kart", tier_root / track / "_global" / "bundle_v2"))
        candidates.append(("tier_global", tier_root / "_global" / "_global" / "bundle_v2"))
        # Backward-compatible fallback to untiered root.
    if not force_global:
        if track and kart:
            candidates.append(("exact", root / track / kart / "bundle_v2"))
        if kart:
            candidates.append(("kart_global_track", root / "_global" / kart / "bundle_v2"))
        if track:
            candidates.append(("track_global_kart", root / track / "_global" / "bundle_v2"))
    candidates.append(("global", root / "_global" / "_global" / "bundle_v2"))

    for source, path in candidates:
        if path.exists():
            return path, source
    return None, "missing"


def build_lap_feature_frame(
    filtered_laps: dict[int, pd.DataFrame],
    lap_times: dict[int, float],
    metadata: SessionMetadata,
    scalars: SessionScalars,
    quality_metrics: dict[str, float],
    *,
    product_tier: str | None = None,
) -> pd.DataFrame:
    """Build online lap features used by bundle_v2 students."""
    tier = normalize_product_tier(product_tier or metadata.product_tier)
    rows: list[dict[str, Any]] = []
    for lap_num in sorted(filtered_laps.keys()):
        lap_df = filtered_laps.get(lap_num)
        if lap_df is None or len(lap_df) < 5:
            continue
        speed = _series(lap_df, COL_SPEED)
        ax = _series(lap_df, COL_ACCEL_LONG)
        ay = np.abs(_series(lap_df, COL_ACCEL_LAT))
        yaw = _series(lap_df, COL_YAW_RATE)
        grade = np.abs(_series(lap_df, COL_GRADE_PCT))
        bank = np.abs(_series(lap_df, COL_BANK_ANGLE_DEG))
        heading = _series(lap_df, COL_HEADING)
        steering = _series(lap_df, COL_STEERING_ANGLE_DEG)
        throttle = np.clip(_series(lap_df, COL_THROTTLE_PCT), 0.0, 100.0)
        brake = np.clip(_series(lap_df, COL_BRAKE_PCT), 0.0, 100.0)
        lap_time = _series(lap_df, COL_TIME)
        actual = float(lap_times.get(lap_num, np.nan))

        steering_rate_std = float(np.nanstd(np.diff(steering))) if steering.size > 2 else 0.0
        steering_jerk_std = (
            float(np.nanstd(np.diff(np.diff(steering))))
            if steering.size > 4
            else 0.0
        )
        throttle_reapply_delay_s = _throttle_reapply_delay_s(
            time_s=lap_time,
            throttle_pct=throttle,
            brake_pct=brake,
        )
        brake_onset_rate = _brake_onset_rate_pctps(time_s=lap_time, brake_pct=brake)
        trail_brake_frac = _trail_brake_fraction(throttle_pct=throttle, brake_pct=brake)
        countersteer_proxy = _countersteer_proxy(steering=steering, yaw_rate=yaw)

        rows.append({
            "lap_number": int(lap_num),
            "actual_lap_time_s": actual,
            "gain_pct": 0.0,
            "accepted_count": 0.0,
            "evaluated_count": 0.0,
            "target_force_scale": 1.0,
            "ml_training_rows": 0.0,
            "ml_used_corners": 0.0,
            "session_mu": float(scalars.mu_session),
            "session_p": float(scalars.p_session),
            "session_b": float(scalars.b_session),
            "session_confidence": float(scalars.confidence),
            "quality_score": float(quality_metrics.get("score", 0.0)),
            "quality_speed_coverage": float(quality_metrics.get("speed_coverage", 0.0)),
            "quality_accel_coverage": float(quality_metrics.get("accel_coverage", 0.0)),
            "quality_yaw_coverage": float(quality_metrics.get("yaw_coverage", 0.0)),
            "driver_weight_kg": float(metadata.driver_weight_kg),
            "kart_weight_kg": float(metadata.kart_weight_kg or 0.0),
            "engine_peak_power_kw": _resolve_engine_kw(metadata),
            "engine_size_cc": float(metadata.engine_size_cc or 0.0),
            "track_record_s": float(metadata.track_record_s or 0.0),
            "track_name": str(metadata.track_name or ""),
            "kart_id": str(metadata.kart_id or ""),
            "kart_class": str(metadata.kart_class or "4t"),
            "condition_label": str(metadata.condition_label or scalars.condition_label or ""),
            "layout_id": str(metadata.layout_id or ""),
            "product_tier": str(tier),
            "sensor_profile": str(metadata.sensor_profile or ""),
            "envelope_source": "",
            "target_status": "",
            "tire_type": str(metadata.tire_type or "slick"),
            # additional dynamic channels (used for diagnostics/richer inference)
            "speed_mean_mps": float(np.nanmean(speed)) if speed.size else 0.0,
            "speed_max_mps": float(np.nanmax(speed)) if speed.size else 0.0,
            "speed_std_mps": float(np.nanstd(speed)) if speed.size else 0.0,
            "brake_peak_mps2": float(np.nanmin(ax)) if ax.size else 0.0,
            "lat_peak_mps2": float(np.nanmax(ay)) if ay.size else 0.0,
            "yaw_std_dps": float(np.nanstd(yaw)) if yaw.size else 0.0,
            "heading_std_deg": float(np.nanstd(heading)) if heading.size else 0.0,
            "grade_abs_mean_pct": float(np.nanmean(grade)) if grade.size else 0.0,
            "bank_abs_mean_deg": float(np.nanmean(bank)) if bank.size else 0.0,
            "steering_abs_mean_deg": float(np.nanmean(np.abs(steering))) if steering.size else 0.0,
            "steering_rate_std_degps": steering_rate_std,
            "steering_jerk_std_degps2": steering_jerk_std,
            "throttle_mean_pct": float(np.nanmean(throttle)) if throttle.size else 0.0,
            "throttle_reapply_delay_s": throttle_reapply_delay_s,
            "brake_peak_pct": float(np.nanmax(brake)) if brake.size else 0.0,
            "brake_onset_rate_pctps": brake_onset_rate,
            "trail_brake_fraction": trail_brake_frac,
            "countersteer_proxy": countersteer_proxy,
        })
    return pd.DataFrame(rows)


def run_bundle_inference(
    bundle_dir: Path,
    lap_features: pd.DataFrame,
    *,
    config: KartEnvelopeConfig,
    product_tier: str | None = None,
) -> BundleV2SessionResult:
    """Run student inference for every lap in session."""
    if lap_features.empty:
        raise ValueError("lap_features is empty")

    student = joblib.load(bundle_dir / "student_regressor.joblib")
    if not isinstance(student, dict):
        raise TypeError("student_regressor.joblib must contain dict artifact")
    pre = student.get("preprocessor")
    model_opt = student.get("model_optimal")
    model_gain = student.get("model_gain")
    model_diag = student.get("model_diag")
    if pre is None or model_opt is None or model_gain is None:
        raise ValueError("bundle student artifact is incomplete")

    schema = _read_json(bundle_dir / "feature_schema.json")
    tier = normalize_product_tier(product_tier or getattr(config, "product_tier", None))
    num_cols, cat_cols, schema_source = _feature_schema_for_tier(schema, tier=tier)
    feat_cols = num_cols + cat_cols
    if not feat_cols:
        raise ValueError("feature schema has no features")

    x = lap_features.copy()
    for c in feat_cols:
        if c not in x.columns:
            x[c] = 0.0 if c in num_cols else ""
    x = x[feat_cols]
    for c in num_cols:
        if c in x.columns:
            x[c] = pd.to_numeric(x[c], errors="coerce").fillna(0.0)
    for c in cat_cols:
        if c in x.columns:
            x[c] = x[c].fillna("").astype(str)
    xt = pre.transform(x)

    pred_opt = np.asarray(model_opt.predict(xt), dtype=float)
    pred_gain = np.maximum(np.asarray(model_gain.predict(xt), dtype=float), 0.0)

    # Apply calibration.
    cal = _read_json(bundle_dir / "calibration.json")
    cal_min = float(cal.get("min", 0.60))
    cal_max = float(cal.get("max", 1.00))
    q = pd.to_numeric(lap_features.get("quality_score", 0.0), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    shrink = np.clip(float(cal.get("intercept", 0.90)) + float(cal.get("slope_quality", 0.0)) * q, cal_min, cal_max)
    pred_gain = np.maximum(pred_gain * shrink, 0.0)

    actual = pd.to_numeric(lap_features.get("actual_lap_time_s", np.nan), errors="coerce").to_numpy(dtype=float)
    max_gain_pct = float(max(config.bundle_v2_max_gain_pct, 0.0)) / 100.0
    pred_gain = np.minimum(pred_gain, np.maximum(actual, 0.0) * max_gain_pct)
    pred_opt = np.minimum(pred_opt, np.maximum(actual - pred_gain, 0.01))

    # Diagnostics label.
    if model_diag is not None:
        diag_code = np.asarray(model_diag.predict(xt), dtype=object)
    else:
        diag_code = np.asarray(["unknown"] * len(x), dtype=object)

    # Gate summary.
    gate = joblib.load(bundle_dir / "gate_model.joblib")
    gate_summary: dict[str, Any] = {}
    if hasattr(gate, "predict"):
        try:
            gate_pred = np.asarray(gate.predict(xt), dtype=object)
            gate_summary["predicted_condition_mode"] = str(pd.Series(gate_pred).mode().iloc[0])
        except Exception:
            gate_summary["predicted_condition_mode"] = "unknown"
    elif isinstance(gate, dict):
        gate_summary["predicted_condition_mode"] = str(gate.get("default_condition", "unknown"))
    else:
        gate_summary["predicted_condition_mode"] = "unknown"

    uq = _read_json(bundle_dir / "uncertainty_quantiles.json")
    q10 = float(uq.get("residual_q10_s", -0.20))
    q90 = float(uq.get("residual_q90_s", 0.20))

    lap_rows: list[dict[str, Any]] = []
    for i in range(len(lap_features)):
        low = max(0.01, float(pred_opt[i] + q10))
        high = max(low, float(pred_opt[i] + q90))
        lap_rows.append({
            "lap_number": int(lap_features.iloc[i].get("lap_number", i + 1)),
            "actual_lap_time_s": round(float(actual[i]), 4),
            "predicted_optimal_lap_time_s": round(float(pred_opt[i]), 4),
            "predicted_gain_s": round(float(pred_gain[i]), 4),
            "predicted_gain_pct": round(float(100.0 * pred_gain[i] / max(actual[i], 1e-6)), 4),
            "predicted_error_code": str(diag_code[i]),
            "uncertainty_low_s": round(low, 4),
            "uncertainty_high_s": round(high, 4),
            "calibration_shrink": round(float(shrink[i]), 4),
        })

    best_actual = float(np.nanmin(actual))
    best_opt = float(np.nanmin(pred_opt))
    total_gain = float(max(0.0, best_actual - best_opt))

    diag_counts = pd.Series([row["predicted_error_code"] for row in lap_rows]).value_counts().to_dict()
    confidence = float(np.clip(1.0 - abs(q90 - q10) / max(best_actual, 1e-6), config.bundle_v2_confidence_floor, 1.0))

    meta = _read_json(bundle_dir / "bundle_meta.json")
    return BundleV2SessionResult(
        bundle_path=str(bundle_dir),
        bundle_track=str(meta.get("track_name", "")),
        bundle_kart=str(meta.get("kart_id", "")),
        product_tier=tier,
        tier_schema_used=schema_source,
        n_laps=int(len(lap_rows)),
        best_actual_lap_s=best_actual,
        predicted_optimal_lap_s=best_opt,
        predicted_total_gain_s=total_gain,
        model_confidence=confidence,
        uncertainty_low_s=float(best_opt + q10),
        uncertainty_high_s=float(best_opt + q90),
        lap_rows=lap_rows,
        diagnostics_summary={"counts": diag_counts},
        gate_summary=gate_summary,
        calibration_summary={
            "mean_shrink": float(np.mean(shrink)),
            "min_shrink": float(np.min(shrink)),
            "max_shrink": float(np.max(shrink)),
        },
    )


def _ensure_distance(distance_m: np.ndarray | None, n: int) -> np.ndarray:
    if n <= 0:
        return np.array([], dtype=float)
    if distance_m is None:
        return np.arange(n, dtype=float)
    d = np.asarray(distance_m, dtype=float).copy()
    if len(d) != n or len(d) == 0:
        return np.arange(n, dtype=float)
    d[~np.isfinite(d)] = np.nan
    if not np.isfinite(d[0]):
        d[0] = 0.0
    for i in range(1, len(d)):
        if not np.isfinite(d[i]) or d[i] <= d[i - 1]:
            d[i] = d[i - 1] + 1e-3
    return d


def _lap_time_from_profile(distance: np.ndarray, speed: np.ndarray) -> float:
    if len(distance) < 2 or len(speed) < 2:
        return 0.0
    ds = np.diff(distance)
    ds = np.maximum(ds, 1e-4)
    v_avg = 0.5 * (speed[:-1] + speed[1:])
    v_avg = np.maximum(v_avg, 0.3)
    return float(np.sum(ds / v_avg))


def _smooth_series(arr: np.ndarray, window: int = 5) -> np.ndarray:
    if len(arr) < 3 or window <= 1:
        return arr.copy()
    w = int(max(1, window))
    if w % 2 == 0:
        w += 1
    pad = w // 2
    if len(arr) <= pad:
        return arr.copy()
    kernel = np.ones(w, dtype=float) / float(w)
    ext = np.pad(arr, (pad, pad), mode="edge")
    return np.convolve(ext, kernel, mode="valid")


def _window_points_from_distance(distance: np.ndarray, window_m: float) -> int:
    if len(distance) < 3:
        return 1
    ds = np.diff(distance)
    ds = ds[np.isfinite(ds) & (ds > 1e-6)]
    if len(ds) == 0:
        return 1
    mean_ds = float(np.mean(ds))
    pts = int(max(1, round(float(window_m) / max(mean_ds, 1e-6))))
    if pts % 2 == 0:
        pts += 1
    return max(1, pts)


def _smooth_profile_distance(
    distance: np.ndarray,
    speed: np.ndarray,
    *,
    window_m: float,
    passes: int,
) -> np.ndarray:
    out = np.asarray(speed, dtype=float).copy()
    if len(out) < 3:
        return out
    w = _window_points_from_distance(distance, window_m)
    n_pass = int(max(1, passes))
    for _ in range(n_pass):
        out = _smooth_series(out, window=w)
    return out


def _delta_cap_mps(baseline_speed_mps: np.ndarray) -> np.ndarray:
    v = np.asarray(baseline_speed_mps, dtype=float)
    if len(v) == 0:
        return v
    p95 = float(np.nanpercentile(v, 95)) if np.isfinite(np.nanmax(v)) else 1.0
    p95 = max(p95, 1.0)
    rel = 0.02 + 0.16 * np.power(np.clip(1.0 - (v / p95), 0.0, 1.0), 1.35)
    cap = np.minimum(v * rel + 0.12, 2.8)
    return np.maximum(cap, 0.05)


def _add_gaussian(weight: np.ndarray, distance: np.ndarray, center_m: float, width_m: float, amp: float) -> None:
    if len(weight) == 0 or len(distance) == 0:
        return
    if not np.isfinite(center_m) or not np.isfinite(width_m) or not np.isfinite(amp):
        return
    width = max(0.5, float(width_m))
    z = (distance - float(center_m)) / width
    weight += float(amp) * np.exp(-0.5 * z * z)


def _build_corner_weight(
    *,
    distance: np.ndarray,
    baseline_speed_mps: np.ndarray,
    corners: list[dict[str, Any]] | None,
    corner_recommendations: list[dict[str, Any]] | None,
) -> np.ndarray:
    n = len(distance)
    if n == 0:
        return np.array([], dtype=float)
    v = np.asarray(baseline_speed_mps, dtype=float)
    weight = np.zeros(n, dtype=float)

    # Generic underdrive signatures: low-speed regions + braking zones.
    p45 = float(np.nanpercentile(v, 45))
    p95 = max(float(np.nanpercentile(v, 95)), 1.0)
    low_speed = np.clip((p45 - v) / max(p45, 1e-3), 0.0, 1.0)
    weight += 0.55 * low_speed
    dv_ds = np.gradient(v, distance)
    brake = np.clip(-dv_ds, 0.0, None)
    if np.nanmax(brake) > 1e-9:
        weight += 0.35 * (brake / np.nanmax(brake))

    corner_by_id: dict[int, dict[str, Any]] = {}
    for c in corners or []:
        cid = int(c.get("corner_id", -1))
        if cid >= 0:
            corner_by_id[cid] = c
        s_start = float(c.get("s_start", np.nan))
        s_end = float(c.get("s_end", np.nan))
        if not np.isfinite(s_start) or not np.isfinite(s_end) or s_end <= s_start:
            continue
        s_apex = float(c.get("s_apex", 0.5 * (s_start + s_end)))
        _add_gaussian(weight, distance, s_start - 6.0, 8.0, 0.70)  # braking zone
        _add_gaussian(weight, distance, s_apex, 7.0, 1.00)         # line/apex
        _add_gaussian(weight, distance, s_end + 4.0, 10.0, 0.60)   # exit

    for rec in corner_recommendations or []:
        bp = float(rec.get("brake_point_m", np.nan))
        tip = float(rec.get("turn_in_point_m", np.nan))
        gain = max(float(rec.get("gain_s", 0.0)), 0.0)
        brake_shift_s = float(rec.get("brake_shift_s", 0.0))
        turn_shift_m = float(rec.get("turn_shift_m", 0.0))
        cid = int(rec.get("corner_id", -1))
        amp = 0.35 + min(gain * 6.0, 0.90)

        _add_gaussian(weight, distance, bp, 7.5, amp * 0.95)
        _add_gaussian(weight, distance, tip, 6.0, amp)
        if brake_shift_s > 0.0 and np.isfinite(bp):
            v_bp = float(np.interp(bp, distance, v, left=float(v[0]), right=float(v[-1])))
            shift_dist = float(np.clip(brake_shift_s * max(v_bp, 1.0), 2.0, 25.0))
            _add_gaussian(weight, distance, bp - 0.6 * shift_dist, max(4.0, 0.35 * shift_dist), amp * 0.8)
        if abs(turn_shift_m) > 0.2 and np.isfinite(tip):
            _add_gaussian(weight, distance, tip + 0.5 * turn_shift_m, 5.5, amp * 0.7)

        c = corner_by_id.get(cid)
        if isinstance(c, dict):
            s_apex = float(c.get("s_apex", np.nan))
            if np.isfinite(s_apex):
                _add_gaussian(weight, distance, s_apex, 7.0, amp * 0.9)

    # De-emphasize high-speed straights so improvements stay corner-driven.
    straight_scale = np.clip(1.0 - (v / p95), 0.15, 1.0)
    weight *= straight_scale
    weight = _smooth_series(weight, window=9)
    weight = np.clip(weight, 0.0, None)
    w_max = float(np.nanmax(weight))
    if w_max <= 1e-9:
        return np.zeros_like(weight)
    return weight / w_max


def _sparsify_delta(delta: np.ndarray) -> np.ndarray:
    d = np.asarray(delta, dtype=float)
    pos = d[d > 1e-6]
    if len(pos) < 16:
        return np.clip(d, 0.0, None)
    floor = float(np.quantile(pos, 0.35))
    sparse = np.clip(d - floor, 0.0, None)
    if float(np.nanmax(sparse)) < 0.10:
        return np.clip(d, 0.0, None)
    return sparse


def _profile_for_scale(
    baseline: np.ndarray,
    delta_template: np.ndarray,
    delta_cap: np.ndarray,
    scale: float,
) -> np.ndarray:
    cand = baseline + np.minimum(np.maximum(scale, 0.0) * delta_template, delta_cap)
    cand = _smooth_series(cand, window=5)
    cand = np.maximum(cand, baseline)
    cand = np.minimum(cand, baseline + delta_cap)
    return np.maximum(cand, 0.5)


def _fit_profile_to_target_time(
    *,
    distance: np.ndarray,
    baseline: np.ndarray,
    delta_template: np.ndarray,
    target_lap_time_s: float,
) -> np.ndarray:
    delta_cap = _delta_cap_mps(baseline)
    t_base = _lap_time_from_profile(distance, baseline)
    if t_base <= target_lap_time_s + 1e-6:
        return baseline.copy()
    if float(np.nanmax(delta_template)) <= 1e-8:
        return baseline.copy()

    lo = 0.0
    hi = 1.0
    t_hi = _lap_time_from_profile(distance, _profile_for_scale(baseline, delta_template, delta_cap, hi))
    while t_hi > target_lap_time_s and hi < 10.0:
        hi *= 1.6
        t_hi = _lap_time_from_profile(distance, _profile_for_scale(baseline, delta_template, delta_cap, hi))

    if t_hi > target_lap_time_s:
        return _profile_for_scale(baseline, delta_template, delta_cap, hi)

    for _ in range(32):
        mid = 0.5 * (lo + hi)
        t_mid = _lap_time_from_profile(distance, _profile_for_scale(baseline, delta_template, delta_cap, mid))
        if t_mid > target_lap_time_s:
            lo = mid
        else:
            hi = mid
    return _profile_for_scale(baseline, delta_template, delta_cap, hi)


def _rescale_profile_to_lap_time(
    *,
    distance: np.ndarray,
    baseline: np.ndarray,
    profile: np.ndarray,
    target_lap_time_s: float,
) -> np.ndarray:
    if not np.isfinite(target_lap_time_s) or target_lap_time_s <= 1e-6:
        return np.asarray(profile, dtype=float)
    delta = np.clip(np.asarray(profile, dtype=float) - np.asarray(baseline, dtype=float), 0.0, None)
    if len(delta) == 0 or float(np.nanmax(delta)) <= 1e-8:
        return np.asarray(baseline, dtype=float)
    return _fit_profile_to_target_time(
        distance=np.asarray(distance, dtype=float),
        baseline=np.asarray(baseline, dtype=float),
        delta_template=delta,
        target_lap_time_s=float(target_lap_time_s),
    )


def _finalize_profile(
    *,
    distance: np.ndarray,
    baseline: np.ndarray,
    profile: np.ndarray,
    target_lap_time_s: float,
    smoothing_enable: bool,
    smoothing_window_m: float,
    smoothing_passes: int,
    smoothing_preserve_lap_time: bool,
) -> np.ndarray:
    out = np.asarray(profile, dtype=float).copy()
    out = np.maximum(out, baseline)
    out = np.maximum(out, 0.5)
    if not smoothing_enable:
        return out

    t_before = _lap_time_from_profile(distance, out)
    out = _smooth_profile_distance(
        distance=distance,
        speed=out,
        window_m=max(float(smoothing_window_m), 0.25),
        passes=max(1, int(smoothing_passes)),
    )
    out = np.maximum(out, baseline)
    out = np.maximum(out, 0.5)
    if smoothing_preserve_lap_time:
        t_target = (
            float(target_lap_time_s)
            if np.isfinite(target_lap_time_s) and target_lap_time_s > 1e-6
            else float(t_before)
        )
        out = _rescale_profile_to_lap_time(
            distance=distance,
            baseline=baseline,
            profile=out,
            target_lap_time_s=t_target,
        )
    return np.maximum(out, 0.5)


def estimate_optimal_speed_profile(
    baseline_speed_mps: np.ndarray,
    best_actual_lap_s: float,
    predicted_optimal_lap_s: float,
    *,
    distance_m: np.ndarray | None = None,
    sensitivity_template_speed_mps: np.ndarray | None = None,
    corner_recommendations: list[dict[str, Any]] | None = None,
    corners: list[dict[str, Any]] | None = None,
    smoothing_enable: bool = True,
    smoothing_window_m: float = 5.0,
    smoothing_passes: int = 2,
    smoothing_preserve_lap_time: bool = True,
) -> np.ndarray:
    """
    Build a localized optimal speed profile.

    Unlike global ratio scaling, this concentrates gains in braking, turn-in,
    apex, and exit zones so improvements come from line and brake-point changes.
    """
    baseline = np.asarray(baseline_speed_mps, dtype=float)
    if len(baseline) == 0:
        return baseline
    if (
        not np.isfinite(best_actual_lap_s)
        or not np.isfinite(predicted_optimal_lap_s)
        or predicted_optimal_lap_s <= 1e-6
    ):
        return np.maximum(baseline, 0.5)

    distance = _ensure_distance(distance_m, len(baseline))
    t_base_profile = _lap_time_from_profile(distance, baseline)
    if t_base_profile <= 1e-6:
        return np.maximum(baseline, 0.5)
    target_gain = max(0.0, float(best_actual_lap_s) - float(predicted_optimal_lap_s))
    if target_gain <= 1e-5:
        return np.maximum(baseline, 0.5)
    target_lap_time = max(0.01, t_base_profile - target_gain)
    corner_weight = _build_corner_weight(
        distance=distance,
        baseline_speed_mps=baseline,
        corners=corners,
        corner_recommendations=corner_recommendations,
    )

    # Preferred path: use sensitivity corner-rollout profile as shape template.
    if sensitivity_template_speed_mps is not None:
        tpl = np.asarray(sensitivity_template_speed_mps, dtype=float)
        if len(tpl) != len(baseline):
            x_old = np.linspace(float(distance[0]), float(distance[-1]), len(tpl))
            tpl = np.interp(distance, x_old, tpl, left=float(tpl[0]), right=float(tpl[-1]))
        delta_tpl = np.clip(tpl - baseline, 0.0, None)
        if len(corner_weight) == len(delta_tpl) and float(np.nanmax(corner_weight)) > 1e-9:
            if corner_recommendations:
                shape_mask = 0.35 + 0.65 * np.clip(corner_weight, 0.0, 1.0)
            else:
                # No accepted corner recs usually means target-force calibration;
                # enforce corner localization to avoid a near-uniform uplift.
                shape_mask = 0.05 + 0.95 * np.clip(corner_weight, 0.0, 1.0)
            delta_tpl *= shape_mask
        delta_tpl = _sparsify_delta(delta_tpl)
        if float(np.nanmax(delta_tpl)) > 1e-6:
            raw = _fit_profile_to_target_time(
                distance=distance,
                baseline=baseline,
                delta_template=delta_tpl,
                target_lap_time_s=target_lap_time,
            )
            return _finalize_profile(
                distance=distance,
                baseline=baseline,
                profile=raw,
                target_lap_time_s=target_lap_time,
                smoothing_enable=bool(smoothing_enable),
                smoothing_window_m=float(smoothing_window_m),
                smoothing_passes=int(smoothing_passes),
                smoothing_preserve_lap_time=bool(smoothing_preserve_lap_time),
            )

    # Fallback: construct local weights from corner geometry + recommendations.
    weight = corner_weight
    if len(weight) != len(baseline) or float(np.nanmax(weight)) <= 1e-9:
        ratio = float(np.clip(best_actual_lap_s / predicted_optimal_lap_s, 0.85, 1.20))
        raw = np.maximum(baseline * ratio, 0.5)
        return _finalize_profile(
            distance=distance,
            baseline=baseline,
            profile=raw,
            target_lap_time_s=target_lap_time,
            smoothing_enable=bool(smoothing_enable),
            smoothing_window_m=float(smoothing_window_m),
            smoothing_passes=int(smoothing_passes),
            smoothing_preserve_lap_time=bool(smoothing_preserve_lap_time),
        )

    delta_tpl = _delta_cap_mps(baseline) * np.power(np.clip(weight, 0.0, 1.0), 1.15)
    raw = _fit_profile_to_target_time(
        distance=distance,
        baseline=baseline,
        delta_template=delta_tpl,
        target_lap_time_s=target_lap_time,
    )
    return _finalize_profile(
        distance=distance,
        baseline=baseline,
        profile=raw,
        target_lap_time_s=target_lap_time,
        smoothing_enable=bool(smoothing_enable),
        smoothing_window_m=float(smoothing_window_m),
        smoothing_passes=int(smoothing_passes),
        smoothing_preserve_lap_time=bool(smoothing_preserve_lap_time),
    )


def _series(df: pd.DataFrame, col: str) -> np.ndarray:
    if col not in df.columns:
        return np.array([], dtype=float)
    s = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
    if s.size == 0:
        return s
    return s[np.isfinite(s)]


def _feature_schema_for_tier(
    schema: dict[str, Any],
    *,
    tier: str,
) -> tuple[list[str], list[str], str]:
    num_cols = list(schema.get("numeric_features", []))
    cat_cols = list(schema.get("categorical_features", []))
    tier_schema = schema.get("tier_feature_schema", {})
    if not isinstance(tier_schema, dict):
        return num_cols, cat_cols, "default"
    entry = tier_schema.get(tier)
    if not isinstance(entry, dict):
        return num_cols, cat_cols, "default"
    num_tier = entry.get("numeric_features")
    cat_tier = entry.get("categorical_features")
    if not isinstance(num_tier, list) or not isinstance(cat_tier, list):
        return num_cols, cat_cols, "default"
    return list(num_tier), list(cat_tier), f"tier:{tier}"


def _throttle_reapply_delay_s(
    *,
    time_s: np.ndarray,
    throttle_pct: np.ndarray,
    brake_pct: np.ndarray,
) -> float:
    if len(time_s) < 3 or len(throttle_pct) != len(time_s) or len(brake_pct) != len(time_s):
        return 0.0
    brake_mask = brake_pct > 10.0
    if not np.any(brake_mask):
        return 0.0
    last_brake_idx = int(np.where(brake_mask)[0][-1])
    onset_idx = None
    for i in range(last_brake_idx + 1, len(throttle_pct)):
        if throttle_pct[i] >= 12.0:
            onset_idx = i
            break
    if onset_idx is None:
        return 0.0
    dt = float(time_s[onset_idx] - time_s[last_brake_idx])
    if not np.isfinite(dt) or dt < 0.0:
        return 0.0
    return dt


def _brake_onset_rate_pctps(*, time_s: np.ndarray, brake_pct: np.ndarray) -> float:
    if len(time_s) < 4 or len(brake_pct) != len(time_s):
        return 0.0
    db = np.diff(brake_pct)
    dt = np.diff(time_s)
    mask = dt > 1e-6
    if not np.any(mask):
        return 0.0
    rate = db[mask] / dt[mask]
    rate = rate[np.isfinite(rate)]
    if rate.size == 0:
        return 0.0
    # 95th percentile captures initial brake attack without single-sample spikes.
    return float(np.nanpercentile(rate, 95))


def _trail_brake_fraction(*, throttle_pct: np.ndarray, brake_pct: np.ndarray) -> float:
    if len(throttle_pct) == 0 or len(brake_pct) == 0:
        return 0.0
    n = min(len(throttle_pct), len(brake_pct))
    b = brake_pct[:n]
    t = throttle_pct[:n]
    mask = (b > 5.0) & (t < 15.0)
    return float(np.sum(mask) / max(n, 1))


def _countersteer_proxy(*, steering: np.ndarray, yaw_rate: np.ndarray) -> float:
    if len(steering) < 3 or len(yaw_rate) < 3:
        return 0.0
    n = min(len(steering), len(yaw_rate))
    st = steering[:n]
    yr = yaw_rate[:n]
    mask = np.isfinite(st) & np.isfinite(yr)
    if np.sum(mask) < 3:
        return 0.0
    st = st[mask]
    yr = yr[mask]
    opposite = np.sign(st) * np.sign(yr) < 0.0
    return float(np.sum(opposite) / max(len(opposite), 1))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _resolve_engine_kw(meta: SessionMetadata) -> float:
    if meta.engine_peak_power_kw is not None and meta.engine_peak_power_kw > 0:
        return float(meta.engine_peak_power_kw)
    if meta.engine_peak_power_hp is not None and meta.engine_peak_power_hp > 0:
        return float(meta.engine_peak_power_hp) * 0.745699872
    return 0.0


def _safe_key(value: object) -> str:
    if value is None:
        return ""
    s = str(value).strip().lower()
    if not s:
        return ""
    out = []
    for ch in s:
        if ch.isalnum() or ch in {"-", "_"}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_")
