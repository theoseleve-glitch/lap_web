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
