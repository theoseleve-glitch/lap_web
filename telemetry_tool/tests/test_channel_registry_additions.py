"""New canonical channels added for Plan 2/3 loaders."""
from __future__ import annotations

from telemetry_tool.channel_registry import (
    CHANNELS,
    TIER_STANDARD,
    TIER_PROFESSIONAL,
    detect_data_tier,
)

_NEW = {
    "accel_vert_mps2": (TIER_STANDARD, "m/s2"),
    "pitch_rate_dps": (TIER_STANDARD, "deg/s"),
    "roll_rate_dps": (TIER_STANDARD, "deg/s"),
    "exhaust_temp": (TIER_PROFESSIONAL, "C"),
    "head_temp": (TIER_PROFESSIONAL, "C"),
    "heart_rate_bpm": (TIER_PROFESSIONAL, "bpm"),
}


def test_new_channels_registered():
    for name, (tier, unit) in _NEW.items():
        assert name in CHANNELS, f"{name} missing from registry"
        assert CHANNELS[name].tier == tier
        assert CHANNELS[name].unit == unit


def test_new_channels_do_not_change_tier_gating():
    cols = ["time_s", "speed_mps", "accel_long_mps2", "accel_lat_mps2"]
    assert detect_data_tier(cols) == TIER_STANDARD
    assert detect_data_tier(cols + ["accel_vert_mps2", "pitch_rate_dps"]) == TIER_STANDARD
    t4 = cols + ["throttle_pct", "brake_pct", "tire_temp_fl"]
    assert detect_data_tier(t4 + ["heart_rate_bpm", "exhaust_temp", "head_temp"]) == 4
