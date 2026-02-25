"""Test fuel calculator."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fuel_calculator import model_fuel_effect, predict_pit_strategy


class TestFuelCalculator:
    def test_fuel_effect(self):
        sessions = [
            {"fuel_load_kg": 5, "best_lap_time_s": 60},
            {"fuel_load_kg": 10, "best_lap_time_s": 61},
            {"fuel_load_kg": 15, "best_lap_time_s": 62},
        ]
        result = model_fuel_effect(sessions)
        assert result["seconds_per_kg"] > 0

    def test_empty_sessions(self):
        result = model_fuel_effect([])
        assert result["seconds_per_kg"] == 0

    def test_pit_strategy(self):
        result = predict_pit_strategy(
            total_laps=20,
            fuel_effect_s_per_kg=0.1,
            tank_capacity_kg=10,
            consumption_per_lap_kg=0.5,
        )
        assert "strategies" in result
        assert len(result["strategies"]) > 0
