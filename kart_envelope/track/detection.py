"""
detection.py
------------
Wrapper around ``telemetry_tool.track_detection`` that also persists
track geometry alongside the fingerprint.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# telemetry_tool modules use internal relative imports (e.g. 'from path_manager import ...')
_TT_DIR = _PROJECT_ROOT / "telemetry_tool"
if str(_TT_DIR) not in sys.path:
    sys.path.insert(0, str(_TT_DIR))

from telemetry_tool.track_detection import (  # noqa: E402
    compute_track_fingerprint,
    match_track,
)

from kart_envelope.track.geometry import TrackGeometry  # noqa: E402

logger = logging.getLogger(__name__)


def detect_or_register_track(
    raw_df: pd.DataFrame,
    geometry: TrackGeometry,
    tracks_dir: Path,
    track_name_hint: str | None = None,
) -> str:
    """Detect an existing track or register a new one.

    Parameters
    ----------
    raw_df : pd.DataFrame
        Session DataFrame with RaceChrono column names (for fingerprinting).
    geometry : TrackGeometry
        Computed geometry for this session.
    tracks_dir : Path
        Root directory for track storage (``tracks/<track_id>/``).
    track_name_hint : str | None
        Override track name from metadata.

    Returns
    -------
    str
        Track ID (existing or newly assigned).
    """
    tracks_dir.mkdir(parents=True, exist_ok=True)
    db_path = tracks_dir / "track_db.json"

    # Load or create the track database
    db: list[dict] = []
    if db_path.exists():
        with open(db_path, encoding="utf-8") as fh:
            db = json.load(fh)

    # Compute fingerprint from raw GPS
    try:
        fp = compute_track_fingerprint(raw_df)
    except Exception as exc:
        logger.warning("Fingerprinting failed: %s.  Assigning from hint or geometry.", exc)
        track_id = track_name_hint or f"track_{int(geometry.lap_length_m):04d}m"
        geometry.track_id = track_id
        _save_geometry(geometry, tracks_dir / track_id)
        return track_id

    # Try matching against database
    match = None
    try:
        match = match_track(fp, db)
    except Exception:
        pass

    if match is not None:
        # match_track returns a MatchResult dataclass (or dict from older versions)
        m_id = (match.track_id if hasattr(match, "track_id")
                else match.get("track_id") if isinstance(match, dict) else None)
        m_matched = (match.matched if hasattr(match, "matched")
                     else match.get("matched", False) if isinstance(match, dict)
                     else bool(m_id))
        if m_id and m_matched:
            track_id = m_id
            iou = getattr(match, "iou", 0.0)
            logger.info("Matched existing track: %s (IoU=%.2f)", track_id, iou)
            geometry.track_id = track_id
            _save_geometry(geometry, tracks_dir / track_id)
            return track_id

    # Register new track
    track_id = track_name_hint or f"track_{int(geometry.lap_length_m):04d}m"
    # Ensure unique
    existing_ids = {e.get("track_id") for e in db}
    base = track_id
    counter = 2
    while track_id in existing_ids:
        track_id = f"{base}_{counter}"
        counter += 1

    entry = {
        "track_id": track_id,
        "lap_length_m": geometry.lap_length_m,
    }
    # Try to include bbox / start pos from fingerprint
    if hasattr(fp, "bbox"):
        entry["bbox"] = fp.bbox.__dict__ if hasattr(fp.bbox, "__dict__") else {}
    if hasattr(fp, "start_lat"):
        entry["start_lat"] = fp.start_lat
        entry["start_lon"] = fp.start_lon

    db.append(entry)
    with open(db_path, "w", encoding="utf-8") as fh:
        json.dump(db, fh, indent=2)

    geometry.track_id = track_id
    _save_geometry(geometry, tracks_dir / track_id)
    logger.info("Registered new track: %s (%.0f m)", track_id, geometry.lap_length_m)
    return track_id


def _save_geometry(geometry: TrackGeometry, track_dir: Path) -> None:
    """Save geometry.json inside the track directory."""
    track_dir.mkdir(parents=True, exist_ok=True)
    geometry.save(track_dir / "geometry.json")
