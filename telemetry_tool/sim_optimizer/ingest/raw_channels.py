"""Extract raw iRacing telemetry channels into a typed dataclass.

Maps irsdk__ prefixed DataFrame columns to a flat ``RawChannelSet`` whose
fields are either ``np.ndarray`` or ``None`` (when the source column is
absent).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd
    from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

logger = logging.getLogger(__name__)

# ── Wheel constants ──────────────────────────────────────────────────────
_WHEELS = ("LF", "RF", "LR", "RR")
_TEMP_ZONES = ("CL", "CM", "CR")
_WEAR_ZONES = ("L", "M", "R")

# ── Channel groups (sub-model -> raw column list) ────────────────────────

def _per_wheel(template: str) -> list[str]:
    """Expand ``'{wh}'`` in *template* across all four wheels."""
    return [template.format(wh=wh) for wh in _WHEELS]


def _per_wheel_zone(template: str, zones: tuple[str, ...]) -> list[str]:
    return [template.format(wh=wh, z=z) for wh in _WHEELS for z in zones]


CHANNEL_GROUPS: dict[str, list[str]] = {
    "tyre": (
        _per_wheel_zone("irsdk__{wh}temp{z}", _TEMP_ZONES)
        + _per_wheel_zone("irsdk__{wh}wear{z}", _WEAR_ZONES)
        + _per_wheel("irsdk__{wh}coldPressure")
        + _per_wheel("irsdk__{wh}odometer")
    ),
    "aero": [
        "irsdk__Speed",
        "irsdk__AirDensity",
        "irsdk__AirPressure",
        "irsdk__WindVel",
        "irsdk__WindDir",
    ],
    "powertrain": [
        "irsdk__Throttle",
        "irsdk__ThrottleRaw",
        "irsdk__RPM",
        "irsdk__Gear",
        "irsdk__FuelLevel",
        "irsdk__FuelUsePerHour",
        "irsdk__WaterTemp",
        "irsdk__OilTemp",
        "irsdk__Voltage",
    ],
    "brake": (
        ["irsdk__Brake", "irsdk__BrakeRaw", "irsdk__BrakeABSactive"]
        + _per_wheel("irsdk__{wh}brakeLinePress")
        + _per_wheel("irsdk__{wh}brakeTemp")
    ),
    "suspension": (
        _per_wheel("irsdk__{wh}shockDefl")
        + _per_wheel("irsdk__{wh}shockVel")
    ),
    "mass": [
        "irsdk__FuelLevel",
        "irsdk__PlayerCarWeightPenalty",
    ],
    "environment": [
        "irsdk__AirTemp",
        "irsdk__TrackTempCrew",
        "irsdk__AirDensity",
        "irsdk__AirPressure",
        "irsdk__WindVel",
        "irsdk__WindDir",
        "irsdk__TrackWetness",
        "irsdk__RelativeHumidity",
    ],
    "validation": [
        "irsdk__LapDeltaToOptimalLap",
        "irsdk__LapDeltaToOptimalLap_OK",
        "irsdk__PlayerCarSLShiftRPM",
        "irsdk__PlayerCarSLBlinkRPM",
    ],
    "geometry": [
        "irsdk__LapDist",
        "irsdk__LapDistPct",
        "irsdk__Lat",
        "irsdk__Lon",
        "irsdk__Alt",
    ],
    "inputs": [
        "irsdk__Throttle",
        "irsdk__Brake",
        "irsdk__SteeringWheelAngle",
        "irsdk__Gear",
        "irsdk__Clutch",
        "irsdk__dcBrakeBias",
        "irsdk__dcABS",
        "irsdk__dcTractionControl",
        "irsdk__dcFuelMixture",
    ],
}


# ── RawChannelSet dataclass ──────────────────────────────────────────────

@dataclass
class RawChannelSet:
    """Flat container for every physics channel extracted from a raw
    iRacing telemetry DataFrame.

    All array fields default to ``None`` (channel missing).
    ``n_samples`` is the row count of the source DataFrame.
    """

    n_samples: int = 0

    # Timing / session
    session_time_s: np.ndarray | None = None
    lap: np.ndarray | None = None
    lap_dist_m: np.ndarray | None = None
    lap_dist_pct: np.ndarray | None = None
    is_on_track: np.ndarray | None = None
    on_pit_road: np.ndarray | None = None
    session_flags: np.ndarray | None = None

    # Dynamics
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

    # Position
    pos_x: np.ndarray | None = None
    pos_y: np.ndarray | None = None
    pos_z: np.ndarray | None = None

    # Inputs
    throttle: np.ndarray | None = None
    throttle_raw: np.ndarray | None = None
    brake: np.ndarray | None = None
    brake_raw: np.ndarray | None = None
    brake_abs_active: np.ndarray | None = None
    steering_rad: np.ndarray | None = None
    gear: np.ndarray | None = None
    rpm: np.ndarray | None = None
    clutch: np.ndarray | None = None

    # Driver controls
    dc_brake_bias: np.ndarray | None = None
    dc_abs: np.ndarray | None = None
    dc_tc: np.ndarray | None = None
    dc_fuel_mixture: np.ndarray | None = None

    # Per-wheel tyre temps (3 zones x 4 wheels = 12)
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

    # Per-wheel tyre wear (3 zones x 4 wheels = 12)
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

    # Per-wheel cold pressure & odometer
    cold_pressure_lf: np.ndarray | None = None
    cold_pressure_rf: np.ndarray | None = None
    cold_pressure_lr: np.ndarray | None = None
    cold_pressure_rr: np.ndarray | None = None
    odometer_lf: np.ndarray | None = None
    odometer_rf: np.ndarray | None = None
    odometer_lr: np.ndarray | None = None
    odometer_rr: np.ndarray | None = None

    # Per-wheel shock
    shock_defl_lf: np.ndarray | None = None
    shock_defl_rf: np.ndarray | None = None
    shock_defl_lr: np.ndarray | None = None
    shock_defl_rr: np.ndarray | None = None
    shock_vel_lf: np.ndarray | None = None
    shock_vel_rf: np.ndarray | None = None
    shock_vel_lr: np.ndarray | None = None
    shock_vel_rr: np.ndarray | None = None

    # Per-wheel brake
    brake_line_press_lf: np.ndarray | None = None
    brake_line_press_rf: np.ndarray | None = None
    brake_line_press_lr: np.ndarray | None = None
    brake_line_press_rr: np.ndarray | None = None
    brake_temp_lf: np.ndarray | None = None
    brake_temp_rf: np.ndarray | None = None
    brake_temp_lr: np.ndarray | None = None
    brake_temp_rr: np.ndarray | None = None

    # Engine
    water_temp: np.ndarray | None = None
    oil_temp: np.ndarray | None = None
    fuel_level: np.ndarray | None = None
    fuel_use_per_hour: np.ndarray | None = None

    # Environment
    air_temp: np.ndarray | None = None
    track_temp: np.ndarray | None = None
    air_density: np.ndarray | None = None
    air_pressure: np.ndarray | None = None
    wind_vel: np.ndarray | None = None
    wind_dir: np.ndarray | None = None
    track_wetness: np.ndarray | None = None
    humidity: np.ndarray | None = None

    # Player / car
    weight_penalty_kg: np.ndarray | None = None
    power_adjust_pct: np.ndarray | None = None
    track_surface: np.ndarray | None = None
    track_surface_material: np.ndarray | None = None
    car_dist_ahead: np.ndarray | None = None

    # Validation
    delta_to_optimal: np.ndarray | None = None
    delta_to_optimal_ok: np.ndarray | None = None
    shift_rpm: np.ndarray | None = None
    blink_rpm: np.ndarray | None = None

    # Steering
    steering_torque_nm: np.ndarray | None = None

    def available_channels(self) -> list[str]:
        """Return names of fields that are not ``None``."""
        return [
            f.name
            for f in fields(self)
            if f.name != "n_samples" and getattr(self, f.name) is not None
        ]


# ── Field-to-column mapping ─────────────────────────────────────────────

_FIELD_TO_COL: dict[str, str] = {
    # Timing
    "session_time_s": "irsdk__SessionTime",
    "lap": "irsdk__Lap",
    "lap_dist_m": "irsdk__LapDist",
    "lap_dist_pct": "irsdk__LapDistPct",
    "is_on_track": "irsdk__IsOnTrack",
    "on_pit_road": "irsdk__OnPitRoad",
    "session_flags": "irsdk__SessionFlags",
    # Dynamics
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
    # Position
    "pos_x": "irsdk__Lat",
    "pos_y": "irsdk__Lon",
    "pos_z": "irsdk__Alt",
    # Inputs
    "throttle": "irsdk__Throttle",
    "throttle_raw": "irsdk__ThrottleRaw",
    "brake": "irsdk__Brake",
    "brake_raw": "irsdk__BrakeRaw",
    "brake_abs_active": "irsdk__BrakeABSactive",
    "steering_rad": "irsdk__SteeringWheelAngle",
    "gear": "irsdk__Gear",
    "rpm": "irsdk__RPM",
    "clutch": "irsdk__Clutch",
    # Controls
    "dc_brake_bias": "irsdk__dcBrakeBias",
    "dc_abs": "irsdk__dcABS",
    "dc_tc": "irsdk__dcTractionControl",
    "dc_fuel_mixture": "irsdk__dcFuelMixture",
    # Engine
    "water_temp": "irsdk__WaterTemp",
    "oil_temp": "irsdk__OilTemp",
    "fuel_level": "irsdk__FuelLevel",
    "fuel_use_per_hour": "irsdk__FuelUsePerHour",
    # Environment
    "air_temp": "irsdk__AirTemp",
    "track_temp": "irsdk__TrackTempCrew",
    "air_density": "irsdk__AirDensity",
    "air_pressure": "irsdk__AirPressure",
    "wind_vel": "irsdk__WindVel",
    "wind_dir": "irsdk__WindDir",
    "track_wetness": "irsdk__TrackWetness",
    "humidity": "irsdk__RelativeHumidity",
    # Player
    "weight_penalty_kg": "irsdk__PlayerCarWeightPenalty",
    "power_adjust_pct": "irsdk__PlayerCarPowerAdjust",
    "track_surface": "irsdk__PlayerTrackSurface",
    "track_surface_material": "irsdk__PlayerTrackSurfaceMaterial",
    "car_dist_ahead": "irsdk__CarDistAhead",
    # Validation
    "delta_to_optimal": "irsdk__LapDeltaToOptimalLap",
    "delta_to_optimal_ok": "irsdk__LapDeltaToOptimalLap_OK",
    "shift_rpm": "irsdk__PlayerCarSLShiftRPM",
    "blink_rpm": "irsdk__PlayerCarSLBlinkRPM",
    # Steering
    "steering_torque_nm": "irsdk__SteeringWheelTorque",
}

# Programmatically add per-wheel mappings
for _wh in _WHEELS:
    _wh_lower = _wh.lower()
    # Tyre temps
    for _z in _TEMP_ZONES:
        _field = f"tyre_temp_{_wh_lower}_{_z.lower()}"
        _col = f"irsdk__{_wh}temp{_z}"
        _FIELD_TO_COL[_field] = _col
    # Tyre wear
    for _z in _WEAR_ZONES:
        _field = f"tyre_wear_{_wh_lower}_{_z.lower()}"
        _col = f"irsdk__{_wh}wear{_z}"
        _FIELD_TO_COL[_field] = _col
    # Cold pressure
    _FIELD_TO_COL[f"cold_pressure_{_wh_lower}"] = f"irsdk__{_wh}coldPressure"
    # Odometer
    _FIELD_TO_COL[f"odometer_{_wh_lower}"] = f"irsdk__{_wh}odometer"
    # Shock deflection / velocity
    _FIELD_TO_COL[f"shock_defl_{_wh_lower}"] = f"irsdk__{_wh}shockDefl"
    _FIELD_TO_COL[f"shock_vel_{_wh_lower}"] = f"irsdk__{_wh}shockVel"
    # Brake line pressure / temp
    _FIELD_TO_COL[f"brake_line_press_{_wh_lower}"] = f"irsdk__{_wh}brakeLinePress"
    _FIELD_TO_COL[f"brake_temp_{_wh_lower}"] = f"irsdk__{_wh}brakeTemp"


# ── Extraction ───────────────────────────────────────────────────────────

def _safe_col(df: pd.DataFrame, col: str) -> np.ndarray | None:
    """Return column as ndarray, or ``None`` if missing."""
    if col in df.columns:
        return df[col].to_numpy(dtype=np.float64, na_value=np.nan)
    return None


def extract_raw_channels(
    df: pd.DataFrame,
    *,
    config: SimOptimizerConfig,
) -> RawChannelSet:
    """Extract all known iRacing channels from *df* into a ``RawChannelSet``.

    Missing columns are silently set to ``None``.  Speed is clipped to >= 0.
    """
    result = RawChannelSet(n_samples=len(df))

    for field_name, col_name in _FIELD_TO_COL.items():
        arr = _safe_col(df, col_name)
        setattr(result, field_name, arr)

    # Post-process: clip speed
    if result.speed_mps is not None:
        result.speed_mps = np.clip(result.speed_mps, 0.0, None)

    available = result.available_channels()
    logger.info(
        "Extracted %d / %d channels from %d rows",
        len(available),
        len(_FIELD_TO_COL),
        len(df),
    )
    return result
