"""Tests for blackout window enforcement in the stint optimizer."""

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from race_strategy_v2 import optimize_stints


def _base_config(**overrides):
    cfg = {
        "race_duration_s": 10800,  # 3 hours
        "desired_stints": 3,
        "min_pit_stop_s": 60,
    }
    cfg.update(overrides)
    return cfg


def _two_drivers():
    return [
        {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 70},
        {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 80},
    ]


class TestBlackoutStartMin:
    """First stint must be >= blackout_start_min * 60 when set."""

    def test_first_stint_extended_to_blackout_start(self):
        config = _base_config(blackout_start_min=70)  # 70 min = 4200s
        result = optimize_stints(config, _two_drivers())

        first = result["stints"][0]
        assert first["planned_duration_s"] >= 4200, (
            f"First stint {first['planned_duration_s']}s < blackout_start 4200s"
        )

    def test_first_stint_already_long_enough(self):
        # 2 stints in a 3h race => ~5310s each (minus pit), well above 30min
        config = _base_config(desired_stints=2, blackout_start_min=30)
        result = optimize_stints(config, _two_drivers())

        first = result["stints"][0]
        assert first["planned_duration_s"] >= 1800


class TestBlackoutEndMin:
    """No pit stop after race_duration - blackout_end_min * 60 when set."""

    def test_last_pit_before_cutoff(self):
        config = _base_config(blackout_end_min=60)  # last 60 min = no pits
        result = optimize_stints(config, _two_drivers())

        cutoff = 10800 - 60 * 60  # 7200s
        # Check all pit stops are before the cutoff
        for ps in result["pit_stops"]:
            assert ps["at_s"] <= cutoff, (
                f"Pit at {ps['at_s']}s > cutoff {cutoff}s"
            )

    def test_last_stint_absorbs_overshoot(self):
        # Force 4 stints in 3h with 90min blackout at end => cutoff at 5400s
        config = _base_config(desired_stints=4, blackout_end_min=90)
        result = optimize_stints(config, _two_drivers())

        cutoff = 10800 - 90 * 60  # 5400s
        if len(result["pit_stops"]) > 0:
            last_pit = result["pit_stops"][-1]
            assert last_pit["at_s"] <= cutoff, (
                f"Last pit at {last_pit['at_s']}s > cutoff {cutoff}s"
            )


class TestBlackoutNotSet:
    """When blackout fields are None/0, optimizer behaves normally."""

    def test_no_blackout_fields(self):
        config = _base_config()
        result = optimize_stints(config, _two_drivers())
        assert result["feasible"]
        assert len(result["stints"]) == 3

    def test_blackout_zero(self):
        config = _base_config(blackout_start_min=0, blackout_end_min=0)
        result = optimize_stints(config, _two_drivers())
        assert result["feasible"]
        assert len(result["stints"]) == 3

    def test_blackout_none(self):
        config = _base_config(blackout_start_min=None, blackout_end_min=None)
        result = optimize_stints(config, _two_drivers())
        assert result["feasible"]
        assert len(result["stints"]) == 3
