"""Le Mans Ultimate / rFactor 2 vehicle data extractor.

LMU uses the rFactor 2 engine.  Vehicle physics are stored in ``.hdv``
files (INI-like format) inside ``.mas`` archives or loose folders.
Since ``.mas`` files are a custom binary format, this module only reads
loose ``.hdv`` files found in the install tree.

All public functions log warnings on failure and return ``None``/empty.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telemetry_tool.lap_oracle.config import SIM_PATHS

logger = logging.getLogger(__name__)


def parse_lmu_hdv(path: Path) -> Optional[dict]:
    """Parse an rFactor 2 / LMU ``.hdv`` vehicle file.

    The ``.hdv`` format is INI-like with ``[SECTION]`` headers and
    ``Key=Value`` pairs.  Some values use tuples: ``(a, b, c)``.

    Parameters
    ----------
    path:
        Path to a ``.hdv`` file.

    Returns
    -------
    dict or None
        Extracted vehicle parameters.  Keys may include:
        ``mass_kg``, ``wheelbase_m``, ``cg_height_m``,
        ``max_power_w``, ``car_name``, ``sim``.
        Returns ``None`` if file cannot be parsed.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return None

    sections = _parse_hdv_sections(text)
    if not sections:
        return None

    result: dict = {
        "car_name": path.stem,
        "sim": "lmu",
        "source_file": str(path),
    }

    # -- [GENERAL] section: mass, rules category
    general = sections.get("GENERAL", {})
    for key, result_key in (
        ("Mass", "mass_kg"),
        ("mass", "mass_kg"),
    ):
        if key in general and result_key not in result:
            val = _first_float(general[key])
            if val is not None:
                result[result_key] = val

    # Rules class / category
    for key in ("Rules", "Category"):
        if key in general:
            result["category"] = general[key].strip()

    # -- [SUSPENSION] section: wheelbase, track widths
    for susp_key in ("SUSPENSION", "FRONTSUSPENSION", "REARSUSPENSION"):
        sec = sections.get(susp_key, {})
        for key in ("PhysicalModelFile",):
            if key in sec:
                result[f"{susp_key.lower()}_model"] = sec[key].strip()

    # -- [ENGINE] section: power
    engine = sections.get("ENGINE", {})
    for key in ("RPMTorque", "Normal"):
        if key in engine:
            result["engine_hint"] = engine[key][:120]

    # -- [FRONTWING] / [REARWING]: aero
    for wing_key in ("FRONTWING", "REARWING"):
        sec = sections.get(wing_key, {})
        for k in ("FWSetting", "RWSetting", "FWLiftParams", "RWLiftParams"):
            if k in sec:
                val = _first_float(sec[k])
                if val is not None:
                    result[f"{wing_key.lower()}_{k.lower()}"] = val

    # -- [LEFTFENDER] as CG proxy
    for sec_key in ("LEFTFENDER", "BODY"):
        sec = sections.get(sec_key, {})
        if "CG" in sec or "cg" in sec:
            cg_str = sec.get("CG", sec.get("cg", ""))
            parts = _parse_tuple(cg_str)
            if len(parts) >= 3:
                result["cg_height_m"] = parts[1]  # Y is vertical in rF2

    if not result.get("mass_kg"):
        logger.debug("No mass found in %s", path.name)
        return None

    return result


def discover_lmu_vehicles() -> List[Tuple[str, Path]]:
    """Scan LMU install directories for ``.hdv`` vehicle files.

    Searches recursively under the Installed/Vehicles tree.

    Returns
    -------
    list of (vehicle_name, hdv_path)
    """
    results: List[Tuple[str, Path]] = []

    for base in SIM_PATHS.get("lmu", []):
        vehicles_root = base / "Installed" / "Vehicles"
        if not vehicles_root.is_dir():
            # Also try top-level Vehicles
            vehicles_root = base / "Vehicles"
            if not vehicles_root.is_dir():
                continue

        for hdv_path in sorted(vehicles_root.rglob("*.hdv")):
            results.append((hdv_path.stem, hdv_path))

    # If no loose .hdv found, LMU may have them inside .mas archives
    # (which we cannot parse without the binary format spec)
    if not results:
        logger.info(
            "No loose .hdv files found in LMU install paths. "
            "Vehicle data may be inside .mas archives."
        )

    logger.info("Discovered %d LMU vehicle file(s)", len(results))
    return results


# -- helpers ---------------------------------------------------------------

def _parse_hdv_sections(text: str) -> Dict[str, Dict[str, str]]:
    """Parse an HDV file into ``{section: {key: value}}``."""
    result: Dict[str, Dict[str, str]] = {}
    current = "__root__"
    result[current] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue

        # Section header
        if line.startswith("[") and "]" in line:
            current = line[1 : line.index("]")].strip()
            if current not in result:
                result[current] = {}
            continue

        # Key=Value
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            # Strip inline comments
            for cchar in ("//",):
                idx = value.find(cchar)
                if idx != -1:
                    value = value[:idx]
            result[current][key] = value.strip()

    return result


def _first_float(value: str) -> Optional[float]:
    """Extract the first numeric value from a string.

    Handles plain numbers, tuples ``(a, b, c)``, and pipe-separated
    alternatives.
    """
    # Try direct parse first
    try:
        return float(value.strip())
    except ValueError:
        pass
    # Try first number in parentheses or comma-separated
    match = re.search(r"[-+]?\d*\.?\d+", value)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            pass
    return None


def _parse_tuple(value: str) -> List[float]:
    """Parse ``(a, b, c)`` or ``a, b, c`` into list of floats."""
    # Strip parentheses
    cleaned = value.strip().strip("()")
    parts = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", cleaned)
    result: List[float] = []
    for p in parts:
        try:
            result.append(float(p))
        except ValueError:
            pass
    return result
