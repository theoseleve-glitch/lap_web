"""
column_discovery.py
-------------------
Dynamic column discovery engine for motorsport telemetry CSV files.

Parses arbitrary column headers (RaceChrono, RaceBox, generic) into
canonical internal names, detects units, resolves ``*calc`` preference,
and builds a rename + conversion map that can be applied to any DataFrame.

Replaces the hard-coded 11-column mapping in pipeline.py with a
priority-ordered, extensible rule system supporting 34+ channel types.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Callable, Final

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_G: Final[float] = 9.80665  # m/s^2
_DEG_PER_RAD: Final[float] = 180.0 / math.pi

# ---------------------------------------------------------------------------
# Header regex
# ---------------------------------------------------------------------------
HEADER_RE = re.compile(
    r"^\s*(?P<name>.+?)"
    r"(?:\s*\((?P<unit>[^)]+)\))?"
    r"(?:\s*\*(?P<flag>\w+))?"
    r"\s*$"
)


def parse_header(raw: str) -> tuple[str, str | None, str | None]:
    """Parse a column header into (channel_name, unit, flag).

    Examples
    --------
    >>> parse_header("Speed (m/s) *calc")
    ('Speed', 'm/s', 'calc')
    >>> parse_header("Lap #")
    ('Lap #', None, None)
    >>> parse_header("Tire temp FL (°C)")
    ('Tire temp FL', '°C', None)
    """
    m = HEADER_RE.match(raw)
    if m is None:
        return (raw.strip(), None, None)
    name = m.group("name").strip()
    unit = m.group("unit")
    flag = m.group("flag")
    if unit is not None:
        unit = unit.strip()
    if flag is not None:
        flag = flag.strip()
    return (name, unit, flag)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class DiscoveredChannel:
    """A single discovered telemetry channel."""

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
    """Full result of column discovery for a DataFrame."""

    format: str = "unknown"
    channels: list[DiscoveredChannel] = field(default_factory=list)
    rename_map: dict[str, str] = field(default_factory=dict)
    conversions: dict[str, float] = field(default_factory=dict)
    calc_overrides: dict[str, str] = field(default_factory=dict)
    custom_channels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for JSON persistence."""
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Classification rules (priority-ordered)
# ---------------------------------------------------------------------------
_RULES: list[tuple[re.Pattern | str, str, str]] = [
    # (pattern_or_exact, category, internal_name)
    # Priority 1-3: exact / simple matches
    ("__exact__Time",                        "time",        "time_s"),
    (re.compile(r"Lap", re.IGNORECASE),      "lap",         "lap_number"),
    (re.compile(r"Distance", re.IGNORECASE), "distance",    "distance_m"),
    # Priority 4: speed
    (re.compile(r"Speed", re.IGNORECASE),    "speed",       "speed_mps"),
    # Priority 5-6: lat/lon
    (re.compile(r"^Lat(?:itude)?$", re.IGNORECASE),  "position", "latitude_deg"),
    (re.compile(r"^Lon(?:gitude)?$", re.IGNORECASE),  "position", "longitude_deg"),
    # Priority 7-8: X/Y
    ("__exact__X",                           "position",    "x_m"),
    ("__exact__Y",                           "position",    "y_m"),
    # Priority 9-12: acceleration (more specific patterns first)
    (re.compile(r"Longitud.*accel", re.IGNORECASE),   "acceleration", "accel_long_mps2"),
    (re.compile(r"Lateral.*accel", re.IGNORECASE),    "acceleration", "accel_lat_mps2"),
    (re.compile(r"Accel.*X", re.IGNORECASE),          "acceleration", "accel_long_mps2"),
    (re.compile(r"Accel.*Y", re.IGNORECASE),          "acceleration", "accel_lat_mps2"),
    (re.compile(r"Accel.*Z", re.IGNORECASE),          "acceleration", "accel_vert_mps2"),
    # Priority 14-19: gyro
    (re.compile(r"Yaw", re.IGNORECASE),      "gyro",        "yaw_rate_dps"),
    (re.compile(r"Pitch", re.IGNORECASE),    "gyro",        "pitch_rate_dps"),
    (re.compile(r"Roll", re.IGNORECASE),     "gyro",        "roll_rate_dps"),
    (re.compile(r"Gyro.*X", re.IGNORECASE),  "gyro",        "roll_rate_dps"),
    (re.compile(r"Gyro.*Y", re.IGNORECASE),  "gyro",        "pitch_rate_dps"),
    (re.compile(r"Gyro.*Z", re.IGNORECASE),  "gyro",        "yaw_rate_dps"),
    # Priority 20: heading
    (re.compile(r"Bear(?:ing)?|Head(?:ing)?", re.IGNORECASE), "heading", "heading_deg"),
    # Priority 21: altitude
    (re.compile(r"Alt(?:itude)?", re.IGNORECASE),    "altitude",     "altitude_m"),
    # Priority 22-23: GPS quality
    (re.compile(r"Satellite", re.IGNORECASE),        "gps_quality",  "satellites"),
    (re.compile(r"Accuracy|HDOP", re.IGNORECASE),    "gps_quality",  "accuracy_m"),
    # Priority 24-30: engine
    (re.compile(r"RPM", re.IGNORECASE),              "engine",       "engine_rpm"),
    (re.compile(r"Throttle|TPS", re.IGNORECASE),     "engine",       "throttle_pct"),
    (re.compile(r"Coolant", re.IGNORECASE),          "engine",       "coolant_temp_c"),
    (re.compile(r"Oil.*temp", re.IGNORECASE),        "engine",       "oil_temp_c"),
    (re.compile(r"Intake.*temp", re.IGNORECASE),     "engine",       "intake_temp_c"),
    (re.compile(r"Battery|Volt", re.IGNORECASE),     "engine",       "battery_v"),
    (re.compile(r"Boost|^MAP$", re.IGNORECASE),      "engine",       "boost_kpa"),
    # Priority 31: brake
    (re.compile(r"Brake", re.IGNORECASE),            "pedal",        "brake_pct"),
    # Priority 32: steering
    (re.compile(r"Steer", re.IGNORECASE),            "steering",     "steering_angle_deg"),
    # Priority 33: biometric
    (re.compile(r"Heart.*rate|^HR$|BPM", re.IGNORECASE), "biometric", "heart_rate_bpm"),
]


def classify_channel(name: str, unit: str | None) -> tuple[str, str]:
    """Classify a channel name into (category, internal_name).

    Uses priority-ordered pattern matching. Returns ``("custom", raw_name)``
    for anything that does not match a known pattern.
    """
    for pattern, category, internal in _RULES:
        if isinstance(pattern, str):
            # Exact-match sentinel: "__exact__<Name>"
            exact_name = pattern.split("__exact__", 1)[1]
            if name == exact_name:
                return (category, internal)
        else:
            if pattern.search(name):
                return (category, internal)
    # Fallback: custom channel — preserve raw name (with unit if present)
    custom_internal = name if unit is None else f"{name}_{unit}"
    return ("custom", custom_internal)


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------
_FACTOR_MAP: dict[str, float] = {
    "G":      _G,
    "g":      _G,
    "km/h":   1.0 / 3.6,
    "mph":    0.44704,
    "kn":     0.514444,
    "knots":  0.514444,
    "ft":     0.3048,
    "ft/s":   0.3048,
    "rad/s":  _DEG_PER_RAD,
    "kPa":    0.01,
    "psi":    0.0689476,
}


def _fahrenheit_to_celsius(v: float) -> float:
    return (v - 32.0) * 5.0 / 9.0


_FUNC_MAP: dict[str, Callable[[float], float]] = {
    "°F": _fahrenheit_to_celsius,
    "F":  _fahrenheit_to_celsius,
}


def get_conversion(
    unit: str | None,
) -> tuple[float | None, Callable[[float], float] | None]:
    """Return (multiplication_factor, function) for the given unit.

    At most one of factor/function will be non-None.
    If no conversion is needed, both are None.
    """
    if unit is None:
        return (None, None)
    if unit in _FUNC_MAP:
        return (None, _FUNC_MAP[unit])
    if unit in _FACTOR_MAP:
        return (_FACTOR_MAP[unit], None)
    return (None, None)


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------
def detect_format(metadata: dict[str, str]) -> str:
    """Detect CSV source format from metadata dict.

    Returns ``"racechrono"`` | ``"racebox"`` | ``"unknown"``.
    """
    for key, val in metadata.items():
        combined = f"{key} {val}".lower()
        if "racechrono" in combined:
            return "racechrono"
        if "racebox" in combined:
            return "racebox"
    return "unknown"


# ---------------------------------------------------------------------------
# Main discovery pipeline
# ---------------------------------------------------------------------------
def discover_columns(df: pd.DataFrame) -> DiscoveryResult:
    """Discover, classify, and plan conversions for all DataFrame columns.

    Conflict resolution:
    - ``*calc`` columns win over non-calc for the same internal name.
    - Among same-flag columns, the first match wins.
    - Losers go into ``custom_channels``.
    """
    result = DiscoveryResult()

    # Track which internal names are claimed and by whom
    # key = internal_name, value = (raw_col, is_calc)
    claimed: dict[str, tuple[str, bool]] = {}

    # First pass: parse, classify, determine conversions
    parsed_channels: list[DiscoveredChannel] = []
    for raw_col in df.columns:
        name, unit, flag = parse_header(raw_col)
        is_calc = flag == "calc" if flag else False
        category, internal = classify_channel(name, unit)
        factor, func = get_conversion(unit)

        ch = DiscoveredChannel(
            raw_name=raw_col,
            internal_name=internal,
            category=category,
            unit_raw=unit,
            unit_internal=None,
            is_calc=is_calc,
            conversion_factor=factor,
            n_valid=int(df[raw_col].notna().sum()),
        )
        # Store the function-based conversion reference on the channel object
        # (not serialized — only used during apply_discovery)
        ch._conversion_func = func  # type: ignore[attr-defined]
        parsed_channels.append(ch)

    # Second pass: resolve conflicts
    for ch in parsed_channels:
        internal = ch.internal_name
        if internal in claimed:
            existing_raw, existing_calc = claimed[internal]
            if ch.is_calc and not existing_calc:
                # *calc wins — demote the existing one
                result.custom_channels.append(existing_raw)
                result.calc_overrides[internal] = ch.raw_name
                claimed[internal] = (ch.raw_name, ch.is_calc)
            else:
                # Existing wins — this one becomes custom
                result.custom_channels.append(ch.raw_name)
                continue
        else:
            claimed[internal] = (ch.raw_name, ch.is_calc)
            if ch.is_calc:
                result.calc_overrides[internal] = ch.raw_name

    # Third pass: build rename_map and conversions from winners only
    winner_raws = {raw for raw, _calc in claimed.values()}
    for ch in parsed_channels:
        if ch.raw_name not in winner_raws:
            continue
        result.channels.append(ch)
        if ch.raw_name != ch.internal_name:
            result.rename_map[ch.raw_name] = ch.internal_name
        if ch.conversion_factor is not None:
            result.conversions[ch.raw_name] = ch.conversion_factor

    return result


# ---------------------------------------------------------------------------
# Apply discovery result to a DataFrame
# ---------------------------------------------------------------------------
def apply_discovery(df: pd.DataFrame, result: DiscoveryResult) -> pd.DataFrame:
    """Apply rename + conversions to a DataFrame.

    1. Function-based conversions (e.g. degF -> degC) applied BEFORE rename.
    2. Rename via ``df.rename()``.
    3. Multiplication-factor conversions applied AFTER rename (using internal name).
    """
    df = df.copy()

    # Step 1: function-based conversions (operate on raw column names)
    for ch in result.channels:
        func = getattr(ch, "_conversion_func", None)
        if func is not None and ch.raw_name in df.columns:
            df[ch.raw_name] = df[ch.raw_name].apply(
                lambda v, f=func: f(v) if pd.notna(v) else v
            )

    # Step 2: rename
    df = df.rename(columns=result.rename_map)

    # Step 3: multiplication-factor conversions (operate on internal names)
    for raw_col, factor in result.conversions.items():
        internal = result.rename_map.get(raw_col, raw_col)
        if internal in df.columns:
            df[internal] = df[internal] * factor

    return df
