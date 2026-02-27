"""Tests for corner-level sensitivity optimizer."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kart_envelope.coaching.corner_coaching import detect_corners_from_curvature
from kart_envelope.ingest.acd_parser import ACDEngineData
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.inference.session_scalars import SessionScalars
import kart_envelope.optimizer.sensitivity as sensitivity


def _make_suboptimal_best_lap(distance_m: np.ndarray, curvature_1pm: np.ndarray) -> pd.DataFrame:
    """Build a lap profile with intentionally slow speed through one corner."""
    speed_mps = np.full_like(distance_m, 15.0, dtype=float)
    slow_mask = (distance_m >= 100.0) & (distance_m <= 190.0)
    speed_mps[slow_mask] = 8.0

    accel_long_mps2 = np.gradient(speed_mps, distance_m, edge_order=1) * speed_mps
    accel_lat_mps2 = speed_mps * speed_mps * np.abs(curvature_1pm)

    return pd.DataFrame({
        "distance_m": distance_m,
        "speed_mps": speed_mps,
        "accel_long_mps2": accel_long_mps2,
        "accel_lat_mps2": accel_lat_mps2,
    })


def test_rescale_profile_to_target_lap_hits_target():
    distance = np.linspace(0.0, 600.0, 1200)
    baseline = np.full_like(distance, 14.0)
    delta = (
        1.8 * np.exp(-0.5 * ((distance - 160.0) / 28.0) ** 2)
        + 1.3 * np.exp(-0.5 * ((distance - 420.0) / 34.0) ** 2)
    )
    reference = baseline + delta

    target_scale = 0.62
    target_profile = baseline + target_scale * delta
    target_lap = sensitivity._integrate_range(distance, target_profile, float(distance[0]), float(distance[-1]))

    out, lap_s, scale = sensitivity._rescale_profile_to_target_lap(
        distance=distance,
        baseline_speed=baseline,
        reference_speed=reference,
        target_lap_time_s=target_lap,
        max_gain_scale=1.5,
    )
    assert len(out) == len(distance)
    assert np.all(out >= baseline - 1e-9)
    assert lap_s == pytest.approx(target_lap, abs=0.03)
    assert scale == pytest.approx(target_scale, abs=0.06)


def test_smooth_profile_by_distance_reduces_roughness():
    distance = np.linspace(0.0, 500.0, 1000)
    raw = 13.0 + 0.45 * np.sin(distance * 0.35) + 0.25 * np.sin(distance * 1.4)
    sm = sensitivity._smooth_profile_by_distance(
        distance=distance,
        speed=raw,
        window_m=5.0,
        passes=2,
    )
    assert len(sm) == len(raw)
    rough_raw = float(np.mean(np.abs(np.diff(raw, n=2))))
    rough_sm = float(np.mean(np.abs(np.diff(sm, n=2))))
    assert rough_sm < rough_raw


def test_optimize_corner_sensitivity_improves_suboptimal_corner(
    default_config,
    known_envelope,
    small_oval_geometry,
):
    """Sensitivity sweep should find at least one faster candidate."""
    best_lap = _make_suboptimal_best_lap(
        small_oval_geometry.distance_m,
        small_oval_geometry.curvature_1pm,
    )
    corners = detect_corners_from_curvature(
        small_oval_geometry.curvature_1pm,
        small_oval_geometry.distance_m,
    )
    assert corners

    cfg = replace(
        default_config,
        sensitivity_two_stage_search=False,
        sensitivity_grid_size=5,
        sensitivity_apex_grid_size=1,
        sensitivity_line_grid_size=1,
        sensitivity_accept_gain_s=0.001,
        sensitivity_consistency_iterations=2,
        sensitivity_top_recommendations=5,
    )
    metadata = SessionMetadata(
        session_file="synthetic.csv",
        kart_id="test_kart",
        kart_class="4t",
        driver_weight_kg=80.0,
        kart_weight_kg=95.0,
    )

    result = sensitivity.optimize_corner_sensitivity(
        best_lap_df=best_lap,
        resampled_laps={1: best_lap.copy()},
        geometry=small_oval_geometry,
        envelope=known_envelope,
        scalars=SessionScalars(),
        metadata=metadata,
        corners=corners[:1],  # one corner keeps test fast and deterministic
        config=cfg,
    )

    assert result.total_gain_s > 0.0
    assert result.ideal_lap_time_s < result.baseline_lap_time_s
    assert result.accepted_count >= 1
    assert len(result.recommendations) >= 1
    expected_candidates = (
        len(sensitivity._build_shift_candidates(cfg))
        * cfg.sensitivity_force_grid_size ** 2
    )
    assert len(result.candidate_rows) == expected_candidates


def test_optimize_corner_sensitivity_reverts_when_stitched_lap_is_slower(
    default_config,
    known_envelope,
    small_oval_geometry,
    monkeypatch,
):
    """If stitched profile is slower than baseline, result should revert."""
    best_lap = _make_suboptimal_best_lap(
        small_oval_geometry.distance_m,
        small_oval_geometry.curvature_1pm,
    )
    corners = detect_corners_from_curvature(
        small_oval_geometry.curvature_1pm,
        small_oval_geometry.distance_m,
    )

    cfg = replace(
        default_config,
        sensitivity_two_stage_search=False,
        sensitivity_grid_size=3,
        sensitivity_apex_grid_size=1,
        sensitivity_line_grid_size=1,
        sensitivity_accept_gain_s=0.001,
        sensitivity_apply_global_consistency_after_corner=True,
        sensitivity_target_lap_time_s=None,
    )
    metadata = SessionMetadata(session_file="synthetic.csv")

    def _forced_slow_consistency(**kwargs):
        return np.asarray(kwargs["speed_seed"], dtype=float) * 0.5

    monkeypatch.setattr(sensitivity, "_global_consistency_pass", _forced_slow_consistency)

    result = sensitivity.optimize_corner_sensitivity(
        best_lap_df=best_lap,
        resampled_laps={1: best_lap.copy()},
        geometry=small_oval_geometry,
        envelope=known_envelope,
        scalars=SessionScalars(),
        metadata=metadata,
        corners=corners[:1],
        config=cfg,
    )

    assert result.total_gain_s == pytest.approx(0.0, abs=1e-9)
    assert result.accepted_count == 0
    assert result.recommendations == []
    np.testing.assert_allclose(result.ideal_speed_mps, result.baseline_speed_mps)


def test_build_vehicle_model_applies_engine_power_cap(default_config, known_envelope):
    """Explicit engine peak power metadata should cap fitted power envelope."""
    distance_m = np.linspace(0.0, 495.0, 100)
    speed_mps = np.linspace(3.0, 18.0, 100)
    accel_long_mps2 = np.linspace(0.2, 2.0, 100)

    lap_df = pd.DataFrame({
        "distance_m": distance_m,
        "speed_mps": speed_mps,
        "accel_long_mps2": accel_long_mps2,
    })
    metadata = SessionMetadata(
        session_file="synthetic.csv",
        driver_weight_kg=80.0,
        kart_weight_kg=95.0,
        engine_peak_power_kw=1.0,
    )

    model = sensitivity._build_vehicle_model(
        resampled_laps={1: lap_df},
        env=known_envelope,
        metadata=metadata,
        config=default_config,
    )
    assert model is not None

    expected_power_w_per_kg = 1000.0 / (80.0 + 95.0)
    assert model.estimated_peak_power_w_per_kg == pytest.approx(expected_power_w_per_kg)
    assert float(np.max(model.power_envelope_w_per_kg)) <= expected_power_w_per_kg + 1e-9


def test_build_vehicle_model_uses_hp_when_kw_missing(default_config, known_envelope):
    """Horsepower metadata should convert to kW and cap power envelope."""
    distance_m = np.linspace(0.0, 495.0, 100)
    speed_mps = np.linspace(3.0, 18.0, 100)
    accel_long_mps2 = np.linspace(0.2, 2.0, 100)

    lap_df = pd.DataFrame({
        "distance_m": distance_m,
        "speed_mps": speed_mps,
        "accel_long_mps2": accel_long_mps2,
    })
    metadata = SessionMetadata(
        session_file="synthetic.csv",
        driver_weight_kg=80.0,
        kart_weight_kg=95.0,
        engine_peak_power_hp=8.0,
    )
    model = sensitivity._build_vehicle_model(
        resampled_laps={1: lap_df},
        env=known_envelope,
        metadata=metadata,
        config=default_config,
    )
    assert model is not None
    expected_power_w_per_kg = 8.0 * 0.745699872 * 1000.0 / (80.0 + 95.0)
    assert model.estimated_peak_power_w_per_kg == pytest.approx(expected_power_w_per_kg)


def test_knn_corner_ml_prediction_is_finite(default_config):
    dataset = sensitivity._CornerMLDataset(
        feature_matrix=np.array([
            [14.0, 20.0, 2.0],
            [14.5, 18.0, 1.0],
            [13.5, 22.0, 3.0],
        ], dtype=float),
        target_time_s=np.array([8.20, 8.05, 8.35], dtype=float),
        feature_scale=np.array([0.5, 2.0, 1.0], dtype=float),
    )
    cfg = replace(default_config, sensitivity_ml_k_neighbors=2)
    pred = sensitivity._predict_corner_time_knn(
        dataset=dataset,
        features=np.array([14.2, 19.0, 1.5], dtype=float),
        config=cfg,
    )
    assert pred is not None
    assert np.isfinite(pred)
    assert 7.5 < pred < 9.0


def test_optimize_corner_sensitivity_populates_ml_fields(
    default_config,
    known_envelope,
    small_oval_geometry,
):
    best_lap = _make_suboptimal_best_lap(
        small_oval_geometry.distance_m,
        small_oval_geometry.curvature_1pm,
    )
    lap_fast = best_lap.copy()
    lap_slow = best_lap.copy()

    # Build lap variants so the ML layer has multiple corner examples.
    d = small_oval_geometry.distance_m
    lap_fast.loc[(d >= 105.0) & (d <= 190.0), "speed_mps"] = 9.5
    lap_slow.loc[(d >= 95.0) & (d <= 190.0), "speed_mps"] = 7.5
    for lap in (lap_fast, lap_slow):
        lap["accel_long_mps2"] = np.gradient(lap["speed_mps"].to_numpy(), d, edge_order=1) * lap["speed_mps"].to_numpy()
        lap["accel_lat_mps2"] = lap["speed_mps"].to_numpy() ** 2 * np.abs(small_oval_geometry.curvature_1pm)

    corners = detect_corners_from_curvature(
        small_oval_geometry.curvature_1pm,
        small_oval_geometry.distance_m,
    )
    cfg = replace(
        default_config,
        sensitivity_two_stage_search=False,
        sensitivity_grid_size=5,
        sensitivity_apex_grid_size=1,
        sensitivity_line_grid_size=1,
        sensitivity_accept_gain_s=0.001,
        sensitivity_ml_enable=True,
        sensitivity_ml_min_samples=2,
        sensitivity_ml_k_neighbors=2,
        sensitivity_ml_blend=0.5,
    )
    metadata = SessionMetadata(session_file="synthetic.csv")

    result = sensitivity.optimize_corner_sensitivity(
        best_lap_df=best_lap,
        resampled_laps={1: best_lap.copy(), 2: lap_fast, 3: lap_slow},
        geometry=small_oval_geometry,
        envelope=known_envelope,
        scalars=SessionScalars(),
        metadata=metadata,
        corners=corners[:1],
        config=cfg,
    )

    assert result.ml_enabled is True
    assert result.ml_training_rows >= 2
    assert any(row.get("ml_corner_time_s") is not None for row in result.candidate_rows)


@pytest.mark.parametrize(
    ("tire_type", "condition_label", "expected"),
    [
        ("slick", "dry", 1.00),
        ("slick", "wet", 0.88),
        ("wet", "dry", 0.94),
        ("wet", "damp", 1.00),
        ("unknown", "wet", 1.00),  # fallback
    ],
)
def test_tire_condition_scale_lookup(tire_type: str, condition_label: str, expected: float):
    metadata = SessionMetadata(
        session_file="synthetic.csv",
        tire_type=tire_type,
        condition_label=condition_label,
    )
    scalars = SessionScalars(condition_label=condition_label)
    actual = sensitivity._tire_condition_scale(metadata, scalars)
    assert actual == pytest.approx(expected)


def test_build_vehicle_model_uses_acd_curve_when_available(
    default_config,
    known_envelope,
    monkeypatch,
):
    """ACD RPM/torque curve should raise available power envelope."""
    distance_m = np.linspace(0.0, 495.0, 120)
    speed_mps = np.linspace(3.0, 18.0, 120)
    accel_long_mps2 = np.linspace(0.2, 1.2, 120)
    lap_df = pd.DataFrame({
        "distance_m": distance_m,
        "speed_mps": speed_mps,
        "accel_long_mps2": accel_long_mps2,
    })
    metadata = SessionMetadata(
        session_file="synthetic.csv",
        driver_weight_kg=85.0,
        kart_weight_kg=95.0,
        kart_data_acd="dummy/data.acd",
    )

    acd = ACDEngineData(
        acd_path="dummy/data.acd",
        key="1-2-3-4-5-6-7-8",
        key_score=1.0,
        entry_count=3,
        engine_curve_file="power.lut",
        limiter_rpm=5000.0,
        minimum_rpm=1200.0,
        coast_rpm=5000.0,
        coast_torque_nm=25.0,
        total_mass_kg=220.0,
        screen_name="Dummy GX390",
        displacement_cc=390.0,
        rpm=np.array([1000.0, 2500.0, 4000.0, 5000.0]),
        torque_nm=np.array([12.0, 26.0, 22.0, 0.0]),
        power_kw=np.array([1.2, 6.8, 9.2, 0.0]),
    )

    monkeypatch.setattr(
        sensitivity,
        "resolve_acd_path",
        lambda _meta: Path("dummy/data.acd"),
    )
    monkeypatch.setattr(
        sensitivity,
        "load_acd_engine_data",
        lambda _path: acd,
    )

    model = sensitivity._build_vehicle_model(
        resampled_laps={1: lap_df},
        env=known_envelope,
        metadata=metadata,
        config=default_config,
    )
    assert model is not None
    # Peak from ACD: 9.2 kW with quality scale 1.0 and total mass 180 kg.
    expected_peak = 9200.0 / (85.0 + 95.0)
    assert model.estimated_peak_power_w_per_kg >= expected_peak * 0.999
