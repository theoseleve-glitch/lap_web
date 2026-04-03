"""Multi-sim track extraction -- AC AI files and raw telemetry.

All public functions log warnings on failure and return ``None`` instead
of raising.
"""
from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from telemetry_tool.lap_oracle.config import SIM_PATHS, TrackModel
from telemetry_tool.lap_oracle.track.model import build_from_xy

logger = logging.getLogger(__name__)


# -- Assetto Corsa AI lane files -----------------------------------------

def _try_binary_fast_lane(path: Path) -> Optional[np.ndarray]:
    """Try to parse an AC ``fast_lane.ai`` binary file.

    Binary format: 4-byte uint32 point count, then per-point records.
    AC uses x, z as the horizontal plane (y is vertical).  We try two
    common record sizes: 18 bytes (6 * 3-byte? -- actually 3 floats +
    padding) and 12 bytes (3 floats exactly).
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return None

    if len(data) < 8:
        return None

    count = struct.unpack_from("<I", data, 0)[0]
    if count < 10 or count > 500_000:
        return None

    # Try 18-byte records (common AC format: 3 floats + 6 extra bytes)
    for record_size in (18, 12):
        expected = 4 + count * record_size
        if len(data) < expected:
            continue
        try:
            points = []
            offset = 4
            for _ in range(count):
                x, y, z = struct.unpack_from("<fff", data, offset)
                points.append((x, z))  # AC: x,z = horizontal
                offset += record_size
            return np.array(points, dtype=np.float64)
        except struct.error:
            continue

    return None


def _try_csv_ai(path: Path) -> Optional[np.ndarray]:
    """Try to load an AI CSV file (comma-delimited, first 2 cols = x, y)."""
    try:
        arr = np.loadtxt(str(path), delimiter=",", dtype=np.float64)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot parse CSV %s: %s", path, exc)
        return None

    if arr.ndim == 1:
        return None
    if arr.shape[0] < 10 or arr.shape[1] < 2:
        return None
    return arr[:, :2]


def extract_ac_track(track_folder: Path) -> Optional[TrackModel]:
    """Extract a track model from an AC track folder.

    Looks for ``ai/fast_lane.ai`` (binary) first, then falls back to
    any ``ai/*.csv`` file.

    Parameters
    ----------
    track_folder:
        Path to an AC track folder (e.g.
        ``content/tracks/monza``).

    Returns
    -------
    TrackModel or None
        Parsed track model, or ``None`` on failure.
    """
    ai_dir = track_folder / "ai"
    name = track_folder.name

    # Binary fast_lane.ai
    fast_lane = ai_dir / "fast_lane.ai"
    if fast_lane.is_file():
        xy = _try_binary_fast_lane(fast_lane)
        if xy is not None and xy.shape[0] >= 10:
            logger.info(
                "Extracted %d points from %s", xy.shape[0], fast_lane
            )
            try:
                return build_from_xy(xy, name=name, sim="ac")
            except ValueError as exc:
                logger.warning("build_from_xy failed for %s: %s", name, exc)

    # CSV fallback
    if ai_dir.is_dir():
        for csv_path in sorted(ai_dir.glob("*.csv")):
            xy = _try_csv_ai(csv_path)
            if xy is not None and xy.shape[0] >= 10:
                logger.info(
                    "Extracted %d points from %s", xy.shape[0], csv_path
                )
                try:
                    return build_from_xy(xy, name=name, sim="ac")
                except ValueError as exc:
                    logger.warning(
                        "build_from_xy failed for %s: %s", csv_path, exc
                    )

    logger.warning("No usable AI data in %s", track_folder)
    return None


# -- Raw telemetry extraction --------------------------------------------

def extract_from_telemetry_xy(
    positions: np.ndarray,
    name: str = "",
    sim: str = "",
) -> Optional[TrackModel]:
    """Build a track model from recorded telemetry positions.

    Parameters
    ----------
    positions:
        (N, 2) or (N, 3) position array.  If 3 columns, only the first
        two are used.
    name:
        Track name.
    sim:
        Simulator identifier.

    Returns
    -------
    TrackModel or None
        Track model, or ``None`` if fewer than 20 points.
    """
    positions = np.asarray(positions, dtype=np.float64)

    if positions.ndim != 2:
        logger.warning(
            "Expected 2-D position array, got ndim=%d", positions.ndim
        )
        return None

    if positions.shape[1] >= 3:
        positions = positions[:, :2]

    if positions.shape[0] < 20:
        logger.warning(
            "Need at least 20 telemetry points, got %d", positions.shape[0]
        )
        return None

    try:
        return build_from_xy(positions, name=name, sim=sim)
    except ValueError as exc:
        logger.warning("build_from_xy failed: %s", exc)
        return None


# -- AC track discovery --------------------------------------------------

def discover_ac_tracks() -> List[Tuple[str, Path]]:
    """Scan all known AC install paths for track AI data.

    Checks both top-level track folders and layout variants::

        content/tracks/<track>/ai/
        content/tracks/<track>/<layout>/ai/

    Returns
    -------
    list of (name, path)
        Each entry is ``(track_name, track_folder_path)``.
    """
    results: List[Tuple[str, Path]] = []

    for base in SIM_PATHS.get("ac", []):
        tracks_dir = base / "content" / "tracks"
        if not tracks_dir.is_dir():
            continue

        for track_dir in sorted(tracks_dir.iterdir()):
            if not track_dir.is_dir():
                continue

            # Top-level AI folder
            ai_dir = track_dir / "ai"
            if ai_dir.is_dir():
                results.append((track_dir.name, track_dir))

            # Layout variants
            for sub in sorted(track_dir.iterdir()):
                if not sub.is_dir() or sub.name == "ai":
                    continue
                layout_ai = sub / "ai"
                if layout_ai.is_dir():
                    results.append(
                        (f"{track_dir.name}/{sub.name}", sub)
                    )

    logger.info("Discovered %d AC track(s)", len(results))
    return results
