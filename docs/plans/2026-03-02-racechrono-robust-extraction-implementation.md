# Robust RaceChrono & RaceBox CSV Extraction — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the hard-coded 11-variant column mapping with a dynamic discovery engine that parses, classifies, converts, and persists ALL channels from RaceChrono and RaceBox CSV exports.

**Architecture:** New `column_discovery.py` module with regex header parsing → classification → unit conversion → `*calc` preference. Integrates into `pipeline.py` replacing `_RAW_TO_INTERNAL` + `_map_to_internal_names()`. Persists channel inventory as JSON in sessions table. Two new API endpoints for channel queries.

**Tech Stack:** Python 3, pandas, regex, SQLite (schema v28), Flask API

---

### Task 1: Core Discovery Engine — Header Parsing + Dataclasses

**Files:**
- Create: `telemetry_tool/column_discovery.py`
- Test: `telemetry_tool/tests/test_column_discovery.py`

**Step 1: Write the failing tests for header regex parsing**

```python
# telemetry_tool/tests/test_column_discovery.py
"""Tests for the dynamic column discovery engine."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from column_discovery import parse_header, DiscoveredChannel, DiscoveryResult


class TestParseHeader:
    """Regex parsing of RaceChrono/RaceBox column headers."""

    def test_speed_with_unit_and_calc(self):
        name, unit, flag = parse_header("Speed (m/s) *calc")
        assert name == "Speed"
        assert unit == "m/s"
        assert flag == "calc"

    def test_accel_with_unit_no_flag(self):
        name, unit, flag = parse_header("Lateral acceleration (G)")
        assert name == "Lateral acceleration"
        assert unit == "G"
        assert flag is None

    def test_lap_number_no_unit(self):
        name, unit, flag = parse_header("Lap #")
        assert name == "Lap #"
        assert unit is None
        assert flag is None

    def test_tire_temp_with_degree(self):
        name, unit, flag = parse_header("Tire temp FL (°C)")
        assert name == "Tire temp FL"
        assert unit == "°C"
        assert flag is None

    def test_raw_flag(self):
        name, unit, flag = parse_header("Speed (m/s) *raw")
        assert name == "Speed"
        assert unit == "m/s"
        assert flag == "raw"

    def test_whitespace_handling(self):
        name, unit, flag = parse_header("  Speed (m/s)  *calc  ")
        assert name == "Speed"
        assert unit == "m/s"
        assert flag == "calc"

    def test_empty_string(self):
        name, unit, flag = parse_header("")
        assert name == ""
        assert unit is None
        assert flag is None

    def test_unit_with_slash(self):
        name, unit, flag = parse_header("Longitudinal acceleration (m/s²)")
        assert name == "Longitudinal acceleration"
        assert unit == "m/s²"
        assert flag is None

    def test_gps_accuracy(self):
        name, unit, flag = parse_header("GPS accuracy (m)")
        assert name == "GPS accuracy"
        assert unit == "m"
        assert flag is None
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestParseHeader -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'column_discovery'`

**Step 3: Write the dataclasses and `parse_header()` function**

```python
# telemetry_tool/column_discovery.py
"""
column_discovery.py
-------------------
Dynamic column discovery engine for RaceChrono and RaceBox CSV exports.

Parses all column headers, classifies channels by category, converts units
to canonical internal form, and applies *calc preference when duplicates exist.

Public API
~~~~~~~~~~
- ``parse_header(raw)``         — parse a single header into (name, unit, flag)
- ``discover_columns(df)``      — classify all columns → DiscoveryResult
- ``apply_discovery(df, result)`` — rename + convert columns in-place
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Header regex
# ---------------------------------------------------------------------------

HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<name>.+?)"
    r"(?:\s*\((?P<unit>[^)]+)\))?"
    r"(?:\s*\*(?P<flag>\w+))?"
    r"\s*$"
)


def parse_header(raw: str) -> tuple[str, str | None, str | None]:
    """Parse a column header into (channel_name, unit, flag).

    Examples:
        "Speed (m/s) *calc" → ("Speed", "m/s", "calc")
        "Lap #"             → ("Lap #", None, None)
    """
    m = HEADER_RE.match(raw)
    if not m or not m.group("name"):
        return (raw.strip(), None, None)
    return (m.group("name").strip(), m.group("unit"), m.group("flag"))


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredChannel:
    raw_name: str
    internal_name: str
    category: str
    unit_raw: str | None = None
    unit_internal: str | None = None
    is_calc: bool = False
    conversion_factor: float | None = None
    n_valid: int = 0


@dataclass
class DiscoveryResult:
    format: str = "unknown"
    channels: list[DiscoveredChannel] = field(default_factory=list)
    rename_map: dict[str, str] = field(default_factory=dict)
    conversions: dict[str, float] = field(default_factory=dict)
    calc_overrides: dict[str, str] = field(default_factory=dict)
    custom_channels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for JSON persistence."""
        return {
            "format": self.format,
            "channels": [
                {
                    "raw": ch.raw_name,
                    "internal": ch.internal_name,
                    "category": ch.category,
                    "unit": ch.unit_internal or ch.unit_raw,
                    "is_calc": ch.is_calc,
                    "n_valid": ch.n_valid,
                }
                for ch in self.channels
            ],
            "custom": self.custom_channels,
        }
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestParseHeader -v`
Expected: PASS (all 9 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/column_discovery.py telemetry_tool/tests/test_column_discovery.py
git commit -m "feat: add column_discovery module — header parsing + dataclasses"
```

---

### Task 2: Classification Rules — Channel Categorization

**Files:**
- Modify: `telemetry_tool/column_discovery.py`
- Modify: `telemetry_tool/tests/test_column_discovery.py`

**Step 1: Write the failing tests for channel classification**

Add to `telemetry_tool/tests/test_column_discovery.py`:

```python
from column_discovery import classify_channel


class TestClassifyChannel:
    """Priority-ordered pattern matching on parsed channel names."""

    def test_time(self):
        cat, internal = classify_channel("Time", None)
        assert cat == "time"
        assert internal == "time_s"

    def test_lap_number(self):
        cat, internal = classify_channel("Lap #", None)
        assert cat == "lap"
        assert internal == "lap_number"

    def test_distance(self):
        cat, internal = classify_channel("Distance", "m")
        assert cat == "distance"
        assert internal == "distance_m"

    def test_speed(self):
        cat, internal = classify_channel("Speed", "m/s")
        assert cat == "speed"
        assert internal == "speed_mps"

    def test_latitude(self):
        cat, internal = classify_channel("Latitude", "deg")
        assert cat == "position"
        assert internal == "latitude_deg"

    def test_lat_short(self):
        cat, internal = classify_channel("Lat", "deg")
        assert cat == "position"
        assert internal == "latitude_deg"

    def test_longitude(self):
        cat, internal = classify_channel("Longitude", "deg")
        assert cat == "position"
        assert internal == "longitude_deg"

    def test_lon_short(self):
        cat, internal = classify_channel("Lon", None)
        assert cat == "position"
        assert internal == "longitude_deg"

    def test_x_position(self):
        cat, internal = classify_channel("X", "m")
        assert cat == "position"
        assert internal == "x_m"

    def test_y_position(self):
        cat, internal = classify_channel("Y", "m")
        assert cat == "position"
        assert internal == "y_m"

    def test_longitudinal_acceleration(self):
        cat, internal = classify_channel("Longitudinal acceleration", "G")
        assert cat == "acceleration"
        assert internal == "accel_long_mps2"

    def test_lateral_acceleration(self):
        cat, internal = classify_channel("Lateral acceleration", "G")
        assert cat == "acceleration"
        assert internal == "accel_lat_mps2"

    def test_accel_x(self):
        cat, internal = classify_channel("Acceleration X", "m/s²")
        assert cat == "acceleration"
        assert internal == "accel_long_mps2"

    def test_accel_y(self):
        cat, internal = classify_channel("Acceleration Y", "m/s²")
        assert cat == "acceleration"
        assert internal == "accel_lat_mps2"

    def test_accel_z(self):
        cat, internal = classify_channel("Acceleration Z", "m/s²")
        assert cat == "acceleration"
        assert internal == "accel_vert_mps2"

    def test_yaw_rate(self):
        cat, internal = classify_channel("Yaw rate", "deg/s")
        assert cat == "gyro"
        assert internal == "yaw_rate_dps"

    def test_pitch_rate(self):
        cat, internal = classify_channel("Pitch rate", "deg/s")
        assert cat == "gyro"
        assert internal == "pitch_rate_dps"

    def test_roll_rate(self):
        cat, internal = classify_channel("Roll rate", "deg/s")
        assert cat == "gyro"
        assert internal == "roll_rate_dps"

    def test_gyro_x(self):
        cat, internal = classify_channel("Gyro X", "deg/s")
        assert cat == "gyro"
        assert internal == "roll_rate_dps"

    def test_gyro_y(self):
        cat, internal = classify_channel("Gyro Y", "deg/s")
        assert cat == "gyro"
        assert internal == "pitch_rate_dps"

    def test_gyro_z(self):
        cat, internal = classify_channel("Gyro Z", "deg/s")
        assert cat == "gyro"
        assert internal == "yaw_rate_dps"

    def test_bearing(self):
        cat, internal = classify_channel("Bearing", "deg")
        assert cat == "heading"
        assert internal == "heading_deg"

    def test_heading(self):
        cat, internal = classify_channel("Heading", "deg")
        assert cat == "heading"
        assert internal == "heading_deg"

    def test_altitude(self):
        cat, internal = classify_channel("Altitude", "m")
        assert cat == "altitude"
        assert internal == "altitude_m"

    def test_gps_altitude(self):
        cat, internal = classify_channel("GPS Altitude", "m")
        assert cat == "altitude"
        assert internal == "altitude_m"

    def test_satellites(self):
        cat, internal = classify_channel("Satellites", None)
        assert cat == "gps_quality"
        assert internal == "satellites"

    def test_accuracy(self):
        cat, internal = classify_channel("GPS accuracy", "m")
        assert cat == "gps_quality"
        assert internal == "accuracy_m"

    def test_hdop(self):
        cat, internal = classify_channel("HDOP", None)
        assert cat == "gps_quality"
        assert internal == "accuracy_m"

    def test_rpm(self):
        cat, internal = classify_channel("Engine RPM", "rpm")
        assert cat == "engine"
        assert internal == "engine_rpm"

    def test_throttle(self):
        cat, internal = classify_channel("Throttle position", "%")
        assert cat == "engine"
        assert internal == "throttle_pct"

    def test_tps(self):
        cat, internal = classify_channel("TPS", "%")
        assert cat == "engine"
        assert internal == "throttle_pct"

    def test_coolant_temp(self):
        cat, internal = classify_channel("Coolant temperature", "°C")
        assert cat == "engine"
        assert internal == "coolant_temp_c"

    def test_oil_temp(self):
        cat, internal = classify_channel("Oil temperature", "°C")
        assert cat == "engine"
        assert internal == "oil_temp_c"

    def test_intake_temp(self):
        cat, internal = classify_channel("Intake air temperature", "°C")
        assert cat == "engine"
        assert internal == "intake_temp_c"

    def test_battery(self):
        cat, internal = classify_channel("Battery voltage", "V")
        assert cat == "engine"
        assert internal == "battery_v"

    def test_boost(self):
        cat, internal = classify_channel("Boost pressure", "kPa")
        assert cat == "engine"
        assert internal == "boost_kpa"

    def test_map_sensor(self):
        cat, internal = classify_channel("MAP", "kPa")
        assert cat == "engine"
        assert internal == "boost_kpa"

    def test_brake(self):
        cat, internal = classify_channel("Brake pressure", "bar")
        assert cat == "pedal"
        assert internal == "brake_pct"

    def test_steering(self):
        cat, internal = classify_channel("Steering angle", "deg")
        assert cat == "steering"
        assert internal == "steering_angle_deg"

    def test_heart_rate(self):
        cat, internal = classify_channel("Heart rate", "bpm")
        assert cat == "biometric"
        assert internal == "heart_rate_bpm"

    def test_custom_unknown(self):
        cat, internal = classify_channel("Tire temp FL", "°C")
        assert cat == "custom"
        assert internal == "Tire temp FL (°C)"
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestClassifyChannel -v`
Expected: FAIL with `ImportError: cannot import name 'classify_channel'`

**Step 3: Implement `classify_channel()` with priority-ordered pattern matching**

Add to `telemetry_tool/column_discovery.py` below the dataclasses:

```python
# ---------------------------------------------------------------------------
# Classification rules — priority-ordered
# ---------------------------------------------------------------------------

_RULES: Final[list[tuple[re.Pattern[str], str, str]]] = [
    # (pattern on channel name, category, internal_name)
    (re.compile(r"^Time$", re.I),                          "time",         "time_s"),
    (re.compile(r"Lap", re.I),                             "lap",          "lap_number"),
    (re.compile(r"Distance", re.I),                        "distance",     "distance_m"),
    (re.compile(r"Speed", re.I),                           "speed",        "speed_mps"),
    (re.compile(r"^Lat(?:itude)?$", re.I),                 "position",     "latitude_deg"),
    (re.compile(r"^Lon(?:gitude)?$", re.I),                "position",     "longitude_deg"),
    (re.compile(r"^X$", re.I),                             "position",     "x_m"),
    (re.compile(r"^Y$", re.I),                             "position",     "y_m"),
    (re.compile(r"Longitud.*accel", re.I),                 "acceleration", "accel_long_mps2"),
    (re.compile(r"Lateral.*accel", re.I),                  "acceleration", "accel_lat_mps2"),
    (re.compile(r"Accel.*X", re.I),                        "acceleration", "accel_long_mps2"),
    (re.compile(r"Accel.*Y", re.I),                        "acceleration", "accel_lat_mps2"),
    (re.compile(r"Accel.*Z", re.I),                        "acceleration", "accel_vert_mps2"),
    (re.compile(r"Yaw", re.I),                             "gyro",         "yaw_rate_dps"),
    (re.compile(r"Pitch", re.I),                           "gyro",         "pitch_rate_dps"),
    (re.compile(r"Roll", re.I),                            "gyro",         "roll_rate_dps"),
    (re.compile(r"Gyro.*X", re.I),                         "gyro",         "roll_rate_dps"),
    (re.compile(r"Gyro.*Y", re.I),                         "gyro",         "pitch_rate_dps"),
    (re.compile(r"Gyro.*Z", re.I),                         "gyro",         "yaw_rate_dps"),
    (re.compile(r"Bear(?:ing)?|Head(?:ing)?", re.I),       "heading",      "heading_deg"),
    (re.compile(r"Alt(?:itude)?", re.I),                   "altitude",     "altitude_m"),
    (re.compile(r"Satellite", re.I),                       "gps_quality",  "satellites"),
    (re.compile(r"Accuracy|HDOP", re.I),                   "gps_quality",  "accuracy_m"),
    (re.compile(r"RPM", re.I),                             "engine",       "engine_rpm"),
    (re.compile(r"Throttle|TPS", re.I),                    "engine",       "throttle_pct"),
    (re.compile(r"Coolant", re.I),                         "engine",       "coolant_temp_c"),
    (re.compile(r"Oil.*temp", re.I),                       "engine",       "oil_temp_c"),
    (re.compile(r"Intake.*temp", re.I),                    "engine",       "intake_temp_c"),
    (re.compile(r"Battery|Volt", re.I),                    "engine",       "battery_v"),
    (re.compile(r"Boost|^MAP$", re.I),                     "engine",       "boost_kpa"),
    (re.compile(r"Brake", re.I),                           "pedal",        "brake_pct"),
    (re.compile(r"Steer", re.I),                           "steering",     "steering_angle_deg"),
    (re.compile(r"Heart.*rate|^HR$|BPM", re.I),            "biometric",    "heart_rate_bpm"),
]


def classify_channel(name: str, unit: str | None) -> tuple[str, str]:
    """Classify a parsed channel name into (category, internal_name).

    Returns ("custom", original_name_with_unit) for unrecognized channels.
    """
    for pattern, category, internal in _RULES:
        if pattern.search(name):
            return category, internal

    # Unknown → custom, preserve original name with unit for identification
    if unit:
        return "custom", f"{name} ({unit})"
    return "custom", name
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestClassifyChannel -v`
Expected: PASS (all 38 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/column_discovery.py telemetry_tool/tests/test_column_discovery.py
git commit -m "feat: add channel classification rules — 34 patterns + custom fallback"
```

---

### Task 3: Unit Conversion + `*calc` Preference + `discover_columns()`

**Files:**
- Modify: `telemetry_tool/column_discovery.py`
- Modify: `telemetry_tool/tests/test_column_discovery.py`

**Step 1: Write the failing tests for unit conversion and full discovery**

Add to `telemetry_tool/tests/test_column_discovery.py`:

```python
import math
import pandas as pd
from column_discovery import discover_columns, apply_discovery, get_conversion


class TestUnitConversion:
    """Unit conversion factors from header units to canonical internal units."""

    def test_g_to_mps2(self):
        factor, func = get_conversion("G")
        assert factor == pytest.approx(9.80665)
        assert func is None

    def test_kmh_to_mps(self):
        factor, func = get_conversion("km/h")
        assert factor == pytest.approx(1 / 3.6)
        assert func is None

    def test_mph_to_mps(self):
        factor, func = get_conversion("mph")
        assert factor == pytest.approx(0.44704)
        assert func is None

    def test_knots_to_mps(self):
        factor, func = get_conversion("kn")
        assert factor == pytest.approx(0.514444)

    def test_ft_to_m(self):
        factor, func = get_conversion("ft")
        assert factor == pytest.approx(0.3048)

    def test_rad_s_to_deg_s(self):
        factor, func = get_conversion("rad/s")
        assert factor == pytest.approx(180 / math.pi)

    def test_fahrenheit_to_celsius(self):
        factor, func = get_conversion("°F")
        assert factor is None
        assert func is not None
        assert func(212.0) == pytest.approx(100.0)
        assert func(32.0) == pytest.approx(0.0)

    def test_psi_to_bar(self):
        factor, func = get_conversion("psi")
        assert factor == pytest.approx(0.0689476)

    def test_kpa_to_bar(self):
        factor, func = get_conversion("kPa")
        assert factor == pytest.approx(0.01)

    def test_no_conversion_needed(self):
        factor, func = get_conversion("m/s")
        assert factor is None
        assert func is None


class TestDiscoverColumns:
    """Full discovery pipeline: parse → classify → convert → preference."""

    def test_basic_racechrono_headers(self):
        df = pd.DataFrame({
            "Time (s)": [0.0, 0.1],
            "Speed (m/s) *calc": [10.0, 11.0],
            "Lateral acceleration (G) *calc": [0.5, 0.6],
            "Distance (m)": [0.0, 1.0],
            "Lap #": [1, 1],
        })
        result = discover_columns(df)
        assert result.rename_map["Time (s)"] == "time_s"
        assert result.rename_map["Speed (m/s) *calc"] == "speed_mps"
        assert result.rename_map["Lateral acceleration (G) *calc"] == "accel_lat_mps2"
        assert "accel_lat_mps2" in result.conversions  # G → m/s²
        assert result.conversions["accel_lat_mps2"] == pytest.approx(9.80665)

    def test_calc_preference(self):
        """*calc variant wins over non-calc for the same internal name."""
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "Speed (m/s)": [10.0],
            "Speed (m/s) *calc": [10.5],
        })
        result = discover_columns(df)
        # *calc should win
        assert result.rename_map.get("Speed (m/s) *calc") == "speed_mps"
        # non-calc goes to custom
        assert "Speed (m/s)" not in result.rename_map or result.rename_map.get("Speed (m/s)") != "speed_mps"

    def test_custom_channels_preserved(self):
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "Tire temp FL (°C)": [45.0],
            "Tire temp FR (°C)": [46.0],
        })
        result = discover_columns(df)
        assert "Tire temp FL (°C)" in result.custom_channels
        assert "Tire temp FR (°C)" in result.custom_channels

    def test_kmh_conversion_in_result(self):
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "Speed (km/h)": [36.0],
        })
        result = discover_columns(df)
        assert result.rename_map["Speed (km/h)"] == "speed_mps"
        assert "speed_mps" in result.conversions

    def test_n_valid_count(self):
        df = pd.DataFrame({
            "Time (s)": [0.0, 0.1, None],
            "Speed (m/s)": [10.0, None, None],
        })
        result = discover_columns(df)
        time_ch = next(c for c in result.channels if c.internal_name == "time_s")
        speed_ch = next(c for c in result.channels if c.internal_name == "speed_mps")
        assert time_ch.n_valid == 2
        assert speed_ch.n_valid == 1


class TestApplyDiscovery:
    """apply_discovery() renames columns and applies unit conversions."""

    def test_rename_and_convert(self):
        df = pd.DataFrame({
            "Time (s)": [0.0, 0.1],
            "Speed (km/h)": [36.0, 72.0],
            "Lateral acceleration (G)": [0.5, 1.0],
        })
        result = discover_columns(df)
        df = apply_discovery(df, result)
        assert "speed_mps" in df.columns
        assert "time_s" in df.columns
        assert df["speed_mps"].iloc[0] == pytest.approx(10.0)
        assert df["speed_mps"].iloc[1] == pytest.approx(20.0)
        assert df["accel_lat_mps2"].iloc[0] == pytest.approx(0.5 * 9.80665)

    def test_fahrenheit_conversion(self):
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "Coolant temperature (°F)": [212.0],
        })
        result = discover_columns(df)
        df = apply_discovery(df, result)
        assert "coolant_temp_c" in df.columns
        assert df["coolant_temp_c"].iloc[0] == pytest.approx(100.0)

    def test_columns_not_in_rename_map_pass_through(self):
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "custom_sensor": [42.0],
        })
        result = discover_columns(df)
        df = apply_discovery(df, result)
        assert "custom_sensor" in df.columns
        assert "time_s" in df.columns
```

**Step 2: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestUnitConversion tests/test_column_discovery.py::TestDiscoverColumns tests/test_column_discovery.py::TestApplyDiscovery -v`
Expected: FAIL with `ImportError`

**Step 3: Implement `get_conversion()`, `discover_columns()`, and `apply_discovery()`**

Add to `telemetry_tool/column_discovery.py`:

```python
# ---------------------------------------------------------------------------
# Unit conversion table
# ---------------------------------------------------------------------------

# Simple multiplications: (unit_from → (factor, canonical_unit))
_UNIT_FACTORS: Final[dict[str, tuple[float, str]]] = {
    "G":      (9.80665,             "m/s²"),
    "km/h":   (1.0 / 3.6,          "m/s"),
    "mph":    (0.44704,             "m/s"),
    "kn":     (0.514444,            "m/s"),
    "knots":  (0.514444,            "m/s"),
    "ft":     (0.3048,              "m"),
    "ft/s":   (0.3048,              "m/s"),
    "rad/s":  (180.0 / np.pi,      "deg/s"),
    "kPa":    (0.01,                "bar"),
    "psi":    (0.0689476,           "bar"),
}


def _fahrenheit_to_celsius(v: float) -> float:
    return (v - 32.0) * 5.0 / 9.0


# Non-linear conversions: unit → callable
_UNIT_FUNCTIONS: Final[dict[str, tuple[callable, str]]] = {
    "°F": (_fahrenheit_to_celsius, "°C"),
}


def get_conversion(unit: str | None) -> tuple[float | None, callable | None]:
    """Return (multiplication_factor, function) for a unit.

    Exactly one of factor/function will be non-None, or both None if
    no conversion is needed.
    """
    if unit is None:
        return None, None
    if unit in _UNIT_FACTORS:
        return _UNIT_FACTORS[unit][0], None
    if unit in _UNIT_FUNCTIONS:
        return None, _UNIT_FUNCTIONS[unit][0]
    return None, None


# ---------------------------------------------------------------------------
# Discovery engine
# ---------------------------------------------------------------------------


def discover_columns(df: pd.DataFrame) -> DiscoveryResult:
    """Parse all column headers, classify, convert units, apply *calc preference."""
    result = DiscoveryResult()
    channels: list[DiscoveredChannel] = []

    # First pass: parse and classify every column
    for raw_col in df.columns:
        name, unit, flag = parse_header(str(raw_col))
        category, internal = classify_channel(name, unit)
        is_calc = flag == "calc"

        factor, func = get_conversion(unit)
        conversion_factor = factor  # None if no multiplication needed

        n_valid = int(df[raw_col].notna().sum()) if raw_col in df.columns else 0

        # Determine canonical unit after conversion
        unit_internal = unit
        if unit and unit in _UNIT_FACTORS:
            unit_internal = _UNIT_FACTORS[unit][1]
        elif unit and unit in _UNIT_FUNCTIONS:
            unit_internal = _UNIT_FUNCTIONS[unit][1]

        ch = DiscoveredChannel(
            raw_name=raw_col,
            internal_name=internal,
            category=category,
            unit_raw=unit,
            unit_internal=unit_internal,
            is_calc=is_calc,
            conversion_factor=conversion_factor,
            n_valid=n_valid,
        )
        channels.append(ch)

    # Second pass: resolve conflicts (multiple columns → same internal name)
    # *calc wins; among same flag, first match wins.
    claimed: dict[str, DiscoveredChannel] = {}  # internal_name → winning channel
    for ch in channels:
        if ch.category == "custom":
            result.custom_channels.append(ch.raw_name)
            continue

        existing = claimed.get(ch.internal_name)
        if existing is None:
            claimed[ch.internal_name] = ch
        elif ch.is_calc and not existing.is_calc:
            # *calc wins: demote existing to custom
            result.custom_channels.append(existing.raw_name)
            result.calc_overrides[ch.internal_name] = ch.raw_name
            claimed[ch.internal_name] = ch
        else:
            # Duplicate loses → custom
            result.custom_channels.append(ch.raw_name)

    # Build rename_map and conversions from winners
    for internal_name, ch in claimed.items():
        if ch.raw_name != internal_name:
            result.rename_map[ch.raw_name] = internal_name

        factor, func = get_conversion(ch.unit_raw)
        if factor is not None:
            result.conversions[internal_name] = factor
        elif func is not None:
            # Store negative marker to signal function-based conversion
            result.conversions[internal_name] = -1.0  # sentinel

    result.channels = channels
    return result


def apply_discovery(df: pd.DataFrame, result: DiscoveryResult) -> pd.DataFrame:
    """Rename columns to internal names and apply unit conversions in-place."""
    # Apply function-based conversions BEFORE rename (they need raw column names)
    for raw_col, internal_name in result.rename_map.items():
        if internal_name in result.conversions and result.conversions[internal_name] == -1.0:
            # Function-based conversion (e.g. °F → °C)
            ch = next((c for c in result.channels if c.raw_name == raw_col), None)
            if ch and ch.unit_raw:
                _, func = get_conversion(ch.unit_raw)
                if func is not None and raw_col in df.columns:
                    df[raw_col] = df[raw_col].apply(
                        lambda v: func(v) if pd.notna(v) else v
                    )

    # Rename
    if result.rename_map:
        df = df.rename(columns=result.rename_map)

    # Apply multiplication-factor conversions (on renamed columns)
    for internal_name, factor in result.conversions.items():
        if factor > 0 and internal_name in df.columns:
            df[internal_name] = df[internal_name] * factor

    return df
```

**Step 4: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py -v`
Expected: PASS (all tests — parse, classify, conversion, discovery, apply)

**Step 5: Commit**

```bash
git add telemetry_tool/column_discovery.py telemetry_tool/tests/test_column_discovery.py
git commit -m "feat: add unit conversion + *calc preference + discover/apply pipeline"
```

---

### Task 4: Format Detection + Header Sentinel Expansion

**Files:**
- Modify: `telemetry_tool/column_discovery.py`
- Modify: `telemetry_tool/io_racechrono.py`
- Modify: `telemetry_tool/ingest/streaming.py`
- Modify: `telemetry_tool/tests/test_column_discovery.py`

**Step 1: Write failing tests for format detection and expanded sentinels**

Add to `telemetry_tool/tests/test_column_discovery.py`:

```python
from column_discovery import detect_format


class TestFormatDetection:
    """Detect CSV source from metadata rows."""

    def test_racechrono(self):
        assert detect_format({"app": "RaceChrono Pro v7.0"}) == "racechrono"

    def test_racebox(self):
        assert detect_format({"device": "RaceBox Mini S"}) == "racebox"

    def test_unknown(self):
        assert detect_format({"foo": "bar"}) == "unknown"

    def test_case_insensitive(self):
        assert detect_format({"app": "RACECHRONO PRO"}) == "racechrono"
```

**Step 2: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestFormatDetection -v`
Expected: FAIL with `ImportError`

**Step 3: Implement `detect_format()` and expand header sentinels**

Add to `telemetry_tool/column_discovery.py`:

```python
def detect_format(metadata: dict[str, str]) -> str:
    """Detect source format from CSV metadata rows above the header."""
    text = " ".join(str(v) for v in metadata.values()).lower()
    if "racebox" in text:
        return "racebox"
    if "racechrono" in text:
        return "racechrono"
    return "unknown"
```

In `telemetry_tool/io_racechrono.py`, change:

```python
# OLD:
_HEADER_SENTINEL: Final[str] = "Time (s)"

# NEW:
_HEADER_SENTINELS: Final[frozenset[str]] = frozenset({
    "Time (s)", "Time", "UTC Time", "Timestamp", "time_s",
})
```

Then update `_find_header_row_from_lines()` to check against the set:

```python
# OLD:
        if first_cell == _HEADER_SENTINEL:

# NEW:
        if first_cell in _HEADER_SENTINELS:
```

And in `_find_header_row_from_lines()` raise message — update the error message:

```python
# OLD:
        f"Expected first cell to contain {_HEADER_SENTINEL!r} "

# NEW:
        f"Expected first cell to match one of {_HEADER_SENTINELS!r} "
```

Same changes in `telemetry_tool/ingest/streaming.py`:

```python
# OLD:
_HEADER_SENTINEL: Final[str] = "Time (s)"

# NEW:
_HEADER_SENTINELS: Final[frozenset[str]] = frozenset({
    "Time (s)", "Time", "UTC Time", "Timestamp", "time_s",
})
```

Then update `_scan_for_header()` to check against the set (find the line comparing to `_HEADER_SENTINEL` and replace).

**Step 4: Run all tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py tests/test_streaming_ingest.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/column_discovery.py telemetry_tool/io_racechrono.py telemetry_tool/ingest/streaming.py telemetry_tool/tests/test_column_discovery.py
git commit -m "feat: format detection + expand header sentinels for RaceBox support"
```

---

### Task 5: Pipeline Integration — Replace `_RAW_TO_INTERNAL`

**Files:**
- Modify: `telemetry_tool/pipeline.py` (lines ~88-127 and ~1813)
- Modify: `telemetry_tool/tests/test_column_discovery.py`

**Step 1: Write a failing integration test**

Add to `telemetry_tool/tests/test_column_discovery.py`:

```python
class TestPipelineIntegration:
    """Verify discovery integrates correctly with the pipeline's column expectations."""

    def test_all_old_mappings_still_work(self):
        """Every column name in the old _RAW_TO_INTERNAL produces the same internal name."""
        old_mapping = {
            "Distance (m)": "distance_m",
            "Speed (m/s)": "speed_mps",
            "Speed (m/s) *calc": "speed_mps",
            "Longitudinal acceleration (G) *calc": "accel_long_mps2",
            "Longitudinal acceleration (m/s²)": "accel_long_mps2",
            "Lateral acceleration (G) *calc": "accel_lat_mps2",
            "Lateral acceleration (m/s²)": "accel_lat_mps2",
            "Time (s)": "time_s",
            "Lap #": "lap_number",
        }
        for raw, expected_internal in old_mapping.items():
            # Build a single-column DataFrame
            df = pd.DataFrame({raw: [1.0]})
            result = discover_columns(df)
            actual = result.rename_map.get(raw, raw)
            assert actual == expected_internal, (
                f"Column {raw!r}: expected {expected_internal!r}, got {actual!r}"
            )

    def test_raw_accel_without_calc_now_maps(self):
        """Raw 'Longitudinal acceleration (G)' (no *calc) now maps to accel_long_mps2."""
        df = pd.DataFrame({"Longitudinal acceleration (G)": [0.5]})
        result = discover_columns(df)
        assert result.rename_map["Longitudinal acceleration (G)"] == "accel_long_mps2"
        assert "accel_long_mps2" in result.conversions

    def test_racebox_accel_columns(self):
        """RaceBox uses 'Acceleration X/Y/Z' — should map correctly."""
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "Acceleration X (m/s²)": [1.0],
            "Acceleration Y (m/s²)": [2.0],
            "Acceleration Z (m/s²)": [3.0],
        })
        result = discover_columns(df)
        assert result.rename_map["Acceleration X (m/s²)"] == "accel_long_mps2"
        assert result.rename_map["Acceleration Y (m/s²)"] == "accel_lat_mps2"
        assert result.rename_map["Acceleration Z (m/s²)"] == "accel_vert_mps2"
```

**Step 2: Run test to verify it passes (these should pass with existing implementation)**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestPipelineIntegration -v`
Expected: PASS (validates backward compat)

**Step 3: Replace `_RAW_TO_INTERNAL` and `_map_to_internal_names()` in pipeline.py**

In `telemetry_tool/pipeline.py`:

1. Remove the `_RAW_TO_INTERNAL` dict (lines ~88-101) and the `_map_to_internal_names()` function (lines ~104-127). Replace with an import:

```python
from telemetry_tool.column_discovery import discover_columns, apply_discovery
```

2. In the pipeline orchestrator, find where `_map_to_internal_names` is called (grep shows line ~1813) and replace:

```python
# OLD:
            laps_list = [
                _map_to_internal_names(resampled_laps[k])
                for k in sorted_keys
            ]

# NEW:
            laps_list = [
                apply_discovery(resampled_laps[k], _channel_discovery)
                if _channel_discovery else resampled_laps[k]
                for k in sorted_keys
            ]
```

3. Earlier in the pipeline (after the DataFrame is loaded, before derived channels), add the discovery call. Find the appropriate location after CSV is read and add:

```python
            # -- Column discovery (replaces _RAW_TO_INTERNAL) --
            _channel_discovery = None
            try:
                from telemetry_tool.column_discovery import discover_columns, apply_discovery
                _channel_discovery = discover_columns(df)
                df = apply_discovery(df, _channel_discovery)
                summary["channel_discovery"] = _channel_discovery.to_dict()
                logger.info(
                    "Column discovery: %d channels (%d custom), format=%s",
                    len(_channel_discovery.channels),
                    len(_channel_discovery.custom_channels),
                    _channel_discovery.format,
                )
            except Exception as exc:
                logger.warning("Column discovery failed: %s — falling back", exc)
```

**Step 4: Run existing pipeline tests to verify no regression**

Run: `cd telemetry_tool && python -m pytest tests/ -v -x`
Expected: All existing tests pass

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_column_discovery.py
git commit -m "feat: integrate column discovery into pipeline, replace _RAW_TO_INTERNAL"
```

---

### Task 6: DB Schema Migration — `channel_inventory` Column

**Files:**
- Modify: `telemetry_tool/db/schema.py` (bump version, no new table needed — just ALTER)
- Modify: `telemetry_tool/db/migrate.py` (add Phase 28 migration)
- Modify: `telemetry_tool/web/models.py` (persist channel_inventory on session upsert)

**Step 1: Write the failing test for channel inventory persistence**

Add to `telemetry_tool/tests/test_column_discovery.py`:

```python
import json
import sqlite3
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db.migrate import ensure_schema


class TestChannelInventoryDB:
    """Channel inventory persisted to sessions.channel_inventory."""

    @pytest.fixture
    def db(self):
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
        assert row["channel_inventory"] is None  # default is NULL

    def test_can_store_json(self, db):
        """Can store and retrieve JSON in channel_inventory."""
        inventory = {"format": "racechrono", "channels": [], "custom": []}
        db.execute(
            "UPDATE sessions SET channel_inventory = ? WHERE session_id = ?",
            (json.dumps(inventory), "s1"),
        )
        db.commit()
        row = db.execute(
            "SELECT channel_inventory FROM sessions WHERE session_id='s1'"
        ).fetchone()
        loaded = json.loads(row["channel_inventory"])
        assert loaded["format"] == "racechrono"
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestChannelInventoryDB -v`
Expected: FAIL with `OperationalError: no such column: channel_inventory`

**Step 3: Add the migration**

In `telemetry_tool/db/schema.py`, change:

```python
# OLD:
SCHEMA_VERSION = 27

# NEW:
SCHEMA_VERSION = 28
```

In `telemetry_tool/db/migrate.py`, before `conn.commit()` at the end of `ensure_schema()`, add:

```python
    # Phase 28 migration: add channel_inventory to sessions (idempotent).
    try:
        cur.execute("ALTER TABLE sessions ADD COLUMN channel_inventory TEXT;")
        logger.debug("Added column sessions.channel_inventory.")
    except sqlite3.OperationalError:
        pass  # Column already exists.

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (28, "Phase 28 schema — channel_inventory JSON on sessions"),
    )
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestChannelInventoryDB -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/migrate.py telemetry_tool/tests/test_column_discovery.py
git commit -m "feat: schema v28 — add channel_inventory TEXT column to sessions"
```

---

### Task 7: Persist Channel Inventory in `models.py`

**Files:**
- Modify: `telemetry_tool/web/models.py`
- Modify: `telemetry_tool/tests/test_column_discovery.py`

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_column_discovery.py`:

```python
from web.models import upsert_session


class TestChannelInventoryPersistence:
    """upsert_session stores channel_discovery in channel_inventory column."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')"
        )
        conn.commit()
        yield conn
        conn.close()

    def test_channel_discovery_stored(self, db):
        """Pipeline summary with channel_discovery → stored in channel_inventory."""
        summary = {
            "session_meta": {"session_id": "s1", "session_date": "2026-01-01"},
            "csv_path": "test.csv",
            "lap_times": [60.0],
            "resampled_laps": {},
            "channel_discovery": {
                "format": "racechrono",
                "channels": [
                    {"raw": "Speed (m/s) *calc", "internal": "speed_mps",
                     "category": "speed", "unit": "m/s", "is_calc": True, "n_valid": 100}
                ],
                "custom": ["Tire temp FL (°C)"],
            },
        }
        session_id = upsert_session(db, summary, driver_id=1)
        row = db.execute(
            "SELECT channel_inventory FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        assert row["channel_inventory"] is not None
        loaded = json.loads(row["channel_inventory"])
        assert loaded["format"] == "racechrono"
        assert len(loaded["channels"]) == 1

    def test_no_channel_discovery_no_error(self, db):
        """Summary without channel_discovery → channel_inventory stays NULL."""
        summary = {
            "session_meta": {"session_id": "s2", "session_date": "2026-01-01"},
            "csv_path": "test.csv",
            "lap_times": [60.0],
            "resampled_laps": {},
        }
        session_id = upsert_session(db, summary, driver_id=1)
        row = db.execute(
            "SELECT channel_inventory FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        assert row["channel_inventory"] is None
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestChannelInventoryPersistence -v`
Expected: FAIL (channel_inventory not being written)

**Step 3: Add channel_inventory persistence to `upsert_session()`**

In `telemetry_tool/web/models.py`, in the `upsert_session()` function, find where the INSERT statement builds its column list. Add `channel_inventory` to the INSERT and populate it from `summary.get("channel_discovery")`:

```python
    channel_discovery = summary.get("channel_discovery")
    channel_inventory_json = json.dumps(channel_discovery) if channel_discovery else None
```

Then include `channel_inventory` in the INSERT/UPDATE SQL and pass `channel_inventory_json` as the parameter value.

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestChannelInventoryPersistence -v`
Expected: PASS

**Step 5: Run full test suite for regression**

Run: `cd telemetry_tool && python -m pytest tests/ -v -x`
Expected: All tests pass

**Step 6: Commit**

```bash
git add telemetry_tool/web/models.py telemetry_tool/tests/test_column_discovery.py
git commit -m "feat: persist channel_inventory JSON in sessions table via upsert_session"
```

---

### Task 8: API Endpoints — Channel Inventory + Channel Data

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py`
- Modify: `telemetry_tool/tests/test_column_discovery.py` (or new `test_data_api_v2.py` if it exists)

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_column_discovery.py`:

```python
class TestChannelsAPI:
    """GET /api/v1/sessions/<id>/channels returns channel inventory."""

    @pytest.fixture
    def db(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')"
        )
        inventory = json.dumps({
            "format": "racechrono",
            "channels": [
                {"raw": "Speed (m/s) *calc", "internal": "speed_mps",
                 "category": "speed", "unit": "m/s", "is_calc": True, "n_valid": 100},
                {"raw": "Engine RPM (rpm)", "internal": "engine_rpm",
                 "category": "engine", "unit": "rpm", "is_calc": False, "n_valid": 95},
            ],
            "custom": ["Tire temp FL (°C)"],
        })
        conn.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, "
            "session_type, session_date, channel_inventory) "
            "VALUES ('s1', 'test.csv', 1, 'practice', '2026-01-01', ?)",
            (inventory,),
        )
        conn.commit()
        yield conn
        conn.close()

    def test_get_channels_returns_inventory(self, db):
        row = db.execute(
            "SELECT channel_inventory FROM sessions WHERE session_id = 's1'"
        ).fetchone()
        inventory = json.loads(row["channel_inventory"])
        assert inventory["format"] == "racechrono"
        assert len(inventory["channels"]) == 2
        assert inventory["channels"][0]["internal"] == "speed_mps"
        assert "Tire temp FL (°C)" in inventory["custom"]

    def test_no_inventory_returns_null(self, db):
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, "
            "session_type, session_date) "
            "VALUES ('s2', 'test2.csv', 1, 'practice', '2026-01-01')"
        )
        db.commit()
        row = db.execute(
            "SELECT channel_inventory FROM sessions WHERE session_id = 's2'"
        ).fetchone()
        assert row["channel_inventory"] is None
```

**Step 2: Run test to verify it passes (DB-level — these are just verifying the read side)**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestChannelsAPI -v`
Expected: PASS

**Step 3: Add API endpoint for channel inventory**

In `telemetry_tool/web/routes/data_v2.py`, add:

```python
@bp.route("/sessions/<session_id>/channels", methods=["GET"])
@_safe_api
def get_session_channels(session_id: str):
    """Return the channel inventory discovered during CSV ingestion."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT channel_inventory FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return api_error("Session not found", ErrorCode.NOT_FOUND, 404)

    inventory = None
    if row["channel_inventory"]:
        try:
            inventory = json.loads(row["channel_inventory"])
        except (json.JSONDecodeError, TypeError):
            inventory = None

    return api_response(inventory)
```

**Step 4: Run all tests to verify no regression**

Run: `cd telemetry_tool && python -m pytest tests/ -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_column_discovery.py
git commit -m "feat: add GET /sessions/<id>/channels endpoint for channel inventory"
```

---

### Task 9: Alembic Migration for PostgreSQL

**Files:**
- Create: `alembic/versions/017_channel_inventory.py`

**Step 1: Create the Alembic migration file**

```python
# alembic/versions/017_channel_inventory.py
"""Add channel_inventory column to sessions table.

Revision ID: 017
Revises: 016
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("channel_inventory", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "channel_inventory")
```

**Step 2: Verify the migration file is syntactically valid**

Run: `cd telemetry_tool && python -c "import ast; ast.parse(open('../alembic/versions/017_channel_inventory.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add alembic/versions/017_channel_inventory.py
git commit -m "feat: Alembic migration 017 — channel_inventory column on sessions"
```

---

### Task 10: Edge Case Tests + Regression Suite

**Files:**
- Modify: `telemetry_tool/tests/test_column_discovery.py`

**Step 1: Write edge case tests**

Add to `telemetry_tool/tests/test_column_discovery.py`:

```python
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
        # First one (m/s) wins, second (km/h) goes to custom
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
        # *calc should win
        mapped = [k for k, v in result.rename_map.items() if v == "accel_lat_mps2"]
        assert "Lateral acceleration (G) *calc" in mapped
        assert "Lateral acceleration (G)" in result.custom_channels

    def test_mixed_accel_units(self):
        """G and m/s² variants for same axis — *calc G should win."""
        df = pd.DataFrame({
            "Time (s)": [0.0],
            "Longitudinal acceleration (m/s²)": [5.0],
            "Longitudinal acceleration (G) *calc": [0.5],
        })
        result = discover_columns(df)
        mapped = [k for k, v in result.rename_map.items() if v == "accel_long_mps2"]
        assert "Longitudinal acceleration (G) *calc" in mapped

    def test_european_decimal_values_ok(self):
        """Numeric values should work regardless of discovery."""
        df = pd.DataFrame({
            "Time (s)": [0.0, 0.1],
            "Speed (m/s)": [10.5, 11.3],
        })
        result = discover_columns(df)
        df2 = apply_discovery(df, result)
        assert df2["speed_mps"].iloc[0] == pytest.approx(10.5)
```

**Step 2: Run tests**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestEdgeCases -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `cd telemetry_tool && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add telemetry_tool/tests/test_column_discovery.py
git commit -m "test: add edge case tests — NaN, empty, duplicates, mixed units"
```

---

### Task 11: Update `derived_channels.py` Column Name References

**Files:**
- Modify: `telemetry_tool/derived_channels.py`

**Step 1: Verify derived_channels still works with internal names**

The `derived_channels.py` module hard-codes raw RaceChrono column names (`"Longitudinal acceleration (G) *calc"`, `"Speed (m/s)"`, etc.). After column discovery runs, these raw names will have been renamed to internal names.

The module already checks for internal names as fallbacks (e.g., `OUT_LONG = "accel_long_mps2"`). We need to ensure the priority order checks the INTERNAL name FIRST (since discovery runs before derived channels).

Review the `derive_longitudinal_accel()` function — it should check for `accel_long_mps2` first, then fall back to raw names for legacy compatibility.

**Step 2: Update the priority order if needed**

In `derived_channels.py`, for each `derive_*` function, ensure the internal name is checked first:

```python
# In derive_longitudinal_accel():
# Check internal name first (post-discovery), then raw fallbacks
if OUT_LONG in df.columns:
    # Already computed or mapped by discovery — skip
    ...
elif _RAW_LONG_G in df.columns:
    # Raw G column still present (legacy path without discovery)
    ...
```

This change ensures:
- **With discovery**: internal names exist → derived channels skips (no double work)
- **Without discovery** (legacy/fallback): raw names exist → derived channels does its job

**Step 3: Run all tests**

Run: `cd telemetry_tool && python -m pytest tests/ -v -x`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add telemetry_tool/derived_channels.py
git commit -m "fix: derived_channels checks internal names first (post-discovery compat)"
```

---

### Task 12: Final Integration Test + Cleanup

**Files:**
- Modify: `telemetry_tool/tests/test_column_discovery.py`

**Step 1: Write a full end-to-end integration test**

```python
class TestEndToEnd:
    """Full pipeline: CSV headers → discover → apply → verify internal names."""

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
            "Tire temp FL (°C)": [45.0, 46.0, 47.0],
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
        assert df["accel_long_mps2"].iloc[0] == pytest.approx(0.1 * 9.80665)  # G → m/s²

        # Custom channels preserved
        assert "Tire temp FL (°C)" in result.custom_channels

        # Serialization works
        d = result.to_dict()
        assert d["format"] == "unknown"  # no metadata → unknown
        assert len(d["channels"]) == len(df.columns) + len(result.custom_channels)
```

**Step 2: Run the test**

Run: `cd telemetry_tool && python -m pytest tests/test_column_discovery.py::TestEndToEnd -v`
Expected: PASS

**Step 3: Run full test suite one final time**

Run: `cd telemetry_tool && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Final commit**

```bash
git add telemetry_tool/tests/test_column_discovery.py
git commit -m "test: add end-to-end integration test for column discovery"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Header parsing + dataclasses | `column_discovery.py` (new), `test_column_discovery.py` (new) |
| 2 | Classification rules (34 patterns) | `column_discovery.py`, `test_column_discovery.py` |
| 3 | Unit conversion + `*calc` preference + discover/apply | `column_discovery.py`, `test_column_discovery.py` |
| 4 | Format detection + sentinel expansion | `column_discovery.py`, `io_racechrono.py`, `streaming.py` |
| 5 | Pipeline integration (replace `_RAW_TO_INTERNAL`) | `pipeline.py`, `test_column_discovery.py` |
| 6 | DB schema migration (v28) | `schema.py`, `migrate.py` |
| 7 | Persist channel inventory in models | `models.py`, `test_column_discovery.py` |
| 8 | API endpoint `/channels` | `data_v2.py`, `test_column_discovery.py` |
| 9 | Alembic migration for PostgreSQL | `017_channel_inventory.py` (new) |
| 10 | Edge case tests | `test_column_discovery.py` |
| 11 | Update derived_channels.py compat | `derived_channels.py` |
| 12 | End-to-end integration test | `test_column_discovery.py` |
