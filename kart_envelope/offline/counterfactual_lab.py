"""
counterfactual_lab.py
---------------------
Offline synthetic counterfactual expansion for bundle_v2 training.

The goal is to increase model coverage offline while keeping online inference
cheap. This module perturbs lap-level features and derives conservative target
adjustments using a deterministic heuristic.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from kart_envelope.offline.dataset_builder import (
    CATEGORICAL_FEATURE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    TARGET_COLUMNS,
)

logger = logging.getLogger(__name__)


def generate_counterfactual_dataset(
    df: pd.DataFrame,
    output_path: Path,
    *,
    samples_per_row: int = 6,
    noise_scale: float = 0.08,
    random_state: int = 42,
) -> pd.DataFrame:
    """
    Generate synthetic counterfactual rows from a base offline dataset.

    The perturbation space focuses on driving execution proxies:
    - pace/consistency (actual_lap_time_s, gain_pct)
    - braking/turning execution (accepted/evaluated ratio proxy)
    - condition grip quality (session_mu/session_b)
    """
    if df.empty:
        raise ValueError("Counterfactual generator received an empty dataset.")

    rng = np.random.default_rng(int(random_state))
    out_rows: list[dict[str, object]] = []
    s_per = int(max(1, samples_per_row))
    ns = float(max(1e-4, noise_scale))

    numeric_cols = [c for c in NUMERIC_FEATURE_COLUMNS if c in df.columns]
    for base in df.to_dict(orient="records"):
        base_gain = float(_to_float(base.get("gain_s")))
        base_opt = float(_to_float(base.get("optimal_lap_time_s")))
        base_actual = float(_to_float(base.get("actual_lap_time_s")))
        for _ in range(s_per):
            row = dict(base)
            z1 = float(rng.normal(0.0, ns))
            z2 = float(rng.normal(0.0, ns))
            z3 = float(rng.normal(0.0, ns))

            # Execution perturbations.
            _scale(row, "actual_lap_time_s", 1.0 + z1)
            _scale(row, "gain_pct", 1.0 + 1.2 * z2)
            _scale(row, "session_mu", 1.0 + 0.6 * z3)
            _scale(row, "session_b", 1.0 + 0.4 * z2)
            _scale(row, "quality_score", 1.0 + 0.2 * z3)
            _scale(row, "quality_accel_coverage", 1.0 + 0.2 * z1)

            # Keep bounded features in realistic ranges.
            row["quality_score"] = _clip(row.get("quality_score"), 0.0, 1.0)
            row["quality_speed_coverage"] = _clip(row.get("quality_speed_coverage"), 0.0, 1.0)
            row["quality_accel_coverage"] = _clip(row.get("quality_accel_coverage"), 0.0, 1.0)
            row["quality_yaw_coverage"] = _clip(row.get("quality_yaw_coverage"), 0.0, 1.0)
            row["session_mu"] = _clip(row.get("session_mu"), 0.35, 1.40)
            row["session_p"] = _clip(row.get("session_p"), 0.35, 1.70)
            row["session_b"] = _clip(row.get("session_b"), 0.35, 1.60)

            # Heuristic target update: better quality/grip tends to increase gain.
            quality_delta = float(_to_float(row.get("quality_score"))) - float(_to_float(base.get("quality_score")))
            mu_delta = float(_to_float(row.get("session_mu"))) - float(_to_float(base.get("session_mu")))
            actual_delta = float(_to_float(row.get("actual_lap_time_s"))) - base_actual
            gain_delta = 0.7 * quality_delta + 1.1 * mu_delta + 0.05 * actual_delta
            new_gain = max(0.0, base_gain + gain_delta)
            new_opt = max(0.01, float(_to_float(row.get("actual_lap_time_s"))) - new_gain)

            row["gain_s"] = float(new_gain)
            row["optimal_lap_time_s"] = float(new_opt)
            row["synthetic"] = 1
            row["counterfactual_noise_z"] = float(z1)
            out_rows.append(row)

    cf = pd.DataFrame(out_rows)
    for col in numeric_cols + TARGET_COLUMNS + ["counterfactual_noise_z"]:
        if col in cf.columns:
            cf[col] = pd.to_numeric(cf[col], errors="coerce")
    for col in CATEGORICAL_FEATURE_COLUMNS + ["diag_primary_code", "session_id", "session_file"]:
        if col in cf.columns:
            cf[col] = cf[col].fillna("").astype(str)
    cf = cf.replace([np.inf, -np.inf], np.nan).dropna(subset=["optimal_lap_time_s", "gain_s"])
    cf = cf.reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".parquet":
        try:
            cf.to_parquet(output_path, index=False)
        except Exception:
            cf.to_csv(output_path.with_suffix(".csv"), index=False)
    else:
        cf.to_csv(output_path, index=False)

    logger.info("Counterfactual dataset generated: %d rows -> %s", len(cf), output_path)
    return cf


def _to_float(v: object) -> float:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(out):
        return 0.0
    return float(out)


def _scale(row: dict[str, object], key: str, factor: float) -> None:
    if key not in row:
        return
    base = _to_float(row.get(key))
    row[key] = float(base * factor)


def _clip(v: object, lo: float, hi: float) -> float:
    return float(np.clip(_to_float(v), lo, hi))

