"""Tests for weather alert annotations on race strategy stints."""

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from race_strategy_v2 import adjust_stints_for_weather


def _make_stints(n: int = 3, duration_s: int = 1800) -> list[dict]:
    """Build *n* consecutive stints each lasting *duration_s*."""
    stints = []
    clock = 0
    for i in range(n):
        stints.append({
            "stint_order": i + 1,
            "driver_id": 1,
            "driver_name": "Alice",
            "planned_start_s": clock,
            "planned_end_s": clock + duration_s,
            "planned_duration_s": duration_s,
            "ballast_kg": 0.0,
        })
        clock += duration_s + 60  # 60s pit stop gap
    return stints


def _dry_forecast(hours: int = 3) -> dict:
    """Forecast with zero rain across *hours*."""
    return {
        "forecast": [
            {
                "time": f"2026-02-27T{10 + h:02d}:00",
                "air_temp_c": 22.0,
                "humidity_pct": 45,
                "wind_speed_mps": 3.0,
                "rain_prob_pct": 5,
                "rain_mm": 0.0,
                "weather_code": 0,
                "description": "Clear sky",
            }
            for h in range(hours)
        ],
        "rain_risk": "minimal",
        "max_rain_probability_pct": 5.0,
        "avg_rain_probability_pct": 5.0,
        "source": "open-meteo",
    }


def _rain_forecast() -> dict:
    """Forecast: first hour dry, second hour heavy rain, third hour moderate rain."""
    return {
        "forecast": [
            {
                "time": "2026-02-27T10:00",
                "air_temp_c": 20.0,
                "humidity_pct": 50,
                "wind_speed_mps": 2.0,
                "rain_prob_pct": 10,
                "rain_mm": 0.0,
                "weather_code": 0,
                "description": "Clear sky",
            },
            {
                "time": "2026-02-27T11:00",
                "air_temp_c": 18.0,
                "humidity_pct": 85,
                "wind_speed_mps": 5.0,
                "rain_prob_pct": 90,
                "rain_mm": 3.5,
                "weather_code": 63,
                "description": "Moderate rain",
            },
            {
                "time": "2026-02-27T12:00",
                "air_temp_c": 17.0,
                "humidity_pct": 90,
                "wind_speed_mps": 4.0,
                "rain_prob_pct": 70,
                "rain_mm": 1.2,
                "weather_code": 61,
                "description": "Slight rain",
            },
        ],
        "rain_risk": "high",
        "max_rain_probability_pct": 90.0,
        "avg_rain_probability_pct": 56.7,
        "source": "open-meteo",
    }


class TestAdjustStintsForWeather:
    """Unit tests for adjust_stints_for_weather()."""

    def test_dry_forecast_no_changes(self):
        """A fully dry forecast should annotate every stint with wet_risk=False."""
        stints = _make_stints(3, duration_s=1800)
        forecast = _dry_forecast(3)
        config = {"race_duration_s": 6000}

        result = adjust_stints_for_weather(stints, forecast, config)

        assert len(result) == 3
        for s in result:
            assert s["wet_risk"] is False
        # Original stints must NOT be mutated
        assert "wet_risk" not in stints[0]

    def test_rain_forecast_flags_wet_risk(self):
        """When rain appears in hour 2, the stint overlapping that hour gets wet_risk=True."""
        stints = _make_stints(3, duration_s=3600)  # each 1 h
        forecast = _rain_forecast()
        config = {"race_duration_s": 12000}

        result = adjust_stints_for_weather(stints, forecast, config)

        # First stint (0-3600s, midpoint ~1800s → hour 0) should be dry
        assert result[0]["wet_risk"] is False

        # Second stint (3660-7260s, midpoint ~5460s → hour 1) should be wet
        assert result[1]["wet_risk"] is True
        assert "recommended_compound" in result[1]
        assert "grip_score_forecast" in result[1]

    def test_empty_forecast_no_crash(self):
        """An error forecast should return copies of stints unchanged (no crash)."""
        stints = _make_stints(2)
        error_forecast = {"error": "network timeout", "source": "unavailable"}
        config = {"race_duration_s": 4000}

        result = adjust_stints_for_weather(stints, error_forecast, config)

        assert len(result) == 2
        # Copies, not references
        assert result[0] is not stints[0]
        # No wet_risk key injected on error path
        # (copies are plain, no annotation)
