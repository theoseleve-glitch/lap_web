# Universal Telemetry Adapter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a universal format adapter layer, progressive 3-tier physics engine, and 7 new visualizations so the platform ingests telemetry from iRacing, ACC, MoTeC, AiM, F1 games, OBD-II loggers, and VBOX — using the extra data channels to improve theoretical lap precision and scoring.

**Architecture:** Format adapters parse native files into a canonical DataFrame with standardized column names from a typed channel registry. The physics engine auto-selects model complexity (tier 1-3) based on which channels are present. New React canvas charts render rich data when available, with graceful "data not available" fallbacks.

**Tech Stack:** Python 3.x + pandas + numpy (backend adapters + physics), pyibt (iRacing binary), ldparser (MoTeC binary), React + TypeScript + Canvas API (frontend charts), Zustand (hover sync), Alembic (migrations)

**Design doc:** `docs/plans/2026-03-02-universal-telemetry-adapter-design.md`

---

## Phase 1: Channel Registry + Base Adapter Interface

### Task 1: Channel Registry Module

**Files:**
- Create: `telemetry_tool/channel_registry.py`
- Test: `telemetry_tool/tests/test_channel_registry.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_channel_registry.py
"""Tests for channel_registry — canonical telemetry channel definitions."""
import pytest
from telemetry_tool.channel_registry import (
    CHANNELS, ChannelDef, get_channels_by_tier, get_channels_by_category,
    detect_data_tier, validate_channel_value, TIER_ESSENTIAL, TIER_STANDARD,
    TIER_CONTROLS, TIER_ADVANCED, TIER_PROFESSIONAL,
)


def test_channel_def_fields():
    ch = CHANNELS["speed_mps"]
    assert ch.name == "speed_mps"
    assert ch.unit == "m/s"
    assert ch.tier == TIER_ESSENTIAL
    assert ch.category == "motion"
    assert ch.valid_range == (0.0, 150.0)


def test_all_channels_have_required_fields():
    for name, ch in CHANNELS.items():
        assert ch.name == name, f"Key mismatch for {name}"
        assert ch.unit is not None
        assert ch.tier in (1, 2, 3, 4, 5)
        assert ch.category in (
            "time", "position", "motion", "controls",
            "tires", "brakes", "engine", "aero", "fuel", "environment",
        )
        assert isinstance(ch.valid_range, tuple) and len(ch.valid_range) == 2


def test_tier_counts():
    t1 = get_channels_by_tier(TIER_ESSENTIAL)
    t3 = get_channels_by_tier(TIER_CONTROLS)
    assert len(t1) >= 7  # time, speed, lat, lon, distance, lap, altitude
    assert len(t3) >= 4  # throttle, brake, steering, rpm


def test_detect_tier_essential():
    cols = ["time_s", "speed_mps", "lat_deg", "lon_deg", "distance_m"]
    assert detect_data_tier(cols) == 1


def test_detect_tier_controls():
    cols = [
        "time_s", "speed_mps", "lat_deg", "lon_deg", "distance_m",
        "accel_long_mps2", "accel_lat_mps2",
        "throttle_pct", "brake_pct", "rpm",
    ]
    assert detect_data_tier(cols) == 3


def test_detect_tier_advanced():
    cols = [
        "time_s", "speed_mps", "lat_deg", "lon_deg", "distance_m",
        "accel_long_mps2", "accel_lat_mps2",
        "throttle_pct", "brake_pct", "rpm",
        "tire_temp_fl", "tire_temp_fr", "tire_temp_rl", "tire_temp_rr",
    ]
    assert detect_data_tier(cols) == 4


def test_validate_channel_in_range():
    assert validate_channel_value("speed_mps", 30.0) is True
    assert validate_channel_value("speed_mps", -5.0) is False
    assert validate_channel_value("speed_mps", 200.0) is False


def test_get_by_category():
    motion = get_channels_by_category("motion")
    assert "speed_mps" in [ch.name for ch in motion]
    assert "throttle_pct" not in [ch.name for ch in motion]
```

**Step 2: Run test to verify it fails**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_channel_registry.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'telemetry_tool.channel_registry')

**Step 3: Write minimal implementation**

```python
# telemetry_tool/channel_registry.py
"""
channel_registry.py — Canonical telemetry channel definitions.

Defines every telemetry channel the system can ingest, organized into 5 tiers
from GPS-only (tier 1) to professional data acquisition (tier 5).
Used by format adapters, physics engine, charts, and scoring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Tier constants
TIER_ESSENTIAL: Final[int] = 1      # GPS loggers
TIER_STANDARD: Final[int] = 2       # phone accelerometer
TIER_CONTROLS: Final[int] = 3       # OBD-II / sim basic
TIER_ADVANCED: Final[int] = 4       # sim full / AiM / MoTeC
TIER_PROFESSIONAL: Final[int] = 5   # full data acquisition


@dataclass(frozen=True)
class ChannelDef:
    """Definition of a single telemetry channel."""
    name: str
    unit: str
    tier: int
    category: str
    valid_range: tuple[float, float]
    description: str = ""


def _ch(name, unit, tier, cat, vmin, vmax, desc=""):
    return ChannelDef(name=name, unit=unit, tier=tier, category=cat,
                      valid_range=(vmin, vmax), description=desc)


CHANNELS: dict[str, ChannelDef] = {
    # ── Tier 1: Essential (GPS loggers) ─────────────────────
    "time_s":         _ch("time_s",         "s",     1, "time",     0,     1e7, "Sample timestamp"),
    "speed_mps":      _ch("speed_mps",      "m/s",   1, "motion",   0,     150, "Vehicle speed"),
    "lat_deg":        _ch("lat_deg",        "deg",   1, "position", -90,    90, "Latitude"),
    "lon_deg":        _ch("lon_deg",        "deg",   1, "position", -180,  180, "Longitude"),
    "distance_m":     _ch("distance_m",     "m",     1, "position",  0,   1e7, "Cumulative distance"),
    "lap_number":     _ch("lap_number",     "",      1, "time",      0,  9999, "Lap identifier"),
    "altitude_m":     _ch("altitude_m",     "m",     1, "position", -500, 9000, "Elevation"),
    # ── Tier 2: Standard (accelerometer) ────────────────────
    "accel_long_mps2":_ch("accel_long_mps2","m/s²",  2, "motion",  -60,    60, "Longitudinal acceleration"),
    "accel_lat_mps2": _ch("accel_lat_mps2", "m/s²",  2, "motion",  -60,    60, "Lateral acceleration"),
    "yaw_rate_dps":   _ch("yaw_rate_dps",   "deg/s", 2, "motion", -1000, 1000, "Yaw rate"),
    "heading_deg":    _ch("heading_deg",    "deg",   2, "motion",    0,   360, "Compass bearing"),
    "combined_g":     _ch("combined_g",     "G",     2, "motion",    0,    10, "Total G-force"),
    # ── Tier 3: Controls (OBD / sim basic) ──────────────────
    "throttle_pct":    _ch("throttle_pct",    "%",    3, "controls", 0, 100, "Throttle position"),
    "brake_pct":       _ch("brake_pct",       "%",    3, "controls", 0, 100, "Brake position/pressure"),
    "steering_angle_deg": _ch("steering_angle_deg", "deg", 3, "controls", -900, 900, "Steering wheel angle"),
    "rpm":             _ch("rpm",             "rev/min", 3, "engine", 0, 20000, "Engine RPM"),
    "gear":            _ch("gear",            "",      3, "engine",  -1, 12, "Current gear"),
    "clutch_pct":      _ch("clutch_pct",      "%",     3, "controls", 0, 100, "Clutch position"),
    # ── Tier 4: Advanced (sim full / pro) ───────────────────
    "tire_temp_fl":    _ch("tire_temp_fl",    "°C",   4, "tires",  -20, 300, "Front-left tire temp"),
    "tire_temp_fr":    _ch("tire_temp_fr",    "°C",   4, "tires",  -20, 300, "Front-right tire temp"),
    "tire_temp_rl":    _ch("tire_temp_rl",    "°C",   4, "tires",  -20, 300, "Rear-left tire temp"),
    "tire_temp_rr":    _ch("tire_temp_rr",    "°C",   4, "tires",  -20, 300, "Rear-right tire temp"),
    "tire_temp_fl_i":  _ch("tire_temp_fl_i",  "°C",   4, "tires",  -20, 300, "FL tire inner temp"),
    "tire_temp_fl_m":  _ch("tire_temp_fl_m",  "°C",   4, "tires",  -20, 300, "FL tire mid temp"),
    "tire_temp_fl_o":  _ch("tire_temp_fl_o",  "°C",   4, "tires",  -20, 300, "FL tire outer temp"),
    "tire_temp_fr_i":  _ch("tire_temp_fr_i",  "°C",   4, "tires",  -20, 300, "FR tire inner temp"),
    "tire_temp_fr_m":  _ch("tire_temp_fr_m",  "°C",   4, "tires",  -20, 300, "FR tire mid temp"),
    "tire_temp_fr_o":  _ch("tire_temp_fr_o",  "°C",   4, "tires",  -20, 300, "FR tire outer temp"),
    "tire_temp_rl_i":  _ch("tire_temp_rl_i",  "°C",   4, "tires",  -20, 300, "RL tire inner temp"),
    "tire_temp_rl_m":  _ch("tire_temp_rl_m",  "°C",   4, "tires",  -20, 300, "RL tire mid temp"),
    "tire_temp_rl_o":  _ch("tire_temp_rl_o",  "°C",   4, "tires",  -20, 300, "RL tire outer temp"),
    "tire_temp_rr_i":  _ch("tire_temp_rr_i",  "°C",   4, "tires",  -20, 300, "RR tire inner temp"),
    "tire_temp_rr_m":  _ch("tire_temp_rr_m",  "°C",   4, "tires",  -20, 300, "RR tire mid temp"),
    "tire_temp_rr_o":  _ch("tire_temp_rr_o",  "°C",   4, "tires",  -20, 300, "RR tire outer temp"),
    "tire_pressure_fl": _ch("tire_pressure_fl", "kPa", 4, "tires", 50, 400, "FL tire pressure"),
    "tire_pressure_fr": _ch("tire_pressure_fr", "kPa", 4, "tires", 50, 400, "FR tire pressure"),
    "tire_pressure_rl": _ch("tire_pressure_rl", "kPa", 4, "tires", 50, 400, "RL tire pressure"),
    "tire_pressure_rr": _ch("tire_pressure_rr", "kPa", 4, "tires", 50, 400, "RR tire pressure"),
    "tire_wear_fl":    _ch("tire_wear_fl",    "%",    4, "tires",   0, 100, "FL tire wear"),
    "tire_wear_fr":    _ch("tire_wear_fr",    "%",    4, "tires",   0, 100, "FR tire wear"),
    "tire_wear_rl":    _ch("tire_wear_rl",    "%",    4, "tires",   0, 100, "RL tire wear"),
    "tire_wear_rr":    _ch("tire_wear_rr",    "%",    4, "tires",   0, 100, "RR tire wear"),
    "brake_temp_fl":   _ch("brake_temp_fl",   "°C",   4, "brakes", -20, 1200, "FL brake disc temp"),
    "brake_temp_fr":   _ch("brake_temp_fr",   "°C",   4, "brakes", -20, 1200, "FR brake disc temp"),
    "brake_temp_rl":   _ch("brake_temp_rl",   "°C",   4, "brakes", -20, 1200, "RL brake disc temp"),
    "brake_temp_rr":   _ch("brake_temp_rr",   "°C",   4, "brakes", -20, 1200, "RR brake disc temp"),
    "wheel_speed_fl":  _ch("wheel_speed_fl",  "m/s",  4, "tires",   0, 150, "FL wheel speed"),
    "wheel_speed_fr":  _ch("wheel_speed_fr",  "m/s",  4, "tires",   0, 150, "FR wheel speed"),
    "wheel_speed_rl":  _ch("wheel_speed_rl",  "m/s",  4, "tires",   0, 150, "RL wheel speed"),
    "wheel_speed_rr":  _ch("wheel_speed_rr",  "m/s",  4, "tires",   0, 150, "RR wheel speed"),
    # ── Tier 5: Professional ────────────────────────────────
    "damper_pos_fl":   _ch("damper_pos_fl",   "mm",   5, "aero",   -200, 200, "FL damper position"),
    "damper_pos_fr":   _ch("damper_pos_fr",   "mm",   5, "aero",   -200, 200, "FR damper position"),
    "damper_pos_rl":   _ch("damper_pos_rl",   "mm",   5, "aero",   -200, 200, "RL damper position"),
    "damper_pos_rr":   _ch("damper_pos_rr",   "mm",   5, "aero",   -200, 200, "RR damper position"),
    "ride_height_f":   _ch("ride_height_f",   "mm",   5, "aero",     0, 500, "Front ride height"),
    "ride_height_r":   _ch("ride_height_r",   "mm",   5, "aero",     0, 500, "Rear ride height"),
    "fuel_kg":         _ch("fuel_kg",         "kg",   5, "fuel",     0, 200, "Fuel remaining"),
    "fuel_consumption_rate": _ch("fuel_consumption_rate", "kg/s", 5, "fuel", 0, 1.0, "Fuel flow"),
    "oil_temp":        _ch("oil_temp",        "°C",   5, "engine",  -20, 200, "Oil temperature"),
    "water_temp":      _ch("water_temp",      "°C",   5, "engine",  -20, 150, "Water/coolant temp"),
    "oil_pressure":    _ch("oil_pressure",    "kPa",  5, "engine",    0, 1000, "Oil pressure"),
    "boost_pressure":  _ch("boost_pressure",  "kPa",  5, "engine",    0, 500, "Turbo/SC boost"),
    "slip_angle_fl":   _ch("slip_angle_fl",   "deg",  5, "tires",  -30, 30, "FL slip angle"),
    "slip_angle_fr":   _ch("slip_angle_fr",   "deg",  5, "tires",  -30, 30, "FR slip angle"),
    "slip_angle_rl":   _ch("slip_angle_rl",   "deg",  5, "tires",  -30, 30, "RL slip angle"),
    "slip_angle_rr":   _ch("slip_angle_rr",   "deg",  5, "tires",  -30, 30, "RR slip angle"),
    "slip_ratio_fl":   _ch("slip_ratio_fl",   "",     5, "tires",  -1, 1, "FL slip ratio"),
    "slip_ratio_fr":   _ch("slip_ratio_fr",   "",     5, "tires",  -1, 1, "FR slip ratio"),
    "slip_ratio_rl":   _ch("slip_ratio_rl",   "",     5, "tires",  -1, 1, "RL slip ratio"),
    "slip_ratio_rr":   _ch("slip_ratio_rr",   "",     5, "tires",  -1, 1, "RR slip ratio"),
    "lambda_afr":      _ch("lambda_afr",      "",     5, "engine",  0.5, 2.0, "Air-fuel ratio"),
    "aero_drs":        _ch("aero_drs",        "",     5, "aero",     0, 1, "DRS active"),
    "ers_deploy_pct":  _ch("ers_deploy_pct",  "%",    5, "engine",   0, 100, "ERS deployment"),
    "air_temp":        _ch("air_temp",        "°C",   5, "environment", -40, 60, "Ambient temp"),
    "track_temp":      _ch("track_temp",      "°C",   5, "environment", -20, 80, "Track surface temp"),
}


def get_channels_by_tier(tier: int) -> list[ChannelDef]:
    """Return all channels at the given tier."""
    return [ch for ch in CHANNELS.values() if ch.tier == tier]


def get_channels_by_category(category: str) -> list[ChannelDef]:
    """Return all channels in the given category."""
    return [ch for ch in CHANNELS.values() if ch.category == category]


def validate_channel_value(channel_name: str, value: float) -> bool:
    """Check if a value is within the channel's valid range."""
    ch = CHANNELS.get(channel_name)
    if ch is None:
        return True  # Unknown channels pass validation
    return ch.valid_range[0] <= value <= ch.valid_range[1]


# Tier detection thresholds: which channels must be present for each tier
_TIER_REQUIREMENTS: dict[int, set[str]] = {
    1: {"time_s", "speed_mps"},
    2: {"accel_long_mps2", "accel_lat_mps2"},
    3: set(),  # Any 2 of {throttle, brake, steering, rpm}
    4: set(),  # Any tire_temp_* or wheel_speed_*
    5: set(),  # Any slip_* or damper_* or fuel_*
}

_TIER3_CHANNELS = {"throttle_pct", "brake_pct", "steering_angle_deg", "rpm"}
_TIER4_PREFIXES = ("tire_temp_", "wheel_speed_", "tire_pressure_", "brake_temp_")
_TIER5_PREFIXES = ("slip_angle_", "slip_ratio_", "damper_pos_", "fuel_", "ride_height_")


def detect_data_tier(available_columns: list[str]) -> int:
    """Determine the highest data tier from available canonical column names."""
    cols = set(available_columns)

    # Tier 1: must have time + speed
    if not cols.issuperset(_TIER_REQUIREMENTS[1]):
        return 0  # Insufficient data

    tier = 1

    # Tier 2: need acceleration data
    if cols.issuperset(_TIER_REQUIREMENTS[2]):
        tier = 2

    # Tier 3: need 2+ control channels
    if tier >= 2 and len(cols & _TIER3_CHANNELS) >= 2:
        tier = 3

    # Tier 4: need any tire temp or wheel speed
    if tier >= 3 and any(c for c in cols if any(c.startswith(p) for p in _TIER4_PREFIXES)):
        tier = 4

    # Tier 5: need any slip, damper, or fuel data
    if tier >= 4 and any(c for c in cols if any(c.startswith(p) for p in _TIER5_PREFIXES)):
        tier = 5

    return tier
```

**Step 4: Run tests**

Run: `cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_channel_registry.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/channel_registry.py telemetry_tool/tests/test_channel_registry.py
git commit -m "feat: add channel registry with 70+ canonical telemetry channels and tier detection"
```

---

### Task 2: Base Adapter Interface

**Files:**
- Create: `telemetry_tool/adapters/__init__.py`
- Create: `telemetry_tool/adapters/base.py`
- Create: `telemetry_tool/adapters/registry.py`
- Test: `telemetry_tool/tests/test_adapter_base.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_adapter_base.py
"""Tests for the adapter base class and format detection registry."""
import pandas as pd
import pytest
from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.registry import detect_format, register_adapter


class MockAdapter(BaseAdapter):
    """Test adapter that recognizes files with 'MOCK' in first line."""
    FORMAT_NAME = "mock"

    @staticmethod
    def detect(file_path: str) -> float:
        try:
            with open(file_path, "r") as f:
                return 1.0 if "MOCK" in f.readline() else 0.0
        except Exception:
            return 0.0

    def parse(self, file_path, progress_cb=None):
        return pd.DataFrame({"time_s": [0, 1, 2], "speed_mps": [0, 10, 20]})

    def metadata(self):
        return {"source": "mock"}

    def available_channels(self):
        return ["time_s", "speed_mps"]


def test_base_adapter_is_abstract():
    with pytest.raises(TypeError):
        BaseAdapter()


def test_mock_adapter_detect(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text("MOCK header\n1,2,3")
    adapter = MockAdapter()
    assert adapter.detect(str(f)) == 1.0


def test_mock_adapter_parse(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text("MOCK header\n1,2,3")
    adapter = MockAdapter()
    df = adapter.parse(str(f))
    assert "time_s" in df.columns
    assert "speed_mps" in df.columns
    assert len(df) == 3


def test_mock_adapter_data_tier(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text("MOCK header\n1,2,3")
    adapter = MockAdapter()
    adapter.parse(str(f))
    assert adapter.data_tier() == 1


def test_format_detection(tmp_path):
    register_adapter(MockAdapter)
    f = tmp_path / "test.csv"
    f.write_text("MOCK header\n1,2,3")
    adapter_cls, confidence = detect_format(str(f))
    assert adapter_cls == MockAdapter
    assert confidence == 1.0


def test_format_detection_no_match(tmp_path):
    f = tmp_path / "unknown.xyz"
    f.write_text("totally unknown format")
    adapter_cls, confidence = detect_format(str(f))
    assert confidence < 0.5 or adapter_cls is None
```

**Step 2: Run test — expect FAIL**

**Step 3: Write implementation**

```python
# telemetry_tool/adapters/__init__.py
"""Universal telemetry format adapters."""
from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.registry import detect_format, register_adapter, parse_file

__all__ = ["BaseAdapter", "detect_format", "register_adapter", "parse_file"]
```

```python
# telemetry_tool/adapters/base.py
"""Base adapter interface for telemetry format parsers."""
from __future__ import annotations

import abc
from typing import Any

import pandas as pd

from telemetry_tool.channel_registry import detect_data_tier


class BaseAdapter(abc.ABC):
    """Abstract base class for all format adapters."""

    FORMAT_NAME: str = "unknown"

    @staticmethod
    @abc.abstractmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that this adapter can handle the file."""

    @abc.abstractmethod
    def parse(self, file_path: str, progress_cb=None) -> pd.DataFrame:
        """Parse file into a canonical DataFrame with registry column names."""

    @abc.abstractmethod
    def metadata(self) -> dict[str, Any]:
        """Return session metadata (car, track, date, driver, conditions)."""

    @abc.abstractmethod
    def available_channels(self) -> list[str]:
        """Which canonical channels are present after parsing."""

    def data_tier(self) -> int:
        """Highest complete data tier based on available channels."""
        return detect_data_tier(self.available_channels())
```

```python
# telemetry_tool/adapters/registry.py
"""Format detection registry — routes files to the correct adapter."""
from __future__ import annotations

import logging
from typing import Type

import pandas as pd

from telemetry_tool.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

_ADAPTERS: list[Type[BaseAdapter]] = []


def register_adapter(adapter_cls: Type[BaseAdapter]) -> None:
    """Register an adapter class for format detection."""
    if adapter_cls not in _ADAPTERS:
        _ADAPTERS.append(adapter_cls)


def detect_format(file_path: str) -> tuple[Type[BaseAdapter] | None, float]:
    """Run all registered adapters' detect() and return best match."""
    best_cls = None
    best_conf = 0.0

    for cls in _ADAPTERS:
        try:
            conf = cls.detect(file_path)
            if conf > best_conf:
                best_conf = conf
                best_cls = cls
        except Exception as exc:
            logger.debug("Adapter %s.detect() failed: %s", cls.FORMAT_NAME, exc)

    if best_conf < 0.5:
        return None, best_conf

    return best_cls, best_conf


def parse_file(file_path: str, progress_cb=None) -> tuple[pd.DataFrame, BaseAdapter]:
    """Detect format and parse file. Raises ValueError if no adapter matches."""
    adapter_cls, confidence = detect_format(file_path)
    if adapter_cls is None:
        raise ValueError(
            f"No adapter recognized file: {file_path} (best confidence: {confidence:.2f})"
        )
    logger.info("Detected format: %s (confidence=%.2f)", adapter_cls.FORMAT_NAME, confidence)
    adapter = adapter_cls()
    df = adapter.parse(file_path, progress_cb=progress_cb)
    return df, adapter
```

**Step 4: Run tests — expect PASS**
**Step 5: Commit**

```bash
git add telemetry_tool/adapters/ telemetry_tool/tests/test_adapter_base.py
git commit -m "feat: add base adapter interface and format detection registry"
```

---

### Task 3: RaceChrono Adapter (refactor existing code)

**Files:**
- Create: `telemetry_tool/adapters/racechrono_adapter.py`
- Modify: `telemetry_tool/pipeline.py:640-645` (use adapter registry instead of direct io_racechrono call)
- Test: `telemetry_tool/tests/test_racechrono_adapter.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_racechrono_adapter.py
"""Tests for the RaceChrono format adapter."""
import textwrap
import pytest
from telemetry_tool.adapters.racechrono_adapter import RaceChronoAdapter


@pytest.fixture
def racechrono_csv(tmp_path):
    content = textwrap.dedent("""\
        Session: Test
        Date: 2024-01-15
        Time (s),Speed (m/s),Latitude (deg),Longitude (deg),Distance (m),Lap #,Longitudinal acceleration (G) *calc,Lateral acceleration (G) *calc
        0.0,0.0,45.123,-73.456,0.0,1,0.0,0.0
        0.1,5.0,45.124,-73.457,0.5,1,0.5,0.1
        0.2,10.0,45.125,-73.458,1.5,1,0.3,0.2
    """)
    f = tmp_path / "session.csv"
    f.write_text(content)
    return str(f)


def test_detect_racechrono(racechrono_csv):
    assert RaceChronoAdapter.detect(racechrono_csv) > 0.8


def test_detect_non_racechrono(tmp_path):
    f = tmp_path / "other.csv"
    f.write_text("Speed,Throttle,Brake\n100,50,0\n")
    assert RaceChronoAdapter.detect(str(f)) < 0.5


def test_parse_returns_canonical_columns(racechrono_csv):
    adapter = RaceChronoAdapter()
    df = adapter.parse(racechrono_csv)
    # Must produce canonical column names
    assert "time_s" in df.columns or "Time (s)" in df.columns
    assert len(df) == 3


def test_available_channels(racechrono_csv):
    adapter = RaceChronoAdapter()
    adapter.parse(racechrono_csv)
    channels = adapter.available_channels()
    assert "time_s" in channels or "speed_mps" in channels


def test_data_tier_basic(racechrono_csv):
    adapter = RaceChronoAdapter()
    adapter.parse(racechrono_csv)
    # Should be at least tier 1 (has time + speed + GPS)
    assert adapter.data_tier() >= 1
```

**Step 2: Run test — expect FAIL**

**Step 3: Implement RaceChrono adapter**

The adapter wraps the existing `io_racechrono.read_racechrono_csv()` function and maps its output to canonical names. It delegates actual CSV parsing to the battle-tested existing code rather than reimplementing it.

Key implementation details:
- `detect()`: Read first 100 lines, check for RaceChrono header sentinels (`Time (s)`, `Time`, `UTC Time`)
- `parse()`: Call `io_racechrono.read_racechrono_csv(path)`, then apply canonical column rename from `kart_envelope/ingest/columns.py` _RAW_MAP
- `metadata()`: Extract RaceChrono metadata from pre-header rows
- `available_channels()`: Map parsed columns to canonical names, filter against channel_registry

**Step 4: Run tests — expect PASS**
**Step 5: Commit**

```bash
git add telemetry_tool/adapters/racechrono_adapter.py telemetry_tool/tests/test_racechrono_adapter.py
git commit -m "feat: add RaceChrono adapter wrapping existing CSV parser"
```

---

### Task 4: iRacing Adapter

**Files:**
- Create: `telemetry_tool/adapters/iracing_adapter.py`
- Test: `telemetry_tool/tests/test_iracing_adapter.py`

**Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_iracing_adapter.py
"""Tests for the iRacing telemetry adapter (CSV export mode)."""
import textwrap
import pytest
from telemetry_tool.adapters.iracing_adapter import IRacingAdapter


@pytest.fixture
def iracing_csv(tmp_path):
    """Simulated iRacing CSV export with typical columns."""
    content = textwrap.dedent("""\
        Lap,LapDist,Speed,Throttle,Brake,Clutch,Gear,RPM,SteeringWheelAngle,Lat,Lon,Alt,LatAccel,LonAccel,YawRate,LFtempCL,LFtempCM,LFtempCR,RFtempCL,RFtempCM,RFtempCR,LRtempCL,LRtempCM,LRtempCR,RRtempCL,RRtempCM,RRtempCR,LFpressure,RFpressure,LRpressure,RRpressure,FuelLevel,LFspd,RFspd,LRspd,RRspd
        1,0.0,0.0,0.0,0.0,0.0,1,800,-0.5,45.123,-73.456,100.0,0.0,0.0,0.0,80.0,82.0,79.0,81.0,83.0,80.0,78.0,80.0,77.0,79.0,81.0,78.0,172.0,172.0,165.0,165.0,45.2,0.0,0.0,0.0,0.0
        1,10.5,22.3,100.0,0.0,0.0,2,4500,2.1,45.124,-73.457,100.1,0.3,5.2,1.2,82.0,84.0,81.0,83.0,85.0,82.0,80.0,82.0,79.0,81.0,83.0,80.0,174.0,174.0,167.0,167.0,45.1,22.1,22.4,22.2,22.5
        1,25.0,33.5,80.0,0.0,0.0,3,5200,-1.3,45.125,-73.458,100.2,-0.5,2.1,-0.8,84.0,86.0,83.0,85.0,87.0,84.0,82.0,84.0,81.0,83.0,85.0,82.0,176.0,176.0,169.0,169.0,45.0,33.3,33.6,33.4,33.7
    """)
    f = tmp_path / "iracing_export.csv"
    f.write_text(content)
    return str(f)


def test_detect_iracing_csv(iracing_csv):
    assert IRacingAdapter.detect(iracing_csv) > 0.8


def test_parse_maps_canonical_columns(iracing_csv):
    adapter = IRacingAdapter()
    df = adapter.parse(iracing_csv)
    assert "throttle_pct" in df.columns
    assert "brake_pct" in df.columns
    assert "rpm" in df.columns
    assert "gear" in df.columns
    assert "steering_angle_deg" in df.columns
    assert "tire_temp_fl_i" in df.columns  # LFtempCL → inner
    assert "tire_temp_fl_m" in df.columns  # LFtempCM → mid
    assert "tire_temp_fl_o" in df.columns  # LFtempCR → outer
    assert "fuel_kg" in df.columns
    assert "wheel_speed_fl" in df.columns


def test_data_tier_iracing(iracing_csv):
    adapter = IRacingAdapter()
    adapter.parse(iracing_csv)
    # iRacing has controls + tire temps + wheel speeds + fuel → tier 5
    assert adapter.data_tier() >= 4


def test_tire_temp_zone_mapping(iracing_csv):
    """iRacing uses CL/CM/CR (center-left, center-mid, center-right)
    which maps to inner/mid/outer depending on which side of the car."""
    adapter = IRacingAdapter()
    df = adapter.parse(iracing_csv)
    # FL: CL=outer, CM=mid, CR=inner (left side: CL is outboard)
    # Wait — iRacing CL/CM/CR naming is: CL=left, CM=center, CR=right
    # For left-side tires: L=inner (close to car), R=outer
    # For right-side tires: L=outer, R=inner
    assert df["tire_temp_fl_o"].iloc[0] == 80.0  # LFtempCL → FL outer
    assert df["tire_temp_fl_m"].iloc[0] == 82.0  # LFtempCM → FL mid
    assert df["tire_temp_fl_i"].iloc[0] == 79.0  # LFtempCR → FL inner
```

**Step 2: Run test — expect FAIL**

**Step 3: Implement iRacing adapter**

Key column mapping (iRacing CSV → canonical):
- `Lap` → `lap_number`, `LapDist` → `distance_m`, `Speed` → `speed_mps` (convert from m/s, iRacing already in m/s)
- `Throttle` → `throttle_pct` (0-100), `Brake` → `brake_pct` (0-100)
- `SteeringWheelAngle` → `steering_angle_deg` (radians → degrees: × 180/π)
- `RPM` → `rpm`, `Gear` → `gear`, `Clutch` → `clutch_pct`
- `Lat`/`Lon`/`Alt` → `lat_deg`/`lon_deg`/`altitude_m`
- `LatAccel` → `accel_lat_mps2`, `LonAccel` → `accel_long_mps2`, `YawRate` → `yaw_rate_dps`
- `LFtempCL/CM/CR` → `tire_temp_fl_o/m/i` (left-side: CL=outer, CR=inner)
- `RFtempCL/CM/CR` → `tire_temp_fr_i/m/o` (right-side: CL=inner, CR=outer)
- `LRtempCL/CM/CR` → `tire_temp_rl_o/m/i`, `RRtempCL/CM/CR` → `tire_temp_rr_i/m/o`
- `LFpressure` → `tire_pressure_fl` (kPa), etc.
- `FuelLevel` → `fuel_kg` (convert from liters if needed)
- `LFspd/RFspd/LRspd/RRspd` → `wheel_speed_fl/fr/rl/rr`

The adapter also handles `.ibt` binary files: if the `pyibt` library is installed, it can parse iRacing's native binary telemetry format directly. If not installed, it falls back to CSV-only support and logs a warning.

Detection: check for `Lap` + `Speed` + `Throttle` + `Brake` in header (CSV mode), or IBT magic bytes (binary mode).

Time synthesis: iRacing CSV doesn't always have a `Time` column. Synthesize from row index × sample period (typically 1/60s = 0.01667s at 60Hz).

**Step 4: Run tests — expect PASS**
**Step 5: Commit**

```bash
git add telemetry_tool/adapters/iracing_adapter.py telemetry_tool/tests/test_iracing_adapter.py
git commit -m "feat: add iRacing adapter for CSV export + IBT binary"
```

---

### Task 5: ACC Adapter

**Files:**
- Create: `telemetry_tool/adapters/acc_adapter.py`
- Test: `telemetry_tool/tests/test_acc_adapter.py`

Similar structure to iRacing adapter. ACC-specific column mapping:
- `speedKmh` → `speed_mps` (÷3.6), `gas` → `throttle_pct` (×100), `brake` → `brake_pct` (×100)
- `steerAngle` → `steering_angle_deg`, `rpms` → `rpm`, `gear` → `gear`
- `tyreTempI`/`tyreTempM`/`tyreTempO` (arrays of 4) → 12-zone tire temps
- `tyrePressure` (array of 4) → tire pressures
- `brakeTemp` (array of 4) → brake temps
- `wheelSlip` (array of 4) → slip ratios

Detection: header contains `speedKmh` or `gas` + `brake` + `steerAngle`.

**Commit:** `feat: add ACC adapter for telemetry CSV/JSON export`

---

### Task 6: MoTeC CSV Adapter

**Files:**
- Create: `telemetry_tool/adapters/motec_adapter.py`
- Test: `telemetry_tool/tests/test_motec_adapter.py`

MoTeC CSV export has variable column names depending on setup. Common pattern:
- `Engine RPM` → `rpm`, `Throttle Pos` or `Throttle Position` → `throttle_pct`
- `Brake Press` or `Brake Pressure` → `brake_pct` (may need normalization)
- `Steer Angle` → `steering_angle_deg`
- `Ground Speed` → `speed_mps`, `GPS Lat`/`GPS Long` → position
- Wheel speeds, damper positions, temperatures all variably named

Detection: header contains `Beacon` or `Lap_Number` + `Engine_RPM` pattern. Also supports `.ld` binary via `ldparser` library (optional dependency).

**Commit:** `feat: add MoTeC adapter for CSV and LD binary formats`

---

### Task 7: Generic CSV Adapter (fuzzy fallback)

**Files:**
- Create: `telemetry_tool/adapters/generic_csv_adapter.py`
- Test: `telemetry_tool/tests/test_generic_csv_adapter.py`

This adapter uses fuzzy string matching against the channel registry to map unknown column names. It handles:
- F1 game exports (`m_speed`, `m_throttle`, `m_steer`)
- AiM CSV exports (`RPM`, `GPS_Speed`, `G_Force_Lat`)
- OBD-II logger exports (`Engine RPM`, `Vehicle Speed`, `Throttle Position (%)`)
- VBOX exports after the header block
- Any other CSV with recognizable column names

Fuzzy matching rules:
1. Exact canonical name match
2. Case-insensitive match with common suffixes stripped (`(m/s)`, `(%)`, `(deg)`)
3. Keyword matching (`"speed"` in any column → `speed_mps` candidate, `"throttle"` → `throttle_pct`)
4. Unit-based disambiguation: if multiple speed columns, prefer `m/s` over `km/h` or `mph`

Always returns confidence < 0.8 (so format-specific adapters win when available).

**Commit:** `feat: add generic CSV adapter with fuzzy column matching`

---

### Task 8: Wire Adapters into Pipeline

**Files:**
- Modify: `telemetry_tool/pipeline.py:640-645` (replace `io_mod.read_racechrono_csv(csv_path)` with adapter-based parsing)
- Modify: `telemetry_tool/web/routes/sessions_v2.py` (accept `.ibt`, `.ld`, `.vbo` file extensions)
- Test: `telemetry_tool/tests/test_pipeline_adapter_integration.py`

**Step 1: Write failing test**

```python
# telemetry_tool/tests/test_pipeline_adapter_integration.py
"""Test that the pipeline uses the adapter registry for ingestion."""
import textwrap
import pytest


def test_pipeline_accepts_iracing_csv(tmp_path):
    """Pipeline should detect and parse iRacing format automatically."""
    content = textwrap.dedent("""\
        Lap,LapDist,Speed,Throttle,Brake,Gear,RPM,SteeringWheelAngle,Lat,Lon,Alt,LatAccel,LonAccel,YawRate
        1,0.0,0.0,0.0,0.0,1,800,-0.5,45.123,-73.456,100.0,0.0,0.0,0.0
        1,10.5,22.3,100.0,0.0,2,4500,2.1,45.124,-73.457,100.1,0.3,5.2,1.2
    """)
    f = tmp_path / "iracing.csv"
    f.write_text(content)

    from telemetry_tool.adapters import parse_file
    df, adapter = parse_file(str(f))
    assert adapter.FORMAT_NAME == "iracing"
    assert "throttle_pct" in df.columns
```

**Step 2: Run — expect FAIL**

**Step 3: Modify pipeline.py ingest stage**

In `pipeline.py` around line 640, replace the direct `io_racechrono` call with:

```python
def _ingest() -> pd.DataFrame:
    # Try adapter registry first (handles all formats)
    try:
        from telemetry_tool.adapters import parse_file
        df, adapter = parse_file(csv_path, progress_cb=progress_callback)
        summary["source_format"] = adapter.FORMAT_NAME
        summary["available_channels"] = adapter.available_channels()
        summary["data_tier"] = adapter.data_tier()
        summary["source_metadata"] = adapter.metadata()
        return df
    except (ValueError, ImportError):
        pass

    # Fallback to original RaceChrono reader
    if io_mod is None:
        raise ImportError("No adapter matched and io_racechrono unavailable")
    return io_mod.read_racechrono_csv(csv_path)
```

Also modify `sessions_v2.py` upload endpoint to accept new extensions:
- Current: likely checks for `.csv` only
- Add: `.ibt`, `.ld`, `.ldx`, `.vbo`, `.xrk`, `.drk`

**Step 4: Run tests — expect PASS**
**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/web/routes/sessions_v2.py telemetry_tool/tests/test_pipeline_adapter_integration.py
git commit -m "feat: wire adapter registry into pipeline and upload endpoint"
```

---

## Phase 2: New Data Endpoints + Frontend Charts

### Task 9: Data Endpoints for Rich Channels

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (add 7 new endpoints)
- Test: `telemetry_tool/tests/test_data_v2_channels.py`

New endpoints (all follow existing pattern in data_v2.py):

```python
# GET /api/v1/sessions/<id>/channels
# Returns: {"available": ["throttle_pct", "brake_pct", ...], "tier": 3}

# GET /api/v1/sessions/<id>/pedals?lap=N
# Returns: {"distances": [...], "throttle": [...], "brake": [...], "steering": [...]}

# GET /api/v1/sessions/<id>/tire-temps?lap=N
# Returns: {"distances": [...], "fl": {"i": [...], "m": [...], "o": [...]}, ...}

# GET /api/v1/sessions/<id>/wheel-slip?lap=N
# Returns: {"distances": [...], "fl_ratio": [...], "fr_ratio": [...], ...}

# GET /api/v1/sessions/<id>/rpm-gear?lap=N
# Returns: {"distances": [...], "rpm": [...], "gear": [...], "speeds": [...]}

# GET /api/v1/sessions/<id>/brake-temps?lap=N
# Returns: {"distances": [...], "fl": [...], "fr": [...], "rl": [...], "rr": [...]}

# GET /api/v1/sessions/<id>/fuel
# Returns: {"laps": [...], "fuel_remaining": [...], "consumption_rate": [...]}
```

All endpoints check `available_channels` and return `{"available": false, "message": "..."}` when required channels are absent.

**Commit:** `feat: add 7 data endpoints for rich telemetry channels`

---

### Task 10: PedalTraceChart

**Files:**
- Create: `lap-website/src/components/shared/charts/PedalTraceChart.tsx`
- Modify: `lap-website/src/components/app/analytics/AnalyticsTab.tsx` (add component)
- No test file (canvas chart — tested via build + visual QA)

React canvas component following the same pattern as `DeltaTimeChart.tsx`:
- Fetch from `/sessions/{id}/pedals?lap=N` via `apiFetch`
- Three traces: throttle (green fill 0-100%), brake (red fill 0-100%), steering (blue line ±deg, right Y axis)
- Trail braking zones highlighted (where brake > 5% AND |steering| > 10deg simultaneously)
- Lap selector dropdown
- Full `useChartHoverStore` integration
- Canvas rendering with DPR scaling, grid, axis labels, crosshair, tooltip

**Commit:** `feat: add PedalTraceChart component for throttle/brake/steering overlay`

---

### Task 11: TireHeatmapChart

**Files:**
- Create: `lap-website/src/components/shared/charts/TireHeatmapChart.tsx`
- Modify: `lap-website/src/components/app/analytics/AnalyticsTab.tsx`

2x2 grid of tire visualizations:
- Each tire rendered as a rounded rectangle
- Color fill: blue (<60°C) → green (optimal ~80-100°C) → yellow → red (>120°C)
- If 12-zone data: three vertical strips per tire (inner/mid/outer)
- If 4-corner only: single color per tire
- Cross-car balance indicators: FL-FR delta, RL-RR delta, F-R average delta
- Lap selector for thermal evolution over session
- Does NOT need hover sync (static per-lap view, not distance-based)

**Commit:** `feat: add TireHeatmapChart component for 4-corner/12-zone tire temps`

---

### Task 12: RPMGearChart

**Files:**
- Create: `lap-website/src/components/shared/charts/RPMGearChart.tsx`
- Modify: `lap-website/src/components/app/analytics/AnalyticsTab.tsx`

Canvas chart:
- RPM trace on distance axis, colored by gear (gear 1=blue, 2=cyan, 3=green, 4=yellow, 5=orange, 6=red, 7=magenta)
- Shift points marked with vertical tick lines
- Speed as thin gray overlay on right Y axis
- Full `useChartHoverStore` integration
- Tooltip shows RPM, gear, speed at hover distance

**Commit:** `feat: add RPMGearChart component for engine RPM and gear trace`

---

### Task 13: LiveFrictionCircle

**Files:**
- Create: `lap-website/src/components/shared/charts/LiveFrictionCircle.tsx`
- Modify: `lap-website/src/components/app/analytics/AnalyticsTab.tsx`

Enhanced GG diagram:
- Scatter dots colored by input: green (throttle > 20%), red (brake > 5%), yellow (throttle+brake overlap), blue (coast)
- Theoretical grip circle overlay (from scoring data)
- Grip utilization percentage label
- `useChartHoverStore` integration: when hovering speed trace at distance D, highlight the corresponding dot on the friction circle with a larger marker
- Lap selector

**Commit:** `feat: add LiveFrictionCircle with input-colored GG diagram`

---

### Task 14: WheelSlipChart + BrakeAnalysisChart + FuelStrategyChart

**Files:**
- Create: `lap-website/src/components/shared/charts/WheelSlipChart.tsx`
- Create: `lap-website/src/components/shared/charts/BrakeAnalysisChart.tsx`
- Create: `lap-website/src/components/shared/charts/FuelStrategyChart.tsx`
- Modify: `lap-website/src/components/app/analytics/AnalyticsTab.tsx`

Three smaller charts following the established canvas pattern:
- **WheelSlipChart**: 4 traces (FL/FR/RL/RR slip ratio) on distance. Lockup events (<-0.15) highlighted red. Wheelspin (>0.10) highlighted orange.
- **BrakeAnalysisChart**: Brake pressure trace + optional 4 brake temp traces. Fade zones highlighted.
- **FuelStrategyChart**: Fuel remaining vs lap number. Consumption rate per lap. Projected fuel-out line.

**Commit:** `feat: add WheelSlipChart, BrakeAnalysisChart, FuelStrategyChart`

---

### Task 15: Wire All Charts into AnalyticsTab with Channel Detection

**Files:**
- Modify: `lap-website/src/components/app/analytics/AnalyticsTab.tsx`
- Create: `lap-website/src/hooks/useSessionChannels.ts`

Create a hook that fetches `/sessions/{id}/channels` to know which channels are available:

```typescript
// src/hooks/useSessionChannels.ts
export function useSessionChannels(sessionId: string) {
  // Fetch available channels and tier from backend
  // Returns { channels: string[], tier: number, loading: boolean }
}
```

In AnalyticsTab, conditionally render new charts based on channel availability:

```tsx
{/* Only show if controls data available (tier >= 3) */}
{tier >= 3 && (
  <PedalTraceChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} />
)}

{/* Only show if tire temp data available (tier >= 4) */}
{channels.includes("tire_temp_fl") && (
  <TireHeatmapChart sessionId={sessionId} gpsLaps={gpsLaps} />
)}
```

Charts that lack data show a styled placeholder:
```tsx
<div className="text-steel/60 text-sm text-center p-6 border border-dashed border-steel/20 rounded-lg">
  <p className="font-telemetry text-chalk mb-1">Pedal Traces</p>
  <p>Requires throttle & brake data — available in iRacing, ACC, and MoTeC formats</p>
</div>
```

**Commit:** `feat: wire all charts into AnalyticsTab with channel-aware rendering`

---

## Phase 3: Progressive Physics Engine

### Task 16: Tier 2 Controls Physics — Brake Model

**Files:**
- Create: `telemetry_tool/physics/__init__.py`
- Create: `telemetry_tool/physics/controls_physics.py`
- Test: `telemetry_tool/tests/test_controls_physics.py`

When `brake_pct` is available:
- **Brake point detection**: Find exact distance where `brake_pct` crosses threshold (e.g., 5%), replacing the current `accel_long < -1.0` heuristic
- **Trail braking measurement**: Compute overlap between `brake_pct > 5%` and `|steering_angle_deg| > threshold` per corner
- **Brake modulation quality**: Variance of brake profiles across repeated corners (lower = more consistent)
- **Peak brake pressure**: Per-corner maximum brake_pct

Functions:
```python
def detect_brake_points(distances, brake_pct, threshold=5.0) -> list[float]:
    """Return distances where braking begins."""

def measure_trail_braking(distances, brake_pct, steering_deg, corners) -> list[dict]:
    """For each corner, compute trail_brake_pct and duration."""

def score_brake_modulation(laps_brake_profiles: list, corners) -> float:
    """Score 0-1 for brake consistency across laps at each corner."""
```

**Commit:** `feat: add Tier 2 brake model using actual brake pressure data`

---

### Task 17: Tier 2 Controls Physics — Throttle + Steering Models

**Files:**
- Modify: `telemetry_tool/physics/controls_physics.py` (add throttle and steering functions)
- Test: `telemetry_tool/tests/test_controls_physics.py` (extend)

Throttle model:
- **Application rate**: How quickly throttle goes from 0→100% on corner exit (degrees/second)
- **Hesitation detection**: Zones where throttle < 20% but accel demand is available
- **Coasting detection**: Zones where throttle = 0 AND brake = 0

Steering model:
- **Over/understeer ratio**: Compare actual yaw_rate to expected yaw from steering input at given speed
- **Correction frequency**: Count steering reversals per corner (high = fighting the car)
- **Smoothness**: High-frequency noise in steering signal

**Commit:** `feat: add Tier 2 throttle and steering analysis models`

---

### Task 18: Tier 2 — Power Curve from RPM

**Files:**
- Modify: `telemetry_tool/physics/controls_physics.py`
- Test: `telemetry_tool/tests/test_controls_physics.py`

When `rpm` + `throttle_pct` + `speed_mps` are available:
- Fit engine torque map: T(RPM) from observed (RPM, accel_long) at full throttle
- Convert to power: P(RPM) = T × ω = T × RPM × 2π/60
- Identify optimal shift RPM (where P(RPM) peaks)
- Shift quality score: how close actual shift RPMs are to optimal

This replaces the current speed-only power envelope with an RPM-resolved curve.

**Commit:** `feat: add RPM-resolved power curve fitting for Tier 2 physics`

---

### Task 19: Tier 3 — Tire Thermal Model

**Files:**
- Create: `telemetry_tool/physics/tire_thermal.py`
- Test: `telemetry_tool/tests/test_tire_thermal.py`

```python
def compute_grip_factor(tire_temp: float, optimal_low: float, optimal_high: float,
                        k_cold: float = 0.005, k_hot: float = 0.008) -> float:
    """Grip multiplier based on tire temperature.
    Returns 1.0 at optimal, <1.0 when cold or overheated."""

def detect_optimal_window(distances_list, tire_temps_list, grip_proxy_list) -> tuple[float, float]:
    """Find optimal temperature range by correlating tire temp with grip (lateral accel)."""

def compute_thermal_balance(fl, fr, rl, rr) -> dict:
    """Compute cross-car and front-rear thermal balance."""

def analyze_camber_from_zones(inner, mid, outer) -> str:
    """Classify camber: 'optimal', 'too_much', 'too_little' from 3-zone temps."""

def predict_tire_degradation(lap_temps: list[dict]) -> dict:
    """From per-lap tire temps, predict degradation rate and remaining grip window."""
```

**Commit:** `feat: add Tier 3 tire thermal model with grip factor and degradation prediction`

---

### Task 20: Tier 3 — Wheel Slip + Fuel Models

**Files:**
- Create: `telemetry_tool/physics/slip_model.py`
- Create: `telemetry_tool/physics/fuel_model.py`
- Test: `telemetry_tool/tests/test_slip_model.py`
- Test: `telemetry_tool/tests/test_fuel_model.py`

Slip model:
```python
def compute_slip_ratios(wheel_speeds_4, vehicle_speed) -> dict:
    """Compute slip ratio for each wheel: (ws - vs) / max(ws, vs)."""

def detect_lockups(slip_ratios, threshold=-0.15) -> list[dict]:
    """Find lockup events: distance, duration, severity."""

def detect_wheelspin(slip_ratios, threshold=0.10) -> list[dict]:
    """Find wheelspin events: distance, duration, severity."""
```

Fuel model:
```python
def compute_fuel_corrected_pace(lap_times, fuel_levels) -> list[float]:
    """Normalize lap times to account for fuel weight change."""

def predict_fuel_remaining(fuel_history, target_laps) -> float:
    """Linear extrapolation of fuel consumption to predict remaining."""
```

**Commit:** `feat: add Tier 3 slip and fuel models`

---

### Task 21: Integrate Progressive Physics into Pipeline

**Files:**
- Modify: `telemetry_tool/pipeline.py` (after stage 09d, add progressive physics stages)
- Modify: `telemetry_tool/scoring.py:_score_execution` (use real brake/throttle when available)

In pipeline.py, after vehicle classification:
```python
# -- 09e: Progressive physics (tier 2+) --
data_tier = summary.get("data_tier", 1)
if data_tier >= 2:
    from telemetry_tool.physics import controls_physics
    # Run brake/throttle/steering analysis per lap
    ...

if data_tier >= 3:
    from telemetry_tool.physics import tire_thermal, slip_model, fuel_model
    # Run thermal, slip, fuel models
    ...
```

In scoring.py, modify `_score_execution()` to use real data when available:
```python
# Current: infer trail braking from accel_long overlap with lateral accel
# Tier 2+: use actual brake_pct overlap with steering_angle_deg
if "brake_points" in corner_analysis:
    trail_brake_score = _score_trail_braking_from_pedals(corner_analysis)
else:
    trail_brake_score = _score_trail_braking_from_accel(corner_analysis)  # current code
```

**Commit:** `feat: integrate progressive physics into pipeline and scoring`

---

## Phase 4: Database + Deployment

### Task 22: Alembic Migration for Channel Metadata

**Files:**
- Create: `alembic/versions/017_add_telemetry_channels.py`

```python
def upgrade():
    op.add_column('sessions', sa.Column('data_tier', sa.Integer(), server_default='1'))
    op.add_column('sessions', sa.Column('available_channels', sa.JSON(), server_default='[]'))
    op.add_column('sessions', sa.Column('source_format', sa.String(32), server_default='racechrono'))
    op.add_column('sessions', sa.Column('source_metadata', sa.JSON(), server_default='{}'))
```

**Commit:** `feat: add migration 017 for telemetry channel metadata columns`

---

### Task 23: Persist Channel Metadata on Upload

**Files:**
- Modify: `telemetry_tool/web/routes/sessions_v2.py` (save data_tier, available_channels, source_format after pipeline runs)
- Modify: `telemetry_tool/web/routes/data_v2.py` (read available_channels to serve /channels endpoint)

After pipeline completes in the upload handler:
```python
# Save channel metadata to session record
conn.execute(
    "UPDATE sessions SET data_tier = %(tier)s, available_channels = %(channels)s, "
    "source_format = %(fmt)s, source_metadata = %(meta)s WHERE id = %(id)s",
    {"tier": summary.get("data_tier", 1),
     "channels": json.dumps(summary.get("available_channels", [])),
     "fmt": summary.get("source_format", "racechrono"),
     "meta": json.dumps(summary.get("source_metadata", {})),
     "id": session_id}
)
```

**Commit:** `feat: persist channel metadata on session upload`

---

### Task 24: Build + Test Full Stack

**Step 1:** Run all backend tests
```bash
cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai
python -m pytest telemetry_tool/tests/ -v --tb=short
```

**Step 2:** Build frontend
```bash
cd lap-website && npm run build
```

**Step 3:** Run frontend lint
```bash
npm run lint
```

**Step 4:** Commit any fixes, then final commit
```bash
git add -A
git commit -m "chore: final integration pass — all tests green, build clean"
```

---

## Summary: Implementation Order

| Phase | Tasks | Deliverable |
|-------|-------|-------------|
| **1: Foundation** | 1-8 | Channel registry, base adapter, RaceChrono/iRacing/ACC/MoTeC/generic adapters, pipeline wiring |
| **2: Frontend** | 9-15 | 7 new data endpoints, 7 new chart components, channel-aware AnalyticsTab |
| **3: Physics** | 16-21 | Tier 2 brake/throttle/steering/RPM models, Tier 3 tire/slip/fuel models, scoring enhancements |
| **4: Database** | 22-24 | Migration, persistence, full-stack test |

**Estimated tasks:** 24
**Dependencies:** Phase 1 before Phase 2-3. Phase 2 and Phase 3 can run in parallel. Phase 4 after both.
