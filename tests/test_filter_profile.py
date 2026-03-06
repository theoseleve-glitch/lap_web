"""
test_filter_profile.py
----------------------
Tests for configurable filter profiles (Task 4).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.filter_profile import (
    FilterProfile,
    list_profiles,
    resolve_filter_profile,
)

_CONFIG_DIR = _PROJECT_ROOT / "config" / "filter_profiles"


@pytest.mark.domain
class TestFilterProfileLoading:
    def test_default_profile_loads(self):
        p = resolve_filter_profile(config_dir=_CONFIG_DIR)
        assert p.profile_name == "default"
        assert p.gps_min_satellites == 5
        assert p.gps_max_speed_mps == 80.0

    def test_named_profile_loads(self):
        p = resolve_filter_profile("kart_indoor", config_dir=_CONFIG_DIR)
        assert p.profile_name == "kart_indoor"
        assert p.gps_max_speed_mps == 30.0

    def test_inheritance_merges(self):
        p = resolve_filter_profile("kart_indoor", config_dir=_CONFIG_DIR)
        # Inherited from default
        assert p.gps_min_satellites == 5
        # Overridden by kart_indoor
        assert p.gps_max_speed_mps == 30.0
        assert p.gps_max_accel_mps2 == 25.0
        assert p.laps_min_lap_distance_m == 200.0

    def test_gt_car_profile(self):
        p = resolve_filter_profile("gt_car", config_dir=_CONFIG_DIR)
        assert p.gps_max_speed_mps == 90.0
        assert p.gps_max_accel_mps2 == 60.0

    def test_missing_profile_falls_back_to_defaults(self):
        p = resolve_filter_profile("nonexistent_profile_xyz", config_dir=_CONFIG_DIR)
        assert p.profile_name == "default"

    def test_list_profiles(self):
        profiles = list_profiles(config_dir=_CONFIG_DIR)
        names = [p["name"] for p in profiles]
        assert "default" in names
        assert "kart_indoor" in names

    def test_to_dict_roundtrip(self):
        p = resolve_filter_profile("default", config_dir=_CONFIG_DIR)
        d = p.to_dict()
        assert d["profile_name"] == "default"
        assert d["gps_max_speed_mps"] == 80.0
        assert isinstance(d["version"], int)

    def test_profile_is_frozen(self):
        p = resolve_filter_profile("default", config_dir=_CONFIG_DIR)
        with pytest.raises(AttributeError):
            p.gps_max_speed_mps = 999.0  # type: ignore[misc]
