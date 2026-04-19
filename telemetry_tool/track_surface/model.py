"""
track_surface/model.py
----------------------
TrackSurface dataclass — the complete reconstructed track surface model.

Holds the Frenet frame (centerline + curvature), optional boundary estimates,
elevation, camber, and 2D grip map.  Quality degrades gracefully: a single
lap gives a basic centerline; 100+ laps give a full surface with grip.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from track_surface.frenet import FrenetFrame
from track_surface.grip_2d import GripSurface


@dataclass
class TrackSurface:
    """Complete reconstructed track surface from telemetry data."""

    track_id: str
    frenet: FrenetFrame

    # Boundaries (None if < 3 laps)
    width_left: np.ndarray | None = None    # (M,) metres from center to left edge
    width_right: np.ndarray | None = None   # (M,) metres from center to right edge

    # Elevation (None if no z-data)
    elevation_m: np.ndarray | None = None   # (M,) height above datum
    slope_pct: np.ndarray | None = None     # (M,) longitudinal slope %

    # Vertical curvature (None if no elevation data)
    vert_curvature_1pm: np.ndarray | None = None  # (M,) d²z/ds², + = compression, - = crest

    # Camber (None if < 5 laps or insufficient lateral spread)
    camber_rad: np.ndarray | None = None    # (M,) banking angle, radians

    # 3D elevation surface z(s,n) (None if insufficient lateral z-coverage)
    elevation_surface: object | None = None  # ElevationSurface from elevation.py

    # Detected curbs at track edges
    curbs: list | None = None  # list[CurbDetection] from elevation.py

    # 2D grip (None if < 10 laps)
    grip_2d: GripSurface | None = None

    # Provenance
    n_laps: int = 0
    sim_sources: list[str] = field(default_factory=list)

    @property
    def has_boundaries(self) -> bool:
        return self.width_left is not None and self.width_right is not None

    @property
    def has_elevation(self) -> bool:
        return self.elevation_m is not None

    @property
    def has_vert_curvature(self) -> bool:
        return self.vert_curvature_1pm is not None

    @property
    def has_camber(self) -> bool:
        return self.camber_rad is not None

    @property
    def has_elevation_3d(self) -> bool:
        return self.elevation_surface is not None

    @property
    def has_curbs(self) -> bool:
        return self.curbs is not None and len(self.curbs) > 0

    @property
    def has_grip_2d(self) -> bool:
        return self.grip_2d is not None

    @property
    def quality_tier(self) -> str:
        """Quality tier based on available data.

        bronze  : 1 lap   — centerline + curvature only
        silver  : 3+ laps — + boundaries + elevation
        gold    : 10+ laps — + 2D grip
        platinum: 100+ laps — high-confidence 2D grip
        """
        if self.n_laps >= 100 and self.has_grip_2d:
            return "platinum"
        if self.n_laps >= 10 and self.has_grip_2d:
            return "gold"
        if self.n_laps >= 3 and self.has_boundaries:
            return "silver"
        return "bronze"

    def to_summary_dict(self) -> dict:
        """Minimal JSON-safe summary for API responses."""
        return {
            "track_id": self.track_id,
            "total_length_m": round(self.frenet.total_length_m, 1),
            "n_points": self.frenet.n_points,
            "n_laps": self.n_laps,
            "sim_sources": self.sim_sources,
            "quality_tier": self.quality_tier,
            "has_boundaries": self.has_boundaries,
            "has_elevation": self.has_elevation,
            "has_camber": self.has_camber,
            "has_vert_curvature": self.has_vert_curvature,
            "has_elevation_3d": self.has_elevation_3d,
            "has_curbs": self.has_curbs,
            "n_curbs": len(self.curbs) if self.curbs else 0,
            "has_grip_2d": self.has_grip_2d,
        }
