"""
calibration.py
--------------
Cycle-A telemetry calibration and parameter-identification helpers.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.ingest.metadata import SessionMetadata


def build_calibration_report(
    *,
    metadata: SessionMetadata,
    config: KartEnvelopeConfig,
    lap_times: dict[int, float],
    scalars: SessionScalars,
    quality_metrics: dict[str, float],
    sensitivity_result: Any | None = None,
    bundle_v2_result: Any | None = None,
) -> dict[str, Any]:
    """
    Build calibration + parameter-identification summary for one session.

    This report is intentionally lightweight for online use while preserving
    enough structure to support offline calibration workflows.
    """
    if not lap_times:
        return {
            "enabled": bool(config.calibration_enable_telemetry_calibration),
            "status": "no_laps",
        }

    actual = np.asarray(sorted(float(v) for v in lap_times.values()), dtype=float)
    best_actual = float(np.nanmin(actual))
    median_actual = float(np.nanmedian(actual))
    std_actual = float(np.nanstd(actual))
    q_score = float(np.clip(quality_metrics.get("score", 0.0), 0.0, 1.0))

    predicted_optimal = best_actual
    method = "baseline"
    if sensitivity_result is not None:
        try:
            predicted_optimal = float(sensitivity_result.ideal_lap_time_s)
            method = "sensitivity"
        except Exception:
            pass
    elif bundle_v2_result is not None:
        try:
            predicted_optimal = float(bundle_v2_result.predicted_optimal_lap_s)
            method = "bundle_v2"
        except Exception:
            pass

    raw_gain = max(0.0, best_actual - predicted_optimal)
    max_adj = float(np.clip(config.calibration_max_adjustment_pct, 0.0, 50.0)) / 100.0
    bounded_gain = min(raw_gain, best_actual * max_adj)
    calibrated_optimal = max(0.01, best_actual - bounded_gain)
    adjustment_scale = float(np.clip(
        calibrated_optimal / max(predicted_optimal, 1e-6),
        0.90,
        1.10,
    ))

    telemetry = {
        "enabled": bool(config.calibration_enable_telemetry_calibration),
        "method": method,
        "best_actual_lap_s": round(best_actual, 4),
        "predicted_optimal_lap_s": round(predicted_optimal, 4),
        "calibrated_optimal_lap_s": round(calibrated_optimal, 4),
        "raw_gain_s": round(raw_gain, 4),
        "bounded_gain_s": round(bounded_gain, 4),
        "adjustment_scale": round(adjustment_scale, 4),
        "consistency_std_s": round(std_actual, 4),
        "session_pace_span_s": round(float(np.nanmax(actual) - np.nanmin(actual)), 4),
    }

    # Constrained parameter-ID + residual learner confidence channel.
    underdrive_idx = float(np.clip((best_actual - calibrated_optimal) / max(best_actual, 1e-6), 0.0, 0.25))
    base_identified = _constrained_base_estimator(
        mu_session=float(scalars.mu_session),
        p_session=float(scalars.p_session),
        b_session=float(scalars.b_session),
        underdrive_idx=underdrive_idx,
        quality_score=q_score,
    )
    residual = _residual_learner_proxy(
        quality_score=q_score,
        pace_std_s=std_actual,
        median_time_s=median_actual,
        underdrive_idx=underdrive_idx,
    )
    param_conf = float(np.clip(0.60 * residual["confidence"] + 0.40 * base_identified["confidence"], 0.0, 1.0))
    param_id = {
        "enabled": bool(config.calibration_enable_param_id),
        "method": str(config.calibration_param_id_method),
        "identified": {
            "mu_effective": round(float(base_identified["mu_effective"]), 4),
            "power_effective": round(float(base_identified["power_effective"]), 4),
            "brake_effective": round(float(base_identified["brake_effective"]), 4),
            "underdrive_index": round(underdrive_idx, 4),
        },
        "base_estimator": base_identified,
        "residual_learner": residual,
        "confidence": round(param_conf, 4),
    }

    local_elast: list[dict[str, Any]] = []
    if sensitivity_result is not None and getattr(sensitivity_result, "recommendations", None):
        for rec in list(sensitivity_result.recommendations)[:12]:
            b_shift = float(getattr(rec, "brake_shift_s", 0.0) or 0.0)
            t_shift = float(getattr(rec, "turn_shift_m", 0.0) or 0.0)
            gain = float(getattr(rec, "gain_s", 0.0) or 0.0)
            mag = abs(b_shift) + 0.1 * abs(t_shift)
            elasticity = gain / max(mag, 1e-6)
            local_elast.append({
                "corner_id": int(getattr(rec, "corner_id", 0)),
                "gain_s": round(gain, 4),
                "control_magnitude": round(mag, 4),
                "elasticity": round(float(elasticity), 4),
            })

    global_elast = {
        "dT_d_mu": round(float(-0.55 * best_actual), 4),
        "dT_d_power": round(float(-0.30 * best_actual), 4),
        "dT_d_brake": round(float(-0.22 * best_actual), 4),
        "quality_score": round(q_score, 4),
    }

    uncertainty = {
        "lap_time_sigma_s": round(float(max(0.05, 0.20 * std_actual + 0.08 * (1.0 - q_score))), 4),
        "confidence": round(float(np.clip(0.5 * q_score + 0.5 * param_conf, 0.0, 1.0)), 4),
    }

    return {
        "enabled": bool(config.calibration_enable_telemetry_calibration or config.calibration_enable_param_id),
        "status": "ok",
        "track_name": metadata.track_name or "",
        "kart_id": metadata.kart_id,
        "condition_label": metadata.condition_label or "",
        "telemetry_calibration": telemetry,
        "parameter_identification": param_id,
        "sensitivity_elasticities": {
            "local": local_elast,
            "global": global_elast,
        },
        "uncertainty": uncertainty,
    }


def _constrained_base_estimator(
    *,
    mu_session: float,
    p_session: float,
    b_session: float,
    underdrive_idx: float,
    quality_score: float,
) -> dict[str, Any]:
    """Constrained base estimator for key effective parameters."""
    u = float(np.clip(underdrive_idx, 0.0, 0.35))
    q = float(np.clip(quality_score, 0.0, 1.0))
    mu_eff = float(np.clip(mu_session * (1.0 - 0.22 * u) * (0.95 + 0.10 * q), 0.50, 1.65))
    p_eff = float(np.clip(p_session * (1.0 - 0.18 * u) * (0.92 + 0.14 * q), 0.35, 1.70))
    b_eff = float(np.clip(b_session * (1.0 - 0.12 * u) * (0.94 + 0.10 * q), 0.35, 1.70))
    conf = float(np.clip(0.45 + 0.40 * q + 0.15 * (1.0 - u / 0.35), 0.0, 1.0))
    return {
        "name": "constrained_base_estimator",
        "mu_effective": round(mu_eff, 6),
        "power_effective": round(p_eff, 6),
        "brake_effective": round(b_eff, 6),
        "confidence": round(conf, 6),
    }


def _residual_learner_proxy(
    *,
    quality_score: float,
    pace_std_s: float,
    median_time_s: float,
    underdrive_idx: float,
) -> dict[str, Any]:
    """
    Residual learner proxy with optional sklearn ridge fit.

    Online path stays lightweight and falls back to deterministic coefficients
    when sklearn is unavailable.
    """
    q = float(np.clip(quality_score, 0.0, 1.0))
    rel_std = float(np.clip(pace_std_s / max(median_time_s, 1e-6), 0.0, 0.5))
    u = float(np.clip(underdrive_idx, 0.0, 0.35))
    feat = np.asarray([[q, rel_std, u]], dtype=float)

    coef = np.array([0.18, -0.35, -0.22], dtype=float)
    intercept = 0.05
    method = "linear_proxy"
    try:
        from sklearn.linear_model import Ridge  # type: ignore[import-not-found]

        # Tiny synthetic anchor set keeps behavior deterministic and bounded.
        X = np.array(
            [
                [0.25, 0.22, 0.20],
                [0.45, 0.18, 0.16],
                [0.65, 0.12, 0.11],
                [0.82, 0.08, 0.06],
                [0.92, 0.05, 0.03],
            ],
            dtype=float,
        )
        y = np.array([0.32, 0.22, 0.14, 0.08, 0.04], dtype=float)
        mdl = Ridge(alpha=1.0, random_state=0)
        mdl.fit(X, y)
        pred = float(mdl.predict(feat)[0])
        method = "ridge_residual_proxy"
    except Exception:
        pred = float(intercept + np.dot(feat.reshape(-1), coef))
        method = "linear_proxy"

    pred = float(np.clip(pred, -0.35, 0.35))
    conf = float(np.clip(0.50 + 0.35 * q - 0.25 * rel_std, 0.0, 1.0))
    return {
        "enabled": True,
        "method": method,
        "predicted_residual_s": round(pred, 6),
        "confidence": round(conf, 6),
    }
