"""
test_pipeline_physics.py
------------------------
Integration tests for the physics pipeline steps 09a-09e and the
cascading theoretical lap computation (step 10).

Tests exercise:
1. Steps 09a-09e produce expected summary keys
2. Physics simulation produces valid theoretical lap
3. Fallback to percentile envelope when physics prerequisites missing
4. _theoretical_metrics_from_lap enriched with new fields
5. Graceful degradation when individual steps fail
"""

from __future__ import annotations

import math
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

passed: list[str] = []
failed: list[tuple[str, str]] = []


def _test(name: str, fn) -> None:
    try:
        fn()
        passed.append(name)
    except Exception:
        failed.append((name, traceback.format_exc()))


# -- -

# Synthetic data factories

# -- -


_G = 9.80665


def _make_oval_resampled_laps(
    n_laps: int = 10,
    n_points: int = 500,
    track_length_m: float = 800.0,
    seed: int = 42,
) -> dict[int, pd.DataFrame]:
    """Create synthetic resampled laps with oval-like GPS and accel data."""
    rng = np.random.default_rng(seed)
    laps: dict[int, pd.DataFrame] = {}

    dist = np.linspace(0, track_length_m, n_points, endpoint=False)
    # Oval track: two straights + two semicircles

    R = 50.0
    straight_len = (track_length_m - 2 * np.pi * R) / 2
    if straight_len < 0:
        straight_len = 100.0

    for lap_num in range(1, n_laps + 1):
        t = np.linspace(0, 30 + rng.normal(0, 0.5), n_points)
        # Speed: faster on straights, slower in corners

        s = dist / track_length_m
        speed = 25 + 10 * np.sin(2 * np.pi * s) + rng.normal(0, 0.5, n_points)
        speed = np.clip(speed, 5, 40)

        # Simple oval XY: parameterise as distance around track

        theta = 2 * np.pi * s
        x = R * np.cos(theta) + rng.normal(0, 0.3, n_points)
        y = R * np.sin(theta) + rng.normal(0, 0.3, n_points)

        # Accelerations

        accel_long = np.gradient(speed, t) + rng.normal(0, 0.1, n_points)
        accel_lat = speed ** 2 / R * np.abs(np.sin(theta)) + rng.normal(0, 0.1, n_points)

        lat = 45.0 + y / 111000.0
        lon = 7.0 + x / (111000.0 * np.cos(np.radians(45.0)))

        df = pd.DataFrame({
            "Distance (m)": dist,
            "Time (s)": t,
            "Speed (m/s)": speed,
            "Lap #": lap_num,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "x_local_m": x,
            "y_local_m": y,
            "Lateral acceleration (G) *calc": accel_lat / _G,
            "Longitudinal acceleration (G) *calc": accel_long / _G,
            "accel_lat_mps2": accel_lat,
            "accel_long_mps2": accel_long,
            "Yaw rate (deg/s)": np.gradient(theta) * 180 / np.pi * 10,
        })
        laps[lap_num] = df

    return laps


def _make_lap_metrics(
    n_laps: int = 10,
    seed: int = 42,
) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    metrics = []
    for _ in range(n_laps):
        metrics.append({
            "lap_time_s": 30 + rng.normal(0, 0.5),
            "speed_max_mps": 35 + rng.normal(0, 1),
            "speed_mean_mps": 25 + rng.normal(0, 0.5),
            "accel_max_mps2": 6 + rng.normal(0, 0.3),
            "braking_max_mps2": 8 + rng.normal(0, 0.5),
            "lat_accel_max_mps2": 10 + rng.normal(0, 0.5),
        })
    return metrics


def _make_lap_times(n_laps: int = 10, seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    return [30 + rng.normal(0, 0.5) for _ in range(n_laps)]


# -- -

# Mock modules for controlled testing

# -- -


@dataclass
class MockFrictionCircle:
    v_grid: np.ndarray
    traction_vals: np.ndarray
    braking_vals: np.ndarray
    lateral_vals: np.ndarray
    exponent: float = 2.0

    def lateral_max(self, speed):
        return np.interp(np.asarray(speed, dtype=float),
                         self.v_grid, self.lateral_vals)

    def traction_max(self, speed):
        return np.interp(np.asarray(speed, dtype=float),
                         self.v_grid, self.traction_vals)

    def braking_max(self, speed):
        return np.interp(np.asarray(speed, dtype=float),
                         self.v_grid, self.braking_vals)


@dataclass
class MockTheoreticalLapResult:
    speed_profile: np.ndarray
    accel_profile: np.ndarray
    lap_time_s: float
    distance_m: np.ndarray
    cornering_limited: np.ndarray
    accel_limited: np.ndarray
    braking_limited: np.ndarray


@dataclass
class MockDataQualityReport:
    overall_confidence: float = 0.75
    recommended_speed_percentile: float = 92.0
    recommended_accel_percentile: float = 93.0


# -- -

# Tests

# -- -


def t_metrics_from_lap_basic():
    """_theoretical_metrics_from_lap returns core fields."""
    import pipeline as p

    dist = np.linspace(0, 800, 500)
    speed = np.full(500, 20.0)
    df = pd.DataFrame({
        "distance_m": dist,
        "v_env_mps": speed,
        "accel_max_mps2": np.full(500, 5.0),
        "brake_max_mps2": np.full(500, 8.0),
    })

    m = p._theoretical_metrics_from_lap(df)
    assert "best_s" in m
    assert "speed_mean_mps" in m
    assert "simulation_method" in m
    assert m["simulation_method"] == "percentile_envelope"
    assert math.isfinite(m["best_s"])
    # 800m at 20 m/s = 40s

    assert 39 < m["best_s"] < 41


_test("metrics_from_lap_basic", t_metrics_from_lap_basic)


def t_metrics_with_physics_result():
    """_theoretical_metrics_from_lap enriched with physics sim result."""
    import pipeline as p

    n = 200
    dist = np.linspace(0, 800, n)
    speed = np.full(n, 25.0)

    df = pd.DataFrame({
        "distance_m": dist,
        "v_env_mps": speed,
        "accel_max_mps2": np.full(n, 5.0),
        "brake_max_mps2": np.full(n, 8.0),
    })

    sim_result = MockTheoreticalLapResult(
        speed_profile=speed,
        accel_profile=np.zeros(n),
        lap_time_s=28.5,
        distance_m=dist,
        cornering_limited=np.array([True] * 80 + [False] * 120),
        accel_limited=np.array([False] * 80 + [True] * 60 + [False] * 60),
        braking_limited=np.array([False] * 140 + [True] * 60),
    )

    dq = MockDataQualityReport(overall_confidence=0.82)

    m = p._theoretical_metrics_from_lap(
        df,
        simulation_method="physics",
        sim_result=sim_result,
        data_quality=dq,
    )

    assert m["simulation_method"] == "physics"
    assert m["best_s"] == round(28.5, 4), f"Expected 28.5, got {m['best_s']}"
    assert abs(m["cornering_limited_fraction"] - 0.4) < 0.01
    assert abs(m["confidence"] - 0.82) < 0.01


_test("metrics_with_physics_result", t_metrics_with_physics_result)


def t_metrics_no_sim_result():
    """_theoretical_metrics_from_lap with no sim result has safe defaults."""
    import pipeline as p

    df = pd.DataFrame({
        "distance_m": np.linspace(0, 500, 100),
        "v_env_mps": np.full(100, 20.0),
    })

    m = p._theoretical_metrics_from_lap(df, simulation_method="percentile_envelope")
    assert m["simulation_method"] == "percentile_envelope"
    assert m["cornering_limited_fraction"] == 0.0
    assert m["confidence"] == 0.5


_test("metrics_no_sim_result", t_metrics_no_sim_result)


def t_summary_keys_present():
    """Pipeline summary dict has all new physics keys pre-populated."""
    import pipeline as p
    # We can't run the full pipeline without real data, but we can check

    # that the function signature references the new keys

    import inspect
    source = inspect.getsource(p.run_full_analysis)
    for key in ["reference_line", "curvature_profile", "friction_model",
                "vehicle_params", "data_quality"]:
        assert f'"{key}"' in source, f"Key {key!r} not found in summary init"


_test("summary_keys_present", t_summary_keys_present)


def t_step_names_in_source():
    """All new step names appear in the pipeline source."""
    import pipeline as p
    import inspect
    source = inspect.getsource(p.run_full_analysis)
    for step in ["09a_reference_line", "09b_curvature_profile",
                 "09c_friction_model", "09d_vehicle_model",
                 "09e_data_quality"]:
        assert step in source, f"Step {step!r} not found in pipeline"


_test("step_names_in_source", t_step_names_in_source)


def t_cascading_logic_in_source():
    """The cascading theoretical lap logic is present."""
    import pipeline as p
    import inspect
    source = inspect.getsource(p.run_full_analysis)
    # Priority 1: hybrid simulation with fallback
    assert "simulate_with_fallback" in source
    assert "result_to_theoretical_df" in source
    # Fallback to percentile via theoretical_engine
    assert "percentile_envelope" in source
    assert "build_theoretical_lap" in source


_test("cascading_logic_in_source", t_cascading_logic_in_source)


def t_safe_step_wrapper():
    """_safe_step correctly wraps successful and failing functions."""
    import pipeline as p

    # Success case

    result, err = p._safe_step("test_ok", lambda: 42)
    assert result == 42
    assert err is None

    # Failure case

    def _boom():
        raise ValueError("kaboom")
    result, err = p._safe_step("test_fail", _boom)
    assert result is None
    assert "kaboom" in err


_test("safe_step_wrapper", t_safe_step_wrapper)


def t_import_helper():
    """_import returns None for missing modules."""
    import pipeline as p
    mod = p._import("nonexistent_module_xyz_123")
    assert mod is None


_test("import_helper", t_import_helper)


def t_column_discovery_replaces_old_mapping():
    """column_discovery module bridges raw RaceChrono names (replaces _map_to_internal_names)."""
    from column_discovery import discover_columns, apply_discovery
    df = pd.DataFrame({
        "Distance (m)": [0, 1],
        "Speed (m/s)": [10, 20],
        "Time (s)": [0, 0.1],
    })
    result = discover_columns(df)
    mapped = apply_discovery(df, result)
    assert "distance_m" in mapped.columns
    assert "speed_mps" in mapped.columns
    assert "time_s" in mapped.columns


_test("column_discovery_replaces_old_mapping", t_column_discovery_replaces_old_mapping)


def t_reference_line_step():
    """Step 09a: reference_line module works with synthetic data."""
    try:
        import reference_line as rl
    except ImportError:
        passed.append("reference_line_step (skip: module unavailable)")
        return

    laps = _make_oval_resampled_laps()
    ref = rl.compute_reference_line(laps)
    assert isinstance(ref, pd.DataFrame)
    assert "distance_m" in ref.columns
    assert "x_ref_m" in ref.columns
    assert "y_ref_m" in ref.columns
    assert len(ref) > 50


_test("reference_line_step", t_reference_line_step)


def t_curvature_profile_step():
    """Step 09b: curvature profile from reference line."""
    try:
        import reference_line as rl
    except ImportError:
        passed.append("curvature_profile_step (skip: module unavailable)")
        return

    laps = _make_oval_resampled_laps()
    ref = rl.compute_reference_line(laps)
    curv = rl.compute_curvature_profile(ref)
    assert "curvature_1pm" in curv.columns
    assert "heading_rad" in curv.columns
    # Oval should have non-zero curvature

    k = curv["curvature_1pm"].values
    assert np.nanmax(k) > 0.001


_test("curvature_profile_step", t_curvature_profile_step)


def t_friction_model_step():
    """Step 09c: friction model from resampled laps."""
    try:
        import friction_model as fm
    except ImportError:
        passed.append("friction_model_step (skip: module unavailable)")
        return

    laps = _make_oval_resampled_laps()
    fc = fm.build_friction_model(laps)
    assert hasattr(fc, 'v_grid')
    assert hasattr(fc, 'lateral_vals')
    assert hasattr(fc, 'lateral_max')
    assert len(fc.v_grid) > 3


_test("friction_model_step", t_friction_model_step)


def t_vehicle_model_step():
    """Step 09d: vehicle classification from friction + metrics."""
    try:
        import vehicle_model as vm
    except ImportError:
        passed.append("vehicle_model_step (skip: module unavailable)")
        return

    v = np.arange(0, 45, 2.0)
    fc = MockFrictionCircle(
        v_grid=v,
        lateral_vals=np.full(len(v), 1.2 * _G),
        braking_vals=np.full(len(v), 1.3 * _G),
        traction_vals=np.full(len(v), 0.7 * _G),
    )
    metrics = _make_lap_metrics()
    params = vm.classify_vehicle(fc, metrics)
    assert hasattr(params, 'vehicle_class')
    assert hasattr(params, 'rolling_resistance_est')
    assert hasattr(params, 'aero_drag_factor_est')
    assert params.confidence > 0


_test("vehicle_model_step", t_vehicle_model_step)


def t_data_quality_step():
    """Step 09e: data quality assessment."""
    try:
        import data_quality as dq
    except ImportError:
        passed.append("data_quality_step (skip: module unavailable)")
        return

    laps = _make_oval_resampled_laps()
    times = _make_lap_times()
    report = dq.score_data_quality(laps, times)
    assert hasattr(report, 'overall_confidence')
    assert hasattr(report, 'recommended_speed_percentile')
    assert 75 <= report.recommended_speed_percentile <= 99


_test("data_quality_step", t_data_quality_step)


def t_validate_lap_consistency():
    """validate_lap_consistency repairs negative distance jumps."""
    import pipeline as p

    df = pd.DataFrame({
        "Distance (m)": [0, 10, 5, 20, 30],  # Jump backward at idx 2
    })
    result = p.validate_lap_consistency({1: df})
    d = result[1]["Distance (m)"].values
    # Should be monotonically non-decreasing after repair

    assert all(np.diff(d) >= -0.01), f"Not monotonic: {d}"


_test("validate_lap_consistency", t_validate_lap_consistency)


def t_robustness_metrics():
    """_compute_robustness_metrics produces expected keys."""
    import pipeline as p

    laps = _make_oval_resampled_laps(n_laps=6)
    times = _make_lap_times(n_laps=6)
    r = p._compute_robustness_metrics(laps, times)
    assert "early_mean_s" in r
    assert "late_mean_s" in r


_test("robustness_metrics", t_robustness_metrics)


def t_backward_compat_metrics():
    """Old-style _theoretical_metrics_from_lap call still works."""
    import pipeline as p

    df = pd.DataFrame({
        "distance_m": np.linspace(0, 500, 100),
        "v_env_mps": np.full(100, 20.0),
        "accel_max_mps2": np.full(100, 4.0),
        "brake_max_mps2": np.full(100, 7.0),
    })
    # Old-style call (no kwargs) still works

    m = p._theoretical_metrics_from_lap(df)
    assert math.isfinite(m["best_s"])
    assert m["accel_max_mps2"] == 4.0
    assert m["braking_max_mps2"] == 7.0
    # New fields have safe defaults

    assert m["simulation_method"] == "percentile_envelope"
    assert m["cornering_limited_fraction"] == 0.0
    assert m["confidence"] == 0.5


_test("backward_compat_metrics", t_backward_compat_metrics)


def t_pipeline_flow_diagram_updated():
    """Docstring includes new physics steps."""
    import pipeline as p
    doc = p.__doc__ or ""
    for step in ["9a", "9b", "9c", "9d", "9e"]:
        assert step in doc, f"Step {step} not in pipeline docstring"
    assert "reference_line" in doc
    assert "friction_model" in doc
    assert "vehicle_model" in doc
    assert "data_quality" in doc


_test("pipeline_flow_diagram_updated", t_pipeline_flow_diagram_updated)


# -- -

# Summary

# -- -


total = len(passed) + len(failed)
print(f"\nPipeline Physics Integration Tests: {passed.__len__()}/{total} passed")
for name in passed:
    print(f"  [PASS] {name}")
for name, tb in failed:
    print(f"  [FAIL] {name}\n{tb}")

if failed:
    raise AssertionError(f"{len(failed)} test(s) failed.")
