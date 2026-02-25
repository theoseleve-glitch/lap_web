"""Test setup tracker."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from setup_tracker import correlate_setup_vs_pace


class TestSetupTracker:
    def test_linear_correlation(self):
        setups = [
            {"front_pressure": 10, "best_lap_time_s": 60},
            {"front_pressure": 11, "best_lap_time_s": 59},
            {"front_pressure": 12, "best_lap_time_s": 58},
            {"front_pressure": 13, "best_lap_time_s": 57},
        ]
        result = correlate_setup_vs_pace(setups)
        assert "front_pressure" in result["correlations"]
        assert abs(result["correlations"]["front_pressure"]["r"]) > 0.9

    def test_empty_input(self):
        result = correlate_setup_vs_pace([])
        assert result["n_sessions"] == 0

    def test_few_sessions(self):
        result = correlate_setup_vs_pace([{"front_pressure": 10, "best_lap_time_s": 60}])
        assert result["n_sessions"] == 1
