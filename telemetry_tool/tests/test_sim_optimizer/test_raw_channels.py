"""Tests for sim_optimizer.ingest.raw_channels."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.sim_optimizer.ingest.raw_channels import (
    CHANNEL_GROUPS,
    RawChannelSet,
    extract_raw_channels,
)


# ── Tests ────────────────────────────────────────────────────────────────


def test_extracts_speed(synthetic_raw_df, sim_config):
    result = extract_raw_channels(synthetic_raw_df, config=sim_config)
    assert result.speed_mps is not None
    assert len(result.speed_mps) == len(synthetic_raw_df)
    assert np.all(result.speed_mps >= 0)


def test_extracts_per_wheel_temps(synthetic_raw_df, sim_config):
    result = extract_raw_channels(synthetic_raw_df, config=sim_config)
    assert result.tyre_temp_lf_cl is not None
    assert result.tyre_temp_rr_cr is not None
    assert len(result.tyre_temp_lf_cl) == len(synthetic_raw_df)


def test_extracts_shock_deflection(synthetic_raw_df, sim_config):
    result = extract_raw_channels(synthetic_raw_df, config=sim_config)
    assert result.shock_defl_lf is not None
    assert result.shock_defl_rr is not None


def test_extracts_body_velocities(synthetic_raw_df, sim_config):
    result = extract_raw_channels(synthetic_raw_df, config=sim_config)
    assert result.velocity_x is not None
    assert result.velocity_y is not None


def test_extracts_brake_line_press(synthetic_raw_df, sim_config):
    result = extract_raw_channels(synthetic_raw_df, config=sim_config)
    assert result.brake_line_press_lf is not None


def test_missing_column_returns_none(sim_config):
    """A minimal df with only Speed should leave shock_defl_lf as None."""
    df = pd.DataFrame({"irsdk__Speed": [30.0, 31.0, 32.0]})
    result = extract_raw_channels(df, config=sim_config)
    assert result.speed_mps is not None
    assert result.shock_defl_lf is None


def test_channel_groups_complete():
    expected = {
        "tyre", "aero", "powertrain", "brake", "suspension",
        "mass", "environment", "validation", "geometry", "inputs",
    }
    assert set(CHANNEL_GROUPS.keys()) == expected


def test_validates_speed_range(synthetic_raw_df, sim_config):
    """Inject negative speed values and verify they are clipped to >= 0."""
    df = synthetic_raw_df.copy()
    df["irsdk__Speed"] = -10.0  # all negative
    result = extract_raw_channels(df, config=sim_config)
    assert result.speed_mps is not None
    assert np.all(result.speed_mps >= 0)
