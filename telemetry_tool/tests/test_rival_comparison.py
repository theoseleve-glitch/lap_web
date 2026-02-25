"""Test rival comparison module."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rival_comparison import compare_rivals


class TestRivalComparison:
    def test_two_drivers(self):
        data = [
            {"driver_id": 1, "driver_name": "A", "best_lap_time_s": 60},
            {"driver_id": 2, "driver_name": "B", "best_lap_time_s": 59},
        ]
        result = compare_rivals(data)
        assert len(result["rankings"]) == 2

    def test_single_driver(self):
        data = [{"driver_id": 1, "driver_name": "A", "best_lap_time_s": 60}]
        result = compare_rivals(data)
        assert len(result["rankings"]) == 1

    def test_empty(self):
        result = compare_rivals([])
        assert result["rankings"] == []
