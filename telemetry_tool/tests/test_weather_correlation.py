"""Test weather correlation module."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from weather_correlation import compute_weather_pace_correlation, compute_optimal_conditions


class TestWeatherCorrelation:
    def test_known_correlation(self):
        # Need 5+ sessions for correlation computation
        sessions = [
            {"air_temp_c": 15, "track_temp_c": 25, "humidity_pct": 45, "wind_speed_mps": 1, "best_lap_time_s": 59},
            {"air_temp_c": 20, "track_temp_c": 30, "humidity_pct": 50, "wind_speed_mps": 2, "best_lap_time_s": 60},
            {"air_temp_c": 25, "track_temp_c": 35, "humidity_pct": 55, "wind_speed_mps": 3, "best_lap_time_s": 61},
            {"air_temp_c": 30, "track_temp_c": 40, "humidity_pct": 60, "wind_speed_mps": 4, "best_lap_time_s": 62},
            {"air_temp_c": 35, "track_temp_c": 45, "humidity_pct": 65, "wind_speed_mps": 5, "best_lap_time_s": 63},
        ]
        result = compute_weather_pace_correlation(sessions)
        assert "air_temp_c" in result["correlations"]
        assert abs(result["correlations"]["air_temp_c"]["r"]) > 0.8

    def test_empty(self):
        result = compute_weather_pace_correlation([])
        assert result["correlations"] == {}

    def test_optimal_conditions(self):
        sessions = [
            {"air_temp_c": 20, "track_temp_c": 30, "humidity_pct": 50, "wind_speed_mps": 2, "best_lap_time_s": 59},
            {"air_temp_c": 25, "track_temp_c": 35, "humidity_pct": 55, "wind_speed_mps": 3, "best_lap_time_s": 62},
            {"air_temp_c": 22, "track_temp_c": 32, "humidity_pct": 48, "wind_speed_mps": 2, "best_lap_time_s": 60},
            {"air_temp_c": 28, "track_temp_c": 38, "humidity_pct": 58, "wind_speed_mps": 4, "best_lap_time_s": 63},
        ]
        result = compute_optimal_conditions(sessions, top_pct=50)
        assert "air_temp_c" in result
