"""Resolve a track's GPS centroid from its ground-truth geojson.

The conditions classifier needs (lat, lon) for Open-Meteo lookup. The
authoritative source is the hand-traced gt polyline; centroid is the
arithmetic mean of all left + right boundary coordinates.

Brief mentioned a ``gps_centroid`` field on ``track_aliases.json``;
empirically that field doesn't exist (verified Day 11 Phase A). The
single-source-of-truth approach is to read the same gt geojson the
boundary code reads, via ``track_surface.gt_loader.load_gt``.
"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=64)
def resolve_track_centroid(track_id: str) -> tuple[float, float]:
    """Return ``(lat, lon)`` for ``track_id`` from gt geojson.

    Args:
        track_id: Canonical alias (or any alias the registry resolves).
            Resolution is case-insensitive; the gt_loader does the alias
            walk (e.g., ``slk-fp1 → slk → gt_slk-fp1.geojson``).

    Returns:
        ``(lat, lon)`` rounded to 4 decimals; ~11 m precision at the
        equator, well within Open-Meteo's grid resolution.

    Raises:
        FileNotFoundError: If no gt geojson resolves for ``track_id``.
            Day-11 classifier catches this and falls back to safe-dry.

    Result is LRU-cached per process; the gt geojson doesn't change at
    runtime so re-classification of multiple sessions on the same track
    is zero-IO after the first call.
    """
    # Imported lazily to avoid circular imports at module load.
    from telemetry_tool.track_surface.gt_loader import load_gt

    gt = load_gt(track_id)
    if gt is None:
        raise FileNotFoundError(
            f"no gt geojson resolves for track_id={track_id!r}; "
            "classifier will fall back to safe-dry"
        )

    coords = list(gt.left_polyline) + list(gt.right_polyline)
    if not coords:
        raise FileNotFoundError(
            f"gt geojson for {track_id!r} ({gt.source_filename}) has no "
            "boundary coordinates"
        )

    # GeoJSON coord order is (lon, lat). Return as (lat, lon) for clarity.
    mean_lon = sum(c[0] for c in coords) / len(coords)
    mean_lat = sum(c[1] for c in coords) / len(coords)
    return (round(mean_lat, 4), round(mean_lon, 4))
