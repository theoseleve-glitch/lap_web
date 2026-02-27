"""
metadata.py
-----------
Parse a sidecar metadata file (CSV, JSON, or YAML) that maps session
files to kart/driver/condition information.
"""
from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MetadataError(ValueError):
    """Raised when the metadata file cannot be parsed."""


@dataclass
class SessionMetadata:
    """Metadata for a single telemetry session file."""

    session_file: str
    product_tier: str | None = None
    layout_id: str | None = None
    domain_whitelist_id: str | None = None
    sensor_profile: str | None = None
    kart_id: str = "unknown_kart"
    kart_model: str | None = None
    kart_class: str = "4t"           # "2t" or "4t"
    driver_weight_kg: float = 85.0
    kart_weight_kg: float | None = None
    engine_peak_power_kw: float | None = None
    engine_peak_power_hp: float | None = None
    engine_peak_torque_nm: float | None = None
    engine_type: str | None = None
    engine_size_cc: float | None = None
    kart_data_acd: str | None = None
    # Optional external assets / advanced model inputs.
    track_lidar_profile_path: str | None = None
    track_grip_map_path: str | None = None
    load_transfer_fe_map_path: str | None = None
    # Optional aero + transmission metadata.
    aero_cda: float | None = None
    aero_cl: float | None = None
    gear_count: int | None = None
    gear_ratios: str | None = None
    final_drive_ratio: float | None = None
    shift_rpm_up: float | None = None
    shift_rpm_down: float | None = None
    tire_type: str = "slick"         # "slick" or "wet"
    track_name: str | None = None
    condition_label: str | None = None  # dry / damp / wet / green
    track_record_s: float | None = None
    notes: str = ""


def parse_metadata(path: str | Path) -> list[SessionMetadata]:
    """Auto-detect format (CSV / JSON / YAML) and parse.

    Returns
    -------
    list[SessionMetadata]
        One entry per session described in the metadata file.

    Raises
    ------
    MetadataError
        If the file is missing, empty, or has an unsupported format.
    """
    path = Path(path)
    if not path.exists():
        raise MetadataError(f"Metadata file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _parse_csv(path)
    if suffix == ".json":
        return _parse_json(path)
    if suffix in {".yaml", ".yml"}:
        return _parse_yaml(path)

    raise MetadataError(f"Unsupported metadata format: {suffix}")


# ---------------------------------------------------------------------------
# Format-specific parsers
# ---------------------------------------------------------------------------

def _row_to_meta(d: dict[str, Any]) -> SessionMetadata:
    """Convert a flat dict to a SessionMetadata, coercing types."""
    # Normalise key names (lowercase, strip whitespace, underscores)
    nd: dict[str, Any] = {}
    for k, v in d.items():
        nk = str(k).strip().lower().replace(" ", "_")
        # common aliases
        if nk in ("file_name", "file", "filename", "csv"):
            nk = "session_file"
        if nk in ("product_tier", "tier", "plan_tier", "subscription_tier"):
            nk = "product_tier"
        if nk in ("layout", "layout_id", "track_layout"):
            nk = "layout_id"
        if nk in ("domain_whitelist", "domain_whitelist_id", "scope_id"):
            nk = "domain_whitelist_id"
        if nk in ("sensor_profile", "sensor_contract", "sensor_tier"):
            nk = "sensor_profile"
        if nk in ("kart_model_name", "kart"):
            nk = "kart_id"
        if nk in ("model", "chassis", "kart_name"):
            nk = "kart_model"
        if nk in ("class", "kart_type", "kart_category"):
            nk = "kart_class"
        if nk in ("engine_type", "engine", "motor_type", "power_unit"):
            nk = "engine_type"
        if nk in ("driver_weight", "weight_kg", "weight"):
            nk = "driver_weight_kg"
        if nk in ("kart_weight", "kart_mass_kg"):
            nk = "kart_weight_kg"
        if nk in ("peak_power_kw", "power_kw", "engine_power_kw", "engine_peak_power"):
            nk = "engine_peak_power_kw"
        if nk in ("peak_power_hp", "power_hp", "engine_power_hp", "horsepower", "hp"):
            nk = "engine_peak_power_hp"
        if nk in ("peak_torque_nm", "torque_nm", "engine_torque_nm", "engine_peak_torque"):
            nk = "engine_peak_torque_nm"
        if nk in ("engine_cc", "displacement_cc", "engine_size", "size_cc", "cc", "displacement"):
            nk = "engine_size_cc"
        if nk in ("kart_data_acd", "acd", "acd_path", "acd_file", "kart_acd", "kart_data"):
            nk = "kart_data_acd"
        if nk in ("track_lidar_profile", "lidar_profile", "lidar_profile_path", "track_lidar"):
            nk = "track_lidar_profile_path"
        if nk in ("track_grip_map", "grip_map", "gripmap", "track_grip_map_path"):
            nk = "track_grip_map_path"
        if nk in ("load_transfer_map", "load_transfer_fe", "load_transfer_fe_map", "load_transfer_fe_map_path"):
            nk = "load_transfer_fe_map_path"
        if nk in ("cda", "aero_cda", "drag_cda"):
            nk = "aero_cda"
        if nk in ("cl", "aero_cl", "lift_coeff"):
            nk = "aero_cl"
        if nk in ("gear_count", "n_gears"):
            nk = "gear_count"
        if nk in ("gear_ratios", "ratios", "gear_ratio_list"):
            nk = "gear_ratios"
        if nk in ("final_drive", "final_drive_ratio"):
            nk = "final_drive_ratio"
        if nk in ("shift_rpm_up", "upshift_rpm"):
            nk = "shift_rpm_up"
        if nk in ("shift_rpm_down", "downshift_rpm"):
            nk = "shift_rpm_down"
        if nk in ("tyre_type", "tire", "tyre", "compound_type"):
            nk = "tire_type"
        if nk in ("track", "circuit"):
            nk = "track_name"
        if nk in ("condition", "conditions", "weather"):
            nk = "condition_label"
        if nk in ("track_record", "record", "record_time", "record_s",
                   "track_record_seconds"):
            nk = "track_record_s"
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                v = None
        nd[nk] = v

    # Coerce floats
    for fld in (
        "driver_weight_kg",
        "kart_weight_kg",
        "engine_peak_power_kw",
        "engine_peak_power_hp",
        "engine_peak_torque_nm",
        "engine_size_cc",
        "aero_cda",
        "aero_cl",
        "final_drive_ratio",
        "shift_rpm_up",
        "shift_rpm_down",
    ):
        if fld in nd and nd[fld] is not None:
            nd[fld] = _coerce_float(nd[fld])

    if "gear_count" in nd and nd["gear_count"] is not None:
        try:
            nd["gear_count"] = int(float(nd["gear_count"]))
        except (TypeError, ValueError):
            nd["gear_count"] = None

    if "track_record_s" in nd and nd["track_record_s"] is not None:
        nd["track_record_s"] = _parse_time_seconds(nd["track_record_s"])

    # Backward compatibility: old metadata sometimes stores "2t"/"4t" in engine_type.
    if "kart_class" not in nd and isinstance(nd.get("engine_type"), str):
        et = nd["engine_type"].strip().lower()
        if et in {"2t", "4t"}:
            nd["kart_class"] = et

    # Filter to valid fields
    valid_fields = {f.name for f in SessionMetadata.__dataclass_fields__.values()}
    filtered = {k: v for k, v in nd.items() if k in valid_fields and v is not None}

    if "session_file" not in filtered:
        raise MetadataError(f"Row missing 'session_file' (or alias): {d}")

    return SessionMetadata(**filtered)


def _parse_csv(path: Path) -> list[SessionMetadata]:
    results: list[SessionMetadata] = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        # auto-detect delimiter
        sample = fh.read(4096)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        reader = csv.DictReader(fh, dialect=dialect)
        for row in reader:
            results.append(_row_to_meta(row))
    logger.info("Loaded %d session entries from CSV %s", len(results), path.name)
    return results


def _parse_json(path: Path) -> list[SessionMetadata]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        # support {"sessions": [...]} wrapper
        data = data.get("sessions", [data])
    if not isinstance(data, list):
        raise MetadataError(f"Expected JSON array or object with 'sessions' key: {path}")
    results = [_row_to_meta(d) for d in data]
    logger.info("Loaded %d session entries from JSON %s", len(results), path.name)
    return results


def _parse_yaml(path: Path) -> list[SessionMetadata]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise MetadataError("PyYAML is required to parse YAML metadata") from exc

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if isinstance(data, dict):
        data = data.get("sessions", [data])
    if not isinstance(data, list):
        raise MetadataError(f"Expected YAML list or mapping with 'sessions': {path}")
    results = [_row_to_meta(d) for d in data]
    logger.info("Loaded %d session entries from YAML %s", len(results), path.name)
    return results


def _coerce_float(value: Any) -> float | None:
    """Parse numeric values from plain floats or strings like '390cc'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            out = float(value)
            return out if out == out else None
        except (TypeError, ValueError):
            return None

    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _parse_time_seconds(value: Any) -> float | None:
    """
    Parse track record time to seconds.

    Accepts:
    - float seconds: 42.513
    - mm:ss.xxx: 1:03.097
    - mm:ss:xxx: 1:03:097
    - s\"mmm: 43\"486
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            out = float(value)
            return out if out > 0 else None
        except (TypeError, ValueError):
            return None

    s = str(value).strip().lower()
    if not s:
        return None
    s = s.replace(" ", "")
    s = s.replace("'", ":")
    s = s.replace('"', ":")

    # mm:ss:ms format
    if re.fullmatch(r"\d+:\d{1,2}:\d{1,3}", s):
        mm_s, ss_s, ms_s = s.split(":")
        mm = int(mm_s)
        ss = int(ss_s)
        ms = int(ms_s)
        if ss >= 60:
            return None
        scale = 10 ** len(ms_s)
        return float(mm * 60 + ss + (ms / scale))

    # mm:ss(.sss) format
    if re.fullmatch(r"\d+:\d{1,2}(\.\d+)?", s):
        mm_s, sec_s = s.split(":")
        mm = int(mm_s)
        sec = float(sec_s)
        if sec >= 60:
            return None
        return float(mm * 60 + sec)

    # fallback numeric parse
    return _coerce_float(s)
