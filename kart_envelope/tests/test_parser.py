"""Tests for CSV parsing and column normalisation."""
from __future__ import annotations

import pandas as pd
import pytest

from kart_envelope.ingest.columns import (
    COL_ACCEL_LAT,
    COL_ACCEL_LONG,
    COL_BRAKE_PCT,
    COL_DIST,
    COL_LAP,
    COL_SPEED,
    COL_STEERING_ANGLE_DEG,
    COL_THROTTLE_PCT,
    COL_TIME,
    normalize_columns,
)


def _make_raw_df(**extra_cols) -> pd.DataFrame:
    """Build a minimal RaceChrono-style DataFrame."""
    data = {
        "Time (s)": [0.0, 0.1, 0.2],
        "Speed (m/s)": [10.0, 11.0, 12.0],
        "Distance (m)": [0.0, 1.0, 2.3],
        "Lap #": [1, 1, 1],
    }
    data.update(extra_cols)
    return pd.DataFrame(data)


class TestNormalizeColumns:
    def test_basic_rename(self):
        df = normalize_columns(_make_raw_df())
        assert COL_TIME in df.columns
        assert COL_SPEED in df.columns
        assert COL_DIST in df.columns
        assert COL_LAP in df.columns

    def test_calc_preference(self):
        """*calc variant should win over non-*calc."""
        raw = _make_raw_df(**{
            "Speed (m/s) *calc": [10.5, 11.5, 12.5],
        })
        df = normalize_columns(raw)
        assert df[COL_SPEED].iloc[0] == pytest.approx(10.5)

    def test_g_conversion(self):
        """G-unit accel columns should be converted to m/s²."""
        raw = _make_raw_df(**{
            "Lateral acceleration (G) *calc": [1.0, 0.5, -0.5],
        })
        df = normalize_columns(raw)
        assert COL_ACCEL_LAT in df.columns
        # 1.0 G ≈ 9.80665 m/s²
        assert df[COL_ACCEL_LAT].iloc[0] == pytest.approx(9.80665, rel=1e-4)

    def test_duplicate_columns(self):
        """Duplicate columns (pandas .1 suffix) should be de-duplicated."""
        raw = pd.DataFrame({
            "Time (s)": [0.0, 0.1],
            "Speed (m/s)": [10.0, 11.0],
            "Speed (m/s).1": [9.0, 10.0],  # duplicate
            "Distance (m)": [0.0, 1.0],
            "Lap #": [1, 1],
        })
        df = normalize_columns(raw)
        # Should keep the first "Speed (m/s)" (10, 11), not the .1 copy
        assert df[COL_SPEED].iloc[0] == pytest.approx(10.0)

    def test_missing_required_warns(self):
        """Missing required columns should log a warning but not crash."""
        raw = pd.DataFrame({"Time (s)": [0.0], "Lap #": [1]})
        df = normalize_columns(raw)
        # speed_mps and distance_m missing
        assert COL_SPEED not in df.columns

    def test_control_channel_aliases(self):
        raw = _make_raw_df(**{
            "Steering angle (deg)": [1.0, 2.0, 3.0],
            "Throttle position (%)": [10.0, 20.0, 30.0],
            "Brake pressure (%)": [0.0, 25.0, 10.0],
        })
        df = normalize_columns(raw)
        assert COL_STEERING_ANGLE_DEG in df.columns
        assert COL_THROTTLE_PCT in df.columns
        assert COL_BRAKE_PCT in df.columns
