"""Tests for bundle_v2 inference and validation helpers."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kart_envelope.config import default_config
from kart_envelope.inference.bundle_v2 import (
    estimate_optimal_speed_profile,
    resolve_bundle_path,
    run_bundle_inference,
)
from kart_envelope.offline.validate_bundle import validate_bundle

try:
    import joblib  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
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


def _fit_minimal_bundle_models() -> dict[str, object]:
    pytest.importorskip("sklearn")
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.preprocessing import OneHotEncoder

    num_cols = ["actual_lap_time_s", "quality_score"]
    cat_cols = ["track_name", "kart_id", "condition_label"]
    x = pd.DataFrame({
        "actual_lap_time_s": [50.0, 51.0, 52.0, 49.5, 53.0, 48.0],
        "quality_score": [0.3, 0.4, 0.5, 0.8, 0.6, 0.9],
        "track_name": ["cks", "cks", "cks", "cks", "cks", "cks"],
        "kart_id": ["kart1"] * 6,
        "condition_label": ["dry", "dry", "wet", "dry", "wet", "dry"],
    })
    y_opt = np.array([49.4, 50.4, 51.4, 48.5, 52.4, 47.2], dtype=float)
    y_gain = np.array([0.6, 0.6, 0.6, 1.0, 0.6, 0.8], dtype=float)

    try:
        ohe = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        ohe = OneHotEncoder(handle_unknown="ignore", sparse=False)
    pre = ColumnTransformer([
        ("num", "passthrough", num_cols),
        ("cat", ohe, cat_cols),
    ])
    xt = pre.fit_transform(x)

    m_opt = GradientBoostingRegressor(random_state=42, n_estimators=40, max_depth=2)
    m_gain = GradientBoostingRegressor(random_state=43, n_estimators=40, max_depth=2)
    m_opt.fit(xt, y_opt)
    m_gain.fit(xt, y_gain)
    return {"pre": pre, "m_opt": m_opt, "m_gain": m_gain}


def test_resolve_bundle_path_exact_and_global(tmp_path: Path):
    cfg = default_config()
    root = tmp_path / "bundles"
    object.__setattr__(cfg, "bundle_v2_dir", str(root))
    object.__setattr__(cfg, "bundle_v2_tier_subdirs", True)
    object.__setattr__(cfg, "product_tier", "b2c")

    exact = root / "b2c" / "cks" / "kart1" / "bundle_v2"
    exact.mkdir(parents=True)
    got, source = resolve_bundle_path("CKS", "kart1", cfg, product_tier="b2c")
    assert got == exact
    assert source == "tier_exact"

    # remove exact; fallback to global
    for p in exact.iterdir():
        p.unlink()
    exact.rmdir()
    (root / "b2c" / "_global" / "_global" / "bundle_v2").mkdir(parents=True)
    got2, source2 = resolve_bundle_path("CKS", "kart1", cfg, product_tier="b2c")
    assert source2 == "tier_global"
    assert got2 is not None


def test_run_bundle_inference_and_validate_bundle(tmp_path: Path):
    bundle_dir = tmp_path / "cks" / "kart1" / "bundle_v2"
    bundle_dir.mkdir(parents=True)
    fitted = _fit_minimal_bundle_models()

    joblib.dump(
        {
            "preprocessor": fitted["pre"],
            "model_optimal": fitted["m_opt"],
            "model_gain": fitted["m_gain"],
            "model_diag": None,
        },
        bundle_dir / "student_regressor.joblib",
    )
    joblib.dump({"preprocessor": fitted["pre"], "model_optimal": fitted["m_opt"], "model_gain": fitted["m_gain"]},
                bundle_dir / "student_multitask.joblib")
    joblib.dump({"default_condition": "dry"}, bundle_dir / "gate_model.joblib")

    schema = {
        "numeric_features": ["actual_lap_time_s", "quality_score"],
        "categorical_features": ["track_name", "kart_id", "condition_label"],
        "targets": ["optimal_lap_time_s", "gain_s"],
        "version": 2,
    }
    (bundle_dir / "policy_corner_table.parquet").write_text("placeholder", encoding="utf-8")
    (bundle_dir / "envelope_4d_lut.parquet").write_text("placeholder", encoding="utf-8")
    (bundle_dir / "sector_dp_cache.parquet").write_text("placeholder", encoding="utf-8")
    with open(bundle_dir / "feature_schema.json", "w", encoding="utf-8") as fh:
        json.dump(schema, fh)
    with open(bundle_dir / "uncertainty_quantiles.json", "w", encoding="utf-8") as fh:
        json.dump({"residual_q10_s": -0.2, "residual_q90_s": 0.2, "residual_sigma_s": 0.1}, fh)
    with open(bundle_dir / "calibration.json", "w", encoding="utf-8") as fh:
        json.dump({"intercept": 0.9, "slope_quality": 0.1, "min": 0.6, "max": 1.0}, fh)
    with open(bundle_dir / "bundle_meta.json", "w", encoding="utf-8") as fh:
        json.dump({"track_name": "cks", "kart_id": "kart1"}, fh)

    lap_features = pd.DataFrame([
        {
            "lap_number": 1,
            "actual_lap_time_s": 50.0,
            "quality_score": 0.8,
            "track_name": "cks",
            "kart_id": "kart1",
            "condition_label": "dry",
        },
        {
            "lap_number": 2,
            "actual_lap_time_s": 51.0,
            "quality_score": 0.7,
            "track_name": "cks",
            "kart_id": "kart1",
            "condition_label": "wet",
        },
    ])
    cfg = default_config()
    result = run_bundle_inference(bundle_dir, lap_features, config=cfg)
    assert result.n_laps == 2
    assert result.predicted_optimal_lap_s > 0
    assert len(result.lap_rows) == 2

    rep = validate_bundle(bundle_dir, sample_df=lap_features)
    assert rep["smoke_inference_ok"] is True
    assert rep["errors"] == []


def _lap_time(distance: np.ndarray, speed: np.ndarray) -> float:
    ds = np.diff(distance)
    v = np.maximum(0.5 * (speed[:-1] + speed[1:]), 0.3)
    return float(np.sum(np.maximum(ds, 1e-4) / v))


def test_estimate_optimal_speed_profile_prefers_corner_template_shape():
    distance = np.linspace(0.0, 1000.0, 1200)
    baseline = (
        20.0
        - 5.0 * np.exp(-0.5 * ((distance - 260.0) / 45.0) ** 2)
        - 4.0 * np.exp(-0.5 * ((distance - 650.0) / 55.0) ** 2)
    )
    baseline = np.maximum(baseline, 5.0)
    template = baseline + (
        1.7 * np.exp(-0.5 * ((distance - 255.0) / 22.0) ** 2)
        + 1.4 * np.exp(-0.5 * ((distance - 648.0) / 24.0) ** 2)
    )

    best_actual = 53.0
    predicted_optimal = 52.5
    out = estimate_optimal_speed_profile(
        baseline_speed_mps=baseline,
        best_actual_lap_s=best_actual,
        predicted_optimal_lap_s=predicted_optimal,
        distance_m=distance,
        sensitivity_template_speed_mps=template,
    )

    assert len(out) == len(baseline)
    assert np.all(out >= baseline - 1e-9)
    assert _lap_time(distance, out) < _lap_time(distance, baseline)

    delta = out - baseline
    corner_mask = (
        ((distance >= 210.0) & (distance <= 320.0))
        | ((distance >= 600.0) & (distance <= 710.0))
    )
    straight_mask = (distance < 120.0) | (distance > 870.0)
    assert float(np.mean(delta[corner_mask])) > float(np.mean(delta[straight_mask])) * 2.0


def test_estimate_optimal_speed_profile_fallback_is_not_uniform():
    distance = np.linspace(0.0, 950.0, 950)
    baseline = (
        19.0
        - 4.5 * np.exp(-0.5 * ((distance - 230.0) / 40.0) ** 2)
        - 3.8 * np.exp(-0.5 * ((distance - 560.0) / 45.0) ** 2)
        - 2.7 * np.exp(-0.5 * ((distance - 790.0) / 34.0) ** 2)
    )
    baseline = np.maximum(baseline, 4.8)
    corners = [
        {"corner_id": 1, "s_start": 190.0, "s_apex": 230.0, "s_end": 280.0},
        {"corner_id": 2, "s_start": 520.0, "s_apex": 560.0, "s_end": 610.0},
        {"corner_id": 3, "s_start": 760.0, "s_apex": 790.0, "s_end": 825.0},
    ]
    recs = [
        {"corner_id": 1, "gain_s": 0.08, "brake_point_m": 186.0, "turn_in_point_m": 205.0, "brake_shift_s": 0.12, "turn_shift_m": 2.5},
        {"corner_id": 2, "gain_s": 0.05, "brake_point_m": 515.0, "turn_in_point_m": 535.0, "brake_shift_s": 0.08, "turn_shift_m": 1.8},
    ]

    out = estimate_optimal_speed_profile(
        baseline_speed_mps=baseline,
        best_actual_lap_s=51.2,
        predicted_optimal_lap_s=50.8,
        distance_m=distance,
        corners=corners,
        corner_recommendations=recs,
    )
    delta = out - baseline
    assert len(delta) == len(baseline)
    assert np.all(delta >= -1e-9)
    assert _lap_time(distance, out) < _lap_time(distance, baseline)

    boost_near_corner = float(np.mean(delta[(distance > 500.0) & (distance < 620.0)]))
    boost_straight = float(np.mean(delta[(distance < 90.0) | (distance > 900.0)]))
    assert boost_near_corner > boost_straight * 1.8
