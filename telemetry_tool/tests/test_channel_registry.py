"""Tests for the universal channel registry module."""

from __future__ import annotations

import pytest

from channel_registry import (
    CHANNELS,
    TIER_ADVANCED,
    TIER_CONTROLS,
    TIER_ESSENTIAL,
    TIER_PROFESSIONAL,
    TIER_STANDARD,
    ChannelDef,
    detect_data_tier,
    get_channels_by_category,
    get_channels_by_tier,
    validate_channel_value,
)

# ---------------------------------------------------------------------------
# Valid categories for all channels
# ---------------------------------------------------------------------------
VALID_CATEGORIES = frozenset(
    {
        "time",
        "position",
        "motion",
        "controls",
        "tires",
        "brakes",
        "engine",
        "aero",
        "fuel",
        "environment",
        "driver",
    }
)


# ---------------------------------------------------------------------------
# ChannelDef dataclass basics
# ---------------------------------------------------------------------------
class TestChannelDef:
    """Tests for the ChannelDef frozen dataclass."""

    def test_field_access(self):
        ch = ChannelDef(
            name="speed_mps",
            unit="m/s",
            tier=TIER_ESSENTIAL,
            category="motion",
            valid_range=(0.0, 120.0),
            description="Vehicle speed",
        )
        assert ch.name == "speed_mps"
        assert ch.unit == "m/s"
        assert ch.tier == TIER_ESSENTIAL
        assert ch.category == "motion"
        assert ch.valid_range == (0.0, 120.0)
        assert ch.description == "Vehicle speed"

    def test_default_description(self):
        ch = ChannelDef(
            name="test",
            unit="x",
            tier=1,
            category="time",
            valid_range=(0.0, 1.0),
        )
        assert ch.description == ""

    def test_frozen(self):
        ch = ChannelDef(
            name="test",
            unit="x",
            tier=1,
            category="time",
            valid_range=(0.0, 1.0),
        )
        with pytest.raises(AttributeError):
            ch.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tier constants
# ---------------------------------------------------------------------------
class TestTierConstants:
    def test_tier_values(self):
        assert TIER_ESSENTIAL == 1
        assert TIER_STANDARD == 2
        assert TIER_CONTROLS == 3
        assert TIER_ADVANCED == 4
        assert TIER_PROFESSIONAL == 5


# ---------------------------------------------------------------------------
# CHANNELS dict integrity
# ---------------------------------------------------------------------------
class TestChannelsDict:
    """Validate every entry in the CHANNELS registry."""

    def test_channels_is_dict(self):
        assert isinstance(CHANNELS, dict)

    def test_minimum_channel_count(self):
        assert len(CHANNELS) >= 70

    def test_all_values_are_channeldef(self):
        for name, ch in CHANNELS.items():
            assert isinstance(ch, ChannelDef), f"{name} is not a ChannelDef"

    def test_key_matches_name(self):
        for key, ch in CHANNELS.items():
            assert key == ch.name, f"key {key!r} != ch.name {ch.name!r}"

    def test_all_categories_valid(self):
        for name, ch in CHANNELS.items():
            assert ch.category in VALID_CATEGORIES, (
                f"{name} has invalid category {ch.category!r}"
            )

    def test_valid_range_is_tuple_of_two_floats(self):
        for name, ch in CHANNELS.items():
            assert isinstance(ch.valid_range, tuple), f"{name} valid_range not tuple"
            assert len(ch.valid_range) == 2, f"{name} valid_range length != 2"
            lo, hi = ch.valid_range
            assert isinstance(lo, (int, float)), f"{name} lo is not numeric"
            assert isinstance(hi, (int, float)), f"{name} hi is not numeric"
            assert lo <= hi, f"{name} lo ({lo}) > hi ({hi})"

    def test_tier_in_valid_range(self):
        for name, ch in CHANNELS.items():
            assert ch.tier in (1, 2, 3, 4, 5), f"{name} has invalid tier {ch.tier}"

    def test_unit_is_nonempty_string(self):
        for name, ch in CHANNELS.items():
            assert isinstance(ch.unit, str) and len(ch.unit) > 0, (
                f"{name} has empty or non-string unit"
            )


# ---------------------------------------------------------------------------
# Tier population
# ---------------------------------------------------------------------------
class TestTierPopulation:
    """Verify minimum channel counts per tier."""

    def test_tier1_minimum(self):
        tier1 = [ch for ch in CHANNELS.values() if ch.tier == TIER_ESSENTIAL]
        assert len(tier1) >= 7

    def test_tier2_minimum(self):
        tier2 = [ch for ch in CHANNELS.values() if ch.tier == TIER_STANDARD]
        assert len(tier2) >= 3

    def test_tier3_minimum(self):
        tier3 = [ch for ch in CHANNELS.values() if ch.tier == TIER_CONTROLS]
        assert len(tier3) >= 4

    def test_tier4_minimum(self):
        tier4 = [ch for ch in CHANNELS.values() if ch.tier == TIER_ADVANCED]
        assert len(tier4) >= 20

    def test_tier5_minimum(self):
        tier5 = [ch for ch in CHANNELS.values() if ch.tier == TIER_PROFESSIONAL]
        assert len(tier5) >= 15

    def test_essential_channels_present(self):
        essential_names = {
            "time_s",
            "speed_mps",
            "lat_deg",
            "lon_deg",
            "distance_m",
            "lap_number",
            "altitude_m",
        }
        for name in essential_names:
            assert name in CHANNELS, f"essential channel {name!r} missing"
            assert CHANNELS[name].tier == TIER_ESSENTIAL


# ---------------------------------------------------------------------------
# get_channels_by_tier
# ---------------------------------------------------------------------------
class TestGetChannelsByTier:
    def test_returns_list(self):
        result = get_channels_by_tier(TIER_ESSENTIAL)
        assert isinstance(result, list)

    def test_all_correct_tier(self):
        for tier in (1, 2, 3, 4, 5):
            for ch in get_channels_by_tier(tier):
                assert ch.tier == tier

    def test_empty_for_invalid_tier(self):
        assert get_channels_by_tier(99) == []


# ---------------------------------------------------------------------------
# get_channels_by_category
# ---------------------------------------------------------------------------
class TestGetChannelsByCategory:
    def test_returns_list(self):
        result = get_channels_by_category("motion")
        assert isinstance(result, list)

    def test_all_correct_category(self):
        for cat in VALID_CATEGORIES:
            for ch in get_channels_by_category(cat):
                assert ch.category == cat

    def test_motion_includes_speed(self):
        names = {ch.name for ch in get_channels_by_category("motion")}
        assert "speed_mps" in names

    def test_controls_includes_throttle(self):
        names = {ch.name for ch in get_channels_by_category("controls")}
        assert "throttle_pct" in names

    def test_tires_has_entries(self):
        tires = get_channels_by_category("tires")
        assert len(tires) >= 8

    def test_empty_for_unknown_category(self):
        assert get_channels_by_category("nonexistent") == []


# ---------------------------------------------------------------------------
# validate_channel_value
# ---------------------------------------------------------------------------
class TestValidateChannelValue:
    def test_in_range_returns_true(self):
        assert validate_channel_value("speed_mps", 30.0) is True

    def test_at_lower_bound(self):
        lo = CHANNELS["speed_mps"].valid_range[0]
        assert validate_channel_value("speed_mps", lo) is True

    def test_at_upper_bound(self):
        hi = CHANNELS["speed_mps"].valid_range[1]
        assert validate_channel_value("speed_mps", hi) is True

    def test_below_range_returns_false(self):
        lo = CHANNELS["speed_mps"].valid_range[0]
        assert validate_channel_value("speed_mps", lo - 1.0) is False

    def test_above_range_returns_false(self):
        hi = CHANNELS["speed_mps"].valid_range[1]
        assert validate_channel_value("speed_mps", hi + 1.0) is False

    def test_unknown_channel_raises(self):
        with pytest.raises(KeyError):
            validate_channel_value("nonexistent_channel", 0.0)

    def test_throttle_valid(self):
        assert validate_channel_value("throttle_pct", 50.0) is True

    def test_throttle_above_100(self):
        assert validate_channel_value("throttle_pct", 105.0) is False


# ---------------------------------------------------------------------------
# detect_data_tier
# ---------------------------------------------------------------------------
class TestDetectDataTier:
    def test_tier0_when_missing_essentials(self):
        assert detect_data_tier(["heading_deg", "altitude_m"]) == 0

    def test_tier1_with_time_and_speed(self):
        cols = ["time_s", "speed_mps", "lat_deg"]
        assert detect_data_tier(cols) == 1

    def test_tier2_with_accel(self):
        cols = ["time_s", "speed_mps", "accel_long_mps2", "accel_lat_mps2"]
        assert detect_data_tier(cols) == 2

    def test_tier3_with_controls(self):
        cols = [
            "time_s",
            "speed_mps",
            "accel_long_mps2",
            "accel_lat_mps2",
            "throttle_pct",
            "brake_pct",
        ]
        assert detect_data_tier(cols) == 3

    def test_tier4_with_tire_data(self):
        cols = [
            "time_s",
            "speed_mps",
            "accel_long_mps2",
            "accel_lat_mps2",
            "throttle_pct",
            "brake_pct",
            "tire_temp_fl",
        ]
        assert detect_data_tier(cols) == 4

    def test_tier4_with_wheel_speed(self):
        cols = [
            "time_s",
            "speed_mps",
            "accel_long_mps2",
            "accel_lat_mps2",
            "rpm",
            "steering_angle_deg",
            "wheel_speed_fl",
        ]
        assert detect_data_tier(cols) == 4

    def test_tier4_with_brake_temp(self):
        cols = [
            "time_s",
            "speed_mps",
            "accel_long_mps2",
            "accel_lat_mps2",
            "throttle_pct",
            "rpm",
            "brake_temp_rl",
        ]
        assert detect_data_tier(cols) == 4

    def test_tier5_with_slip_angle(self):
        cols = [
            "time_s",
            "speed_mps",
            "accel_long_mps2",
            "accel_lat_mps2",
            "throttle_pct",
            "brake_pct",
            "tire_temp_fl",
            "slip_angle_fl",
        ]
        assert detect_data_tier(cols) == 5

    def test_tier5_with_damper(self):
        cols = [
            "time_s",
            "speed_mps",
            "accel_long_mps2",
            "accel_lat_mps2",
            "throttle_pct",
            "brake_pct",
            "wheel_speed_fr",
            "damper_pos_fl",
        ]
        assert detect_data_tier(cols) == 5

    def test_tier5_with_fuel(self):
        cols = [
            "time_s",
            "speed_mps",
            "accel_long_mps2",
            "accel_lat_mps2",
            "throttle_pct",
            "brake_pct",
            "brake_temp_fl",
            "fuel_kg",
        ]
        assert detect_data_tier(cols) == 5

    def test_tier5_with_slip_ratio(self):
        cols = [
            "time_s",
            "speed_mps",
            "accel_long_mps2",
            "accel_lat_mps2",
            "throttle_pct",
            "brake_pct",
            "tire_temp_rr",
            "slip_ratio_rr",
        ]
        assert detect_data_tier(cols) == 5

    def test_does_not_skip_tiers(self):
        """Tier 5 columns without tier 3/4 prerequisites => lower tier."""
        cols = [
            "time_s",
            "speed_mps",
            "accel_long_mps2",
            "accel_lat_mps2",
            "slip_angle_fl",
        ]
        # Missing controls (tier 3) => caps at tier 2
        assert detect_data_tier(cols) == 2

    def test_empty_list(self):
        assert detect_data_tier([]) == 0
