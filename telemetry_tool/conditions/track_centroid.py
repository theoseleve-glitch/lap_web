"""Resolve a track's GPS centroid from its ground-truth geojson.

The conditions classifier needs (lat, lon) for Open-Meteo lookup. The
authoritative source is the hand-traced gt polyline; centroid is the
arithmetic mean of all left + right boundary coordinates.

Brief mentioned a ``gps_centroid`` field on ``track_aliases.json``;
empirically that field doesn't exist (verified Day 11 Phase A). The
single-source-of-truth approach is to read the same gt geojson the
boundary code reads, via the same resolver chain ``gt_loader`` uses.

Phase B-or-D implementation; this module is a stub for Gate-A.
"""
from __future__ import annotations


def resolve_track_centroid(track_id: str) -> tuple[float, float]:
    """Return ``(lat, lon)`` for ``track_id`` from gt geojson.

    Args:
        track_id: Canonical alias (or any alias the registry resolves).

    Returns:
        ``(lat, lon)`` rounded to 4 decimals; this is the Open-Meteo
        precision sweet spot (~11 m at the equator).

    Raises:
        FileNotFoundError: If no gt geojson resolves for ``track_id``.
            Day-11 classifier catches this and falls back to safe-dry.

    Implementation note (Phase B/D):
        Reuse ``track_surface.gt_loader``'s resolver chain to find the
        gt file. Then iterate features keyed by
        ``properties.role ∈ {"left_boundary_gt", "right_boundary_gt"}``
        and average all coordinates. Coordinate order in the geojson
        is ``[lon, lat]`` (EPSG:4326).
    """
    raise NotImplementedError(
        "Phase B/D — implement when classifier needs to resolve centroid"
    )
