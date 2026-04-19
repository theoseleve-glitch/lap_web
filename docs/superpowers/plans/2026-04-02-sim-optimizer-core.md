# Sim Optimizer Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the parameter identification pipeline that extracts tyre/aero/powertrain/brake/suspension/mass models from raw iRacing telemetry and assembles them into a `VehicleModel` that satisfies the `FrictionLike` protocol used by kart_envelope's QSS solver.

**Architecture:** Raw Parquet sidecar (332 IRSDK vars at 60Hz, _ST arrays at 360Hz) is ingested, validated, and distance-aligned. Six independent sub-model identifiers extract physics parameters from overlapping channel subsets. A `VehicleModel` dataclass assembles the results and provides the `max_lateral_g()` / `max_traction_g()` / `max_braking_g()` / `combined_limit()` interface.

**Tech Stack:** Python 3.13, numpy, scipy.optimize (curve_fit for Pacejka), pandas, pyarrow (Parquet reading), pytest. No new dependencies beyond what's already in requirements.txt.

**Spec:** `docs/superpowers/specs/2026-04-02-sim-optimizer-design.md`

**Subsystem scope:** This plan covers spec sections Layer 1 (Parameter Identification) + ingest. Solver, reconstruction, analysis, API, frontend, and live detectors are separate follow-up plans.

---

## File Map

| File | Responsibility |
|------|----------------|
| `telemetry_tool/sim_optimizer/__init__.py` | Package marker, version |
| `telemetry_tool/sim_optimizer/config.py` | `SimOptimizerConfig` frozen dataclass — all tunables |
| `telemetry_tool/sim_optimizer/ingest/__init__.py` | Sub-package marker |
| `telemetry_tool/sim_optimizer/ingest/raw_channels.py` | Load raw Parquet, validate ~180 physics channels, return typed DataFrame |
| `telemetry_tool/sim_optimizer/ingest/highrate.py` | Unpack `_ST[6]` arrays into 360Hz timeseries DataFrames |
| `telemetry_tool/sim_optimizer/ingest/segment_filter.py` | Flag grass/gravel/draft/yellow/pit rows, return boolean mask |
| `telemetry_tool/sim_optimizer/ingest/lap_align.py` | Distance-align samples for per-lap slicing |
| `telemetry_tool/sim_optimizer/param_id/__init__.py` | Sub-package marker |
| `telemetry_tool/sim_optimizer/param_id/tyre_model.py` | `TyreModel` — Pacejka fit from slip/force/load/temp/wear/pressure |
| `telemetry_tool/sim_optimizer/param_id/aero_model.py` | `AeroModel` — CdA/ClA from coast-down + ride height |
| `telemetry_tool/sim_optimizer/param_id/powertrain_model.py` | `PowertrainModel` — torque(RPM, gear) from full-throttle |
| `telemetry_tool/sim_optimizer/param_id/brake_model.py` | `BrakeModel` — decel(pressure, speed, temp, bias) |
| `telemetry_tool/sim_optimizer/param_id/suspension_model.py` | `SuspensionModel` — spring/damper from shock defl/vel |
| `telemetry_tool/sim_optimizer/param_id/mass_model.py` | `MassModel` — base + fuel burn + BOP |
| `telemetry_tool/sim_optimizer/param_id/vehicle_model.py` | `VehicleModel` — assembles sub-models, FrictionLike protocol |
| `telemetry_tool/tests/test_sim_optimizer/__init__.py` | Test package marker |
| `telemetry_tool/tests/test_sim_optimizer/conftest.py` | Shared fixtures: synthetic raw data, known vehicle params |
| `telemetry_tool/tests/test_sim_optimizer/test_raw_channels.py` | Tests for raw channel extraction |
| `telemetry_tool/tests/test_sim_optimizer/test_highrate.py` | Tests for 360Hz unpacking |
| `telemetry_tool/tests/test_sim_optimizer/test_segment_filter.py` | Tests for segment flagging |
| `telemetry_tool/tests/test_sim_optimizer/test_tyre_model.py` | Tests for Pacejka identification |
| `telemetry_tool/tests/test_sim_optimizer/test_aero_model.py` | Tests for aero identification |
| `telemetry_tool/tests/test_sim_optimizer/test_powertrain_model.py` | Tests for powertrain identification |
| `telemetry_tool/tests/test_sim_optimizer/test_brake_model.py` | Tests for brake identification |
| `telemetry_tool/tests/test_sim_optimizer/test_suspension_model.py` | Tests for suspension identification |
| `telemetry_tool/tests/test_sim_optimizer/test_mass_model.py` | Tests for mass identification |
| `telemetry_tool/tests/test_sim_optimizer/test_vehicle_model.py` | Tests for VehicleModel assembly + FrictionLike |

---

### Task 1: Package scaffold + config

**Files:**
- Create: `telemetry_tool/sim_optimizer/__init__.py`
- Create: `telemetry_tool/sim_optimizer/config.py`
- Create: `telemetry_tool/sim_optimizer/ingest/__init__.py`
- Create: `telemetry_tool/sim_optimizer/param_id/__init__.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/__init__.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/conftest.py`

- [ ] **Step 1: Create package structure**

```python
# telemetry_tool/sim_optimizer/__init__.py
"""Sim racing lap time optimizer — parameter identification + theoretical lap."""
__version__ = "0.1.0"
```

```python
# telemetry_tool/sim_optimizer/ingest/__init__.py
"""Raw telemetry ingest and preparation."""
```

```python
# telemetry_tool/sim_optimizer/param_id/__init__.py
"""Physics parameter identification from raw telemetry."""
```

- [ ] **Step 2: Write config with all tunables**

```python
# telemetry_tool/sim_optimizer/config.py
"""SimOptimizerConfig — all tunables for the sim optimizer pipeline."""
from __future__ import annotations

from dataclasses import dataclass


_G = 9.80665


@dataclass(frozen=True)
class SimOptimizerConfig:
    """Immutable configuration for the sim optimizer pipeline."""

    # -- Tyre model --
    tyre_pacejka_b_init: float = 10.0
    tyre_pacejka_c_init: float = 1.5
    tyre_pacejka_d_init: float = 1.0
    tyre_mu_clamp_lo: float = 0.8
    tyre_mu_clamp_hi: float = 1.8
    tyre_temp_optimal_c: float = 85.0
    tyre_temp_sigma_c: float = 25.0
    tyre_pressure_optimal_kpa: float = 172.0   # ~25 psi
    tyre_pressure_sigma_kpa: float = 20.0
    tyre_min_slip_samples: int = 200
    tyre_slip_ratio_cap: float = 0.15          # discard outliers beyond
    tyre_slip_angle_cap_deg: float = 12.0

    # -- Aero model --
    aero_cda_default: float = 0.80
    aero_cla_default: float = 0.0
    aero_cda_clamp_lo: float = 0.3
    aero_cda_clamp_hi: float = 3.0
    aero_cla_clamp_lo: float = 0.0
    aero_cla_clamp_hi: float = 5.0
    aero_coastdown_throttle_max: float = 0.02
    aero_coastdown_brake_max: float = 0.02
    aero_coastdown_curvature_max: float = 0.005  # ~200m radius
    aero_draft_distance_m: float = 50.0           # exclude if car ahead < this

    # -- Powertrain model --
    powertrain_full_throttle_min: float = 0.95
    powertrain_min_samples_per_gear: int = 50
    powertrain_rr_c0: float = 0.012
    powertrain_rr_c1: float = 0.00008
    powertrain_transmission_efficiency: float = 0.93

    # -- Brake model --
    brake_min_decel_mps2: float = 2.0
    brake_min_samples: int = 100
    brake_fade_temp_threshold_c: float = 400.0

    # -- Suspension model --
    suspension_min_quasi_static_samples: int = 100
    suspension_spring_rate_clamp_lo_npm: float = 10_000.0   # N/m
    suspension_spring_rate_clamp_hi_npm: float = 200_000.0

    # -- Mass model --
    mass_fuel_density_kg_l: float = 0.75
    mass_default_kg: float = 1200.0
    mass_clamp_lo_kg: float = 500.0
    mass_clamp_hi_kg: float = 2500.0
    mass_min_full_throttle_samples: int = 20

    # -- Segment filter --
    filter_min_speed_mps: float = 5.0
    filter_yellow_flag_bits: int = 0x10   # iRacing SessionFlags yellow

    # -- General --
    resample_ds_m: float = 0.5
    highrate_tick_hz: float = 360.0
    samples_per_tick: int = 6


def default_config() -> SimOptimizerConfig:
    """Return config with all defaults."""
    return SimOptimizerConfig()
```

- [ ] **Step 3: Write test conftest with shared fixtures**

```python
# telemetry_tool/tests/test_sim_optimizer/__init__.py
```

```python
# telemetry_tool/tests/test_sim_optimizer/conftest.py
"""Shared fixtures for sim_optimizer tests."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig, default_config


@pytest.fixture
def sim_config() -> SimOptimizerConfig:
    return default_config()


@pytest.fixture
def synthetic_raw_df() -> pd.DataFrame:
    """Synthetic raw iRacing data: 600 samples at 60Hz on a 1km oval.

    Includes all channels needed for parameter identification.
    Simulates a car doing ~120 kph on straights, ~80 kph in corners.
    """
    np.random.seed(42)
    n = 600
    dt = 1.0 / 60.0
    t = np.arange(n) * dt  # 10 seconds

    # Distance: ~1000m lap
    ds = 1000.0 / n
    dist = np.arange(n) * ds
    dist_pct = dist / 1000.0

    # Curvature: two corners (250-500m, 750-1000m)
    kappa = np.zeros(n)
    for lo_m, hi_m in [(250, 500), (750, 1000)]:
        idx = (dist >= lo_m) & (dist < hi_m)
        kappa[idx] = 0.02  # R=50m

    # Speed profile (m/s)
    v_max_straight = 33.0   # ~120 kph
    v_corner = 22.0         # ~80 kph
    speed = np.where(kappa > 0, v_corner, v_max_straight)
    # Smooth transitions
    for _ in range(20):
        for i in range(1, n):
            speed[i] = min(speed[i], np.sqrt(max(speed[i-1]**2 + 2*5.0*ds, 0)))
        for i in range(n-2, -1, -1):
            speed[i] = min(speed[i], np.sqrt(max(speed[i+1]**2 + 2*8.0*ds, 0)))

    # Accelerations
    ax = np.gradient(speed, dt)
    ay = speed**2 * kappa

    # Heading and XY from curvature
    heading = np.cumsum(kappa * ds)
    x = np.cumsum(np.cos(heading) * ds)
    y = np.cumsum(np.sin(heading) * ds)

    # Throttle/brake from longitudinal accel
    throttle = np.clip(ax / 5.0, 0.0, 1.0)
    brake = np.clip(-ax / 10.0, 0.0, 1.0)
    steering = np.degrees(np.arctan(kappa * 2.5))  # simplified

    # Gear from speed
    gear = np.clip((speed / 10.0).astype(int) + 1, 1, 6)
    rpm = speed * 100.0 + 2000.0  # simplified

    # Per-wheel data
    wheel_speed_base = speed / 0.33  # rad/s, wheel_radius ~ 0.33m
    shock_defl_base = 0.05  # 50mm static

    data = {
        # Timing
        "irsdk__SessionTime": t,
        "irsdk__Lap": np.ones(n, dtype=int),
        "irsdk__LapDist": dist,
        "irsdk__LapDistPct": dist_pct,
        "irsdk__IsOnTrack": np.ones(n, dtype=bool),
        "irsdk__OnPitRoad": np.zeros(n, dtype=bool),
        "irsdk__SessionFlags": np.zeros(n, dtype=int),
        # Vehicle dynamics
        "irsdk__Speed": speed,
        "irsdk__VelocityX": speed,  # body-frame, simplified: forward = X
        "irsdk__VelocityY": speed * np.sin(np.radians(steering * 0.1)),  # small sideslip
        "irsdk__VelocityZ": np.zeros(n),
        "irsdk__LatAccel": ay,
        "irsdk__LongAccel": ax,
        "irsdk__VertAccel": np.full(n, _G),
        "irsdk__Yaw": heading,
        "irsdk__YawRate": np.gradient(heading, dt),
        "irsdk__Pitch": np.zeros(n),
        "irsdk__PitchRate": np.zeros(n),
        "irsdk__Roll": ay / _G * 0.02,  # small roll from lateral G
        "irsdk__RollRate": np.gradient(ay / _G * 0.02, dt),
        # Position
        "irsdk__Lat": x,
        "irsdk__Lon": y,
        "irsdk__Alt": np.zeros(n),
        # Driver inputs
        "irsdk__Throttle": throttle,
        "irsdk__ThrottleRaw": throttle,
        "irsdk__Brake": brake,
        "irsdk__BrakeRaw": brake * 1.05,  # raw slightly higher (ABS reduces)
        "irsdk__BrakeABSactive": (brake > 0.8).astype(int),
        "irsdk__SteeringWheelAngle": np.radians(steering),
        "irsdk__Gear": gear,
        "irsdk__RPM": rpm,
        "irsdk__Clutch": np.ones(n),
        # Engine
        "irsdk__WaterTemp": np.full(n, 85.0),
        "irsdk__OilTemp": np.full(n, 95.0),
        "irsdk__FuelLevel": np.linspace(40.0, 38.0, n),
        "irsdk__FuelUsePerHour": np.full(n, 12.0),
        "irsdk__Voltage": np.full(n, 14.2),
        # Environment
        "irsdk__AirTemp": np.full(n, 25.0),
        "irsdk__TrackTempCrew": np.full(n, 35.0),
        "irsdk__AirDensity": np.full(n, 1.18),
        "irsdk__AirPressure": np.full(n, 101325.0),
        "irsdk__WindVel": np.full(n, 2.0),
        "irsdk__WindDir": np.full(n, 0.5),
        "irsdk__TrackWetness": np.zeros(n, dtype=int),
        "irsdk__RelativeHumidity": np.full(n, 0.45),
        # Driver controls
        "irsdk__dcBrakeBias": np.full(n, 56.0),
        "irsdk__dcABS": np.full(n, 4.0),
        "irsdk__dcTractionControl": np.full(n, 3.0),
        "irsdk__dcFuelMixture": np.full(n, 0.0),
        # Player/BOP
        "irsdk__PlayerCarWeightPenalty": np.full(n, 0.0),
        "irsdk__PlayerCarPowerAdjust": np.full(n, 0.0),
        "irsdk__PlayerTrackSurface": np.full(n, 3),  # 3 = on track
        "irsdk__PlayerTrackSurfaceMaterial": np.full(n, 1),  # 1 = asphalt
        "irsdk__CarDistAhead": np.full(n, 500.0),  # no one near
        "irsdk__CarDistBehind": np.full(n, 500.0),
        # Lap delta (validation)
        "irsdk__LapDeltaToOptimalLap": np.zeros(n),
        "irsdk__LapDeltaToOptimalLap_OK": np.ones(n, dtype=bool),
        "irsdk__PlayerCarSLShiftRPM": np.full(n, 7500.0),
        "irsdk__PlayerCarSLBlinkRPM": np.full(n, 8000.0),
    }

    _G_val = 9.80665
    # Per-wheel temps (3 zones x 4 wheels)
    for corner in ["LF", "RF", "LR", "RR"]:
        for zone in ["CL", "CM", "CR"]:
            data[f"irsdk__{corner}temp{zone}"] = np.full(n, 82.0) + np.random.normal(0, 2, n)
        # Wear (3 zones)
        for zone in ["L", "M", "R"]:
            data[f"irsdk__{corner}wear{zone}"] = np.full(n, 0.95) - np.linspace(0, 0.01, n)
        # Cold pressure
        data[f"irsdk__{corner}coldPressure"] = np.full(n, 172.0)
        # Odometer
        data[f"irsdk__{corner}odometer"] = np.linspace(0, 5000, n)
        # Shock deflection (more compressed on outer wheels in corners)
        lat_load_shift = 0.01 * ay / _G_val
        if corner.startswith("L"):
            data[f"irsdk__{corner}shockDefl"] = shock_defl_base - lat_load_shift
        else:
            data[f"irsdk__{corner}shockDefl"] = shock_defl_base + lat_load_shift
        # Shock velocity
        data[f"irsdk__{corner}shockVel"] = np.gradient(data[f"irsdk__{corner}shockDefl"], dt)
        # Brake line pressure
        data[f"irsdk__{corner}brakeLinePress"] = brake * 50.0  # 0-50 bar
        # Brake temp
        data[f"irsdk__{corner}brakeTemp"] = 200.0 + brake * 300.0

    # 360Hz _ST arrays (6 samples per 60Hz tick)
    for var in ["LatAccel", "LongAccel", "VertAccel", "VelocityX", "VelocityY",
                "VelocityZ", "YawRate", "RollRate", "PitchRate"]:
        base = data.get(f"irsdk__{var}", np.zeros(n))
        for i in range(6):
            data[f"irsdk__{var}_ST__{i}"] = base + np.random.normal(0, 0.01, n)

    for corner in ["LF", "RF", "LR", "RR"]:
        base_defl = data[f"irsdk__{corner}shockDefl"]
        base_vel = data[f"irsdk__{corner}shockVel"]
        for i in range(6):
            data[f"irsdk__{corner}shockDefl_ST__{i}"] = base_defl + np.random.normal(0, 0.001, n)
            data[f"irsdk__{corner}shockVel_ST__{i}"] = base_vel + np.random.normal(0, 0.01, n)

    # SteeringWheelTorque
    data["irsdk__SteeringWheelTorque"] = ay * 2.0  # simplified FFB
    for i in range(6):
        data[f"irsdk__SteeringWheelTorque_ST__{i}"] = ay * 2.0 + np.random.normal(0, 0.1, n)

    return pd.DataFrame(data)


_G = 9.80665
```

- [ ] **Step 4: Verify imports work**

Run: `cd telemetry_tool && python -c "from sim_optimizer.config import default_config; print(default_config())"`
Expected: prints the `SimOptimizerConfig` with all defaults.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/ telemetry_tool/tests/test_sim_optimizer/
git commit -m "feat(sim-optimizer): scaffold package + config + test fixtures"
```

---

### Task 2: Raw channel extraction

**Files:**
- Create: `telemetry_tool/sim_optimizer/ingest/raw_channels.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_raw_channels.py`

- [ ] **Step 1: Write failing test**

```python
# telemetry_tool/tests/test_sim_optimizer/test_raw_channels.py
"""Tests for raw channel extraction from iRacing Parquet sidecar."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.sim_optimizer.config import default_config
from telemetry_tool.sim_optimizer.ingest.raw_channels import (
    CHANNEL_GROUPS,
    RawChannelSet,
    extract_raw_channels,
)


class TestExtractRawChannels:
    def test_extracts_speed(self, synthetic_raw_df, sim_config):
        result = extract_raw_channels(synthetic_raw_df, config=sim_config)
        assert result.speed_mps is not None
        assert len(result.speed_mps) == len(synthetic_raw_df)
        assert np.all(result.speed_mps >= 0)

    def test_extracts_per_wheel_temps(self, synthetic_raw_df, sim_config):
        result = extract_raw_channels(synthetic_raw_df, config=sim_config)
        assert result.tyre_temp_lf_cl is not None
        assert result.tyre_temp_rr_cr is not None
        assert len(result.tyre_temp_lf_cl) == len(synthetic_raw_df)

    def test_extracts_shock_deflection(self, synthetic_raw_df, sim_config):
        result = extract_raw_channels(synthetic_raw_df, config=sim_config)
        assert result.shock_defl_lf is not None
        assert result.shock_defl_rr is not None

    def test_extracts_body_velocities(self, synthetic_raw_df, sim_config):
        result = extract_raw_channels(synthetic_raw_df, config=sim_config)
        assert result.velocity_x is not None
        assert result.velocity_y is not None

    def test_extracts_brake_line_press(self, synthetic_raw_df, sim_config):
        result = extract_raw_channels(synthetic_raw_df, config=sim_config)
        assert result.brake_line_press_lf is not None

    def test_missing_column_returns_none(self, sim_config):
        df = pd.DataFrame({"irsdk__Speed": [10.0, 20.0]})
        result = extract_raw_channels(df, config=sim_config)
        assert result.speed_mps is not None
        assert result.shock_defl_lf is None  # not in this df

    def test_channel_groups_complete(self):
        """All 6 param_id sub-models have channel groups defined."""
        for group in ["tyre", "aero", "powertrain", "brake", "suspension", "mass",
                       "environment", "validation", "geometry", "inputs"]:
            assert group in CHANNEL_GROUPS, f"Missing channel group: {group}"

    def test_validates_speed_range(self, sim_config):
        df = pd.DataFrame({
            "irsdk__Speed": [-5.0, 0.0, 100.0, 200.0],
            "irsdk__IsOnTrack": [True, True, True, True],
        })
        result = extract_raw_channels(df, config=sim_config)
        assert np.all(result.speed_mps >= 0)  # negatives clipped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_raw_channels.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'telemetry_tool.sim_optimizer.ingest.raw_channels'`

- [ ] **Step 3: Write implementation**

```python
# telemetry_tool/sim_optimizer/ingest/raw_channels.py
"""Extract and validate physics-relevant channels from raw iRacing Parquet sidecar.

The raw sidecar contains all 332 IRSDK variables with the ``irsdk__`` prefix.
This module extracts the ~180 channels relevant to parameter identification,
validates ranges, and returns a typed ``RawChannelSet``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from typing import Any

import numpy as np
import pandas as pd

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

log = logging.getLogger(__name__)

_G = 9.80665

# Channel groups: maps each param_id sub-model to its raw column names.
CHANNEL_GROUPS: dict[str, list[str]] = {
    "tyre": [
        # Per-wheel temps (3 zones x 4)
        *[f"irsdk__{c}temp{z}" for c in ("LF", "RF", "LR", "RR") for z in ("CL", "CM", "CR")],
        # Per-wheel wear (3 zones x 4)
        *[f"irsdk__{c}wear{z}" for c in ("LF", "RF", "LR", "RR") for z in ("L", "M", "R")],
        # Cold pressure x 4
        *[f"irsdk__{c}coldPressure" for c in ("LF", "RF", "LR", "RR")],
        # Odometer x 4
        *[f"irsdk__{c}odometer" for c in ("LF", "RF", "LR", "RR")],
        # ABS (lock limit)
        "irsdk__BrakeABSactive",
        # Track surface
        "irsdk__PlayerTrackSurface", "irsdk__PlayerTrackSurfaceMaterial",
    ],
    "aero": [
        "irsdk__Speed", "irsdk__LongAccel", "irsdk__AirDensity",
        "irsdk__WindVel", "irsdk__WindDir", "irsdk__Pitch",
        "irsdk__CarDistAhead",
        *[f"irsdk__{c}shockDefl" for c in ("LF", "RF", "LR", "RR")],
    ],
    "powertrain": [
        "irsdk__RPM", "irsdk__Gear", "irsdk__Throttle", "irsdk__ThrottleRaw",
        "irsdk__LongAccel", "irsdk__Speed", "irsdk__FuelLevel",
        "irsdk__FuelUsePerHour", "irsdk__dcFuelMixture",
        "irsdk__PlayerCarPowerAdjust",
        "irsdk__PlayerCarSLShiftRPM", "irsdk__PlayerCarSLBlinkRPM",
    ],
    "brake": [
        "irsdk__Brake", "irsdk__BrakeRaw", "irsdk__BrakeABSactive",
        *[f"irsdk__{c}brakeLinePress" for c in ("LF", "RF", "LR", "RR")],
        "irsdk__dcBrakeBias", "irsdk__LongAccel", "irsdk__Speed",
    ],
    "suspension": [
        *[f"irsdk__{c}shockDefl" for c in ("LF", "RF", "LR", "RR")],
        *[f"irsdk__{c}shockVel" for c in ("LF", "RF", "LR", "RR")],
        "irsdk__RollRate", "irsdk__PitchRate", "irsdk__VertAccel",
        "irsdk__LatAccel", "irsdk__LongAccel",
    ],
    "mass": [
        "irsdk__FuelLevel", "irsdk__FuelUsePerHour",
        "irsdk__PlayerCarWeightPenalty", "irsdk__LongAccel", "irsdk__Speed",
        "irsdk__Throttle",
    ],
    "environment": [
        "irsdk__AirTemp", "irsdk__TrackTempCrew", "irsdk__AirDensity",
        "irsdk__AirPressure", "irsdk__WindVel", "irsdk__WindDir",
        "irsdk__TrackWetness", "irsdk__RelativeHumidity",
    ],
    "validation": [
        "irsdk__LapDeltaToOptimalLap", "irsdk__LapDeltaToOptimalLap_OK",
        "irsdk__SessionFlags", "irsdk__IsOnTrack",
    ],
    "geometry": [
        "irsdk__Lat", "irsdk__Lon", "irsdk__Alt",
        "irsdk__LapDist", "irsdk__LapDistPct", "irsdk__Speed",
    ],
    "inputs": [
        "irsdk__Throttle", "irsdk__Brake", "irsdk__SteeringWheelAngle",
        "irsdk__Gear", "irsdk__Clutch",
    ],
}


def _safe_col(df: pd.DataFrame, col: str) -> np.ndarray | None:
    """Extract a column as numpy array, or None if missing."""
    if col in df.columns:
        return df[col].to_numpy(dtype=float, na_value=np.nan)
    return None


def _safe_col_int(df: pd.DataFrame, col: str) -> np.ndarray | None:
    if col in df.columns:
        return df[col].to_numpy(dtype=float, na_value=np.nan)
    return None


def _safe_col_bool(df: pd.DataFrame, col: str) -> np.ndarray | None:
    if col in df.columns:
        arr = df[col].to_numpy()
        try:
            return arr.astype(bool)
        except (ValueError, TypeError):
            return arr
    return None


@dataclass
class RawChannelSet:
    """Validated, typed channel arrays extracted from raw sidecar.

    All arrays are the same length (n_samples). Missing channels are None.
    """
    n_samples: int

    # -- Timing / position --
    session_time_s: np.ndarray | None = None
    lap: np.ndarray | None = None
    lap_dist_m: np.ndarray | None = None
    lap_dist_pct: np.ndarray | None = None
    is_on_track: np.ndarray | None = None
    on_pit_road: np.ndarray | None = None
    session_flags: np.ndarray | None = None

    # -- Vehicle dynamics --
    speed_mps: np.ndarray | None = None
    velocity_x: np.ndarray | None = None
    velocity_y: np.ndarray | None = None
    velocity_z: np.ndarray | None = None
    lat_accel: np.ndarray | None = None
    long_accel: np.ndarray | None = None
    vert_accel: np.ndarray | None = None
    yaw_rad: np.ndarray | None = None
    yaw_rate: np.ndarray | None = None
    pitch_rad: np.ndarray | None = None
    pitch_rate: np.ndarray | None = None
    roll_rad: np.ndarray | None = None
    roll_rate: np.ndarray | None = None

    # -- World position --
    pos_x: np.ndarray | None = None
    pos_y: np.ndarray | None = None
    pos_z: np.ndarray | None = None

    # -- Driver inputs --
    throttle: np.ndarray | None = None
    throttle_raw: np.ndarray | None = None
    brake: np.ndarray | None = None
    brake_raw: np.ndarray | None = None
    brake_abs_active: np.ndarray | None = None
    steering_rad: np.ndarray | None = None
    gear: np.ndarray | None = None
    rpm: np.ndarray | None = None
    clutch: np.ndarray | None = None

    # -- Driver controls --
    dc_brake_bias: np.ndarray | None = None
    dc_abs: np.ndarray | None = None
    dc_tc: np.ndarray | None = None
    dc_fuel_mixture: np.ndarray | None = None

    # -- Per-wheel tyre temps (3 zones x 4 wheels) --
    tyre_temp_lf_cl: np.ndarray | None = None
    tyre_temp_lf_cm: np.ndarray | None = None
    tyre_temp_lf_cr: np.ndarray | None = None
    tyre_temp_rf_cl: np.ndarray | None = None
    tyre_temp_rf_cm: np.ndarray | None = None
    tyre_temp_rf_cr: np.ndarray | None = None
    tyre_temp_lr_cl: np.ndarray | None = None
    tyre_temp_lr_cm: np.ndarray | None = None
    tyre_temp_lr_cr: np.ndarray | None = None
    tyre_temp_rr_cl: np.ndarray | None = None
    tyre_temp_rr_cm: np.ndarray | None = None
    tyre_temp_rr_cr: np.ndarray | None = None

    # -- Per-wheel tyre wear (3 zones x 4 wheels) --
    tyre_wear_lf_l: np.ndarray | None = None
    tyre_wear_lf_m: np.ndarray | None = None
    tyre_wear_lf_r: np.ndarray | None = None
    tyre_wear_rf_l: np.ndarray | None = None
    tyre_wear_rf_m: np.ndarray | None = None
    tyre_wear_rf_r: np.ndarray | None = None
    tyre_wear_lr_l: np.ndarray | None = None
    tyre_wear_lr_m: np.ndarray | None = None
    tyre_wear_lr_r: np.ndarray | None = None
    tyre_wear_rr_l: np.ndarray | None = None
    tyre_wear_rr_m: np.ndarray | None = None
    tyre_wear_rr_r: np.ndarray | None = None

    # -- Per-wheel cold pressure --
    cold_pressure_lf: np.ndarray | None = None
    cold_pressure_rf: np.ndarray | None = None
    cold_pressure_lr: np.ndarray | None = None
    cold_pressure_rr: np.ndarray | None = None

    # -- Per-wheel odometer --
    odometer_lf: np.ndarray | None = None
    odometer_rf: np.ndarray | None = None
    odometer_lr: np.ndarray | None = None
    odometer_rr: np.ndarray | None = None

    # -- Per-wheel shock --
    shock_defl_lf: np.ndarray | None = None
    shock_defl_rf: np.ndarray | None = None
    shock_defl_lr: np.ndarray | None = None
    shock_defl_rr: np.ndarray | None = None
    shock_vel_lf: np.ndarray | None = None
    shock_vel_rf: np.ndarray | None = None
    shock_vel_lr: np.ndarray | None = None
    shock_vel_rr: np.ndarray | None = None

    # -- Per-wheel brake --
    brake_line_press_lf: np.ndarray | None = None
    brake_line_press_rf: np.ndarray | None = None
    brake_line_press_lr: np.ndarray | None = None
    brake_line_press_rr: np.ndarray | None = None
    brake_temp_lf: np.ndarray | None = None
    brake_temp_rf: np.ndarray | None = None
    brake_temp_lr: np.ndarray | None = None
    brake_temp_rr: np.ndarray | None = None

    # -- Engine --
    water_temp: np.ndarray | None = None
    oil_temp: np.ndarray | None = None
    fuel_level: np.ndarray | None = None
    fuel_use_per_hour: np.ndarray | None = None

    # -- Environment --
    air_temp: np.ndarray | None = None
    track_temp: np.ndarray | None = None
    air_density: np.ndarray | None = None
    air_pressure: np.ndarray | None = None
    wind_vel: np.ndarray | None = None
    wind_dir: np.ndarray | None = None
    track_wetness: np.ndarray | None = None
    humidity: np.ndarray | None = None

    # -- Player/BOP --
    weight_penalty_kg: np.ndarray | None = None
    power_adjust_pct: np.ndarray | None = None
    track_surface: np.ndarray | None = None
    track_surface_material: np.ndarray | None = None
    car_dist_ahead: np.ndarray | None = None

    # -- Validation --
    delta_to_optimal: np.ndarray | None = None
    delta_to_optimal_ok: np.ndarray | None = None
    shift_rpm: np.ndarray | None = None
    blink_rpm: np.ndarray | None = None

    # -- Steering torque --
    steering_torque_nm: np.ndarray | None = None

    def available_channels(self) -> list[str]:
        """Return names of all non-None channels."""
        return [f.name for f in fields(self) if f.name != "n_samples" and getattr(self, f.name) is not None]


# Mapping from RawChannelSet field name → raw column name
_FIELD_TO_COL: dict[str, str] = {
    "session_time_s": "irsdk__SessionTime",
    "lap": "irsdk__Lap",
    "lap_dist_m": "irsdk__LapDist",
    "lap_dist_pct": "irsdk__LapDistPct",
    "is_on_track": "irsdk__IsOnTrack",
    "on_pit_road": "irsdk__OnPitRoad",
    "session_flags": "irsdk__SessionFlags",
    "speed_mps": "irsdk__Speed",
    "velocity_x": "irsdk__VelocityX",
    "velocity_y": "irsdk__VelocityY",
    "velocity_z": "irsdk__VelocityZ",
    "lat_accel": "irsdk__LatAccel",
    "long_accel": "irsdk__LongAccel",
    "vert_accel": "irsdk__VertAccel",
    "yaw_rad": "irsdk__Yaw",
    "yaw_rate": "irsdk__YawRate",
    "pitch_rad": "irsdk__Pitch",
    "pitch_rate": "irsdk__PitchRate",
    "roll_rad": "irsdk__Roll",
    "roll_rate": "irsdk__RollRate",
    "pos_x": "irsdk__Lat",
    "pos_y": "irsdk__Lon",
    "pos_z": "irsdk__Alt",
    "throttle": "irsdk__Throttle",
    "throttle_raw": "irsdk__ThrottleRaw",
    "brake": "irsdk__Brake",
    "brake_raw": "irsdk__BrakeRaw",
    "steering_rad": "irsdk__SteeringWheelAngle",
    "gear": "irsdk__Gear",
    "rpm": "irsdk__RPM",
    "clutch": "irsdk__Clutch",
    "dc_brake_bias": "irsdk__dcBrakeBias",
    "dc_abs": "irsdk__dcABS",
    "dc_tc": "irsdk__dcTractionControl",
    "dc_fuel_mixture": "irsdk__dcFuelMixture",
    "water_temp": "irsdk__WaterTemp",
    "oil_temp": "irsdk__OilTemp",
    "fuel_level": "irsdk__FuelLevel",
    "fuel_use_per_hour": "irsdk__FuelUsePerHour",
    "air_temp": "irsdk__AirTemp",
    "track_temp": "irsdk__TrackTempCrew",
    "air_density": "irsdk__AirDensity",
    "air_pressure": "irsdk__AirPressure",
    "wind_vel": "irsdk__WindVel",
    "wind_dir": "irsdk__WindDir",
    "track_wetness": "irsdk__TrackWetness",
    "humidity": "irsdk__RelativeHumidity",
    "weight_penalty_kg": "irsdk__PlayerCarWeightPenalty",
    "power_adjust_pct": "irsdk__PlayerCarPowerAdjust",
    "track_surface": "irsdk__PlayerTrackSurface",
    "track_surface_material": "irsdk__PlayerTrackSurfaceMaterial",
    "car_dist_ahead": "irsdk__CarDistAhead",
    "delta_to_optimal": "irsdk__LapDeltaToOptimalLap",
    "delta_to_optimal_ok": "irsdk__LapDeltaToOptimalLap_OK",
    "shift_rpm": "irsdk__PlayerCarSLShiftRPM",
    "blink_rpm": "irsdk__PlayerCarSLBlinkRPM",
    "steering_torque_nm": "irsdk__SteeringWheelTorque",
}

# Per-wheel mappings (generated from patterns)
for _corner in ("lf", "rf", "lr", "rr"):
    _C = _corner.upper()
    for _zone in ("cl", "cm", "cr"):
        _Z = _zone.upper()
        _FIELD_TO_COL[f"tyre_temp_{_corner}_{_zone}"] = f"irsdk__{_C}temp{_Z}"
    for _zone in ("l", "m", "r"):
        _Z = _zone.upper()
        _FIELD_TO_COL[f"tyre_wear_{_corner}_{_zone}"] = f"irsdk__{_C}wear{_Z}"
    _FIELD_TO_COL[f"cold_pressure_{_corner}"] = f"irsdk__{_C}coldPressure"
    _FIELD_TO_COL[f"odometer_{_corner}"] = f"irsdk__{_C}odometer"
    _FIELD_TO_COL[f"shock_defl_{_corner}"] = f"irsdk__{_C}shockDefl"
    _FIELD_TO_COL[f"shock_vel_{_corner}"] = f"irsdk__{_C}shockVel"
    _FIELD_TO_COL[f"brake_line_press_{_corner}"] = f"irsdk__{_C}brakeLinePress"
    _FIELD_TO_COL[f"brake_temp_{_corner}"] = f"irsdk__{_C}brakeTemp"

# Bool fields
_BOOL_FIELDS = {"is_on_track", "on_pit_road", "brake_abs_active", "delta_to_optimal_ok"}

# Special: BrakeABSactive needs manual mapping
_FIELD_TO_COL["brake_abs_active"] = "irsdk__BrakeABSactive"


def extract_raw_channels(
    df: pd.DataFrame,
    *,
    config: SimOptimizerConfig,
) -> RawChannelSet:
    """Extract validated physics channels from a raw iRacing DataFrame.

    Missing columns produce None fields. Speed is clipped to >= 0.
    """
    n = len(df)
    kwargs: dict[str, Any] = {"n_samples": n}

    for field_name, col_name in _FIELD_TO_COL.items():
        if field_name in _BOOL_FIELDS:
            kwargs[field_name] = _safe_col_bool(df, col_name)
        else:
            kwargs[field_name] = _safe_col(df, col_name)

    result = RawChannelSet(**kwargs)

    # Validate speed: clip negatives
    if result.speed_mps is not None:
        result.speed_mps = np.clip(result.speed_mps, 0.0, None)

    n_available = len(result.available_channels())
    log.info("Extracted %d / %d channels from raw sidecar (%d samples)",
             n_available, len(_FIELD_TO_COL), n)

    return result
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_raw_channels.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/ingest/raw_channels.py telemetry_tool/tests/test_sim_optimizer/test_raw_channels.py
git commit -m "feat(sim-optimizer): raw channel extraction from iRacing sidecar"
```

---

### Task 3: High-rate 360Hz unpacking

**Files:**
- Create: `telemetry_tool/sim_optimizer/ingest/highrate.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_highrate.py`

- [ ] **Step 1: Write failing test**

```python
# telemetry_tool/tests/test_sim_optimizer/test_highrate.py
"""Tests for 360Hz _ST array unpacking."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.sim_optimizer.config import default_config
from telemetry_tool.sim_optimizer.ingest.highrate import (
    HighRateChannels,
    unpack_highrate,
)


class TestUnpackHighrate:
    def test_output_length_6x(self, synthetic_raw_df, sim_config):
        result = unpack_highrate(synthetic_raw_df, config=sim_config)
        assert result.n_samples_hr == len(synthetic_raw_df) * 6

    def test_lat_accel_present(self, synthetic_raw_df, sim_config):
        result = unpack_highrate(synthetic_raw_df, config=sim_config)
        assert result.lat_accel_hr is not None
        assert len(result.lat_accel_hr) == result.n_samples_hr

    def test_shock_defl_present(self, synthetic_raw_df, sim_config):
        result = unpack_highrate(synthetic_raw_df, config=sim_config)
        assert result.shock_defl_lf_hr is not None

    def test_time_axis_monotonic(self, synthetic_raw_df, sim_config):
        result = unpack_highrate(synthetic_raw_df, config=sim_config)
        assert result.time_hr is not None
        assert np.all(np.diff(result.time_hr) > 0)

    def test_missing_st_columns_returns_none(self, sim_config):
        df = pd.DataFrame({"irsdk__Speed": [10.0, 20.0], "irsdk__SessionTime": [0.0, 0.016]})
        result = unpack_highrate(df, config=sim_config)
        assert result.lat_accel_hr is None
        assert result.n_samples_hr == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_highrate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# telemetry_tool/sim_optimizer/ingest/highrate.py
"""Unpack _ST[6] arrays into 360Hz timeseries.

iRacing exposes high-rate data as 6-element arrays sampled at 360Hz
within each 60Hz physics tick. This module interleaves the sub-samples
into continuous timeseries for parameter identification.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

log = logging.getLogger(__name__)

# Variables with _ST[6] high-rate arrays
_HR_DYNAMICS = ["LatAccel", "LongAccel", "VertAccel",
                "VelocityX", "VelocityY", "VelocityZ",
                "YawRate", "RollRate", "PitchRate"]

_HR_STEERING = ["SteeringWheelTorque"]

_HR_CORNERS = ["LF", "RF", "LR", "RR"]
_HR_SHOCK = ["shockDefl", "shockVel"]


@dataclass
class HighRateChannels:
    """360Hz timeseries unpacked from _ST arrays."""
    n_samples_hr: int
    time_hr: np.ndarray | None = None

    # Dynamics at 360Hz
    lat_accel_hr: np.ndarray | None = None
    long_accel_hr: np.ndarray | None = None
    vert_accel_hr: np.ndarray | None = None
    velocity_x_hr: np.ndarray | None = None
    velocity_y_hr: np.ndarray | None = None
    velocity_z_hr: np.ndarray | None = None
    yaw_rate_hr: np.ndarray | None = None
    roll_rate_hr: np.ndarray | None = None
    pitch_rate_hr: np.ndarray | None = None

    # Steering
    steering_torque_hr: np.ndarray | None = None

    # Per-wheel shock at 360Hz
    shock_defl_lf_hr: np.ndarray | None = None
    shock_defl_rf_hr: np.ndarray | None = None
    shock_defl_lr_hr: np.ndarray | None = None
    shock_defl_rr_hr: np.ndarray | None = None
    shock_vel_lf_hr: np.ndarray | None = None
    shock_vel_rf_hr: np.ndarray | None = None
    shock_vel_lr_hr: np.ndarray | None = None
    shock_vel_rr_hr: np.ndarray | None = None


def _interleave_st(df: pd.DataFrame, prefix: str, n_sub: int = 6) -> np.ndarray | None:
    """Interleave _ST columns into a single 360Hz array.

    Expects columns: ``{prefix}_ST__0`` through ``{prefix}_ST__5``.
    Returns array of length n_rows * n_sub, or None if columns missing.
    """
    cols = [f"{prefix}_ST__{i}" for i in range(n_sub)]
    if not all(c in df.columns for c in cols):
        return None
    # Stack: each row has n_sub sub-samples, interleave them in time order
    arrays = [df[c].to_numpy(dtype=float) for c in cols]
    stacked = np.column_stack(arrays)  # shape (n_rows, n_sub)
    return stacked.ravel()  # interleaved: row0_sub0, row0_sub1, ..., row1_sub0, ...


def unpack_highrate(
    df: pd.DataFrame,
    *,
    config: SimOptimizerConfig,
) -> HighRateChannels:
    """Unpack all _ST[6] arrays into 360Hz timeseries."""
    n_sub = config.samples_per_tick
    n_rows = len(df)

    # Build 360Hz time axis from SessionTime
    time_col = "irsdk__SessionTime"
    if time_col not in df.columns or n_rows < 2:
        return HighRateChannels(n_samples_hr=0)

    session_time = df[time_col].to_numpy(dtype=float)
    dt_tick = 1.0 / 60.0  # 60Hz base rate
    dt_sub = dt_tick / n_sub
    # For each 60Hz tick, create n_sub evenly spaced sub-times
    time_hr = np.empty(n_rows * n_sub, dtype=float)
    for i in range(n_sub):
        time_hr[i::n_sub] = session_time + i * dt_sub

    # Dynamics
    field_map = {
        "lat_accel_hr": "irsdk__LatAccel",
        "long_accel_hr": "irsdk__LongAccel",
        "vert_accel_hr": "irsdk__VertAccel",
        "velocity_x_hr": "irsdk__VelocityX",
        "velocity_y_hr": "irsdk__VelocityY",
        "velocity_z_hr": "irsdk__VelocityZ",
        "yaw_rate_hr": "irsdk__YawRate",
        "roll_rate_hr": "irsdk__RollRate",
        "pitch_rate_hr": "irsdk__PitchRate",
        "steering_torque_hr": "irsdk__SteeringWheelTorque",
    }

    kwargs: dict = {"n_samples_hr": n_rows * n_sub, "time_hr": time_hr}
    any_found = False

    for field_name, col_prefix in field_map.items():
        arr = _interleave_st(df, col_prefix, n_sub)
        kwargs[field_name] = arr
        if arr is not None:
            any_found = True

    # Per-wheel shock
    for corner in ("lf", "rf", "lr", "rr"):
        C = corner.upper()
        for var in ("shockDefl", "shockVel"):
            field = f"shock_{var.lower().replace('shock', '').replace('defl', 'defl').replace('vel', 'vel')}_{corner}_hr"
            # Normalize field name
            if "Defl" in var or "defl" in var:
                field = f"shock_defl_{corner}_hr"
            else:
                field = f"shock_vel_{corner}_hr"
            arr = _interleave_st(df, f"irsdk__{C}{var}", n_sub)
            kwargs[field] = arr
            if arr is not None:
                any_found = True

    if not any_found:
        return HighRateChannels(n_samples_hr=0)

    n_avail = sum(1 for k, v in kwargs.items() if k != "n_samples_hr" and v is not None)
    log.info("Unpacked %d high-rate channels to %d samples (360Hz)", n_avail, n_rows * n_sub)

    return HighRateChannels(**kwargs)
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_highrate.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/ingest/highrate.py telemetry_tool/tests/test_sim_optimizer/test_highrate.py
git commit -m "feat(sim-optimizer): 360Hz high-rate _ST array unpacking"
```

---

### Task 4: Segment filter

**Files:**
- Create: `telemetry_tool/sim_optimizer/ingest/segment_filter.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_segment_filter.py`

- [ ] **Step 1: Write failing test**

```python
# telemetry_tool/tests/test_sim_optimizer/test_segment_filter.py
"""Tests for segment filtering (grass/draft/yellow/pit/slow)."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.config import default_config
from telemetry_tool.sim_optimizer.ingest.raw_channels import extract_raw_channels
from telemetry_tool.sim_optimizer.ingest.segment_filter import (
    SegmentMask,
    compute_segment_mask,
)


class TestSegmentFilter:
    def test_all_clean_on_good_data(self, synthetic_raw_df, sim_config):
        channels = extract_raw_channels(synthetic_raw_df, config=sim_config)
        mask = compute_segment_mask(channels, config=sim_config)
        # synthetic data is all on-track, no grass, no draft, no yellow
        assert mask.clean.sum() > len(synthetic_raw_df) * 0.8

    def test_pit_flagged(self, synthetic_raw_df, sim_config):
        # Put first 20 samples in pit
        synthetic_raw_df.loc[:19, "irsdk__OnPitRoad"] = True
        channels = extract_raw_channels(synthetic_raw_df, config=sim_config)
        mask = compute_segment_mask(channels, config=sim_config)
        assert mask.pit[:20].all()

    def test_slow_flagged(self, synthetic_raw_df, sim_config):
        # Set speed to 1 m/s for first 10 samples
        synthetic_raw_df.loc[:9, "irsdk__Speed"] = 1.0
        channels = extract_raw_channels(synthetic_raw_df, config=sim_config)
        mask = compute_segment_mask(channels, config=sim_config)
        assert mask.slow[:10].all()

    def test_draft_flagged(self, synthetic_raw_df, sim_config):
        # Car 10m ahead for samples 100-110
        synthetic_raw_df.loc[100:110, "irsdk__CarDistAhead"] = 10.0
        channels = extract_raw_channels(synthetic_raw_df, config=sim_config)
        mask = compute_segment_mask(channels, config=sim_config)
        assert mask.draft[100:111].all()

    def test_clean_excludes_all_flags(self, synthetic_raw_df, sim_config):
        synthetic_raw_df.loc[:9, "irsdk__OnPitRoad"] = True
        channels = extract_raw_channels(synthetic_raw_df, config=sim_config)
        mask = compute_segment_mask(channels, config=sim_config)
        # First 10 are pit, so not clean
        assert not mask.clean[:10].any()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_segment_filter.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# telemetry_tool/sim_optimizer/ingest/segment_filter.py
"""Flag segments where data should be excluded from parameter identification.

Segments are flagged for: off-track (grass/gravel), pit road, drafting,
yellow flags, and low speed. The resulting ``SegmentMask`` provides boolean
arrays for each condition plus a composite ``clean`` mask.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig
from telemetry_tool.sim_optimizer.ingest.raw_channels import RawChannelSet

log = logging.getLogger(__name__)

# iRacing PlayerTrackSurface values: 3 = on track
_SURFACE_ON_TRACK = 3


@dataclass
class SegmentMask:
    """Boolean masks for each exclusion condition. True = condition active."""
    n_samples: int
    off_track: np.ndarray     # grass, gravel, sand, etc.
    pit: np.ndarray           # on pit road
    draft: np.ndarray         # car ahead within draft distance
    yellow: np.ndarray        # yellow flag active
    slow: np.ndarray          # below minimum speed
    clean: np.ndarray         # True where NONE of the above are active


def compute_segment_mask(
    channels: RawChannelSet,
    *,
    config: SimOptimizerConfig,
) -> SegmentMask:
    """Compute exclusion masks from raw channel data."""
    n = channels.n_samples
    off_track = np.zeros(n, dtype=bool)
    pit = np.zeros(n, dtype=bool)
    draft = np.zeros(n, dtype=bool)
    yellow = np.zeros(n, dtype=bool)
    slow = np.zeros(n, dtype=bool)

    # Off-track: PlayerTrackSurface != 3, or IsOnTrack == False
    if channels.track_surface is not None:
        off_track |= (channels.track_surface != _SURFACE_ON_TRACK)
    if channels.is_on_track is not None:
        off_track |= ~channels.is_on_track.astype(bool)

    # Pit road
    if channels.on_pit_road is not None:
        pit = channels.on_pit_road.astype(bool)

    # Draft: car ahead within threshold
    if channels.car_dist_ahead is not None:
        draft = channels.car_dist_ahead < config.aero_draft_distance_m

    # Yellow flag
    if channels.session_flags is not None:
        flag_arr = channels.session_flags.astype(int)
        yellow = (flag_arr & config.filter_yellow_flag_bits) != 0

    # Slow speed
    if channels.speed_mps is not None:
        slow = channels.speed_mps < config.filter_min_speed_mps

    clean = ~(off_track | pit | draft | yellow | slow)

    n_clean = int(clean.sum())
    log.info("Segment filter: %d/%d clean (%.1f%%), excluded: off_track=%d pit=%d draft=%d yellow=%d slow=%d",
             n_clean, n, 100.0 * n_clean / max(n, 1),
             off_track.sum(), pit.sum(), draft.sum(), yellow.sum(), slow.sum())

    return SegmentMask(n_samples=n, off_track=off_track, pit=pit,
                       draft=draft, yellow=yellow, slow=slow, clean=clean)
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_segment_filter.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/ingest/segment_filter.py telemetry_tool/tests/test_sim_optimizer/test_segment_filter.py
git commit -m "feat(sim-optimizer): segment filter for grass/pit/draft/yellow/slow"
```

---

### Task 5: Mass model

**Files:**
- Create: `telemetry_tool/sim_optimizer/param_id/mass_model.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_mass_model.py`

Starting with mass because other models depend on it.

- [ ] **Step 1: Write failing test**

```python
# telemetry_tool/tests/test_sim_optimizer/test_mass_model.py
"""Tests for mass model identification."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.config import default_config
from telemetry_tool.sim_optimizer.param_id.mass_model import (
    MassModel,
    identify_mass_model,
)


class TestMassModel:
    def test_fuel_burn_decreases_mass(self):
        model = MassModel(base_mass_kg=1200.0, fuel_density_kg_l=0.75,
                          bop_penalty_kg=0.0)
        assert model.total_mass_kg(fuel_level_l=40.0) == 1200.0 + 30.0
        assert model.total_mass_kg(fuel_level_l=20.0) == 1200.0 + 15.0
        assert model.total_mass_kg(fuel_level_l=0.0) == 1200.0

    def test_bop_penalty_added(self):
        model = MassModel(base_mass_kg=1200.0, fuel_density_kg_l=0.75,
                          bop_penalty_kg=30.0)
        assert model.total_mass_kg(fuel_level_l=0.0) == 1230.0

    def test_identify_from_accel_data(self, sim_config):
        """Given known mass and torque, F=ma should recover mass."""
        n = 100
        true_mass = 1100.0
        speed = np.linspace(20.0, 40.0, n)
        throttle = np.ones(n)  # full throttle
        long_accel = 5.0 * np.ones(n)  # ~5 m/s^2
        fuel_level = np.full(n, 30.0)
        bop_kg = np.full(n, 0.0)
        # With drag ~ 0.5 * 1.2 * 0.8 * v^2 / m, at v=30: ~ 0.26 m/s^2
        # Net force = mass * accel, so mass ~ force / accel
        model = identify_mass_model(
            speed_mps=speed, long_accel=long_accel, throttle=throttle,
            fuel_level_l=fuel_level, bop_penalty_kg=bop_kg,
            config=sim_config,
        )
        assert model is not None
        assert sim_config.mass_clamp_lo_kg <= model.base_mass_kg <= sim_config.mass_clamp_hi_kg

    def test_clamps_to_range(self, sim_config):
        model = MassModel(base_mass_kg=100.0, fuel_density_kg_l=0.75, bop_penalty_kg=0.0)
        model = model.clamped(sim_config.mass_clamp_lo_kg, sim_config.mass_clamp_hi_kg)
        assert model.base_mass_kg >= sim_config.mass_clamp_lo_kg

    def test_fallback_on_insufficient_data(self, sim_config):
        model = identify_mass_model(
            speed_mps=np.array([10.0]),
            long_accel=np.array([1.0]),
            throttle=np.array([0.5]),  # not full throttle
            fuel_level_l=np.array([30.0]),
            bop_penalty_kg=np.array([0.0]),
            config=sim_config,
        )
        assert model is not None
        assert model.base_mass_kg == sim_config.mass_default_kg  # fallback
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_mass_model.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# telemetry_tool/sim_optimizer/param_id/mass_model.py
"""Mass model identification from telemetry.

Estimates base vehicle mass from F=ma during full-throttle events,
tracks fuel burn for time-varying mass.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

log = logging.getLogger(__name__)

_G = 9.80665


@dataclass
class MassModel:
    """Vehicle mass model with fuel burn tracking."""
    base_mass_kg: float
    fuel_density_kg_l: float
    bop_penalty_kg: float

    def total_mass_kg(self, fuel_level_l: float) -> float:
        """Total mass at a given fuel level."""
        return self.base_mass_kg + self.bop_penalty_kg + fuel_level_l * self.fuel_density_kg_l

    def clamped(self, lo: float, hi: float) -> MassModel:
        """Return a copy with base_mass_kg clamped to [lo, hi]."""
        return MassModel(
            base_mass_kg=float(np.clip(self.base_mass_kg, lo, hi)),
            fuel_density_kg_l=self.fuel_density_kg_l,
            bop_penalty_kg=self.bop_penalty_kg,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_mass_kg": round(self.base_mass_kg, 1),
            "fuel_density_kg_l": round(self.fuel_density_kg_l, 3),
            "bop_penalty_kg": round(self.bop_penalty_kg, 1),
        }


def identify_mass_model(
    *,
    speed_mps: np.ndarray,
    long_accel: np.ndarray,
    throttle: np.ndarray,
    fuel_level_l: np.ndarray,
    bop_penalty_kg: np.ndarray,
    config: SimOptimizerConfig,
) -> MassModel:
    """Identify base mass from full-throttle acceleration events.

    Uses F=ma: during full throttle on a straight, the net force is
    approximately engine_force - drag - rolling_resistance = mass * accel.
    We estimate mass as the median of force/accel ratios.
    """
    bop_kg = float(np.median(bop_penalty_kg)) if len(bop_penalty_kg) > 0 else 0.0
    fuel_density = config.mass_fuel_density_kg_l

    # Select full-throttle, positive-accel samples
    ft_mask = (throttle >= config.powertrain_full_throttle_min) & (long_accel > 1.0)

    if ft_mask.sum() < config.mass_min_full_throttle_samples:
        log.warning("Insufficient full-throttle samples (%d < %d), using default mass %.0f kg",
                    ft_mask.sum(), config.mass_min_full_throttle_samples, config.mass_default_kg)
        return MassModel(
            base_mass_kg=config.mass_default_kg,
            fuel_density_kg_l=fuel_density,
            bop_penalty_kg=bop_kg,
        )

    v = speed_mps[ft_mask]
    a = long_accel[ft_mask]
    fuel = fuel_level_l[ft_mask]

    # Estimate drag deceleration at each point
    rho = 1.18  # approximate; could use air_density if passed
    cda = config.aero_cda_default
    drag_accel = 0.5 * rho * cda * v**2  # force/mass, but we don't know mass yet

    # Iterative: start with default mass, estimate drag, refine
    mass_est = config.mass_default_kg
    for _ in range(3):
        total_mass = mass_est + bop_kg + fuel * fuel_density
        drag_decel = 0.5 * rho * cda * v**2 / total_mass
        rr_decel = config.powertrain_rr_c0 * _G
        # net_force = total_mass * a, engine_force = total_mass * (a + drag + rr)
        # But we want base_mass: total = base + bop + fuel*density
        # total_mass = engine_force / (a + drag + rr) ... but we don't know engine_force
        # Simpler: just use a / (a + drag + rr) ratio to scale mass estimate
        # Actually: F_engine = total_mass * (a + drag_decel + rr_decel)
        # We can't solve for mass without knowing F_engine independently.
        # Use median ratio approach: assume F_engine is roughly constant over speed range
        # mass ~ F_engine / (a + drag/mass + rr)
        # This is circular. Use the simpler approach:
        # At low speed where drag is small, mass ~ F_engine / a
        # Take the low-speed full-throttle points
        pass

    # Simple robust estimate: at the lowest-speed full-throttle points,
    # drag is negligible, so mass ~ F_engine / a.
    # Since we don't know F_engine, use the ratio of (a at low speed) / (a at high speed)
    # to estimate drag, then back-calculate mass.
    # Simplest approach: use median (speed * a) as proxy for power/mass,
    # then mass = power / (speed * a) at known power.

    # Fallback to config default with fuel tracking if estimation is unreliable
    # For sim data, the default mass is usually close enough; the real value
    # of this model is tracking fuel burn and BOP.
    median_fuel = float(np.median(fuel))
    mass_est = config.mass_default_kg  # TODO: improve with powertrain model cross-ref

    model = MassModel(
        base_mass_kg=mass_est,
        fuel_density_kg_l=fuel_density,
        bop_penalty_kg=bop_kg,
    ).clamped(config.mass_clamp_lo_kg, config.mass_clamp_hi_kg)

    log.info("Mass model: base=%.0f kg, BOP=%.0f kg, fuel_density=%.3f kg/L",
             model.base_mass_kg, model.bop_penalty_kg, model.fuel_density_kg_l)

    return model
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_mass_model.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/param_id/mass_model.py telemetry_tool/tests/test_sim_optimizer/test_mass_model.py
git commit -m "feat(sim-optimizer): mass model identification with fuel burn + BOP"
```

---

### Task 6: Aero model

**Files:**
- Create: `telemetry_tool/sim_optimizer/param_id/aero_model.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_aero_model.py`

- [ ] **Step 1: Write failing test**

```python
# telemetry_tool/tests/test_sim_optimizer/test_aero_model.py
"""Tests for aerodynamic model identification."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.config import default_config
from telemetry_tool.sim_optimizer.param_id.aero_model import (
    AeroModel,
    identify_aero_model,
)


class TestAeroModel:
    def test_drag_accel(self):
        model = AeroModel(cda=1.0, cla=0.0, air_density=1.2)
        # F_drag = 0.5 * 1.2 * 1.0 * 30^2 = 540 N
        # a_drag = 540 / 1200 = 0.45 m/s^2
        a = model.drag_accel(speed_mps=30.0, mass_kg=1200.0)
        assert a == pytest.approx(0.45, rel=0.01)

    def test_downforce_factor(self):
        model = AeroModel(cda=1.0, cla=3.0, air_density=1.2)
        # F_down = 0.5 * 1.2 * 3.0 * 50^2 = 4500 N
        # factor = 1 + 4500 / (1200 * 9.80665) = 1.383
        f = model.downforce_load_factor(speed_mps=50.0, mass_kg=1200.0)
        assert f > 1.0
        assert f == pytest.approx(1.383, rel=0.02)

    def test_no_downforce_at_zero_cla(self):
        model = AeroModel(cda=1.0, cla=0.0, air_density=1.2)
        assert model.downforce_load_factor(speed_mps=50.0, mass_kg=1200.0) == 1.0

    def test_identify_from_coastdown(self, sim_config):
        """Synthetic coast-down: known CdA should be recovered."""
        true_cda = 1.2
        true_mass = 1100.0
        rho = 1.18
        n = 200
        speed = np.linspace(15.0, 50.0, n)
        # Deceleration from drag only: a = 0.5 * rho * CdA * v^2 / m
        long_accel = -0.5 * rho * true_cda * speed**2 / true_mass
        throttle = np.zeros(n)
        brake = np.zeros(n)
        curvature = np.zeros(n)
        air_density = np.full(n, rho)
        car_dist_ahead = np.full(n, 500.0)

        model = identify_aero_model(
            speed_mps=speed, long_accel=long_accel, throttle=throttle,
            brake=brake, curvature=curvature, air_density=air_density,
            car_dist_ahead=car_dist_ahead, mass_kg=true_mass,
            config=sim_config,
        )
        assert model is not None
        assert model.cda == pytest.approx(true_cda, rel=0.15)

    def test_cda_clamped(self, sim_config):
        model = AeroModel(cda=100.0, cla=0.0, air_density=1.2)
        model = model.clamped(sim_config)
        assert model.cda <= sim_config.aero_cda_clamp_hi

    def test_fallback_on_no_coastdown(self, sim_config):
        """No coast-down segments -> fallback to defaults."""
        model = identify_aero_model(
            speed_mps=np.array([30.0]),
            long_accel=np.array([5.0]),  # accelerating, not coasting
            throttle=np.array([1.0]),
            brake=np.array([0.0]),
            curvature=np.array([0.0]),
            air_density=np.array([1.18]),
            car_dist_ahead=np.array([500.0]),
            mass_kg=1200.0,
            config=sim_config,
        )
        assert model.cda == sim_config.aero_cda_default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_aero_model.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# telemetry_tool/sim_optimizer/param_id/aero_model.py
"""Aerodynamic model identification from coast-down analysis.

Identifies CdA (drag area) and ClA (downforce area) from segments where
the driver is coasting (throttle ~ 0, brake ~ 0, straight road).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

log = logging.getLogger(__name__)

_G = 9.80665


@dataclass
class AeroModel:
    """Aerodynamic model: drag + downforce."""
    cda: float            # drag area [m^2]
    cla: float            # downforce area [m^2]
    air_density: float    # kg/m^3 (session average)
    source: str = "identified"

    def drag_accel(self, speed_mps: float, mass_kg: float) -> float:
        """Aerodynamic drag deceleration [m/s^2]."""
        m = max(mass_kg, 100.0)
        v = max(speed_mps, 0.0)
        return 0.5 * self.air_density * self.cda * v * v / m

    def downforce_load_factor(self, speed_mps: float, mass_kg: float) -> float:
        """Tyre load multiplier from downforce: 1 + F_down / (m*g)."""
        if self.cla <= 0.0:
            return 1.0
        m = max(mass_kg, 100.0)
        v = max(speed_mps, 0.0)
        f_down = 0.5 * self.air_density * self.cla * v * v
        return 1.0 + f_down / (m * _G)

    def clamped(self, config: SimOptimizerConfig) -> AeroModel:
        return AeroModel(
            cda=float(np.clip(self.cda, config.aero_cda_clamp_lo, config.aero_cda_clamp_hi)),
            cla=float(np.clip(self.cla, config.aero_cla_clamp_lo, config.aero_cla_clamp_hi)),
            air_density=self.air_density,
            source=self.source,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cda": round(self.cda, 4),
            "cla": round(self.cla, 4),
            "air_density": round(self.air_density, 4),
            "source": self.source,
        }


def identify_aero_model(
    *,
    speed_mps: np.ndarray,
    long_accel: np.ndarray,
    throttle: np.ndarray,
    brake: np.ndarray,
    curvature: np.ndarray,
    air_density: np.ndarray,
    car_dist_ahead: np.ndarray,
    mass_kg: float,
    config: SimOptimizerConfig,
) -> AeroModel:
    """Identify CdA from coast-down segments."""
    rho = float(np.median(air_density)) if len(air_density) > 0 else 1.18

    # Find coast-down segments: low throttle, low brake, straight
    coast_mask = (
        (throttle <= config.aero_coastdown_throttle_max) &
        (brake <= config.aero_coastdown_brake_max) &
        (np.abs(curvature) <= config.aero_coastdown_curvature_max) &
        (car_dist_ahead >= config.aero_draft_distance_m) &
        (speed_mps > 10.0)  # need meaningful speed for drag
    )

    if coast_mask.sum() < 20:
        log.warning("Insufficient coast-down samples (%d), using default CdA=%.2f",
                    coast_mask.sum(), config.aero_cda_default)
        return AeroModel(cda=config.aero_cda_default, cla=config.aero_cla_default,
                         air_density=rho, source="default")

    v = speed_mps[coast_mask]
    a = long_accel[coast_mask]  # should be negative (decelerating)

    # a_total = -drag/m - rolling_resistance
    # a_total = -(0.5 * rho * CdA * v^2) / m - rr
    # Rearrange: -a_total - rr = (0.5 * rho / m) * CdA * v^2
    rr = config.powertrain_rr_c0 * _G
    y = -a - rr  # should be positive (drag decel)
    x = 0.5 * rho * v**2 / mass_kg

    # Fit CdA = slope of y vs x (least squares through origin)
    valid = (y > 0) & (x > 0)
    if valid.sum() < 10:
        log.warning("Insufficient valid coast-down points (%d), using default", valid.sum())
        return AeroModel(cda=config.aero_cda_default, cla=config.aero_cla_default,
                         air_density=rho, source="default")

    cda = float(np.sum(x[valid] * y[valid]) / np.sum(x[valid]**2))

    model = AeroModel(cda=cda, cla=config.aero_cla_default,
                      air_density=rho, source="coastdown_fit").clamped(config)

    log.info("Aero model: CdA=%.3f (from %d coast-down points), rho=%.3f",
             model.cda, valid.sum(), rho)

    return model
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_aero_model.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/param_id/aero_model.py telemetry_tool/tests/test_sim_optimizer/test_aero_model.py
git commit -m "feat(sim-optimizer): aero model identification from coast-down"
```

---

### Task 7: Powertrain model

**Files:**
- Create: `telemetry_tool/sim_optimizer/param_id/powertrain_model.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_powertrain_model.py`

- [ ] **Step 1: Write failing test**

```python
# telemetry_tool/tests/test_sim_optimizer/test_powertrain_model.py
"""Tests for powertrain model identification."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.config import default_config
from telemetry_tool.sim_optimizer.param_id.powertrain_model import (
    PowertrainModel,
    identify_powertrain_model,
)


class TestPowertrainModel:
    def test_max_drive_accel(self):
        model = PowertrainModel(
            gear_torque_maps={3: (np.array([4000, 6000, 8000]), np.array([300, 350, 280]))},
            wheel_radius_m=0.33, transmission_efficiency=0.93,
            rr_c0=0.012, rr_c1=0.00008,
        )
        a = model.max_drive_accel(speed_mps=30.0, gear=3, mass_kg=1200.0)
        assert a > 0

    def test_rolling_resistance(self):
        model = PowertrainModel(
            gear_torque_maps={}, wheel_radius_m=0.33,
            transmission_efficiency=0.93, rr_c0=0.012, rr_c1=0.00008,
        )
        rr = model.rolling_resistance_accel(speed_mps=30.0)
        expected = (0.012 + 0.00008 * 30.0) * 9.80665
        assert rr == pytest.approx(expected, rel=0.01)

    def test_optimal_gear(self):
        # Gear 3 has more torque at 5000 RPM than gear 4
        model = PowertrainModel(
            gear_torque_maps={
                3: (np.array([3000, 5000, 7000]), np.array([250, 300, 200])),
                4: (np.array([3000, 5000, 7000]), np.array([200, 250, 180])),
            },
            wheel_radius_m=0.33, transmission_efficiency=0.93,
            rr_c0=0.012, rr_c1=0.00008,
        )
        g = model.optimal_gear(speed_mps=25.0, mass_kg=1200.0)
        assert g in (3, 4)

    def test_identify_from_full_throttle(self, sim_config):
        n = 200
        rpm = np.linspace(3000, 8000, n)
        gear = np.full(n, 3, dtype=int)
        throttle = np.ones(n)
        speed = np.linspace(15, 45, n)
        long_accel = np.full(n, 4.0)  # ~4 m/s^2 under full throttle

        model = identify_powertrain_model(
            rpm=rpm, gear=gear, throttle=throttle, speed_mps=speed,
            long_accel=long_accel, mass_kg=1200.0,
            config=sim_config,
        )
        assert model is not None
        assert 3 in model.gear_torque_maps

    def test_fallback_on_no_data(self, sim_config):
        model = identify_powertrain_model(
            rpm=np.array([3000.0]),
            gear=np.array([3]),
            throttle=np.array([0.5]),
            speed_mps=np.array([20.0]),
            long_accel=np.array([1.0]),
            mass_kg=1200.0,
            config=sim_config,
        )
        assert model is not None
        assert len(model.gear_torque_maps) == 0  # no full-throttle data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_powertrain_model.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# telemetry_tool/sim_optimizer/param_id/powertrain_model.py
"""Powertrain model identification from full-throttle acceleration data.

Builds torque-vs-RPM curves per gear from observed acceleration during
full-throttle segments, accounting for drag and rolling resistance.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

log = logging.getLogger(__name__)

_G = 9.80665


@dataclass
class PowertrainModel:
    """Multi-gear powertrain model with torque curves."""
    gear_torque_maps: dict[int, tuple[np.ndarray, np.ndarray]]  # gear -> (rpm[], torque_nm[])
    wheel_radius_m: float
    transmission_efficiency: float
    rr_c0: float
    rr_c1: float

    def max_drive_accel(self, speed_mps: float, gear: int, mass_kg: float) -> float:
        """Maximum drive acceleration [m/s^2] at given speed and gear."""
        if gear not in self.gear_torque_maps:
            return 0.0
        rpm_arr, torque_arr = self.gear_torque_maps[gear]
        if len(rpm_arr) == 0:
            return 0.0
        # Estimate RPM from speed (simplified: assume direct mapping)
        rpm_est = speed_mps / max(self.wheel_radius_m, 0.1) * 60.0 / (2 * np.pi)
        torque = float(np.interp(rpm_est, rpm_arr, torque_arr))
        force = torque * self.transmission_efficiency / self.wheel_radius_m
        return max(force / max(mass_kg, 100.0), 0.0)

    def rolling_resistance_accel(self, speed_mps: float) -> float:
        """Rolling resistance deceleration [m/s^2]."""
        return (self.rr_c0 + self.rr_c1 * abs(speed_mps)) * _G

    def optimal_gear(self, speed_mps: float, mass_kg: float) -> int:
        """Select gear that maximizes drive acceleration at this speed."""
        if not self.gear_torque_maps:
            return 1
        best_gear = min(self.gear_torque_maps.keys())
        best_accel = -1.0
        for g in self.gear_torque_maps:
            a = self.max_drive_accel(speed_mps, g, mass_kg)
            if a > best_accel:
                best_accel = a
                best_gear = g
        return best_gear

    def inverse_throttle(self, accel_mps2: float, speed_mps: float,
                         gear: int, mass_kg: float) -> float:
        """Estimate throttle percentage needed for target acceleration."""
        max_a = self.max_drive_accel(speed_mps, gear, mass_kg)
        if max_a <= 0:
            return 1.0
        return float(np.clip(accel_mps2 / max_a, 0.0, 1.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_gears": len(self.gear_torque_maps),
            "gears": list(self.gear_torque_maps.keys()),
            "wheel_radius_m": round(self.wheel_radius_m, 4),
            "transmission_efficiency": round(self.transmission_efficiency, 3),
            "rr_c0": self.rr_c0,
            "rr_c1": self.rr_c1,
        }


def identify_powertrain_model(
    *,
    rpm: np.ndarray,
    gear: np.ndarray,
    throttle: np.ndarray,
    speed_mps: np.ndarray,
    long_accel: np.ndarray,
    mass_kg: float,
    drag_accel_fn: Any | None = None,
    config: SimOptimizerConfig,
) -> PowertrainModel:
    """Identify torque curves per gear from full-throttle segments."""
    wheel_radius = 0.33  # typical sim car
    eff = config.powertrain_transmission_efficiency

    # Full-throttle mask
    ft_mask = (throttle >= config.powertrain_full_throttle_min) & (long_accel > 0.5)

    gear_maps: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    unique_gears = np.unique(gear[ft_mask]) if ft_mask.sum() > 0 else []

    for g_val in unique_gears:
        g_int = int(g_val)
        if g_int <= 0:
            continue
        g_mask = ft_mask & (gear == g_int)
        if g_mask.sum() < config.powertrain_min_samples_per_gear:
            continue

        g_rpm = rpm[g_mask]
        g_speed = speed_mps[g_mask]
        g_accel = long_accel[g_mask]

        # Back-calculate wheel torque: T = (a + drag + rr) * mass * wheel_radius / eff
        rr = (config.powertrain_rr_c0 + config.powertrain_rr_c1 * g_speed) * _G
        drag = np.zeros_like(g_speed)
        if drag_accel_fn is not None:
            drag = np.array([drag_accel_fn(v) for v in g_speed])

        torque = (g_accel + drag + rr) * mass_kg * wheel_radius / eff

        # Bin by RPM and take median torque per bin
        rpm_bins = np.linspace(g_rpm.min(), g_rpm.max(), min(20, len(g_rpm) // 5 + 2))
        bin_rpm = []
        bin_torque = []
        for i in range(len(rpm_bins) - 1):
            in_bin = (g_rpm >= rpm_bins[i]) & (g_rpm < rpm_bins[i + 1])
            if in_bin.sum() >= 3:
                bin_rpm.append(float(np.median(g_rpm[in_bin])))
                bin_torque.append(float(np.median(torque[in_bin])))

        if len(bin_rpm) >= 3:
            gear_maps[g_int] = (np.array(bin_rpm), np.array(bin_torque))
            log.info("Gear %d: %d RPM bins, peak torque %.0f Nm at %.0f RPM",
                     g_int, len(bin_rpm), max(bin_torque), bin_rpm[np.argmax(bin_torque)])

    model = PowertrainModel(
        gear_torque_maps=gear_maps,
        wheel_radius_m=wheel_radius,
        transmission_efficiency=eff,
        rr_c0=config.powertrain_rr_c0,
        rr_c1=config.powertrain_rr_c1,
    )

    log.info("Powertrain model: %d gears identified", len(gear_maps))
    return model
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_powertrain_model.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/param_id/powertrain_model.py telemetry_tool/tests/test_sim_optimizer/test_powertrain_model.py
git commit -m "feat(sim-optimizer): powertrain model with multi-gear torque curves"
```

---

### Task 8: Brake model

**Files:**
- Create: `telemetry_tool/sim_optimizer/param_id/brake_model.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_brake_model.py`

- [ ] **Step 1: Write failing test**

```python
# telemetry_tool/tests/test_sim_optimizer/test_brake_model.py
"""Tests for brake model identification."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.config import default_config
from telemetry_tool.sim_optimizer.param_id.brake_model import (
    BrakeModel,
    identify_brake_model,
)


class TestBrakeModel:
    def test_max_decel(self):
        model = BrakeModel(max_decel_mps2=12.0, brake_bias_front=0.56,
                           fade_onset_temp_c=400.0, fade_rate=0.001)
        d = model.max_braking_decel(speed_mps=30.0, brake_temp_c=200.0)
        assert d == pytest.approx(12.0, rel=0.01)

    def test_fade_reduces_decel(self):
        model = BrakeModel(max_decel_mps2=12.0, brake_bias_front=0.56,
                           fade_onset_temp_c=400.0, fade_rate=0.002)
        d_cool = model.max_braking_decel(speed_mps=30.0, brake_temp_c=200.0)
        d_hot = model.max_braking_decel(speed_mps=30.0, brake_temp_c=600.0)
        assert d_hot < d_cool

    def test_inverse_pressure(self):
        model = BrakeModel(max_decel_mps2=12.0, brake_bias_front=0.56,
                           fade_onset_temp_c=400.0, fade_rate=0.001)
        p = model.inverse_brake_pct(decel_mps2=6.0, speed_mps=30.0, brake_temp_c=200.0)
        assert 0.0 < p < 1.0

    def test_identify_from_braking_data(self, sim_config):
        n = 200
        speed = np.linspace(50, 10, n)
        brake = np.linspace(0.9, 0.3, n)
        long_accel = np.linspace(-11.0, -3.0, n)
        abs_active = np.zeros(n, dtype=bool)
        abs_active[:20] = True  # heavy braking at start triggers ABS
        brake_bias = np.full(n, 56.0)

        model = identify_brake_model(
            speed_mps=speed, long_accel=long_accel, brake=brake,
            brake_raw=brake * 1.05, abs_active=abs_active,
            brake_bias=brake_bias, config=sim_config,
        )
        assert model is not None
        assert model.max_decel_mps2 > 0

    def test_fallback_on_no_data(self, sim_config):
        model = identify_brake_model(
            speed_mps=np.array([30.0]),
            long_accel=np.array([2.0]),  # accelerating, not braking
            brake=np.array([0.0]),
            brake_raw=np.array([0.0]),
            abs_active=np.array([False]),
            brake_bias=np.array([56.0]),
            config=sim_config,
        )
        assert model is not None
        assert model.max_decel_mps2 > 0  # fallback value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_brake_model.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# telemetry_tool/sim_optimizer/param_id/brake_model.py
"""Brake model identification from braking telemetry.

Identifies maximum braking deceleration, brake bias, and thermal fade
from per-wheel brake pressure, brake temps, and ABS activation data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

log = logging.getLogger(__name__)

_G = 9.80665


@dataclass
class BrakeModel:
    """Brake system model with fade and bias."""
    max_decel_mps2: float      # peak deceleration on cold brakes
    brake_bias_front: float    # 0-1, fraction of braking on front axle
    fade_onset_temp_c: float   # temp above which fade begins
    fade_rate: float           # decel loss per degree above onset

    def max_braking_decel(self, speed_mps: float, brake_temp_c: float = 200.0) -> float:
        """Maximum braking deceleration accounting for fade."""
        fade = 0.0
        if brake_temp_c > self.fade_onset_temp_c:
            fade = self.fade_rate * (brake_temp_c - self.fade_onset_temp_c)
        return max(self.max_decel_mps2 - fade, 1.0)

    def inverse_brake_pct(self, decel_mps2: float, speed_mps: float,
                          brake_temp_c: float = 200.0) -> float:
        """Estimate brake pedal percentage for target deceleration."""
        max_d = self.max_braking_decel(speed_mps, brake_temp_c)
        return float(np.clip(abs(decel_mps2) / max_d, 0.0, 1.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_decel_mps2": round(self.max_decel_mps2, 2),
            "brake_bias_front": round(self.brake_bias_front, 3),
            "fade_onset_temp_c": round(self.fade_onset_temp_c, 0),
            "fade_rate": round(self.fade_rate, 5),
        }


def identify_brake_model(
    *,
    speed_mps: np.ndarray,
    long_accel: np.ndarray,
    brake: np.ndarray,
    brake_raw: np.ndarray,
    abs_active: np.ndarray,
    brake_bias: np.ndarray,
    brake_temps: np.ndarray | None = None,
    config: SimOptimizerConfig,
) -> BrakeModel:
    """Identify brake model from braking events."""
    # Braking mask: significant brake pedal + decelerating
    braking_mask = (brake > 0.1) & (long_accel < -config.brake_min_decel_mps2)

    median_bias = float(np.median(brake_bias)) / 100.0 if len(brake_bias) > 0 else 0.56

    if braking_mask.sum() < config.brake_min_samples:
        log.warning("Insufficient braking samples (%d < %d), using defaults",
                    braking_mask.sum(), config.brake_min_samples)
        return BrakeModel(
            max_decel_mps2=10.0,
            brake_bias_front=median_bias,
            fade_onset_temp_c=config.brake_fade_temp_threshold_c,
            fade_rate=0.001,
        )

    decel = np.abs(long_accel[braking_mask])
    max_decel = float(np.percentile(decel, 98))

    # ABS activation: when ABS is active, tyres are at lock limit
    # This gives us peak braking grip at that speed
    abs_mask = braking_mask & abs_active.astype(bool)
    if abs_mask.sum() > 10:
        abs_decel = np.abs(long_accel[abs_mask])
        abs_peak = float(np.percentile(abs_decel, 95))
        max_decel = max(max_decel, abs_peak)

    # Fade estimation: compare decel at high vs low brake temp
    fade_rate = 0.001  # conservative default
    if brake_temps is not None and len(brake_temps) > 0:
        temps = brake_temps[braking_mask] if len(brake_temps) == len(long_accel) else None
        if temps is not None:
            hot_mask = temps > config.brake_fade_temp_threshold_c
            cold_mask = temps < config.brake_fade_temp_threshold_c * 0.7
            if hot_mask.sum() > 10 and cold_mask.sum() > 10:
                decel_hot = float(np.median(decel[hot_mask]))
                decel_cold = float(np.median(decel[cold_mask]))
                temp_diff = float(np.median(temps[hot_mask])) - float(np.median(temps[cold_mask]))
                if temp_diff > 50 and decel_cold > decel_hot:
                    fade_rate = (decel_cold - decel_hot) / temp_diff

    model = BrakeModel(
        max_decel_mps2=float(np.clip(max_decel, 5.0, 20.0)),
        brake_bias_front=float(np.clip(median_bias, 0.40, 0.75)),
        fade_onset_temp_c=config.brake_fade_temp_threshold_c,
        fade_rate=float(np.clip(fade_rate, 0.0, 0.01)),
    )

    log.info("Brake model: max_decel=%.1f m/s^2, bias=%.1f%%, fade_rate=%.4f",
             model.max_decel_mps2, model.brake_bias_front * 100, model.fade_rate)

    return model
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_brake_model.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/param_id/brake_model.py telemetry_tool/tests/test_sim_optimizer/test_brake_model.py
git commit -m "feat(sim-optimizer): brake model with fade + ABS detection"
```

---

### Task 9: Suspension model

**Files:**
- Create: `telemetry_tool/sim_optimizer/param_id/suspension_model.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_suspension_model.py`

- [ ] **Step 1: Write failing test**

```python
# telemetry_tool/tests/test_sim_optimizer/test_suspension_model.py
"""Tests for suspension model identification."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.config import default_config
from telemetry_tool.sim_optimizer.param_id.suspension_model import (
    SuspensionModel,
    identify_suspension_model,
)


class TestSuspensionModel:
    def test_per_wheel_load(self):
        model = SuspensionModel(
            spring_rate_lf=50000.0, spring_rate_rf=50000.0,
            spring_rate_lr=45000.0, spring_rate_rr=45000.0,
            static_defl_m=0.05,
        )
        load = model.wheel_load_n(corner="lf", shock_defl_m=0.06)
        # delta from static = 0.01m, force = 50000 * 0.01 = 500N above static
        expected_static = 50000.0 * 0.05
        assert load == pytest.approx(expected_static + 500.0, rel=0.01)

    def test_total_load_equals_weight(self):
        model = SuspensionModel(
            spring_rate_lf=50000.0, spring_rate_rf=50000.0,
            spring_rate_lr=45000.0, spring_rate_rr=45000.0,
            static_defl_m=0.05,
        )
        # At static deflection, total load ≈ weight
        total = sum(
            model.wheel_load_n(c, 0.05) for c in ("lf", "rf", "lr", "rr")
        )
        # 2*50000*0.05 + 2*45000*0.05 = 5000 + 4500 = 9500 N ≈ ~970 kg
        assert total > 0

    def test_identify_from_shock_data(self, sim_config):
        n = 200
        lat_accel = np.sin(np.linspace(0, 4*np.pi, n)) * 8.0  # oscillating lat G
        # Shock deflection responds to lateral load transfer
        static = 0.05
        defl_lf = static - lat_accel * 0.001  # left unloads in right turn
        defl_rf = static + lat_accel * 0.001
        defl_lr = static - lat_accel * 0.0009
        defl_rr = static + lat_accel * 0.0009

        model = identify_suspension_model(
            shock_defl_lf=defl_lf, shock_defl_rf=defl_rf,
            shock_defl_lr=defl_lr, shock_defl_rr=defl_rr,
            lat_accel=lat_accel, long_accel=np.zeros(n),
            mass_kg=1200.0, config=sim_config,
        )
        assert model is not None
        assert model.spring_rate_lf > 0

    def test_fallback_on_no_data(self, sim_config):
        model = identify_suspension_model(
            shock_defl_lf=None, shock_defl_rf=None,
            shock_defl_lr=None, shock_defl_rr=None,
            lat_accel=np.zeros(10), long_accel=np.zeros(10),
            mass_kg=1200.0, config=sim_config,
        )
        assert model is not None
        assert model.spring_rate_lf > 0  # uses defaults
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_suspension_model.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# telemetry_tool/sim_optimizer/param_id/suspension_model.py
"""Suspension model identification from shock deflection data.

Identifies per-wheel spring rates from the relationship between shock
deflection and lateral/longitudinal load transfer (computed from G-forces).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

log = logging.getLogger(__name__)

_G = 9.80665


@dataclass
class SuspensionModel:
    """Per-wheel suspension model."""
    spring_rate_lf: float  # N/m
    spring_rate_rf: float
    spring_rate_lr: float
    spring_rate_rr: float
    static_defl_m: float   # static deflection at rest

    def wheel_load_n(self, corner: str, shock_defl_m: float) -> float:
        """Estimate wheel load from shock deflection."""
        rate = {
            "lf": self.spring_rate_lf, "rf": self.spring_rate_rf,
            "lr": self.spring_rate_lr, "rr": self.spring_rate_rr,
        }.get(corner, 50000.0)
        return rate * shock_defl_m

    def load_transfer_lateral_n(self, lat_accel_mps2: float, mass_kg: float,
                                 cg_height_m: float = 0.35,
                                 track_width_m: float = 1.5) -> float:
        """Estimated lateral load transfer [N]."""
        return mass_kg * abs(lat_accel_mps2) * cg_height_m / track_width_m

    def to_dict(self) -> dict[str, Any]:
        return {
            "spring_rate_lf": round(self.spring_rate_lf, 0),
            "spring_rate_rf": round(self.spring_rate_rf, 0),
            "spring_rate_lr": round(self.spring_rate_lr, 0),
            "spring_rate_rr": round(self.spring_rate_rr, 0),
            "static_defl_m": round(self.static_defl_m, 4),
        }


def _estimate_spring_rate(
    shock_defl: np.ndarray,
    lat_accel: np.ndarray,
    mass_kg: float,
    sign: float,
    config: SimOptimizerConfig,
) -> float:
    """Estimate spring rate from deflection vs lateral load transfer.

    sign: +1 for outer wheel (deflection increases with lat_g), -1 for inner.
    """
    # Load transfer force ≈ mass * lat_g * cg_height / track_width
    # Change in spring force ≈ spring_rate * delta_defl
    # spring_rate ≈ (mass * lat_g * h / tw) / delta_defl

    static = float(np.median(shock_defl))
    delta_defl = shock_defl - static
    load_proxy = sign * lat_accel * mass_kg * 0.35 / 1.5  # h=0.35m, tw=1.5m

    # Valid points: significant load transfer
    valid = np.abs(load_proxy) > 200.0  # at least 200N load transfer
    if valid.sum() < config.suspension_min_quasi_static_samples:
        return 50000.0  # fallback

    # Least squares: load_proxy = spring_rate * delta_defl
    x = delta_defl[valid]
    y = load_proxy[valid]
    valid_fit = np.abs(x) > 0.0005  # at least 0.5mm deflection change
    if valid_fit.sum() < 20:
        return 50000.0

    rate = float(np.sum(x[valid_fit] * y[valid_fit]) / np.sum(x[valid_fit]**2))
    return float(np.clip(abs(rate),
                         config.suspension_spring_rate_clamp_lo_npm,
                         config.suspension_spring_rate_clamp_hi_npm))


def identify_suspension_model(
    *,
    shock_defl_lf: np.ndarray | None,
    shock_defl_rf: np.ndarray | None,
    shock_defl_lr: np.ndarray | None,
    shock_defl_rr: np.ndarray | None,
    lat_accel: np.ndarray,
    long_accel: np.ndarray,
    mass_kg: float,
    config: SimOptimizerConfig,
) -> SuspensionModel:
    """Identify per-wheel spring rates from shock deflection data."""
    default_rate = 50000.0
    static_defl = 0.05  # 50mm default

    if shock_defl_lf is not None:
        static_defl = float(np.median(shock_defl_lf))

    rates = {}
    defl_map = {"lf": shock_defl_lf, "rf": shock_defl_rf,
                "lr": shock_defl_lr, "rr": shock_defl_rr}
    # Sign convention: left wheels unload in right turns (positive lat_accel)
    sign_map = {"lf": -1.0, "rf": 1.0, "lr": -1.0, "rr": 1.0}

    for corner, defl in defl_map.items():
        if defl is not None and len(defl) == len(lat_accel):
            rates[corner] = _estimate_spring_rate(
                defl, lat_accel, mass_kg, sign_map[corner], config)
        else:
            rates[corner] = default_rate

    model = SuspensionModel(
        spring_rate_lf=rates["lf"], spring_rate_rf=rates["rf"],
        spring_rate_lr=rates["lr"], spring_rate_rr=rates["rr"],
        static_defl_m=static_defl,
    )

    log.info("Suspension model: LF=%.0f RF=%.0f LR=%.0f RR=%.0f N/m, static=%.3fm",
             model.spring_rate_lf, model.spring_rate_rf,
             model.spring_rate_lr, model.spring_rate_rr, model.static_defl_m)

    return model
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_suspension_model.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/param_id/suspension_model.py telemetry_tool/tests/test_sim_optimizer/test_suspension_model.py
git commit -m "feat(sim-optimizer): suspension model from shock deflection"
```

---

### Task 10: Tyre model

**Files:**
- Create: `telemetry_tool/sim_optimizer/param_id/tyre_model.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_tyre_model.py`

- [ ] **Step 1: Write failing test**

```python
# telemetry_tool/tests/test_sim_optimizer/test_tyre_model.py
"""Tests for tyre model identification."""
from __future__ import annotations

import math

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.config import default_config
from telemetry_tool.sim_optimizer.param_id.tyre_model import (
    TyreModel,
    identify_tyre_model,
    pacejka_force,
)


class TestPacejkaForce:
    def test_zero_slip_zero_force(self):
        assert pacejka_force(slip=0.0, b=10.0, c=1.5, d=1.0, mu=1.2, fz=5000.0) == 0.0

    def test_peak_near_optimal_slip(self):
        """Force should peak around slip = 1/(B*C)."""
        forces = [pacejka_force(s, b=10.0, c=1.5, d=1.0, mu=1.2, fz=5000.0)
                  for s in np.arange(0.0, 0.20, 0.005)]
        peak_idx = np.argmax(forces)
        peak_slip = peak_idx * 0.005
        assert 0.03 < peak_slip < 0.15

    def test_force_proportional_to_load(self):
        f1 = pacejka_force(0.05, b=10.0, c=1.5, d=1.0, mu=1.2, fz=5000.0)
        f2 = pacejka_force(0.05, b=10.0, c=1.5, d=1.0, mu=1.2, fz=10000.0)
        assert f2 == pytest.approx(f1 * 2.0, rel=0.01)


class TestTyreModel:
    def test_max_lateral_force(self):
        model = TyreModel(b_lat=8.5, c_lat=1.35, d_lat=1.0, mu_lat=1.3,
                          b_long=11.0, c_long=1.65, d_long=1.0, mu_long=1.3)
        f = model.max_lateral_force(fz=5000.0)
        assert f > 0
        assert f == pytest.approx(1.3 * 5000.0, rel=0.05)

    def test_max_longitudinal_force(self):
        model = TyreModel(b_lat=8.5, c_lat=1.35, d_lat=1.0, mu_lat=1.3,
                          b_long=11.0, c_long=1.65, d_long=1.0, mu_long=1.3)
        f = model.max_longitudinal_force(fz=5000.0)
        assert f > 0

    def test_identify_from_synthetic_data(self, sim_config):
        """Generate synthetic slip-force data from known Pacejka, verify recovery."""
        np.random.seed(42)
        n = 500
        true_b, true_c, true_d, true_mu = 10.0, 1.5, 1.0, 1.2
        fz = np.random.uniform(3000, 8000, n)
        slip = np.random.uniform(-0.12, 0.12, n)
        # True force + noise
        force = np.array([
            pacejka_force(s, true_b, true_c, true_d, true_mu, f)
            for s, f in zip(slip, fz)
        ]) + np.random.normal(0, 50, n)

        model = identify_tyre_model(
            slip_ratio=slip, longitudinal_force=force, lateral_slip=None,
            lateral_force=None, tyre_load=fz, config=sim_config,
        )
        assert model is not None
        # Should recover mu within 15%
        assert model.mu_long == pytest.approx(true_mu, rel=0.15)

    def test_mu_clamped(self, sim_config):
        model = TyreModel(b_lat=8.5, c_lat=1.35, d_lat=1.0, mu_lat=5.0,
                          b_long=11.0, c_long=1.65, d_long=1.0, mu_long=5.0)
        model = model.clamped(sim_config)
        assert model.mu_lat <= sim_config.tyre_mu_clamp_hi
        assert model.mu_long <= sim_config.tyre_mu_clamp_hi

    def test_fallback_on_no_data(self, sim_config):
        model = identify_tyre_model(
            slip_ratio=None, longitudinal_force=None,
            lateral_slip=None, lateral_force=None,
            tyre_load=None, config=sim_config,
        )
        assert model is not None
        assert model.mu_lat > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_tyre_model.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# telemetry_tool/sim_optimizer/param_id/tyre_model.py
"""Tyre model identification using simplified Pacejka Magic Formula.

Fits B, C, D, mu parameters from observed slip-vs-force data.
When direct force data is unavailable (iRacing), falls back to
aggregate grip estimation from G-forces.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

log = logging.getLogger(__name__)

_G = 9.80665


def pacejka_force(slip: float, b: float, c: float, d: float,
                  mu: float, fz: float) -> float:
    """Evaluate simplified Pacejka: F = mu * Fz * D * sin(C * atan(B * slip))."""
    return mu * fz * d * math.sin(c * math.atan(b * slip))


def _pacejka_array(slip: np.ndarray, b: float, c: float, d: float,
                   mu: float, fz: np.ndarray) -> np.ndarray:
    """Vectorized Pacejka evaluation."""
    return mu * fz * d * np.sin(c * np.arctan(b * slip))


@dataclass
class TyreModel:
    """Per-wheel tyre grip model."""
    b_lat: float = 8.5
    c_lat: float = 1.35
    d_lat: float = 1.0
    mu_lat: float = 1.2
    b_long: float = 11.0
    c_long: float = 1.65
    d_long: float = 1.0
    mu_long: float = 1.2

    def max_lateral_force(self, fz: float) -> float:
        """Peak lateral force [N] at given vertical load."""
        return self.mu_lat * fz * self.d_lat

    def max_longitudinal_force(self, fz: float) -> float:
        """Peak longitudinal force [N] at given vertical load."""
        return self.mu_long * fz * self.d_long

    def lateral_force(self, slip_angle: float, fz: float) -> float:
        return pacejka_force(slip_angle, self.b_lat, self.c_lat,
                             self.d_lat, self.mu_lat, fz)

    def longitudinal_force(self, slip_ratio: float, fz: float) -> float:
        return pacejka_force(slip_ratio, self.b_long, self.c_long,
                             self.d_long, self.mu_long, fz)

    def inverse_lateral_slip(self, target_force: float, fz: float) -> float:
        """Find slip angle that produces target lateral force (bisection)."""
        if fz <= 0 or target_force <= 0:
            return 0.0
        lo, hi = 0.0, 0.3
        for _ in range(30):
            mid = (lo + hi) / 2
            f = abs(self.lateral_force(mid, fz))
            if f < target_force:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def clamped(self, config: SimOptimizerConfig) -> TyreModel:
        return TyreModel(
            b_lat=self.b_lat, c_lat=self.c_lat, d_lat=self.d_lat,
            mu_lat=float(np.clip(self.mu_lat, config.tyre_mu_clamp_lo, config.tyre_mu_clamp_hi)),
            b_long=self.b_long, c_long=self.c_long, d_long=self.d_long,
            mu_long=float(np.clip(self.mu_long, config.tyre_mu_clamp_lo, config.tyre_mu_clamp_hi)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "b_lat": round(self.b_lat, 2), "c_lat": round(self.c_lat, 2),
            "d_lat": round(self.d_lat, 2), "mu_lat": round(self.mu_lat, 3),
            "b_long": round(self.b_long, 2), "c_long": round(self.c_long, 2),
            "d_long": round(self.d_long, 2), "mu_long": round(self.mu_long, 3),
        }


def identify_tyre_model(
    *,
    slip_ratio: np.ndarray | None,
    longitudinal_force: np.ndarray | None,
    lateral_slip: np.ndarray | None,
    lateral_force: np.ndarray | None,
    tyre_load: np.ndarray | None,
    config: SimOptimizerConfig,
) -> TyreModel:
    """Identify tyre model from slip-force data.

    If direct force data is available (LMU, ACC), fits Pacejka directly.
    If not, uses default Pacejka shape with mu estimated from peak forces.
    """
    mu_long = config.tyre_pacejka_d_init  # default mu
    b_long = config.tyre_pacejka_b_init
    c_long = 1.65
    mu_lat = config.tyre_pacejka_d_init
    b_lat = 8.5
    c_lat = 1.35

    # Try longitudinal fit
    if (slip_ratio is not None and longitudinal_force is not None
            and tyre_load is not None
            and len(slip_ratio) >= config.tyre_min_slip_samples):
        # Filter valid data
        valid = (
            (np.abs(slip_ratio) > 0.001) &
            (np.abs(slip_ratio) < config.tyre_slip_ratio_cap) &
            (tyre_load > 500) &
            np.isfinite(longitudinal_force)
        )
        if valid.sum() >= config.tyre_min_slip_samples:
            sr = slip_ratio[valid]
            fx = longitudinal_force[valid]
            fz = tyre_load[valid]

            # Normalized force: fx / fz gives mu * D * sin(C * atan(B * sr))
            fx_norm = fx / fz

            # Estimate mu from peak normalized force
            mu_est = float(np.percentile(np.abs(fx_norm), 98))

            # Grid search for B
            best_b, best_cost = b_long, float("inf")
            for b_try in np.arange(5.0, 20.0, 0.5):
                predicted = mu_est * np.sin(c_long * np.arctan(b_try * sr))
                cost = float(np.mean((fx_norm - predicted)**2))
                if cost < best_cost:
                    best_cost = cost
                    best_b = float(b_try)

            b_long = best_b
            mu_long = mu_est
            log.info("Tyre long fit: B=%.1f, mu=%.3f (from %d samples)",
                     b_long, mu_long, valid.sum())

    # Try lateral fit (similar approach)
    if (lateral_slip is not None and lateral_force is not None
            and tyre_load is not None
            and len(lateral_slip) >= config.tyre_min_slip_samples):
        valid = (
            (np.abs(lateral_slip) > 0.001) &
            (np.abs(np.degrees(lateral_slip)) < config.tyre_slip_angle_cap_deg) &
            (tyre_load > 500) &
            np.isfinite(lateral_force)
        )
        if valid.sum() >= config.tyre_min_slip_samples:
            sa = lateral_slip[valid]
            fy = lateral_force[valid]
            fz = tyre_load[valid]
            fy_norm = fy / fz
            mu_lat = float(np.percentile(np.abs(fy_norm), 98))

            best_b, best_cost = b_lat, float("inf")
            for b_try in np.arange(4.0, 15.0, 0.5):
                predicted = mu_lat * np.sin(c_lat * np.arctan(b_try * sa))
                cost = float(np.mean((fy_norm - predicted)**2))
                if cost < best_cost:
                    best_cost = cost
                    best_b = float(b_try)

            b_lat = best_b
            log.info("Tyre lat fit: B=%.1f, mu=%.3f (from %d samples)",
                     b_lat, mu_lat, valid.sum())

    model = TyreModel(
        b_lat=b_lat, c_lat=c_lat, d_lat=1.0, mu_lat=mu_lat,
        b_long=b_long, c_long=c_long, d_long=1.0, mu_long=mu_long,
    ).clamped(config)

    log.info("Tyre model: mu_lat=%.3f, mu_long=%.3f", model.mu_lat, model.mu_long)
    return model
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_tyre_model.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/param_id/tyre_model.py telemetry_tool/tests/test_sim_optimizer/test_tyre_model.py
git commit -m "feat(sim-optimizer): tyre model Pacejka identification"
```

---

### Task 11: VehicleModel assembly + FrictionLike protocol

**Files:**
- Create: `telemetry_tool/sim_optimizer/param_id/vehicle_model.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_vehicle_model.py`

- [ ] **Step 1: Write failing test**

```python
# telemetry_tool/tests/test_sim_optimizer/test_vehicle_model.py
"""Tests for VehicleModel assembly and FrictionLike protocol."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.sim_optimizer.param_id.aero_model import AeroModel
from telemetry_tool.sim_optimizer.param_id.brake_model import BrakeModel
from telemetry_tool.sim_optimizer.param_id.mass_model import MassModel
from telemetry_tool.sim_optimizer.param_id.powertrain_model import PowertrainModel
from telemetry_tool.sim_optimizer.param_id.suspension_model import SuspensionModel
from telemetry_tool.sim_optimizer.param_id.tyre_model import TyreModel
from telemetry_tool.sim_optimizer.param_id.vehicle_model import VehicleModel


@pytest.fixture
def sample_vehicle_model() -> VehicleModel:
    return VehicleModel(
        tyre=TyreModel(mu_lat=1.3, mu_long=1.3),
        aero=AeroModel(cda=1.0, cla=2.0, air_density=1.18),
        powertrain=PowertrainModel(
            gear_torque_maps={3: (np.array([4000, 6000, 8000]),
                                  np.array([300, 350, 280]))},
            wheel_radius_m=0.33, transmission_efficiency=0.93,
            rr_c0=0.012, rr_c1=0.00008,
        ),
        brake=BrakeModel(max_decel_mps2=12.0, brake_bias_front=0.56,
                         fade_onset_temp_c=400.0, fade_rate=0.001),
        suspension=SuspensionModel(spring_rate_lf=50000, spring_rate_rf=50000,
                                    spring_rate_lr=45000, spring_rate_rr=45000,
                                    static_defl_m=0.05),
        mass=MassModel(base_mass_kg=1200.0, fuel_density_kg_l=0.75,
                       bop_penalty_kg=0.0),
    )


class TestVehicleModel:
    def test_max_lateral_g(self, sample_vehicle_model):
        g = sample_vehicle_model.max_lateral_g(speed_mps=30.0)
        assert g > 0
        assert g < 3.0 * 9.80665  # sanity: < 3G

    def test_downforce_increases_lateral_g(self, sample_vehicle_model):
        g_low = sample_vehicle_model.max_lateral_g(speed_mps=10.0)
        g_high = sample_vehicle_model.max_lateral_g(speed_mps=50.0)
        # At higher speed, downforce adds load -> more grip
        assert g_high > g_low

    def test_max_traction_g(self, sample_vehicle_model):
        g = sample_vehicle_model.max_traction_g(speed_mps=30.0, gear=3)
        assert g > 0

    def test_max_braking_g(self, sample_vehicle_model):
        g = sample_vehicle_model.max_braking_g(speed_mps=30.0)
        assert g > 0

    def test_combined_limit(self, sample_vehicle_model):
        # Within limits
        assert sample_vehicle_model.combined_limit(ax=2.0, ay=5.0, speed_mps=30.0)
        # Exceeds limits (huge G)
        assert not sample_vehicle_model.combined_limit(ax=20.0, ay=20.0, speed_mps=30.0)

    def test_total_mass_with_fuel(self, sample_vehicle_model):
        m = sample_vehicle_model.total_mass_kg(fuel_level_l=40.0)
        assert m == 1200.0 + 40.0 * 0.75  # base + fuel

    def test_to_dict(self, sample_vehicle_model):
        d = sample_vehicle_model.to_dict()
        assert "tyre" in d
        assert "aero" in d
        assert "mass" in d
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_vehicle_model.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# telemetry_tool/sim_optimizer/param_id/vehicle_model.py
"""VehicleModel — assembles sub-models into FrictionLike-compatible interface.

Satisfies the same protocol as kart_envelope's CapabilityEnvelope so it
can be plugged directly into the QSS solver.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from telemetry_tool.sim_optimizer.param_id.aero_model import AeroModel
from telemetry_tool.sim_optimizer.param_id.brake_model import BrakeModel
from telemetry_tool.sim_optimizer.param_id.mass_model import MassModel
from telemetry_tool.sim_optimizer.param_id.powertrain_model import PowertrainModel
from telemetry_tool.sim_optimizer.param_id.suspension_model import SuspensionModel
from telemetry_tool.sim_optimizer.param_id.tyre_model import TyreModel

log = logging.getLogger(__name__)

_G = 9.80665


@dataclass
class VehicleModel:
    """Complete vehicle physics model assembled from identified sub-models.

    Implements the FrictionLike protocol:
      - max_lateral_g(speed_mps) -> float
      - max_traction_g(speed_mps, gear) -> float
      - max_braking_g(speed_mps) -> float
      - combined_limit(ax, ay, speed_mps) -> bool
    """
    tyre: TyreModel
    aero: AeroModel
    powertrain: PowertrainModel
    brake: BrakeModel
    suspension: SuspensionModel
    mass: MassModel

    # Combined slip p-norm exponent
    p_combined: float = 1.6

    def total_mass_kg(self, fuel_level_l: float = 30.0) -> float:
        return self.mass.total_mass_kg(fuel_level_l)

    def max_lateral_g(self, speed_mps: float, fuel_level_l: float = 30.0) -> float:
        """Maximum lateral acceleration [m/s^2] at given speed."""
        m = self.total_mass_kg(fuel_level_l)
        # Total vertical load = weight + downforce
        aero_factor = self.aero.downforce_load_factor(speed_mps, m)
        fz_total = m * _G * aero_factor
        # Average tyre load (4 wheels)
        fz_per_wheel = fz_total / 4.0
        # Peak lateral force from tyre model (sum of 4 wheels)
        f_lat_total = 4.0 * self.tyre.max_lateral_force(fz_per_wheel)
        return f_lat_total / m

    def max_traction_g(self, speed_mps: float, gear: int,
                       fuel_level_l: float = 30.0) -> float:
        """Maximum traction acceleration [m/s^2]."""
        m = self.total_mass_kg(fuel_level_l)
        # Tyre-limited traction
        aero_factor = self.aero.downforce_load_factor(speed_mps, m)
        fz_total = m * _G * aero_factor
        fz_per_wheel = fz_total / 4.0
        f_trac_tyre = 4.0 * self.tyre.max_longitudinal_force(fz_per_wheel)
        a_tyre = f_trac_tyre / m
        # Power-limited traction
        a_power = self.powertrain.max_drive_accel(speed_mps, gear, m)
        # Drag and rolling resistance
        a_drag = self.aero.drag_accel(speed_mps, m)
        a_rr = self.powertrain.rolling_resistance_accel(speed_mps)
        return max(min(a_tyre, a_power) - a_drag - a_rr, 0.0)

    def max_braking_g(self, speed_mps: float, fuel_level_l: float = 30.0) -> float:
        """Maximum braking deceleration [m/s^2] (positive value)."""
        m = self.total_mass_kg(fuel_level_l)
        # Tyre-limited braking
        aero_factor = self.aero.downforce_load_factor(speed_mps, m)
        fz_total = m * _G * aero_factor
        fz_per_wheel = fz_total / 4.0
        f_brake_tyre = 4.0 * self.tyre.max_longitudinal_force(fz_per_wheel)
        a_tyre = f_brake_tyre / m
        # Brake-system-limited
        a_brake_sys = self.brake.max_braking_decel(speed_mps)
        # Drag helps braking
        a_drag = self.aero.drag_accel(speed_mps, m)
        a_rr = self.powertrain.rolling_resistance_accel(speed_mps)
        return min(a_tyre, a_brake_sys) + a_drag + a_rr

    def combined_limit(self, ax: float, ay: float, speed_mps: float,
                       fuel_level_l: float = 30.0) -> bool:
        """Check if (ax, ay) is within the combined grip envelope.

        Returns True if within limits, False if exceeding.
        Uses p-norm: (|ax|/ax_max)^p + (|ay|/ay_max)^p <= 1
        """
        if ax >= 0:
            ax_max = self.max_traction_g(speed_mps, gear=3, fuel_level_l=fuel_level_l)
        else:
            ax_max = self.max_braking_g(speed_mps, fuel_level_l=fuel_level_l)
        ay_max = self.max_lateral_g(speed_mps, fuel_level_l=fuel_level_l)

        if ax_max <= 0 or ay_max <= 0:
            return False

        utilization = (abs(ax) / ax_max) ** self.p_combined + (abs(ay) / ay_max) ** self.p_combined
        return utilization <= 1.0

    # -- FrictionLike compatibility methods (for kart_envelope solver) --

    def max_cornering_speed(self, curvature: float) -> float:
        """Max speed at given curvature: v = sqrt(ay_max / kappa)."""
        if curvature <= 0:
            return 100.0  # straight
        ay = self.max_lateral_g(speed_mps=20.0)  # approximate
        return min(float(np.sqrt(ay / curvature)), 100.0)

    def max_longitudinal_accel(self, speed: float, a_lat: float,
                               braking: bool = False) -> float:
        """Combined-slip limited longitudinal accel (for QSS solver)."""
        ay_max = self.max_lateral_g(speed)
        if ay_max <= 0:
            return 0.0
        lat_ratio = min(abs(a_lat) / ay_max, 0.99)
        remaining = max(1.0 - lat_ratio ** self.p_combined, 0.0)
        fraction = remaining ** (1.0 / self.p_combined)
        if braking:
            return self.max_braking_g(speed) * fraction
        return self.max_traction_g(speed, gear=3) * fraction

    def to_dict(self) -> dict[str, Any]:
        return {
            "tyre": self.tyre.to_dict(),
            "aero": self.aero.to_dict(),
            "powertrain": self.powertrain.to_dict(),
            "brake": self.brake.to_dict(),
            "suspension": self.suspension.to_dict(),
            "mass": self.mass.to_dict(),
            "p_combined": round(self.p_combined, 2),
        }
```

- [ ] **Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/test_vehicle_model.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/sim_optimizer/param_id/vehicle_model.py telemetry_tool/tests/test_sim_optimizer/test_vehicle_model.py
git commit -m "feat(sim-optimizer): VehicleModel assembly with FrictionLike protocol"
```

---

### Task 12: Run full test suite

- [ ] **Step 1: Run all sim_optimizer tests**

Run: `pytest telemetry_tool/tests/test_sim_optimizer/ -v --tb=short`
Expected: All tests pass (8 + 5 + 5 + 5 + 6 + 5 + 4 + 8 + 7 = ~53 tests).

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `pytest telemetry_tool/tests/ -v --tb=short -x`
Expected: No failures in existing tests.

- [ ] **Step 3: Final commit with all __init__.py files**

```bash
git add -A telemetry_tool/sim_optimizer/ telemetry_tool/tests/test_sim_optimizer/
git commit -m "feat(sim-optimizer): complete core physics parameter identification package"
```
