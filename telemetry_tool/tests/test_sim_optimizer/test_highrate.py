"""Tests for high-rate (360 Hz) sub-sample unpacking."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.sim_optimizer.ingest.highrate import unpack_highrate


class TestUnpackHighrate:
    """Tests for unpack_highrate()."""

    def test_output_length_6x(self, synthetic_raw_df, sim_config):
        """Result n_samples_hr == len(df) * 6."""
        result = unpack_highrate(synthetic_raw_df, config=sim_config)
        assert result.n_samples_hr == len(synthetic_raw_df) * 6

    def test_lat_accel_present(self, synthetic_raw_df, sim_config):
        """lat_accel_hr not None, length == n_samples_hr."""
        result = unpack_highrate(synthetic_raw_df, config=sim_config)
        assert result.lat_accel_hr is not None
        assert len(result.lat_accel_hr) == result.n_samples_hr

    def test_shock_defl_present(self, synthetic_raw_df, sim_config):
        """shock_defl_lf_hr not None."""
        result = unpack_highrate(synthetic_raw_df, config=sim_config)
        assert result.shock_defl_lf_hr is not None
        assert len(result.shock_defl_lf_hr) == result.n_samples_hr

    def test_time_axis_monotonic(self, synthetic_raw_df, sim_config):
        """time_hr is strictly increasing."""
        result = unpack_highrate(synthetic_raw_df, config=sim_config)
        assert result.time_hr is not None
        assert np.all(np.diff(result.time_hr) > 0)

    def test_missing_st_columns_returns_none(self, sim_config):
        """DataFrame with no _ST columns -> lat_accel_hr is None, n_samples_hr == 0."""
        df = pd.DataFrame({
            "irsdk__Speed": np.linspace(10, 30, 100),
            "irsdk__SessionTime": np.linspace(0, 10, 100),
        })
        result = unpack_highrate(df, config=sim_config)
        assert result.lat_accel_hr is None
        assert result.n_samples_hr == 0
