"""Tests for segment_filter masks."""
from __future__ import annotations

import numpy as np

from telemetry_tool.sim_optimizer.ingest.raw_channels import extract_raw_channels
from telemetry_tool.sim_optimizer.ingest.segment_filter import compute_segment_mask


def test_all_clean_on_good_data(synthetic_raw_df, sim_config):
    """Synthetic oval data should be >80% clean."""
    channels = extract_raw_channels(synthetic_raw_df, config=sim_config)
    mask = compute_segment_mask(channels, config=sim_config)

    clean_pct = mask.clean.sum() / mask.n_samples
    assert clean_pct > 0.80, f"Expected >80% clean, got {clean_pct:.1%}"


def test_pit_flagged(synthetic_raw_df, sim_config):
    """First 20 samples with OnPitRoad=True should be flagged."""
    df = synthetic_raw_df.copy()
    df.iloc[:20, df.columns.get_loc("irsdk__OnPitRoad")] = 1.0

    channels = extract_raw_channels(df, config=sim_config)
    mask = compute_segment_mask(channels, config=sim_config)

    assert mask.pit[:20].all(), "First 20 samples should be pit=True"


def test_slow_flagged(synthetic_raw_df, sim_config):
    """First 10 samples with Speed=1.0 should be flagged slow."""
    df = synthetic_raw_df.copy()
    df.iloc[:10, df.columns.get_loc("irsdk__Speed")] = 1.0

    channels = extract_raw_channels(df, config=sim_config)
    mask = compute_segment_mask(channels, config=sim_config)

    assert mask.slow[:10].all(), "First 10 samples should be slow=True"


def test_draft_flagged(synthetic_raw_df, sim_config):
    """Samples 100-110 with CarDistAhead=10.0 should be flagged draft."""
    df = synthetic_raw_df.copy()
    df.iloc[100:111, df.columns.get_loc("irsdk__CarDistAhead")] = 10.0

    channels = extract_raw_channels(df, config=sim_config)
    mask = compute_segment_mask(channels, config=sim_config)

    assert mask.draft[100:111].all(), "Samples 100-110 should be draft=True"


def test_clean_excludes_all_flags(synthetic_raw_df, sim_config):
    """Pit samples should not be clean."""
    df = synthetic_raw_df.copy()
    df.iloc[:20, df.columns.get_loc("irsdk__OnPitRoad")] = 1.0

    channels = extract_raw_channels(df, config=sim_config)
    mask = compute_segment_mask(channels, config=sim_config)

    assert not mask.clean[:20].any(), "Pit samples must not be clean"
