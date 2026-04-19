"""Test distance_m and lap_number derivation for GPS-only formats."""
import numpy as np
import pandas as pd
import pytest


def _derive_distance(df: pd.DataFrame) -> pd.DataFrame:
    """Import the derivation function we'll add to s01_ingest."""
    from telemetry_tool.pipeline.stages.s01_ingest import derive_missing_columns
    return derive_missing_columns(df)


def test_distance_derived_from_speed_and_time():
    df = pd.DataFrame({
        "Time (s)": [0.0, 1.0, 2.0, 3.0],
        "Speed (m/s)": [0.0, 10.0, 10.0, 10.0],
    })
    result = _derive_distance(df)
    assert "Distance (m)" in result.columns
    # cumulative_trapezoid: [5.0, 15.0, 25.0] with initial=0
    np.testing.assert_allclose(result["Distance (m)"].values, [0.0, 5.0, 15.0, 25.0])


def test_distance_not_overwritten_if_present():
    df = pd.DataFrame({
        "Time (s)": [0.0, 1.0],
        "Speed (m/s)": [10.0, 20.0],
        "Distance (m)": [0.0, 999.0],
    })
    result = _derive_distance(df)
    assert result["Distance (m)"].iloc[1] == 999.0  # untouched


def test_lap_number_sentinel_if_missing():
    df = pd.DataFrame({
        "Time (s)": [0.0, 1.0],
        "Speed (m/s)": [10.0, 20.0],
    })
    result = _derive_distance(df)
    assert "Lap #" in result.columns
    assert (result["Lap #"] == 0).all()


def test_lap_number_not_overwritten_if_present():
    df = pd.DataFrame({
        "Time (s)": [0.0, 1.0],
        "Speed (m/s)": [10.0, 20.0],
        "Lap #": [1, 2],
    })
    result = _derive_distance(df)
    assert result["Lap #"].iloc[1] == 2


def test_distance_handles_nan_in_time_and_speed():
    df = pd.DataFrame({
        "Time (s)": [0.0, 1.0, np.nan, 3.0],
        "Speed (m/s)": [10.0, np.nan, 10.0, 10.0],
    })
    result = _derive_distance(df)
    assert "Distance (m)" in result.columns
    # NaN speed filled to 0, NaN time forward-filled to 1.0
    # Result should have no NaN values
    assert not result["Distance (m)"].isna().any()
