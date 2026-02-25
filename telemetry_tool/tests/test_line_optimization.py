"""Test line optimization."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from line_optimization import identify_line_deviations, score_risk_reward


class TestLineOptimization:
    def test_on_optimal(self):
        line = {"latitudes": [45.0, 45.001], "longitudes": [7.0, 7.001]}
        result = identify_line_deviations(line, line)
        assert result["mean_deviation_m"] < 1.0

    def test_offline(self):
        actual = {"latitudes": [45.0, 45.001], "longitudes": [7.0, 7.001]}
        ref = {"latitudes": [45.001, 45.002], "longitudes": [7.0, 7.001]}
        result = identify_line_deviations(actual, ref)
        assert result["mean_deviation_m"] > 0

    def test_empty(self):
        result = identify_line_deviations(
            {"latitudes": [], "longitudes": []},
            {"latitudes": [], "longitudes": []},
        )
        assert result["mean_deviation_m"] == 0

    def test_risk_reward(self):
        deviations = [1.0, 2.0, 3.0]
        gains = [10.0, -5.0, 15.0]
        result = score_risk_reward(deviations, gains)
        assert "classification" in result
