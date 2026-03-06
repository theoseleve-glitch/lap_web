"""
filter_profile.py
-----------------
Configurable filter profiles for GPS quality filtering and outlier thresholds.

Replaces hardcoded defaults with YAML-based configuration that can vary
by track, session type, or sensor profile.

Profiles support single-level inheritance via the ``inherits`` key.

Public API
~~~~~~~~~~
``resolve_filter_profile(name, track_id, session_type, sensor_profile)``
    Load and return a FilterProfile, with priority:
    explicit name > track_id > session_type > "default".

``FilterProfile``
    Frozen dataclass with all threshold values.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Profile dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FilterProfile:
    """Immutable set of filter thresholds."""

    profile_name: str = "default"
    version: int = 1

    # GPS gates
    gps_min_satellites: int = 5
    gps_max_accuracy_m: float = 3.0
    gps_max_speed_mps: float = 80.0
    gps_max_accel_mps2: float = 50.0

    # Lap gates
    laps_min_samples_per_lap: int = 50
    laps_min_lap_distance_m: float = 100.0
    laps_outlap_time_ratio: float = 1.5

    # Outlier gates
    outliers_mad_threshold: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise for metadata storage."""
        return {
            "profile_name": self.profile_name,
            "version": self.version,
            "gps_min_satellites": self.gps_min_satellites,
            "gps_max_accuracy_m": self.gps_max_accuracy_m,
            "gps_max_speed_mps": self.gps_max_speed_mps,
            "gps_max_accel_mps2": self.gps_max_accel_mps2,
            "laps_min_samples_per_lap": self.laps_min_samples_per_lap,
            "laps_min_lap_distance_m": self.laps_min_lap_distance_m,
            "laps_outlap_time_ratio": self.laps_outlap_time_ratio,
            "outliers_mad_threshold": self.outliers_mad_threshold,
        }


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

# Default config directory (can be overridden via env var)
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config" / "filter_profiles"

# Track-to-profile mapping (extendable)
_TRACK_PROFILE_MAP: dict[str, str] = {
    # Add track_id -> profile_name mappings here
}

# Session-type to profile mapping
_SESSION_TYPE_MAP: dict[str, str] = {
    # Add session_type -> profile_name mappings here
}


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, with a fallback to basic parsing if PyYAML absent."""
    try:
        import yaml
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Minimal YAML-like parser for simple flat/nested configs
        result: dict[str, Any] = {}
        current_section = None
        with open(path, "r") as f:
            for line in f:
                line = line.rstrip()
                if not line or line.startswith("#"):
                    continue
                if not line.startswith(" ") and line.endswith(":"):
                    key = line.rstrip(":").strip()
                    if key in ("gps", "laps", "outliers"):
                        current_section = key
                        result[current_section] = {}
                    else:
                        # Top-level key-value
                        current_section = None
                elif ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    # Auto-convert types
                    parsed = _auto_type(val)
                    if current_section and current_section in result:
                        result[current_section][key] = parsed
                    else:
                        result[key] = parsed
        return result


def _auto_type(val: str) -> Any:
    """Convert string to int/float/bool if possible."""
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _merge_dicts(parent: dict, child: dict) -> dict:
    """Deep merge child into parent (child wins)."""
    merged = dict(parent)
    for key, val in child.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], val)
        else:
            merged[key] = val
    return merged


def _dict_to_profile(data: dict[str, Any]) -> FilterProfile:
    """Convert a loaded YAML dict to a FilterProfile."""
    gps = data.get("gps", {})
    laps = data.get("laps", {})
    outliers = data.get("outliers", {})

    return FilterProfile(
        profile_name=data.get("profile_name", "default"),
        version=data.get("version", 1),
        gps_min_satellites=gps.get("min_satellites", 5),
        gps_max_accuracy_m=gps.get("max_accuracy_m", 3.0),
        gps_max_speed_mps=gps.get("max_speed_mps", 80.0),
        gps_max_accel_mps2=gps.get("max_accel_mps2", 50.0),
        laps_min_samples_per_lap=laps.get("min_samples_per_lap", 50),
        laps_min_lap_distance_m=laps.get("min_lap_distance_m", 100.0),
        laps_outlap_time_ratio=laps.get("outlap_time_ratio", 1.5),
        outliers_mad_threshold=outliers.get("mad_threshold", 5.0),
    )


def _load_profile_by_name(
    name: str,
    config_dir: Path | None = None,
    _seen: set[str] | None = None,
) -> dict[str, Any]:
    """Load a profile YAML with inheritance resolution."""
    if _seen is None:
        _seen = set()
    if name in _seen:
        raise ValueError(f"Circular inheritance detected: {name}")
    _seen.add(name)

    search_dir = config_dir or _CONFIG_DIR
    path = search_dir / f"{name}.yaml"
    if not path.exists():
        path = search_dir / f"{name}.yml"
    if not path.exists():
        logger.warning("Filter profile %r not found at %s; using defaults", name, search_dir)
        return {}

    data = _load_yaml(path)
    parent_name = data.get("inherits")
    if parent_name:
        parent = _load_profile_by_name(parent_name, config_dir, _seen)
        data = _merge_dicts(parent, data)

    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_filter_profile(
    name: str | None = None,
    *,
    track_id: str | None = None,
    session_type: str | None = None,
    sensor_profile: str | None = None,
    config_dir: Path | None = None,
) -> FilterProfile:
    """
    Resolve a filter profile by priority:
    1. Explicit ``name`` or ``sensor_profile``
    2. ``track_id`` match in _TRACK_PROFILE_MAP
    3. ``session_type`` match in _SESSION_TYPE_MAP
    4. "default"
    """
    resolved_name = name or sensor_profile

    if not resolved_name and track_id:
        resolved_name = _TRACK_PROFILE_MAP.get(track_id)

    if not resolved_name and session_type:
        resolved_name = _SESSION_TYPE_MAP.get(session_type)

    if not resolved_name:
        resolved_name = "default"

    data = _load_profile_by_name(resolved_name, config_dir)
    if not data:
        logger.info("Using built-in default filter profile")
        return FilterProfile()

    profile = _dict_to_profile(data)
    logger.info(
        "Resolved filter profile: %s (v%d) [source=%s]",
        profile.profile_name, profile.version,
        "explicit" if name else ("track" if track_id else "default"),
    )
    return profile


def list_profiles(config_dir: Path | None = None) -> list[dict[str, Any]]:
    """List all available filter profiles."""
    search_dir = config_dir or _CONFIG_DIR
    if not search_dir.exists():
        return []

    profiles = []
    for path in sorted(search_dir.glob("*.y*ml")):
        data = _load_yaml(path)
        profiles.append({
            "name": data.get("profile_name", path.stem),
            "version": data.get("version", 1),
            "description": data.get("description", ""),
            "inherits": data.get("inherits"),
        })
    return profiles
