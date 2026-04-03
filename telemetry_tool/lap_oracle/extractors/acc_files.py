"""Assetto Corsa Competizione setup file extractor.

ACC stores car setups as JSON files in the user's Documents folder:
``Documents/Assetto Corsa Competizione/Setups/{car_name}/{track_name}/``

All public functions log warnings on failure and return ``None``/empty.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Common ACC Documents path
_ACC_DOCS = Path("C:/Users/Admin/Documents/Assetto Corsa Competizione")


def parse_acc_setup(path: Path) -> Optional[dict]:
    """Parse an ACC JSON setup file.

    Parameters
    ----------
    path:
        Path to a ``.json`` setup file.

    Returns
    -------
    dict or None
        Parsed setup with at least ``car_name``, ``track_name``, and
        any available setup fields.  Returns ``None`` on parse error.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Cannot parse ACC setup %s: %s", path, exc)
        return None

    if not isinstance(data, dict):
        return None

    # Derive car_name and track_name from path hierarchy
    # Expected: .../Setups/{car_name}/{track_name}/{filename}.json
    parts = path.parts
    car_name = ""
    track_name = ""
    try:
        setups_idx = None
        for i, p in enumerate(parts):
            if p.lower() == "setups":
                setups_idx = i
                break
        if setups_idx is not None and setups_idx + 2 < len(parts):
            car_name = parts[setups_idx + 1]
            track_name = parts[setups_idx + 2]
    except (IndexError, ValueError):
        pass

    result: dict = {
        "car_name": car_name,
        "track_name": track_name,
        "sim": "acc",
        "file_path": str(path),
    }

    # Extract known setup sections
    for section_key in (
        "basicSetup",
        "advancedSetup",
        "tyreCompound",
        "fuelLevel",
    ):
        if section_key in data:
            result[section_key] = data[section_key]

    # Try to extract some flat physics-relevant parameters
    basic = data.get("basicSetup", {})
    advanced = data.get("advancedSetup", {})

    # Tyre pressures (ACC stores in integer units, divide by 10 for PSI)
    tyres = basic.get("tyres", {})
    if "tyrePressure" in tyres:
        tp = tyres["tyrePressure"]
        if isinstance(tp, list) and len(tp) == 4:
            result["tyre_pressures"] = [p / 10.0 for p in tp]

    # Brake bias (int, divide by 10 for percentage shift from center)
    mech = advanced.get("mechanicalBalance", {})
    if "brakeBias" in mech:
        result["brake_bias_raw"] = mech["brakeBias"]

    # Ride height (front/rear)
    aero = advanced.get("aeroBalance", {})
    for key in ("rideHeight",):
        if key in aero:
            rh = aero[key]
            if isinstance(rh, list) and len(rh) >= 2:
                result["ride_height_front"] = rh[0]
                result["ride_height_rear"] = rh[1]

    # ARB (anti-roll bar)
    if "bumpStopWindow" in mech:
        result["bump_stop_window"] = mech["bumpStopWindow"]

    return result


def discover_acc_setups(
    docs_path: Optional[Path] = None,
) -> List[dict]:
    """Scan ACC Documents folder for setup JSON files.

    Parameters
    ----------
    docs_path:
        Override for the ACC Documents root.  Defaults to the standard
        Windows location.

    Returns
    -------
    list of dict
        Each dict is the output of :func:`parse_acc_setup`.
    """
    base = (docs_path or _ACC_DOCS) / "Setups"
    if not base.is_dir():
        logger.info("ACC Setups directory not found: %s", base)
        return []

    results: List[dict] = []

    for json_path in sorted(base.rglob("*.json")):
        parsed = parse_acc_setup(json_path)
        if parsed is not None:
            results.append(parsed)

    logger.info("Discovered %d ACC setup(s)", len(results))
    return results
