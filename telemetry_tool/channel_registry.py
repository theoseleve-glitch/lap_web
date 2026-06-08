"""Universal telemetry channel registry.

Defines every possible telemetry channel with canonical name, unit, tier,
category, and validation range.  Supports multi-source ingestion from
RaceChrono, iRacing, ACC, MoTeC, AiM, F1 games, OBD-II loggers, and VBOX.

Tier hierarchy
--------------
1 - Essential : GPS + time + speed (every logger)
2 - Standard  : IMU accelerometers / gyroscopes
3 - Controls  : Throttle, brake, steering, RPM, gear
4 - Advanced  : 4-corner tyre temps, pressures, wheel speeds, brake temps
5 - Professional : Dampers, ride height, slip angles/ratios, fuel, aero
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Tier constants
# ---------------------------------------------------------------------------
TIER_ESSENTIAL: int = 1
TIER_STANDARD: int = 2
TIER_CONTROLS: int = 3
TIER_ADVANCED: int = 4
TIER_PROFESSIONAL: int = 5


# ---------------------------------------------------------------------------
# ChannelDef dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ChannelDef:
    """Immutable definition of a single telemetry channel."""

    name: str
    unit: str
    tier: int
    category: str
    valid_range: tuple[float, float]
    description: str = ""


# ---------------------------------------------------------------------------
# Helper to build corner / zone variants
# ---------------------------------------------------------------------------
_CORNERS = ("fl", "fr", "rl", "rr")
_TIRE_ZONES = ("i", "m", "o")  # inner, middle, outer


def _ch(
    name: str,
    unit: str,
    tier: int,
    category: str,
    valid_range: tuple[float, float],
    description: str = "",
) -> ChannelDef:
    return ChannelDef(
        name=name,
        unit=unit,
        tier=tier,
        category=category,
        valid_range=valid_range,
        description=description,
    )


# ---------------------------------------------------------------------------
# CHANNELS registry
# ---------------------------------------------------------------------------
_channel_list: list[ChannelDef] = []

# ---- Tier 1: Essential ----------------------------------------------------
_channel_list += [
    _ch("time_s", "s", TIER_ESSENTIAL, "time", (0.0, 1e7),
        "Elapsed time since session start"),
    _ch("speed_mps", "m/s", TIER_ESSENTIAL, "motion", (0.0, 120.0),
        "Vehicle speed"),
    _ch("lat_deg", "deg", TIER_ESSENTIAL, "position", (-90.0, 90.0),
        "GPS latitude"),
    _ch("lon_deg", "deg", TIER_ESSENTIAL, "position", (-180.0, 180.0),
        "GPS longitude"),
    _ch("distance_m", "m", TIER_ESSENTIAL, "position", (0.0, 1e8),
        "Cumulative distance travelled"),
    _ch("lap_number", "#", TIER_ESSENTIAL, "time", (0.0, 9999.0),
        "Current lap number"),
    _ch("altitude_m", "m", TIER_ESSENTIAL, "position", (-500.0, 9000.0),
        "GPS altitude above sea level"),
]

# ---- Tier 2: Standard (IMU / derived) ------------------------------------
_channel_list += [
    _ch("accel_long_mps2", "m/s2", TIER_STANDARD, "motion", (-80.0, 80.0),
        "Longitudinal acceleration"),
    _ch("accel_lat_mps2", "m/s2", TIER_STANDARD, "motion", (-80.0, 80.0),
        "Lateral acceleration"),
    _ch("yaw_rate_dps", "deg/s", TIER_STANDARD, "motion", (-500.0, 500.0),
        "Yaw rate"),
    _ch("heading_deg", "deg", TIER_STANDARD, "motion", (0.0, 360.0),
        "Compass heading"),
    _ch("combined_g", "g", TIER_STANDARD, "motion", (0.0, 10.0),
        "Combined longitudinal + lateral g-force magnitude"),
    _ch("accel_vert_mps2", "m/s2", TIER_STANDARD, "motion", (-80.0, 80.0),
        "Vertical acceleration"),
    _ch("pitch_rate_dps", "deg/s", TIER_STANDARD, "motion", (-500.0, 500.0),
        "Pitch rate"),
    _ch("roll_rate_dps", "deg/s", TIER_STANDARD, "motion", (-500.0, 500.0),
        "Roll rate"),
]

# ---- Tier 3: Controls ----------------------------------------------------
_channel_list += [
    _ch("throttle_pct", "%", TIER_CONTROLS, "controls", (0.0, 100.0),
        "Throttle position"),
    _ch("brake_pct", "%", TIER_CONTROLS, "controls", (0.0, 100.0),
        "Brake pressure / position"),
    _ch("steering_angle_deg", "deg", TIER_CONTROLS, "controls", (-900.0, 900.0),
        "Steering wheel angle"),
    _ch("rpm", "rpm", TIER_CONTROLS, "engine", (0.0, 22000.0),
        "Engine RPM"),
    _ch("gear", "#", TIER_CONTROLS, "controls", (-1.0, 12.0),
        "Current gear (-1=reverse, 0=neutral)"),
    _ch("clutch_pct", "%", TIER_CONTROLS, "controls", (0.0, 100.0),
        "Clutch position"),
]

# ---- Tier 4: Advanced (4-corner + zones) ---------------------------------
# Tyre temperature (4-corner aggregate)
for corner in _CORNERS:
    _channel_list.append(
        _ch(f"tire_temp_{corner}", "C", TIER_ADVANCED, "tires",
            (-20.0, 250.0), f"Tyre temperature ({corner.upper()})"),
    )

# Tyre temperature (12-zone: inner/middle/outer per corner)
for corner in _CORNERS:
    for zone in _TIRE_ZONES:
        _channel_list.append(
            _ch(f"tire_temp_{corner}_{zone}", "C", TIER_ADVANCED, "tires",
                (-20.0, 250.0),
                f"Tyre temperature ({corner.upper()} {zone.upper()})"),
        )

# Tyre pressure (4-corner)
for corner in _CORNERS:
    _channel_list.append(
        _ch(f"tire_pressure_{corner}", "kPa", TIER_ADVANCED, "tires",
            (50.0, 400.0), f"Tyre pressure ({corner.upper()})"),
    )

# Tyre wear (4-corner, percentage remaining)
for corner in _CORNERS:
    _channel_list.append(
        _ch(f"tire_wear_{corner}", "%", TIER_ADVANCED, "tires",
            (0.0, 100.0), f"Tyre wear remaining ({corner.upper()})"),
    )

# Brake temperature (4-corner)
for corner in _CORNERS:
    _channel_list.append(
        _ch(f"brake_temp_{corner}", "C", TIER_ADVANCED, "brakes",
            (-20.0, 1200.0), f"Brake disc temperature ({corner.upper()})"),
    )

# Wheel speed (4-corner)
for corner in _CORNERS:
    _channel_list.append(
        _ch(f"wheel_speed_{corner}", "m/s", TIER_ADVANCED, "motion",
            (0.0, 120.0), f"Wheel speed ({corner.upper()})"),
    )

# ---- Tier 5: Professional ------------------------------------------------
# Damper position (4-corner)
for corner in _CORNERS:
    _channel_list.append(
        _ch(f"damper_pos_{corner}", "mm", TIER_PROFESSIONAL, "motion",
            (0.0, 300.0), f"Damper position ({corner.upper()})"),
    )

# Ride height (front / rear)
_channel_list += [
    _ch("ride_height_f", "mm", TIER_PROFESSIONAL, "motion", (0.0, 300.0),
        "Front ride height"),
    _ch("ride_height_r", "mm", TIER_PROFESSIONAL, "motion", (0.0, 300.0),
        "Rear ride height"),
]

# Fuel
_channel_list += [
    _ch("fuel_kg", "kg", TIER_PROFESSIONAL, "fuel", (0.0, 200.0),
        "Fuel mass remaining"),
    _ch("fuel_consumption_rate", "kg/h", TIER_PROFESSIONAL, "fuel", (0.0, 200.0),
        "Fuel consumption rate"),
]

# Engine
_channel_list += [
    _ch("oil_temp", "C", TIER_PROFESSIONAL, "engine", (-40.0, 200.0),
        "Engine oil temperature"),
    _ch("water_temp", "C", TIER_PROFESSIONAL, "engine", (-40.0, 150.0),
        "Engine coolant temperature"),
    _ch("oil_pressure", "kPa", TIER_PROFESSIONAL, "engine", (0.0, 1000.0),
        "Engine oil pressure"),
    _ch("boost_pressure", "kPa", TIER_PROFESSIONAL, "engine", (-100.0, 400.0),
        "Turbo / supercharger boost pressure"),
    _ch("exhaust_temp", "C", TIER_PROFESSIONAL, "engine", (-40.0, 1300.0),
        "Exhaust gas temperature (EGT)"),
    _ch("head_temp", "C", TIER_PROFESSIONAL, "engine", (-40.0, 400.0),
        "Cylinder head temperature (CHT)"),
]

# Slip angle (4-corner)
for corner in _CORNERS:
    _channel_list.append(
        _ch(f"slip_angle_{corner}", "deg", TIER_PROFESSIONAL, "tires",
            (-30.0, 30.0), f"Tyre slip angle ({corner.upper()})"),
    )

# Slip ratio (4-corner)
for corner in _CORNERS:
    _channel_list.append(
        _ch(f"slip_ratio_{corner}", "ratio", TIER_PROFESSIONAL, "tires",
            (-1.0, 1.0), f"Tyre slip ratio ({corner.upper()})"),
    )

# Aero & electronics
_channel_list += [
    _ch("lambda_afr", "ratio", TIER_PROFESSIONAL, "engine", (0.5, 2.0),
        "Lambda / air-fuel ratio"),
    _ch("aero_drs", "bool", TIER_PROFESSIONAL, "aero", (0.0, 1.0),
        "DRS active flag (0 or 1)"),
    _ch("ers_deploy_pct", "%", TIER_PROFESSIONAL, "aero", (0.0, 100.0),
        "ERS deployment percentage"),
]

# Environment
_channel_list += [
    _ch("air_temp", "C", TIER_PROFESSIONAL, "environment", (-40.0, 60.0),
        "Ambient air temperature"),
    _ch("track_temp", "C", TIER_PROFESSIONAL, "environment", (-40.0, 80.0),
        "Track surface temperature"),
]

# Driver biometrics
_channel_list += [
    _ch("heart_rate_bpm", "bpm", TIER_PROFESSIONAL, "driver", (0.0, 250.0),
        "Driver heart rate"),
]

# Build the canonical dict: name -> ChannelDef
CHANNELS: dict[str, ChannelDef] = {ch.name: ch for ch in _channel_list}


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------
def get_channels_by_tier(tier: int) -> list[ChannelDef]:
    """Return all channels belonging to the given tier."""
    return [ch for ch in CHANNELS.values() if ch.tier == tier]


def get_channels_by_category(category: str) -> list[ChannelDef]:
    """Return all channels belonging to the given category."""
    return [ch for ch in CHANNELS.values() if ch.category == category]


def validate_channel_value(channel_name: str, value: float) -> bool:
    """Check whether *value* falls within the valid range for *channel_name*.

    Raises ``KeyError`` if *channel_name* is not in the registry.
    """
    ch = CHANNELS[channel_name]  # raises KeyError if unknown
    lo, hi = ch.valid_range
    return lo <= value <= hi


def detect_data_tier(available_columns: list[str]) -> int:
    """Determine the highest data tier satisfied by *available_columns*.

    Tier requirements are cumulative -- each tier requires all lower tiers
    to be satisfied first.

    Returns 0 if not even tier 1 is met.
    """
    cols = set(available_columns)

    # Tier 1: time_s + speed_mps
    if not ({"time_s", "speed_mps"} <= cols):
        return 0

    # Tier 2: tier 1 + accel_long_mps2 + accel_lat_mps2
    if not ({"accel_long_mps2", "accel_lat_mps2"} <= cols):
        return TIER_ESSENTIAL

    # Tier 3: tier 2 + any 2 of {throttle_pct, brake_pct, steering_angle_deg, rpm}
    controls_set = {"throttle_pct", "brake_pct", "steering_angle_deg", "rpm"}
    controls_present = len(controls_set & cols)
    if controls_present < 2:
        return TIER_STANDARD

    # Tier 4: tier 3 + any column starting with tire_temp_ / wheel_speed_ / brake_temp_
    _T4_PREFIXES = ("tire_temp_", "wheel_speed_", "brake_temp_")
    has_tier4 = any(
        c.startswith(prefix) for c in cols for prefix in _T4_PREFIXES
    )
    if not has_tier4:
        return TIER_CONTROLS

    # Tier 5: tier 4 + any column starting with slip_angle_ / slip_ratio_ / damper_pos_ / fuel_
    _T5_PREFIXES = ("slip_angle_", "slip_ratio_", "damper_pos_", "fuel_")
    has_tier5 = any(
        c.startswith(prefix) for c in cols for prefix in _T5_PREFIXES
    )
    if not has_tier5:
        return TIER_ADVANCED

    return TIER_PROFESSIONAL
