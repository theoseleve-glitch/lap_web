"""Tests for lap extraction and distance-based resampling."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.sim_optimizer.ingest.lap_align import align_lap


def _make_session() -> pd.DataFrame:
    """Two-lap synthetic session."""
    rng = np.random.default_rng(42)
    # Lap 1: 100 rows, distance 0-500
    dist1 = np.sort(rng.uniform(0, 500, 100))
    speed1 = 30.0 + 5.0 * np.sin(dist1 / 50.0)
    # Lap 2: 50 rows, distance 0-500
    dist2 = np.sort(rng.uniform(0, 500, 50))
    speed2 = 28.0 + 4.0 * np.sin(dist2 / 50.0)

    df = pd.DataFrame(
        {
            "irsdk__LapDist": np.concatenate([dist1, dist2]),
            "irsdk__Lap": np.concatenate(
                [np.ones(100, dtype=int), np.full(50, 2, dtype=int)]
            ),
            "speed_mps": np.concatenate([speed1, speed2]),
        }
    )
    return df


class TestAlignBasic:
    def test_align_basic(self) -> None:
        df = _make_session()
        result = align_lap(df, 1, ds_m=1.0)
        assert result is not None
        assert len(result) > 400  # ~500 rows at 1m spacing over 0-500m
        assert "irsdk__LapDist" in result.columns
        assert "speed_mps" in result.columns

    def test_uniform_spacing(self) -> None:
        df = _make_session()
        result = align_lap(df, 1, ds_m=1.0)
        assert result is not None
        diffs = np.diff(result["irsdk__LapDist"].values)
        np.testing.assert_allclose(diffs, 1.0, atol=1e-9)

    def test_returns_none_for_missing_lap(self) -> None:
        df = _make_session()
        result = align_lap(df, 99)
        assert result is None

    def test_interpolates_speed(self) -> None:
        df = _make_session()
        result = align_lap(df, 1, ds_m=1.0)
        assert result is not None
        # Pick a known distance from original lap 1 data
        lap1 = df.loc[df["irsdk__Lap"] == 1].sort_values("irsdk__LapDist")
        orig_dist = lap1["irsdk__LapDist"].values[50]
        orig_speed = lap1["speed_mps"].values[50]
        # Find closest grid point
        idx = np.argmin(np.abs(result["irsdk__LapDist"].values - orig_dist))
        interp_speed = result["speed_mps"].values[idx]
        # Should be close (within 1 m/s given 1m grid spacing)
        assert abs(interp_speed - orig_speed) < 1.0
