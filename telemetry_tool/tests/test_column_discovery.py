"""
Tests for column_discovery module — Core Column Discovery Engine.

Covers:
- Header parsing (regex: name, unit, flag extraction)
- Channel classification (34 priority-ordered rules + custom fallback)
- Unit conversion (factor-based and function-based)
- Full discovery pipeline (conflict resolution, *calc preference, n_valid)
- Apply discovery (rename + conversions)
- Format detection (racechrono, racebox, unknown)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on path (no package install — path manipulation)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from column_discovery import (
    HEADER_RE,
    DiscoveredChannel,
    DiscoveryResult,
    apply_discovery,
    classify_channel,
    detect_format,
    discover_columns,
    get_conversion,
    parse_header,
)


# =====================================================================
# TestParseHeader
# =====================================================================
class TestParseHeader:
    """Tests for parse_header() regex extraction."""

    def test_speed_with_unit_and_calc(self):
        name, unit, flag = parse_header("Speed (m/s) *calc")
        assert name == "Speed"
        assert unit == "m/s"
        assert flag == "calc"

    def test_lap_number_no_unit(self):
        name, unit, flag = parse_header("Lap #")
        assert name == "Lap #"
        assert unit is None
        assert flag is None

    def test_tire_temp_with_unit(self):
        name, unit, flag = parse_header("Tire temp FL (°C)")
        assert name == "Tire temp FL"
        assert unit == "°C"
        assert flag is None

    def test_simple_name(self):
        name, unit, flag = parse_header("Time")
        assert name == "Time"
        assert unit is None
        assert flag is None

    def test_with_whitespace_padding(self):
        name, unit, flag = parse_header("  Speed (m/s)  *calc  ")
        assert name == "Speed"
        assert unit == "m/s"
        assert flag == "calc"

    def test_unit_only_no_flag(self):
        name, unit, flag = parse_header("Distance (m)")
        assert name == "Distance"
        assert unit == "m"
        assert flag is None

    def test_empty_string(self):
        name, unit, flag = parse_header("")
        assert name == ""
        assert unit is None
        assert flag is None

    def test_flag_only_no_unit(self):
        name, unit, flag = parse_header("Speed *calc")
        assert name == "Speed"
        assert unit is None
        assert flag == "calc"

    def test_complex_unit(self):
        name, unit, flag = parse_header("Lateral acceleration (G) *calc")
        assert name == "Lateral acceleration"
        assert unit == "G"
        assert flag == "calc"


# =====================================================================
# TestClassifyChannel
# =====================================================================
class TestClassifyChannel:
    """Tests for classify_channel() — all 34 rules + custom fallback."""

    # Priority 1: Time (exact match)
    def test_time_exact(self):
        assert classify_channel("Time", None) == ("time", "time_s")

    def test_time_not_substring(self):
        # "Datetime" should NOT match the exact "Time" rule
        cat, _ = classify_channel("Datetime", None)
        assert cat == "custom"

    # Priority 2: Lap
    def test_lap_number(self):
        assert classify_channel("Lap #", None) == ("lap", "lap_number")

    def test_lap_count(self):
        assert classify_channel("Lap count", None) == ("lap", "lap_number")

    # Priority 3: Distance
    def test_distance(self):
        assert classify_channel("Distance", "m") == ("distance", "distance_m")

    def test_total_distance(self):
        assert classify_channel("Total Distance", None) == ("distance", "distance_m")

    # Priority 4: Speed
    def test_speed(self):
        assert classify_channel("Speed", "m/s") == ("speed", "speed_mps")

    def test_ground_speed(self):
        assert classify_channel("Ground Speed", "km/h") == ("speed", "speed_mps")

    # Priority 5-6: Latitude / Longitude
    def test_latitude_full(self):
        assert classify_channel("Latitude", "deg") == ("position", "latitude_deg")

    def test_lat_short(self):
        assert classify_channel("Lat", None) == ("position", "latitude_deg")

    def test_longitude_full(self):
        assert classify_channel("Longitude", "deg") == ("position", "longitude_deg")

    def test_lon_short(self):
        assert classify_channel("Lon", None) == ("position", "longitude_deg")

    # Priority 7-8: X / Y (exact)
    def test_x_position(self):
        assert classify_channel("X", "m") == ("position", "x_m")

    def test_y_position(self):
        assert classify_channel("Y", "m") == ("position", "y_m")

    # Priority 9-12: Acceleration
    def test_longitudinal_accel(self):
        assert classify_channel("Longitudinal acceleration", "G") == (
            "acceleration",
            "accel_long_mps2",
        )

    def test_lateral_accel(self):
        assert classify_channel("Lateral acceleration", "G") == (
            "acceleration",
            "accel_lat_mps2",
        )

    def test_accel_x(self):
        assert classify_channel("Accelerometer X", "G") == (
            "acceleration",
            "accel_long_mps2",
        )

    def test_accel_y(self):
        assert classify_channel("Accelerometer Y", "G") == (
            "acceleration",
            "accel_lat_mps2",
        )

    def test_accel_z(self):
        assert classify_channel("Accelerometer Z", "G") == (
            "acceleration",
            "accel_vert_mps2",
        )

    # Priority 14-19: Gyro
    def test_yaw_rate(self):
        assert classify_channel("Yaw rate", "deg/s") == ("gyro", "yaw_rate_dps")

    def test_pitch_rate(self):
        assert classify_channel("Pitch rate", "deg/s") == ("gyro", "pitch_rate_dps")

    def test_roll_rate(self):
        assert classify_channel("Roll rate", "deg/s") == ("gyro", "roll_rate_dps")

    def test_gyro_x(self):
        assert classify_channel("Gyro X", "rad/s") == ("gyro", "roll_rate_dps")

    def test_gyro_y(self):
        assert classify_channel("Gyro Y", "rad/s") == ("gyro", "pitch_rate_dps")

    def test_gyro_z(self):
        assert classify_channel("Gyro Z", "rad/s") == ("gyro", "yaw_rate_dps")

    # Priority 20: Heading / Bearing
    def test_heading(self):
        assert classify_channel("Heading", "deg") == ("heading", "heading_deg")

    def test_bearing(self):
        assert classify_channel("Bearing", "deg") == ("heading", "heading_deg")

    # Priority 21: Altitude
    def test_altitude(self):
        assert classify_channel("Altitude", "m") == ("altitude", "altitude_m")

    def test_alt_short(self):
        assert classify_channel("Alt", "ft") == ("altitude", "altitude_m")

    # Priority 22-23: GPS quality
    def test_satellites(self):
        assert classify_channel("Satellites used", None) == (
            "gps_quality",
            "satellites",
        )

    def test_accuracy(self):
        assert classify_channel("Accuracy", "m") == ("gps_quality", "accuracy_m")

    def test_hdop(self):
        assert classify_channel("HDOP", None) == ("gps_quality", "accuracy_m")

    # Priority 24-30: Engine
    def test_rpm(self):
        assert classify_channel("Engine RPM", "rpm") == ("engine", "engine_rpm")

    def test_throttle(self):
        assert classify_channel("Throttle position", "%") == ("engine", "throttle_pct")

    def test_tps(self):
        assert classify_channel("TPS", "%") == ("engine", "throttle_pct")

    def test_coolant(self):
        assert classify_channel("Coolant temp", "°C") == ("engine", "coolant_temp_c")

    def test_oil_temp(self):
        assert classify_channel("Oil temp", "°C") == ("engine", "oil_temp_c")

    def test_intake_temp(self):
        assert classify_channel("Intake air temp", "°C") == (
            "engine",
            "intake_temp_c",
        )

    def test_battery(self):
        assert classify_channel("Battery voltage", "V") == ("engine", "battery_v")

    def test_voltage(self):
        assert classify_channel("Voltage", "V") == ("engine", "battery_v")

    def test_boost(self):
        assert classify_channel("Boost pressure", "kPa") == ("engine", "boost_kpa")

    def test_map_exact(self):
        assert classify_channel("MAP", "kPa") == ("engine", "boost_kpa")

    # Priority 31: Brake
    def test_brake(self):
        assert classify_channel("Brake pressure", "bar") == ("pedal", "brake_pct")

    # Priority 32: Steering
    def test_steering(self):
        assert classify_channel("Steering angle", "deg") == (
            "steering",
            "steering_angle_deg",
        )

    # Priority 33: Biometric
    def test_heart_rate(self):
        assert classify_channel("Heart rate", "bpm") == (
            "biometric",
            "heart_rate_bpm",
        )

    def test_hr_short(self):
        assert classify_channel("HR", None) == ("biometric", "heart_rate_bpm")

    def test_bpm(self):
        assert classify_channel("BPM", None) == ("biometric", "heart_rate_bpm")

    # Priority 34: Custom fallback
    def test_custom_no_unit(self):
        cat, internal = classify_channel("Tyre wear FL", None)
        assert cat == "custom"
        assert internal == "Tyre wear FL"

    def test_custom_with_unit(self):
        cat, internal = classify_channel("Tyre wear FL", "mm")
        assert cat == "custom"
        assert internal == "Tyre wear FL_mm"


# =====================================================================
# TestUnitConversion
# =====================================================================
class TestUnitConversion:
    """Tests for get_conversion() — factor and function lookups."""

    def test_g_to_mps2(self):
        factor, func = get_conversion("G")
        assert func is None
        assert factor == pytest.approx(9.80665)

    def test_g_lowercase(self):
        factor, func = get_conversion("g")
        assert factor == pytest.approx(9.80665)

    def test_kmh_to_mps(self):
        factor, _ = get_conversion("km/h")
        assert factor == pytest.approx(1.0 / 3.6)

    def test_mph_to_mps(self):
        factor, _ = get_conversion("mph")
        assert factor == pytest.approx(0.44704)

    def test_knots_to_mps(self):
        factor, _ = get_conversion("knots")
        assert factor == pytest.approx(0.514444)

    def test_kn_to_mps(self):
        factor, _ = get_conversion("kn")
        assert factor == pytest.approx(0.514444)

    def test_ft_to_m(self):
        factor, _ = get_conversion("ft")
        assert factor == pytest.approx(0.3048)

    def test_rad_s_to_deg_s(self):
        factor, _ = get_conversion("rad/s")
        assert factor == pytest.approx(180.0 / math.pi)

    def test_fahrenheit_function(self):
        factor, func = get_conversion("°F")
        assert factor is None
        assert func is not None
        assert func(212.0) == pytest.approx(100.0)
        assert func(32.0) == pytest.approx(0.0)

    def test_psi_to_bar(self):
        factor, _ = get_conversion("psi")
        assert factor == pytest.approx(0.0689476)

    def test_kpa_conversion(self):
        factor, _ = get_conversion("kPa")
        assert factor == pytest.approx(0.01)

    def test_no_conversion_needed(self):
        factor, func = get_conversion("m/s")
        assert factor is None
        assert func is None

    def test_none_unit(self):
        factor, func = get_conversion(None)
        assert factor is None
        assert func is None


# =====================================================================
# TestDiscoverColumns
# =====================================================================
class TestDiscoverColumns:
    """Tests for discover_columns() — full pipeline."""

    def test_basic_headers(self):
        df = pd.DataFrame(
            {
                "Time (s)": [0.0, 0.1, 0.2],
                "Speed (m/s)": [10.0, 11.0, 12.0],
                "Lap #": [1, 1, 1],
            }
        )
        result = discover_columns(df)
        assert result.rename_map["Time (s)"] == "time_s"
        assert result.rename_map["Speed (m/s)"] == "speed_mps"
        assert result.rename_map["Lap #"] == "lap_number"
        assert len(result.channels) == 3
        assert len(result.custom_channels) == 0

    def test_calc_preference(self):
        """*calc column wins over non-calc for same internal name."""
        df = pd.DataFrame(
            {
                "Speed (m/s)": [10.0, 11.0],
                "Speed (m/s) *calc": [10.5, 11.5],
            }
        )
        result = discover_columns(df)
        # calc column should win
        assert "speed_mps" in [ch.internal_name for ch in result.channels]
        winner = [ch for ch in result.channels if ch.internal_name == "speed_mps"][0]
        assert winner.raw_name == "Speed (m/s) *calc"
        assert winner.is_calc is True
        # Loser should be in custom_channels
        assert "Speed (m/s)" in result.custom_channels
        # calc_overrides should record the winning calc column
        assert result.calc_overrides["speed_mps"] == "Speed (m/s) *calc"

    def test_custom_channels(self):
        df = pd.DataFrame(
            {
                "Time (s)": [0.0],
                "Tyre wear FL (mm)": [3.2],
                "Fuel level (L)": [15.0],
            }
        )
        result = discover_columns(df)
        # Time is known; the other two are custom
        assert len(result.custom_channels) == 0  # both are unique custom, not conflicts
        customs = [ch for ch in result.channels if ch.category == "custom"]
        assert len(customs) == 2

    def test_kmh_conversion_detected(self):
        df = pd.DataFrame({"Speed (km/h)": [100.0, 200.0]})
        result = discover_columns(df)
        assert "Speed (km/h)" in result.conversions
        assert result.conversions["Speed (km/h)"] == pytest.approx(1.0 / 3.6)

    def test_n_valid_count(self):
        df = pd.DataFrame(
            {
                "Speed (m/s)": [10.0, np.nan, 12.0, np.nan, 14.0],
            }
        )
        result = discover_columns(df)
        ch = result.channels[0]
        assert ch.n_valid == 3

    def test_to_dict_serializable(self):
        df = pd.DataFrame({"Time (s)": [0.0, 0.1], "Speed (m/s)": [10.0, 11.0]})
        result = discover_columns(df)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "channels" in d
        assert "rename_map" in d

    def test_first_match_wins_among_same_flag(self):
        """When two non-calc columns map to the same internal name,
        the first one wins and the second becomes custom."""
        df = pd.DataFrame(
            {
                "Yaw rate (deg/s)": [1.0, 2.0],
                "Gyro Z (deg/s)": [1.1, 2.1],
            }
        )
        result = discover_columns(df)
        winner = [ch for ch in result.channels if ch.internal_name == "yaw_rate_dps"][0]
        assert winner.raw_name == "Yaw rate (deg/s)"
        assert "Gyro Z (deg/s)" in result.custom_channels


# =====================================================================
# TestApplyDiscovery
# =====================================================================
class TestApplyDiscovery:
    """Tests for apply_discovery() — rename + conversions."""

    def test_rename_and_factor_conversion(self):
        df = pd.DataFrame(
            {
                "Speed (km/h)": [36.0, 72.0, 108.0],
                "Lateral acceleration (G)": [0.5, 1.0, 1.5],
            }
        )
        result = discover_columns(df)
        out = apply_discovery(df, result)

        # Speed should be converted from km/h to m/s
        assert "speed_mps" in out.columns
        assert out["speed_mps"].iloc[0] == pytest.approx(10.0, abs=0.01)
        assert out["speed_mps"].iloc[1] == pytest.approx(20.0, abs=0.01)

        # Accel should be converted from G to m/s^2
        assert "accel_lat_mps2" in out.columns
        assert out["accel_lat_mps2"].iloc[0] == pytest.approx(0.5 * 9.80665, abs=0.01)

    def test_fahrenheit_conversion(self):
        df = pd.DataFrame({"Coolant (°F)": [212.0, 32.0, 77.0]})
        result = discover_columns(df)
        out = apply_discovery(df, result)

        assert "coolant_temp_c" in out.columns
        assert out["coolant_temp_c"].iloc[0] == pytest.approx(100.0, abs=0.01)
        assert out["coolant_temp_c"].iloc[1] == pytest.approx(0.0, abs=0.01)
        assert out["coolant_temp_c"].iloc[2] == pytest.approx(25.0, abs=0.01)

    def test_passthrough_no_conversion(self):
        """Columns already in the right units pass through unchanged."""
        df = pd.DataFrame(
            {
                "Time (s)": [0.0, 0.1, 0.2],
                "Speed (m/s)": [10.0, 11.0, 12.0],
            }
        )
        result = discover_columns(df)
        out = apply_discovery(df, result)

        assert "time_s" in out.columns
        assert "speed_mps" in out.columns
        assert out["speed_mps"].iloc[0] == pytest.approx(10.0)
        assert out["time_s"].iloc[2] == pytest.approx(0.2)

    def test_original_df_not_mutated(self):
        df = pd.DataFrame({"Speed (km/h)": [36.0, 72.0]})
        result = discover_columns(df)
        _ = apply_discovery(df, result)
        # Original should still have km/h column and original values
        assert "Speed (km/h)" in df.columns
        assert df["Speed (km/h)"].iloc[0] == pytest.approx(36.0)


# =====================================================================
# TestFormatDetection
# =====================================================================
class TestFormatDetection:
    """Tests for detect_format()."""

    def test_racechrono(self):
        assert detect_format({"source": "RaceChrono Pro v7.0"}) == "racechrono"

    def test_racebox(self):
        assert detect_format({"app": "RaceBox Mini S"}) == "racebox"

    def test_unknown(self):
        assert detect_format({"source": "Custom logger"}) == "unknown"

    def test_case_insensitive(self):
        assert detect_format({"source": "RACECHRONO"}) == "racechrono"
        assert detect_format({"app": "racebox"}) == "racebox"

    def test_empty_metadata(self):
        assert detect_format({}) == "unknown"


# =====================================================================
# TestPipelineIntegration
# =====================================================================
class TestPipelineIntegration:
    """Verify discovery produces same internal names as the old _RAW_TO_INTERNAL."""

    def test_all_old_mappings_still_work(self):
        """Every column name in the old _RAW_TO_INTERNAL produces the same internal name."""
        old_mapping = {
            "Distance (m)": "distance_m",
            "Speed (m/s)": "speed_mps",
            "Speed (m/s) *calc": "speed_mps",
            "Longitudinal acceleration (G) *calc": "accel_long_mps2",
            "Longitudinal acceleration (m/s\u00b2)": "accel_long_mps2",
            "Lateral acceleration (G) *calc": "accel_lat_mps2",
            "Lateral acceleration (m/s\u00b2)": "accel_lat_mps2",
            "Time (s)": "time_s",
            "Lap #": "lap_number",
        }
        for raw, expected_internal in old_mapping.items():
            df = pd.DataFrame({raw: [1.0]})
            result = discover_columns(df)
            actual = result.rename_map.get(raw, raw)
            assert actual == expected_internal, (
                f"Column {raw!r}: expected {expected_internal!r}, got {actual!r}"
            )

    def test_raw_accel_without_calc_now_maps(self):
        """Raw 'Longitudinal acceleration (G)' (no *calc) now maps correctly."""
        df = pd.DataFrame({"Longitudinal acceleration (G)": [0.5]})
        result = discover_columns(df)
        assert result.rename_map["Longitudinal acceleration (G)"] == "accel_long_mps2"

    def test_racebox_accel_columns(self):
        """RaceBox uses 'Acceleration X/Y/Z' -- should map correctly."""
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "Acceleration X (m/s\u00b2)": [1.0],
            "Acceleration Y (m/s\u00b2)": [2.0],
            "Acceleration Z (m/s\u00b2)": [3.0],
        })
        result = discover_columns(df)
        assert result.rename_map["Acceleration X (m/s\u00b2)"] == "accel_long_mps2"
        assert result.rename_map["Acceleration Y (m/s\u00b2)"] == "accel_lat_mps2"
        assert result.rename_map["Acceleration Z (m/s\u00b2)"] == "accel_vert_mps2"


# =====================================================================
# TestChannelInventoryDB
# =====================================================================
class TestChannelInventoryDB:
    """Channel inventory persisted to sessions.channel_inventory."""

    @pytest.fixture
    def db(self):
        import json as _json
        import sqlite3
        from db.migrate import ensure_schema
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')"
        )
        conn.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, "
            "session_type, session_date) VALUES ('s1', 'test.csv', 1, 'practice', '2026-01-01')"
        )
        conn.commit()
        yield conn
        conn.close()

    def test_column_exists_after_migration(self, db):
        """channel_inventory column should exist on sessions table."""
        row = db.execute(
            "SELECT channel_inventory FROM sessions WHERE session_id='s1'"
        ).fetchone()
        assert row is not None
        assert row["channel_inventory"] is None

    def test_can_store_json(self, db):
        """Can store and retrieve JSON in channel_inventory."""
        import json as _json
        inventory = {"format": "racechrono", "channels": [], "custom": []}
        db.execute(
            "UPDATE sessions SET channel_inventory = ? WHERE session_id = ?",
            (_json.dumps(inventory), "s1"),
        )
        db.commit()
        row = db.execute(
            "SELECT channel_inventory FROM sessions WHERE session_id='s1'"
        ).fetchone()
        loaded = _json.loads(row["channel_inventory"])
        assert loaded["format"] == "racechrono"


# =====================================================================
# TestEdgeCases
# =====================================================================
class TestEdgeCases:
    """Edge cases: empty columns, duplicates, all-NaN, mixed units."""

    def test_all_nan_column(self):
        df = pd.DataFrame({
            "Time (s)": [0.0, 0.1],
            "Speed (m/s)": [float("nan"), float("nan")],
        })
        result = discover_columns(df)
        speed_ch = next(c for c in result.channels if c.internal_name == "speed_mps")
        assert speed_ch.n_valid == 0

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = discover_columns(df)
        assert result.channels == []
        assert result.rename_map == {}

    def test_duplicate_internal_names_first_wins(self):
        """Two non-calc columns mapping to same internal: first wins."""
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "Speed (m/s)": [10.0],
            "Speed (km/h)": [36.0],
        })
        result = discover_columns(df)
        speed_mapped = [k for k, v in result.rename_map.items() if v == "speed_mps"]
        assert len(speed_mapped) == 1
        assert speed_mapped[0] == "Speed (m/s)"

    def test_calc_wins_over_non_calc(self):
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "Lateral acceleration (G)": [0.5],
            "Lateral acceleration (G) *calc": [0.6],
        })
        result = discover_columns(df)
        mapped = [k for k, v in result.rename_map.items() if v == "accel_lat_mps2"]
        assert "Lateral acceleration (G) *calc" in mapped
        assert "Lateral acceleration (G)" in result.custom_channels

    def test_mixed_accel_units(self):
        """G and m/s\u00b2 variants for same axis -- *calc G should win."""
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "Longitudinal acceleration (m/s\u00b2)": [5.0],
            "Longitudinal acceleration (G) *calc": [0.5],
        })
        result = discover_columns(df)
        mapped = [k for k, v in result.rename_map.items() if v == "accel_long_mps2"]
        assert "Longitudinal acceleration (G) *calc" in mapped

    def test_european_decimal_values_ok(self):
        df = pd.DataFrame({
            "Time (s)": [0.0, 0.1],
            "Speed (m/s)": [10.5, 11.3],
        })
        result = discover_columns(df)
        df2 = apply_discovery(df, result)
        assert df2["speed_mps"].iloc[0] == pytest.approx(10.5)


# =====================================================================
# TestEndToEnd
# =====================================================================
class TestEndToEnd:
    """Full pipeline: CSV headers -> discover -> apply -> verify internal names."""

    def test_racechrono_full_header_set(self):
        """Simulates a real RaceChrono CSV with many channels."""
        df = pd.DataFrame({
            "Time (s)": [0.0, 0.1, 0.2],
            "Lap #": [1, 1, 1],
            "Distance (m)": [0.0, 2.0, 4.0],
            "Speed (m/s) *calc": [10.0, 11.0, 12.0],
            "Speed (m/s)": [9.8, 10.8, 11.8],
            "Latitude (deg)": [51.5, 51.5001, 51.5002],
            "Longitude (deg)": [-0.1, -0.1001, -0.1002],
            "Longitudinal acceleration (G) *calc": [0.1, 0.2, 0.3],
            "Longitudinal acceleration (G)": [0.09, 0.19, 0.29],
            "Lateral acceleration (G) *calc": [0.5, 0.6, 0.7],
            "Bearing (deg)": [90.0, 91.0, 92.0],
            "Altitude (m)": [100.0, 100.5, 101.0],
            "Yaw rate (deg/s)": [1.0, 1.5, 2.0],
            "Engine RPM (rpm)": [5000, 5500, 6000],
            "Throttle position (%)": [80.0, 85.0, 90.0],
            "Tire temp FL (\u00b0C)": [45.0, 46.0, 47.0],
        })
        result = discover_columns(df)
        df = apply_discovery(df, result)

        # Core channels renamed
        assert "time_s" in df.columns
        assert "speed_mps" in df.columns
        assert "latitude_deg" in df.columns
        assert "longitude_deg" in df.columns
        assert "accel_long_mps2" in df.columns
        assert "accel_lat_mps2" in df.columns
        assert "heading_deg" in df.columns
        assert "altitude_m" in df.columns
        assert "yaw_rate_dps" in df.columns
        assert "engine_rpm" in df.columns
        assert "throttle_pct" in df.columns
        assert "lap_number" in df.columns
        assert "distance_m" in df.columns

        # *calc won for speed and accel
        assert df["speed_mps"].iloc[0] == pytest.approx(10.0)  # *calc value
        assert df["accel_long_mps2"].iloc[0] == pytest.approx(0.1 * 9.80665)  # G -> m/s\u00b2

        # Custom channels: tire temp is a unique custom (in channels list, not in
        # custom_channels which holds conflict losers)
        custom_names = [ch.raw_name for ch in result.channels if ch.category == "custom"]
        assert "Tire temp FL (\u00b0C)" in custom_names

        # Serialization works
        d = result.to_dict()
        assert len(d["channels"]) > 0
        custom_raw_names = [ch["raw_name"] for ch in d["channels"] if ch["category"] == "custom"]
        assert "Tire temp FL (\u00b0C)" in custom_raw_names

    def test_racebox_style_headers(self):
        """RaceBox uses different names: Acceleration X/Y/Z, Lat/Lon."""
        df = pd.DataFrame({
            "Time": [0.0, 0.1],
            "Lat": [51.5, 51.5001],
            "Lon": [-0.1, -0.1001],
            "Speed (km/h)": [36.0, 72.0],
            "Acceleration X (m/s\u00b2)": [1.0, 2.0],
            "Acceleration Y (m/s\u00b2)": [0.5, 1.0],
            "Acceleration Z (m/s\u00b2)": [9.8, 9.8],
            "Altitude (m)": [100.0, 101.0],
        })
        result = discover_columns(df)
        df = apply_discovery(df, result)

        assert "time_s" in df.columns
        assert "latitude_deg" in df.columns
        assert "longitude_deg" in df.columns
        assert "speed_mps" in df.columns
        assert "accel_long_mps2" in df.columns
        assert "accel_lat_mps2" in df.columns
        assert "accel_vert_mps2" in df.columns

        # km/h -> m/s conversion
        assert df["speed_mps"].iloc[0] == pytest.approx(10.0)
        assert df["speed_mps"].iloc[1] == pytest.approx(20.0)
