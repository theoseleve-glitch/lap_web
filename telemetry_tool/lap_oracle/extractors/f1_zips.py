"""F1 open-data ZIP extractor.

Processes ZIP archives from the open-source F1 telemetry project.
Each ZIP contains GP folders, session folders, driver folders, and
per-lap ``{lap_number}_tel.json`` files.

JSON format (per lap)::

    {
      "tel": {
        "time": [...],       // seconds
        "speed": [...],      // km/h
        "throttle": [...],   // 0-100
        "brake": [...],      // 0/100
        "acc_x": [...],      // lateral G? (sign varies)
        "acc_y": [...],      // longitudinal G?
        "x": [...],          // track x position
        "y": [...],          // track y position
        "dataKey": "2022-Abu Dhabi Grand Prix-Practice 1-ALB-10"
      }
    }

All public functions log warnings on failure and return empty/``None``.
"""
from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def process_f1_zip(
    zip_path: Path,
    max_laps: int = 500,
) -> List[dict]:
    """Extract standardized telemetry dicts from an F1 data ZIP.

    Parameters
    ----------
    zip_path:
        Path to a year ZIP (e.g. ``2022-main.zip``).
    max_laps:
        Stop after extracting this many laps (to limit memory).

    Returns
    -------
    list of dict
        Each dict has keys: ``time_s``, ``speed_mps``, ``a_lat_g``,
        ``a_lon_g``, ``x``, ``y``, ``throttle``, ``brake``,
        ``gp_name``, ``driver``, ``session``, ``lap_number``.
        Lists are numpy-free (plain Python floats) for easy JSON
        round-tripping.
    """
    if not zip_path.is_file():
        logger.warning("F1 ZIP not found: %s", zip_path)
        return []

    results: List[dict] = []

    try:
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            # Find all *_tel.json entries
            tel_entries = [
                n for n in zf.namelist()
                if n.endswith("_tel.json") and not n.startswith("__MACOSX")
            ]
            logger.info(
                "Found %d tel.json entries in %s",
                len(tel_entries), zip_path.name,
            )

            for entry_name in tel_entries:
                if len(results) >= max_laps:
                    break

                parsed = _parse_tel_entry(zf, entry_name)
                if parsed is not None:
                    results.append(parsed)

    except (zipfile.BadZipFile, OSError) as exc:
        logger.warning("Error processing %s: %s", zip_path, exc)

    logger.info(
        "Extracted %d laps from %s", len(results), zip_path.name
    )
    return results


def _parse_tel_entry(
    zf: zipfile.ZipFile,
    entry_name: str,
) -> Optional[dict]:
    """Parse a single ``*_tel.json`` entry from an open zip.

    Returns
    -------
    dict or None
        Standardized telemetry dict, or ``None`` on failure.
    """
    try:
        raw = zf.read(entry_name)
        data = json.loads(raw)
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        logger.debug("Cannot parse %s: %s", entry_name, exc)
        return None

    tel = data.get("tel") if isinstance(data, dict) else None
    if tel is None or not isinstance(tel, dict):
        logger.debug("No 'tel' key in %s", entry_name)
        return None

    # Required arrays
    time_arr = tel.get("time")
    speed_arr = tel.get("speed")
    x_arr = tel.get("x")
    y_arr = tel.get("y")

    if not time_arr or not speed_arr or not x_arr or not y_arr:
        return None

    n = len(time_arr)
    if n < 10:
        return None

    # Parse path to extract metadata
    # Path format: YEAR-main/GP Name/Session/DRIVER/LAP_tel.json
    gp_name, session, driver, lap_number = _parse_path_metadata(entry_name)

    # Convert speed km/h -> m/s
    speed_mps = [s / 3.6 if isinstance(s, (int, float)) else 0.0
                 for s in speed_arr]

    # Throttle 0-100 -> 0-1
    throttle_raw = tel.get("throttle", [0.0] * n)
    throttle = [t / 100.0 if isinstance(t, (int, float)) else 0.0
                for t in throttle_raw]

    # Brake 0-100 -> 0-1
    brake_raw = tel.get("brake", [0] * n)
    brake = [b / 100.0 if isinstance(b, (int, float)) else 0.0
             for b in brake_raw]

    # Accelerations -- sign conventions vary; pass through as-is
    a_lat = tel.get("acc_x", [0.0] * n)
    a_lon = tel.get("acc_y", [0.0] * n)

    return {
        "time_s": [float(t) for t in time_arr],
        "speed_mps": speed_mps,
        "a_lat_g": [float(a) if isinstance(a, (int, float)) else 0.0
                    for a in a_lat],
        "a_lon_g": [float(a) if isinstance(a, (int, float)) else 0.0
                    for a in a_lon],
        "x": [float(v) if isinstance(v, (int, float)) else 0.0
              for v in x_arr],
        "y": [float(v) if isinstance(v, (int, float)) else 0.0
              for v in y_arr],
        "throttle": throttle,
        "brake": brake,
        "gp_name": gp_name,
        "driver": driver,
        "session": session,
        "lap_number": lap_number,
    }


def _parse_path_metadata(entry_name: str):
    """Extract GP name, session type, driver code, and lap number from path.

    Expected format: ``YEAR-main/GP Name/Session/DRIVER/LAP_tel.json``

    Returns
    -------
    tuple of (gp_name, session, driver, lap_number)
    """
    parts = entry_name.replace("\\", "/").split("/")

    # Filter out empty parts and the YEAR-main root
    parts = [p for p in parts if p and not p.endswith("-main")]

    gp_name = parts[0] if len(parts) > 0 else "unknown"
    session = parts[1] if len(parts) > 1 else "unknown"
    driver = parts[2] if len(parts) > 2 else "unknown"

    # Lap number from filename
    filename = parts[-1] if parts else ""
    lap_match = re.match(r"(\d+)_tel\.json$", filename)
    lap_number = int(lap_match.group(1)) if lap_match else 0

    return gp_name, session, driver, lap_number
