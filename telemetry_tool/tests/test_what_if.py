"""Test what-if simulator."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from what_if_simulator import simulate_what_if


class TestWhatIf:
    def test_zero_adjustment(self):
        profile = {
            "distances": [0, 50, 100],
            "speeds": [20, 15, 20],
            "corners": [],
        }
        result = simulate_what_if(profile, [])
        assert abs(result["delta_s"]) < 0.001

    def test_speed_increase(self):
        profile = {
            "distances": list(range(0, 201)),
            "speeds": [20.0] * 50 + [15.0] * 101 + [20.0] * 50,
            "corners": [{"corner_id": 1, "d_start": 50, "d_end": 150}],
        }
        result = simulate_what_if(profile, [{"corner_id": 1, "speed_pct_change": 10.0}])
        assert result["predicted_time_s"] < result["baseline_time_s"]

    def test_empty_profile(self):
        result = simulate_what_if({"distances": [], "speeds": []}, [])
        assert result["baseline_time_s"] == 0
