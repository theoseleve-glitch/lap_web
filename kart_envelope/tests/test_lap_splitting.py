"""Tests for lap splitting and selection."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from kart_envelope.config import default_config
from kart_envelope.processing.lap_splitting import (
    LapSplittingError,
    compute_lap_times,
    split_and_select_laps,
)


def _make_session(n_laps: int = 5, points_per_lap: int = 200) -> pd.DataFrame:
    """Build a synthetic session DataFrame."""
    rows = []
    for lap in range(n_laps):
        t_start = lap * 30.0
        for i in range(points_per_lap):
            rows.append({
                "time_s": t_start + i * 0.1,
                "speed_mps": 10.0 + np.random.normal(0, 0.5),
                "distance_m": lap * 500.0 + i * 2.5,
                "lap_number": float(lap),
            })
    return pd.DataFrame(rows)


class TestSplitAndSelect:
    def test_basic_split(self):
        df = _make_session(n_laps=4)
        cfg = default_config()
        laps = split_and_select_laps(df, cfg)
        # Lap 0 should be dropped (outlap)
        assert 0 not in laps
        assert len(laps) >= 1

    def test_no_valid_laps_raises(self):
        df = pd.DataFrame({
            "time_s": [0.0],
            "speed_mps": [5.0],
            "distance_m": [0.0],
            "lap_number": [0.0],
        })
        with pytest.raises(LapSplittingError):
            split_and_select_laps(df, default_config())

    def test_outlap_removal(self):
        """Laps much slower than median should be removed."""
        df = _make_session(n_laps=5)
        # Make lap 4 very slow by spreading its time span to 3x normal
        mask = df["lap_number"] == 4.0
        lap4_idx = df.index[mask]
        t_start = df.loc[lap4_idx[0], "time_s"]
        # Normal lap is ~20s (200 points * 0.1s); stretch to 60s
        df.loc[mask, "time_s"] = t_start + np.arange(mask.sum()) * 0.3
        cfg = default_config()
        laps = split_and_select_laps(df, cfg)
        assert 4 not in laps


class TestComputeLapTimes:
    def test_lap_times(self):
        laps = {
            1: pd.DataFrame({"time_s": [0.0, 10.0, 20.0, 30.0]}),
            2: pd.DataFrame({"time_s": [30.0, 40.0, 50.0, 62.0]}),
        }
        times = compute_lap_times(laps)
        assert times[1] == pytest.approx(30.0)
        assert times[2] == pytest.approx(32.0)
