"""Shared fixtures for sim_optimizer tests."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure project root is importable (mirrors kart_envelope pattern)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def sim_config():
    """Return a default SimOptimizerConfig."""
    from telemetry_tool.sim_optimizer.config import default_config

    return default_config()


# ---------------------------------------------------------------------------
# Helpers for synthetic oval generation
# ---------------------------------------------------------------------------

_WHEELS = ("LF", "RF", "LR", "RR")

_ST_DYNAMICS = (
    "LatAccel",
    "LongAccel",
    "VertAccel",
    "VelocityX",
    "VelocityY",
    "VelocityZ",
    "YawRate",
    "RollRate",
    "PitchRate",
)

_SAMPLES_PER_TICK = 6


def _build_oval_profile(n: int, rng: np.random.Generator) -> dict:
    """Build physically-reasonable 1 km oval telemetry for *n* rows.

    Layout (by distance fraction):
        0.00 – 0.35  straight-1  (350 m)
        0.35 – 0.50  corner-1    (150 m, ~50 m radius)
        0.50 – 0.85  straight-2  (350 m)
        0.85 – 1.00  corner-2    (150 m, ~50 m radius)
    """
    track_length_m = 1000.0
    dt = 0.0167  # ~60 Hz

    dist = np.linspace(0, track_length_m, n, endpoint=False)
    dist_pct = dist / track_length_m

    # Region masks
    corner1 = (dist_pct >= 0.35) & (dist_pct < 0.50)
    corner2 = (dist_pct >= 0.85) & (dist_pct < 1.00)
    in_corner = corner1 | corner2

    # Speed profile: ~33 m/s straights, ~22 m/s corners with smooth blend
    speed = np.full(n, 33.0)
    speed[in_corner] = 22.0
    # Smooth transitions
    for _ in range(10):
        speed[1:] = 0.8 * speed[1:] + 0.2 * speed[:-1]
        speed[:-1] = 0.8 * speed[:-1] + 0.2 * speed[1:]
    speed += rng.normal(0, 0.3, n)
    speed = np.clip(speed, 10.0, 40.0)

    # Curvature: 1/R in corners (~1/50), 0 on straights
    kappa = np.zeros(n)
    kappa[corner1] = 1.0 / 50.0
    kappa[corner2] = -1.0 / 50.0

    # Time from speed
    ds = np.diff(dist, prepend=0)
    ds[0] = ds[1]
    time = np.cumsum(ds / np.maximum(speed, 1.0))

    # Accelerations
    long_accel = np.gradient(speed, time)
    long_accel = np.clip(long_accel, -15, 10)
    lat_accel = speed ** 2 * kappa  # v^2 / R
    vert_accel = rng.normal(9.81, 0.05, n)

    # Heading / yaw
    heading = np.cumsum(kappa * ds)
    yaw_rate = np.gradient(heading, time)

    # Velocity components in body frame
    vel_x = speed * np.cos(heading)
    vel_y = speed * np.sin(heading)
    vel_z = rng.normal(0, 0.02, n)

    # Pitch / roll
    pitch = np.arctan2(long_accel, 9.81) * 0.1
    roll = np.arctan2(lat_accel, 9.81) * 0.15
    pitch_rate = np.gradient(pitch, time)
    roll_rate = np.gradient(roll, time)

    # Inputs
    throttle = np.where(long_accel > 0.5, np.clip(long_accel / 5.0, 0, 1), 0.0)
    throttle += rng.normal(0, 0.02, n)
    throttle = np.clip(throttle, 0, 1)

    brake_input = np.where(long_accel < -1.0, np.clip(-long_accel / 10.0, 0, 1), 0.0)
    brake_input += rng.normal(0, 0.01, n)
    brake_input = np.clip(brake_input, 0, 1)

    steering = np.arctan(kappa * 2.5)  # approx wheelbase 2.5 m
    steering += rng.normal(0, 0.005, n)

    # Gear from speed
    gear = np.clip((speed / 10).astype(int) + 1, 1, 6)
    rpm = 2000 + speed * 120 + rng.normal(0, 50, n)
    rpm = np.clip(rpm, 800, 9000)

    # Lat/Lon (simple circle-ish around origin)
    lat = 36.0 + heading * 0.0001
    lon = -115.0 + dist_pct * 0.005
    alt = 600.0 + rng.normal(0, 0.1, n)

    # Per-wheel quantities
    base_tyre_temp = 85.0
    tyre_temps = {}
    for wh in _WHEELS:
        lat_load_factor = 1.0
        if wh.endswith("F"):
            lat_load_factor += 0.15 * np.abs(lat_accel) / 9.81
        else:
            lat_load_factor += 0.10 * np.abs(lat_accel) / 9.81
        temp_base = base_tyre_temp * lat_load_factor + rng.normal(0, 1.5, n)
        for zone in ("CL", "CM", "CR"):
            offset = rng.normal(0, 2.0, n)
            tyre_temps[f"{wh}temp{zone}"] = temp_base + offset

    tyre_wear = {}
    for wh in _WHEELS:
        base_wear = np.linspace(100, 98, n)
        for zone in ("L", "M", "R"):
            tyre_wear[f"{wh}wear{zone}"] = base_wear + rng.normal(0, 0.1, n)

    cold_pressure = {}
    for wh in _WHEELS:
        cold_pressure[f"{wh}coldPressure"] = 172.0 + rng.normal(0, 0.5, n)

    odometer = {}
    for wh in _WHEELS:
        odometer[f"{wh}odometer"] = dist + rng.normal(0, 0.01, n)

    # Shock deflection: varies with lateral load transfer
    shock_defl = {}
    shock_vel = {}
    for wh in _WHEELS:
        sign = 1.0 if wh in ("LF", "LR") else -1.0
        defl = 0.05 + sign * 0.003 * lat_accel + rng.normal(0, 0.001, n)
        shock_defl[f"{wh}shockDefl"] = defl
        shock_vel[f"{wh}shockVel"] = np.gradient(defl, time) + rng.normal(0, 0.01, n)

    # Brake line pressure and temp (correlate with brake input)
    brake_press = {}
    brake_temp = {}
    for wh in _WHEELS:
        bp = brake_input * 5000 + rng.normal(0, 50, n)
        brake_press[f"{wh}brakeLinePress"] = np.clip(bp, 0, 8000)
        bt = 200 + brake_input * 300 + rng.normal(0, 10, n)
        brake_temp[f"{wh}brakeTemp"] = np.clip(bt, 100, 800)

    # Lap assignment (2 laps)
    lap = np.where(dist_pct < 0.5, 1, 2).astype(float)

    # Build the column dict with irsdk__ prefix
    p = "irsdk__"
    data = {
        f"{p}SessionTime": time,
        f"{p}Lap": lap,
        f"{p}LapDist": dist,
        f"{p}LapDistPct": dist_pct,
        f"{p}IsOnTrack": np.ones(n),
        f"{p}OnPitRoad": np.zeros(n),
        f"{p}SessionFlags": np.zeros(n, dtype=int),
        f"{p}Speed": speed,
        f"{p}VelocityX": vel_x,
        f"{p}VelocityY": vel_y,
        f"{p}VelocityZ": vel_z,
        f"{p}LatAccel": lat_accel,
        f"{p}LongAccel": long_accel,
        f"{p}VertAccel": vert_accel,
        f"{p}Yaw": heading,
        f"{p}YawRate": yaw_rate,
        f"{p}Pitch": pitch,
        f"{p}PitchRate": pitch_rate,
        f"{p}Roll": roll,
        f"{p}RollRate": roll_rate,
        f"{p}Lat": lat,
        f"{p}Lon": lon,
        f"{p}Alt": alt,
        f"{p}Throttle": throttle,
        f"{p}ThrottleRaw": throttle + rng.normal(0, 0.005, n),
        f"{p}Brake": brake_input,
        f"{p}BrakeRaw": brake_input + rng.normal(0, 0.005, n),
        f"{p}BrakeABSactive": np.zeros(n),
        f"{p}SteeringWheelAngle": steering,
        f"{p}Gear": gear,
        f"{p}RPM": rpm,
        f"{p}Clutch": np.ones(n),
        f"{p}dcBrakeBias": np.full(n, 57.0),
        f"{p}dcABS": np.full(n, 2.0),
        f"{p}dcTractionControl": np.full(n, 3.0),
        f"{p}dcFuelMixture": np.full(n, 8.0),
        f"{p}WaterTemp": 80.0 + rng.normal(0, 1, n),
        f"{p}OilTemp": 110.0 + rng.normal(0, 2, n),
        f"{p}FuelLevel": np.linspace(40, 35, n),
        f"{p}FuelUsePerHour": 25.0 + rng.normal(0, 0.5, n),
        f"{p}Voltage": 13.8 + rng.normal(0, 0.1, n),
        f"{p}AirTemp": np.full(n, 28.0) + rng.normal(0, 0.2, n),
        f"{p}TrackTempCrew": np.full(n, 42.0) + rng.normal(0, 0.3, n),
        f"{p}AirDensity": np.full(n, 1.15) + rng.normal(0, 0.005, n),
        f"{p}AirPressure": np.full(n, 29.4) + rng.normal(0, 0.01, n),
        f"{p}WindVel": np.full(n, 3.0) + rng.normal(0, 0.5, n),
        f"{p}WindDir": np.full(n, 180.0) + rng.normal(0, 5, n),
        f"{p}TrackWetness": np.zeros(n),
        f"{p}RelativeHumidity": np.full(n, 40.0) + rng.normal(0, 1, n),
        f"{p}PlayerCarWeightPenalty": np.zeros(n),
        f"{p}PlayerCarPowerAdjust": np.zeros(n),
        f"{p}PlayerTrackSurface": np.full(n, 3),  # 3 = on-track
        f"{p}PlayerTrackSurfaceMaterial": np.full(n, 1),
        f"{p}CarDistAhead": np.full(n, 200.0) + rng.normal(0, 10, n),
        f"{p}CarDistBehind": np.full(n, 150.0) + rng.normal(0, 10, n),
        f"{p}LapDeltaToOptimalLap": rng.normal(0, 0.3, n),
        f"{p}LapDeltaToOptimalLap_OK": np.ones(n),
        f"{p}PlayerCarSLShiftRPM": np.full(n, 7500.0),
        f"{p}PlayerCarSLBlinkRPM": np.full(n, 7800.0),
        f"{p}SteeringWheelTorque": steering * 15 + rng.normal(0, 0.5, n),
    }

    # Per-wheel columns
    for wh in _WHEELS:
        for zone in ("CL", "CM", "CR"):
            data[f"{p}{wh}temp{zone}"] = tyre_temps[f"{wh}temp{zone}"]
        for zone in ("L", "M", "R"):
            data[f"{p}{wh}wear{zone}"] = tyre_wear[f"{wh}wear{zone}"]
        data[f"{p}{wh}coldPressure"] = cold_pressure[f"{wh}coldPressure"]
        data[f"{p}{wh}odometer"] = odometer[f"{wh}odometer"]
        data[f"{p}{wh}shockDefl"] = shock_defl[f"{wh}shockDefl"]
        data[f"{p}{wh}shockVel"] = shock_vel[f"{wh}shockVel"]
        data[f"{p}{wh}brakeLinePress"] = brake_press[f"{wh}brakeLinePress"]
        data[f"{p}{wh}brakeTemp"] = brake_temp[f"{wh}brakeTemp"]

    # 360 Hz _ST sub-sample arrays (6 samples per tick)
    for var in _ST_DYNAMICS:
        base = data[f"{p}{var}"]
        for i in range(_SAMPLES_PER_TICK):
            jitter = rng.normal(0, 0.01 * np.abs(base).mean() + 1e-6, n)
            data[f"{p}{var}_ST__{i}"] = base + jitter

    # 360 Hz shock _ST
    for wh in _WHEELS:
        for ch in ("shockDefl", "shockVel"):
            base = data[f"{p}{wh}{ch}"]
            for i in range(_SAMPLES_PER_TICK):
                jitter = rng.normal(0, 0.01 * np.abs(base).mean() + 1e-6, n)
                data[f"{p}{wh}{ch}_ST__{i}"] = base + jitter

    # 360 Hz steering torque _ST
    base_torque = data[f"{p}SteeringWheelTorque"]
    for i in range(_SAMPLES_PER_TICK):
        jitter = rng.normal(0, 0.01 * np.abs(base_torque).mean() + 1e-6, n)
        data[f"{p}SteeringWheelTorque_ST__{i}"] = base_torque + jitter

    return data


@pytest.fixture
def synthetic_raw_df() -> pd.DataFrame:
    """600-row synthetic iRacing raw telemetry for a 1 km oval."""
    rng = np.random.default_rng(42)
    data = _build_oval_profile(600, rng)
    return pd.DataFrame(data)
