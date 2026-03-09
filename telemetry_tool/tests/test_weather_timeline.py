"""Tests for weather_timeline module — per-lap weather interpolation."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from weather_timeline import build_weather_timeline, parse_session_datetime

# ---------------------------------------------------------------------------
# Helper: build a minimal hourly_weather dict
# ---------------------------------------------------------------------------

def _make_hourly_weather(hours_data, date="2026-02-15", source="open-meteo-archive"):
    """Build an hourly_weather dict matching fetch_historical_weather output."""
    return {
        "date": date,
        "hours": hours_data,
        "source": source,
    }


def _hour(time_str, air_temp_c=20.0, humidity_pct=60.0, wind_speed_mps=3.0,
          wind_dir_deg=180.0, rain_mm=0.0, cloud_cover_pct=20.0, weather_code=1):
    """Build a single hourly weather entry."""
    return {
        "time": time_str,
        "air_temp_c": air_temp_c,
        "humidity_pct": humidity_pct,
        "wind_speed_mps": wind_speed_mps,
        "wind_dir_deg": wind_dir_deg,
        "rain_mm": rain_mm,
        "cloud_cover_pct": cloud_cover_pct,
        "weather_code": weather_code,
    }


REQUIRED_COLUMNS = [
    "lap_number", "timestamp", "air_temp_c", "humidity_pct",
    "wind_speed_mps", "wind_dir_deg", "rain_mm", "cloud_cover_pct",
    "weather_code", "grip_score", "track_state", "track_temp_est_c",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWeatherTimeline:

    def test_interpolation_between_hours(self):
        """Lap at exact midpoint between two hours gets midpoint values."""
        hourly = _make_hourly_weather([
            _hour("2026-02-15T14:00", air_temp_c=20.0, humidity_pct=40.0,
                  wind_speed_mps=2.0, wind_dir_deg=100.0, rain_mm=0.0,
                  cloud_cover_pct=10.0),
            _hour("2026-02-15T15:00", air_temp_c=24.0, humidity_pct=60.0,
                  wind_speed_mps=6.0, wind_dir_deg=200.0, rain_mm=2.0,
                  cloud_cover_pct=50.0),
        ])
        session_start = datetime(2026, 2, 15, 14, 0, 0)
        # Lap at 30 min = 1800s → midpoint between hour 0 and hour 1
        lap_timestamps = [1800.0]

        df = build_weather_timeline(hourly, lap_timestamps, session_start)

        assert len(df) == 1
        row = df.iloc[0]
        assert abs(row["air_temp_c"] - 22.0) < 0.01  # midpoint 20↔24
        assert abs(row["humidity_pct"] - 50.0) < 0.01  # midpoint 40↔60
        assert abs(row["wind_speed_mps"] - 4.0) < 0.01  # midpoint 2↔6
        assert abs(row["wind_dir_deg"] - 150.0) < 0.01  # midpoint 100↔200
        assert abs(row["rain_mm"] - 1.0) < 0.01  # midpoint 0↔2
        assert abs(row["cloud_cover_pct"] - 30.0) < 0.01  # midpoint 10↔50

    def test_nearest_weather_code(self):
        """WMO weather_code uses nearest-hour, not linear interpolation."""
        hourly = _make_hourly_weather([
            _hour("2026-02-15T14:00", weather_code=1),  # Mainly clear
            _hour("2026-02-15T15:00", weather_code=63),  # Moderate rain
        ])
        session_start = datetime(2026, 2, 15, 14, 0, 0)

        # Lap at 10 min → closer to 14:00 (code 1)
        df_early = build_weather_timeline(hourly, [600.0], session_start)
        assert df_early.iloc[0]["weather_code"] == 1

        # Lap at 50 min → closer to 15:00 (code 63)
        df_late = build_weather_timeline(hourly, [3000.0], session_start)
        assert df_late.iloc[0]["weather_code"] == 63

    def test_grip_score_computed(self):
        """Each lap has grip_score and track_state from estimate_track_conditions."""
        hourly = _make_hourly_weather([
            _hour("2026-02-15T14:00", air_temp_c=25.0, rain_mm=0.0),
            _hour("2026-02-15T15:00", air_temp_c=25.0, rain_mm=0.0),
        ])
        session_start = datetime(2026, 2, 15, 14, 0, 0)
        lap_timestamps = [300.0, 600.0, 900.0]

        df = build_weather_timeline(hourly, lap_timestamps, session_start)

        assert len(df) == 3
        for _, row in df.iterrows():
            assert isinstance(row["grip_score"], (int, float))
            assert row["grip_score"] > 0
            assert row["track_state"] in ("dry", "damp", "greasy", "wet")
            assert isinstance(row["track_temp_est_c"], (int, float))

    def test_empty_lap_timestamps(self):
        """Empty laps → empty DataFrame with correct columns."""
        hourly = _make_hourly_weather([
            _hour("2026-02-15T14:00"),
        ])
        session_start = datetime(2026, 2, 15, 14, 0, 0)

        df = build_weather_timeline(hourly, [], session_start)

        assert len(df) == 0
        for col in REQUIRED_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_single_hour_session(self):
        """When only one hour of data, all laps get those same values."""
        hourly = _make_hourly_weather([
            _hour("2026-02-15T14:00", air_temp_c=22.0, humidity_pct=55.0,
                  wind_speed_mps=4.0, wind_dir_deg=270.0, rain_mm=0.5,
                  cloud_cover_pct=40.0, weather_code=51),
        ])
        session_start = datetime(2026, 2, 15, 14, 0, 0)
        lap_timestamps = [120.0, 240.0, 360.0]

        df = build_weather_timeline(hourly, lap_timestamps, session_start)

        assert len(df) == 3
        for _, row in df.iterrows():
            assert abs(row["air_temp_c"] - 22.0) < 0.01
            assert abs(row["humidity_pct"] - 55.0) < 0.01
            assert abs(row["wind_speed_mps"] - 4.0) < 0.01
            assert abs(row["wind_dir_deg"] - 270.0) < 0.01
            assert abs(row["rain_mm"] - 0.5) < 0.01
            assert abs(row["cloud_cover_pct"] - 40.0) < 0.01
            assert row["weather_code"] == 51

    def test_missing_weather_fields_graceful(self):
        """Missing optional fields in hourly data don't crash the function."""
        hourly = _make_hourly_weather([
            {
                "time": "2026-02-15T14:00",
                "air_temp_c": 20.0,
                # All other fields missing
            },
            {
                "time": "2026-02-15T15:00",
                "air_temp_c": 24.0,
                # All other fields missing
            },
        ])
        session_start = datetime(2026, 2, 15, 14, 0, 0)
        lap_timestamps = [1800.0]

        df = build_weather_timeline(hourly, lap_timestamps, session_start)

        assert len(df) == 1
        # air_temp_c should still be interpolated
        assert abs(df.iloc[0]["air_temp_c"] - 22.0) < 0.01
        # All required columns must still exist
        for col in REQUIRED_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_has_expected_columns(self):
        """Output DataFrame has all required columns."""
        hourly = _make_hourly_weather([
            _hour("2026-02-15T14:00"),
            _hour("2026-02-15T15:00"),
        ])
        session_start = datetime(2026, 2, 15, 14, 0, 0)
        lap_timestamps = [300.0, 1800.0, 3300.0]

        df = build_weather_timeline(hourly, lap_timestamps, session_start)

        for col in REQUIRED_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"
        # lap_number should be 1-indexed
        assert list(df["lap_number"]) == [1, 2, 3]


# ---------------------------------------------------------------------------
# Tests for parse_session_datetime
# ---------------------------------------------------------------------------

class TestParseSessionDatetime:

    def test_racechrono_date_header(self, tmp_path):
        """CSV with RaceChrono '# Date:' and '# Time:' headers."""
        csv_file = tmp_path / "session.csv"
        csv_file.write_text(
            "# RaceChrono Pro v1.2\n"
            "# Date: 2026-02-15\n"
            "# Time: 14:05:30\n"
            "# Track: Spa-Francorchamps\n"
            "Lap #,Speed (m/s),Lat,Lon\n"
            "1,25.4,50.437,5.971\n"
        )
        result = parse_session_datetime(csv_file)
        assert result == datetime(2026, 2, 15, 14, 5, 30)

    def test_date_only_no_time(self, tmp_path):
        """CSV with '# Date:' but no '# Time:' header -> midnight."""
        csv_file = tmp_path / "session.csv"
        csv_file.write_text(
            "# RaceChrono Pro v1.2\n"
            "# Date: 2026-03-10\n"
            "Lap #,Speed (m/s),Lat,Lon\n"
            "1,30.0,50.437,5.971\n"
        )
        result = parse_session_datetime(csv_file)
        assert result == datetime(2026, 3, 10, 0, 0, 0)

    def test_no_metadata_returns_none(self, tmp_path):
        """CSV with no date headers at all -> None."""
        csv_file = tmp_path / "session.csv"
        csv_file.write_text(
            "Lap #,Speed (m/s),Lat,Lon\n"
            "1,25.4,50.437,5.971\n"
            "2,26.1,50.438,5.972\n"
        )
        result = parse_session_datetime(csv_file)
        assert result is None

    def test_racebox_timestamp_header(self, tmp_path):
        """CSV with ISO-8601 '# Session:' timestamp."""
        csv_file = tmp_path / "session.csv"
        csv_file.write_text(
            "# RaceBox Mini S\n"
            "# Session: 2026-02-20T09:30:00Z\n"
            "# Driver: Test Driver\n"
            "Lap #,Speed (m/s),Lat,Lon\n"
            "1,28.0,45.621,9.285\n"
        )
        result = parse_session_datetime(csv_file)
        assert result == datetime(2026, 2, 20, 9, 30, 0)
