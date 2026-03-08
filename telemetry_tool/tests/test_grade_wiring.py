"""Tests for grade wiring and altitude quality gating."""
import numpy as np
import pandas as pd
import pytest


def test_grade_unavailable_flat_altitude():
    """Altitude with < 0.5m range -> grade_status='grade_unavailable'."""
    from derived_channels import compute_elevation_profile_with_quality

    n = 200
    df = pd.DataFrame({
        "Altitude (m)": np.full(n, 100.0) + np.random.default_rng(42).uniform(-0.1, 0.1, n),
        "Distance (m)": np.linspace(0, 500, n),
        "Time (s)": np.linspace(0, 30, n),
        "Speed (m/s)": np.full(n, 20.0),
    })
    grade, status = compute_elevation_profile_with_quality(df)
    assert status == "grade_unavailable"
    # Grade should be zeros
    assert np.allclose(grade.values, 0.0, atol=0.1)


def test_grade_low_confidence_noisy():
    """Very noisy altitude -> grade_status='grade_low_confidence'."""
    from derived_channels import compute_elevation_profile_with_quality

    n = 200
    rng = np.random.default_rng(42)
    # Real elevation change + huge noise
    alt = np.linspace(100, 110, n) + rng.normal(0, 10, n)
    df = pd.DataFrame({
        "Altitude (m)": alt,
        "Distance (m)": np.linspace(0, 500, n),
        "Time (s)": np.linspace(0, 30, n),
        "Speed (m/s)": np.full(n, 20.0),
    })
    grade, status = compute_elevation_profile_with_quality(df)
    assert status == "grade_low_confidence"


def test_grade_used_clean_altitude():
    """Clean altitude with real elevation -> grade_status='grade_used'."""
    from derived_channels import compute_elevation_profile_with_quality

    n = 200
    # 5% grade = 25m rise over 500m
    alt = np.linspace(100, 125, n) + np.random.default_rng(42).normal(0, 0.5, n)
    df = pd.DataFrame({
        "Altitude (m)": alt,
        "Distance (m)": np.linspace(0, 500, n),
        "Time (s)": np.linspace(0, 30, n),
        "Speed (m/s)": np.full(n, 20.0),
    })
    grade, status = compute_elevation_profile_with_quality(df)
    assert status == "grade_used"
    # Mean grade should be around 5%
    assert 3.0 < grade.mean() < 7.0


def test_grade_unavailable_no_altitude_col():
    """No altitude column at all -> grade_status='grade_unavailable'."""
    from derived_channels import compute_elevation_profile_with_quality

    df = pd.DataFrame({
        "Distance (m)": np.linspace(0, 500, 200),
        "Speed (m/s)": np.full(200, 20.0),
    })
    grade, status = compute_elevation_profile_with_quality(df)
    assert status == "grade_unavailable"


def test_slope_correction_uphill():
    """Synthetic 5% uphill: corrected accel removes gravity bias."""
    from derived_channels import compute_longitudinal_accel

    n = 200
    grade_pct = 5.0  # 5% uphill
    grade_rad = np.arctan(grade_pct / 100.0)
    gravity_bias = 9.80665 * np.sin(grade_rad)  # ~0.49 m/s^2

    df = pd.DataFrame({
        "Longitudinal acceleration (G) *calc": np.full(n, gravity_bias / 9.80665),  # biased reading
        "Speed (m/s)": np.full(n, 20.0),
        "Time (s)": np.linspace(0, 10, n),
        "Distance (m)": np.linspace(0, 200, n),
        "Altitude (m)": np.linspace(0, 10, n),  # 10m rise over 200m = 5%
    })

    result = compute_longitudinal_accel(df, correct_for_slope=True)
    accel = result["accel_long_mps2"].values
    # After correction, accel should be near zero (bias removed)
    assert np.nanmean(np.abs(accel)) < 0.3, (
        f"Slope correction should remove gravity bias, got mean |accel|={np.nanmean(np.abs(accel)):.3f}"
    )


def test_slope_correction_downhill():
    """Synthetic -5% downhill: corrected accel removes negative bias."""
    from derived_channels import compute_longitudinal_accel

    n = 200
    grade_pct = -5.0
    grade_rad = np.arctan(grade_pct / 100.0)
    gravity_bias = 9.80665 * np.sin(grade_rad)  # ~-0.49 m/s^2

    df = pd.DataFrame({
        "Longitudinal acceleration (G) *calc": np.full(n, gravity_bias / 9.80665),
        "Speed (m/s)": np.full(n, 20.0),
        "Time (s)": np.linspace(0, 10, n),
        "Distance (m)": np.linspace(0, 200, n),
        "Altitude (m)": np.linspace(10, 0, n),  # 10m drop
    })

    result = compute_longitudinal_accel(df, correct_for_slope=True)
    accel = result["accel_long_mps2"].values
    assert np.nanmean(np.abs(accel)) < 0.3


def test_data_quality_has_fusion_confidence():
    """DataQualityReport includes fusion_confidence field."""
    from data_quality import DataQualityReport

    report = DataQualityReport(
        n_laps=5,
        gps_quality=0.9,
        accel_quality=0.8,
        yaw_quality=0.7,
        sample_rate_hz=25.0,
        lap_time_consistency=0.95,
        overall_confidence=0.85,
        recommended_speed_percentile=90.0,
        recommended_accel_percentile=91.0,
        fusion_confidence=0.75,
    )
    assert report.fusion_confidence == 0.75
    d = report.to_dict()
    assert "fusion_confidence" in d
    assert d["fusion_confidence"] == 0.75
