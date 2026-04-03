"""Assetto Corsa car data extractors.

Reads car physics parameters from AC's ``data.acd`` archives (ZIP format)
or plain-text fallbacks in ``data/`` subfolders.  All public functions
log warnings on failure and return ``None``/empty instead of raising.
"""
from __future__ import annotations

import configparser
import io
import logging
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telemetry_tool.lap_oracle.config import SIM_PATHS

logger = logging.getLogger(__name__)


# -- INI parser ------------------------------------------------------------

def parse_ac_ini(text: str) -> Dict[str, Dict[str, str]]:
    """Parse AC's INI-style configuration text.

    Returns a nested dict ``{section: {key: value}}``.  Handles AC quirks:
    bare keys, inline comments, and duplicate sections (last wins).

    Parameters
    ----------
    text:
        Raw INI text (e.g. contents of ``car.ini`` or ``tyres.ini``).

    Returns
    -------
    dict
        ``{section_name: {key: value}}``.  Section and key names are
        preserved in their original case.
    """
    result: Dict[str, Dict[str, str]] = {}
    current_section = "__root__"
    result[current_section] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("//"):
            continue

        # Section header
        if line.startswith("[") and "]" in line:
            current_section = line[1 : line.index("]")].strip()
            if current_section not in result:
                result[current_section] = {}
            continue

        # Key=value
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            # Strip inline comments
            for comment_char in (";", "//"):
                idx = value.find(comment_char)
                if idx != -1:
                    value = value[:idx]
            result[current_section][key] = value.strip()

    return result


# -- ACD / plain data extraction ------------------------------------------

def _read_acd_entry(acd_path: Path, entry_name: str) -> Optional[str]:
    """Try to read a file from a data.acd ZIP archive.

    Parameters
    ----------
    acd_path:
        Path to ``data.acd``.
    entry_name:
        Name inside the archive (e.g. ``"car.ini"``).

    Returns
    -------
    str or None
        Decoded text content, or ``None`` on any failure.
    """
    try:
        with zipfile.ZipFile(str(acd_path), "r") as zf:
            # Case-insensitive lookup
            lower_map = {n.lower(): n for n in zf.namelist()}
            real_name = lower_map.get(entry_name.lower())
            if real_name is None:
                return None
            return zf.read(real_name).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError, KeyError) as exc:
        logger.debug("Cannot read %s from %s: %s", entry_name, acd_path, exc)
        return None


def _read_plain_data(data_dir: Path, entry_name: str) -> Optional[str]:
    """Read a plain-text data file from an unencrypted ``data/`` subfolder.

    Parameters
    ----------
    data_dir:
        Path to the ``data/`` directory alongside (or replacing) ``data.acd``.
    entry_name:
        Filename to read (e.g. ``"car.ini"``).

    Returns
    -------
    str or None
        File content, or ``None`` if not found.
    """
    # Case-insensitive file search
    if not data_dir.is_dir():
        return None
    for child in data_dir.iterdir():
        if child.name.lower() == entry_name.lower() and child.is_file():
            try:
                return child.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.debug("Cannot read %s: %s", child, exc)
    return None


def _read_car_entry(car_folder: Path, entry_name: str) -> Optional[str]:
    """Read *entry_name* from a car's data, trying ACD first, then plain."""
    acd = car_folder / "data.acd"
    text = _read_acd_entry(acd, entry_name)
    if text is not None:
        return text
    return _read_plain_data(car_folder / "data", entry_name)


# -- Public API ------------------------------------------------------------

def parse_ac_car_data(car_folder: Path) -> Optional[dict]:
    """Extract physics parameters from an AC car folder.

    Tries ``data.acd`` (ZIP) first, falls back to ``data/`` plain files.
    Reads ``car.ini``, ``suspensions.ini``, ``tyres.ini``, and
    ``drivetrain.ini`` to build a parameter dict.

    Parameters
    ----------
    car_folder:
        Path to a car folder (e.g. ``content/cars/bmw_1m``).

    Returns
    -------
    dict or None
        Extracted parameters, or ``None`` if no usable data found.
        Keys may include: ``mass_kg``, ``wheelbase_m``, ``cg_height_m``,
        ``track_width_front_m``, ``track_width_rear_m``,
        ``max_power_w``, ``weight_dist_front``, ``car_name``, ``sim``.
    """
    car_text = _read_car_entry(car_folder, "car.ini")
    if car_text is None:
        logger.debug("No car.ini found in %s", car_folder)
        return None

    car_ini = parse_ac_ini(car_text)
    result: dict = {"car_name": car_folder.name, "sim": "ac"}

    # -- BASIC section: mass, inertia
    basic = car_ini.get("BASIC", {})
    if "totalmass" in {k.lower(): k for k in basic}:
        for k, v in basic.items():
            if k.lower() == "totalmass":
                result["mass_kg"] = _safe_float(v)

    # -- RIDE section or SUSPENSION: wheelbase, cg
    for section_name in ("RIDE", "CAR", "BASIC"):
        section = car_ini.get(section_name, {})
        for k, v in section.items():
            kl = k.lower()
            if kl == "wheelbase" and "wheelbase_m" not in result:
                result["wheelbase_m"] = _safe_float(v)
            elif kl == "cg_height" and "cg_height_m" not in result:
                result["cg_height_m"] = _safe_float(v)

    # -- SUSPENSION: front/rear track widths
    susp_text = _read_car_entry(car_folder, "suspensions.ini")
    if susp_text is not None:
        susp = parse_ac_ini(susp_text)
        for section_key, result_key in (
            ("FRONT", "track_width_front_m"),
            ("REAR", "track_width_rear_m"),
        ):
            sec = susp.get(section_key, {})
            for k, v in sec.items():
                if k.lower() == "track":
                    result[result_key] = _safe_float(v)
                    break

    # -- DRIVETRAIN: power
    dt_text = _read_car_entry(car_folder, "drivetrain.ini")
    if dt_text is not None:
        dt = parse_ac_ini(dt_text)
        # Look for max power in ENGINE section (may be in power.lut ref)
        engine = dt.get("ENGINE", {})
        for k, v in engine.items():
            if k.lower() == "bhp":
                bhp = _safe_float(v)
                if bhp is not None:
                    result["max_power_w"] = bhp * 745.7

    # Only return if we got at least mass
    if "mass_kg" not in result:
        logger.debug("No mass found for %s", car_folder.name)
        return None

    return result


def discover_ac_cars() -> List[Tuple[str, Path]]:
    """Scan all known AC install paths for car data.

    Returns
    -------
    list of (car_name, car_folder_path)
        Each entry identifies a car with either ``data.acd`` or ``data/``.
    """
    results: List[Tuple[str, Path]] = []

    for base in SIM_PATHS.get("ac", []):
        cars_dir = base / "content" / "cars"
        if not cars_dir.is_dir():
            continue

        for car_dir in sorted(cars_dir.iterdir()):
            if not car_dir.is_dir():
                continue
            # Check for data.acd or data/ subfolder
            has_acd = (car_dir / "data.acd").is_file()
            has_data = (car_dir / "data").is_dir()
            if has_acd or has_data:
                results.append((car_dir.name, car_dir))

    logger.info("Discovered %d AC car(s)", len(results))
    return results


# -- helpers ---------------------------------------------------------------

def _safe_float(value: str) -> Optional[float]:
    """Convert string to float, returning ``None`` on failure."""
    try:
        return float(value.split("|")[0].strip())
    except (ValueError, AttributeError, IndexError):
        return None
