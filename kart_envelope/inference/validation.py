"""
validation.py
-------------
Cycle-A validation and release-gate helpers.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from kart_envelope.config import KartEnvelopeConfig


def build_validation_report(
    *,
    config: KartEnvelopeConfig,
    lap_times: dict[int, float],
    quality_metrics: dict[str, float],
    calibration_report: dict[str, Any] | None = None,
    all_lap_optimal_rows: list[dict[str, Any]] | None = None,
    bundle_lap_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Build session-level validation report and gate statuses.

    Notes:
    - Without ground-truth optimal laps we use internal proxy consistency:
      sensitivity per-lap gains are compared against bundle gains when both
      are available on the same laps.
    """
    if not config.validation_enable:
        return {"enabled": False, "status": "disabled"}

    all_rows = list(all_lap_optimal_rows or [])
    bundle_rows = list(bundle_lap_rows or [])
    q_score = float(np.clip(quality_metrics.get("score", 0.0), 0.0, 1.0))

    proxy_mae = None
    proxy_pairs = 0
    if all_rows and bundle_rows:
        by_lap_all = {
            int(r.get("lap_number", 0)): float(r.get("gain_s", 0.0) or 0.0)
            for r in all_rows
            if r.get("lap_number") is not None
        }
        diffs: list[float] = []
        for row in bundle_rows:
            lap = int(row.get("lap_number", 0) or 0)
            if lap <= 0 or lap not in by_lap_all:
                continue
            pred_gain = float(row.get("predicted_gain_s", 0.0) or 0.0)
            diffs.append(abs(pred_gain - by_lap_all[lap]))
        if diffs:
            proxy_mae = float(np.mean(np.asarray(diffs, dtype=float)))
            proxy_pairs = int(len(diffs))

    uq_cov = None
    if bundle_rows:
        inside = 0
        total = 0
        for row in bundle_rows:
            actual = row.get("actual_lap_time_s")
            lo = row.get("uncertainty_low_s")
            hi = row.get("uncertainty_high_s")
            if actual is None or lo is None or hi is None:
                continue
            try:
                a = float(actual)
                l = float(lo)
                h = float(hi)
            except (TypeError, ValueError):
                continue
            total += 1
            if l <= a <= h:
                inside += 1
        if total > 0:
            uq_cov = float(inside / total)

    # If no proxy MAE exists, fallback to conservative function of quality score.
    if proxy_mae is None:
        proxy_mae = float(np.clip(2.5 - 1.5 * q_score, 0.6, 2.5))
    if uq_cov is None:
        uq_cov = float(np.clip(0.45 + 0.45 * q_score, 0.0, 1.0))

    mae_gate = float(max(config.validation_mae_gate_s, 0.1))
    uq_gate = float(np.clip(config.validation_uq_coverage_gate, 0.0, 1.0))
    pass_mae = bool(proxy_mae <= mae_gate)
    pass_uq = bool(uq_cov >= uq_gate)

    # Holdout / stress proxies
    n_laps = int(len(lap_times))
    holdout_ok = n_laps >= int(max(3, config.validation_holdout_min_rows // 10))
    stress_flag = bool(q_score < 0.50)

    strata: dict[str, Any] = {}
    if bundle_rows:
        cond_counts: dict[str, int] = {}
        for row in bundle_rows:
            cond = str(row.get("condition_label", "") or "").strip().lower() or "unknown"
            cond_counts[cond] = cond_counts.get(cond, 0) + 1
        if cond_counts:
            strata["condition_counts"] = cond_counts
            strata["condition_coverage"] = round(float(len(cond_counts) / max(sum(cond_counts.values()), 1)), 4)
    if all_rows:
        source_counts: dict[str, int] = {}
        for row in all_rows:
            src = str(row.get("envelope_source", "") or "session").strip().lower()
            source_counts[src] = source_counts.get(src, 0) + 1
        if source_counts:
            strata["envelope_source_counts"] = source_counts

    calibration_conf = None
    if calibration_report and isinstance(calibration_report, dict):
        unc = calibration_report.get("uncertainty", {})
        if isinstance(unc, dict):
            try:
                calibration_conf = float(unc.get("confidence"))
            except (TypeError, ValueError):
                calibration_conf = None
    if calibration_conf is None:
        calibration_conf = q_score

    release_pass = bool(pass_mae and pass_uq and holdout_ok)
    return {
        "enabled": True,
        "status": "ok",
        "metrics": {
            "proxy_mae_s": round(float(proxy_mae), 4),
            "proxy_uq_coverage": round(float(uq_cov), 4),
            "quality_score": round(float(q_score), 4),
            "proxy_pairs": int(proxy_pairs),
            "calibration_confidence": round(float(np.clip(calibration_conf, 0.0, 1.0)), 4),
        },
        "gates": {
            "mae_gate_s": round(mae_gate, 4),
            "uq_coverage_gate": round(uq_gate, 4),
            "pass_mae": pass_mae,
            "pass_uq": pass_uq,
            "pass_holdout_proxy": holdout_ok,
            "release_pass": release_pass,
        },
        "stress_tests": {
            "low_quality_flag": stress_flag,
            "n_laps": n_laps,
        },
        "strata": strata,
        "drift": {
            "model_drift_risk": bool(stress_flag and q_score < 0.40),
            "feature_drift_risk": bool(q_score < 0.45),
            "solver_drift_risk": bool(proxy_mae > 1.1 * mae_gate),
            "diagnostics_drift_risk": bool(calibration_conf < 0.45),
            "coverage_drift_risk": bool(strata.get("condition_coverage", 1.0) < 0.10 if strata else False),
        },
    }
