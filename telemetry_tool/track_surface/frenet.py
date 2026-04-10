"""
track_surface/frenet.py
-----------------------
Frenet frame for track-relative coordinate projection.

Provides bidirectional mapping between world coordinates (x, y) and track
coordinates (s, n) where s is arc-length along the centerline and n is
signed lateral offset (positive = track left, negative = track right).

Uses a KD-tree for O(log M) nearest-point lookups, making batch projection
of thousands of telemetry samples efficient.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _compute_arc_lengths(xy: np.ndarray) -> np.ndarray:
    """Cumulative arc length for (M, 2) centerline."""
    diffs = np.diff(xy, axis=0)
    seg = np.sqrt(diffs[:, 0] ** 2 + diffs[:, 1] ** 2)
    return np.concatenate([[0.0], np.cumsum(seg)])


def _compute_heading(xy: np.ndarray) -> np.ndarray:
    """Heading angle (radians) at each centerline point via central differences.

    Uses forward difference at start, backward at end, central elsewhere.
    """
    n = len(xy)
    heading = np.empty(n)

    # Central differences for interior points
    dx = np.empty(n)
    dy = np.empty(n)
    dx[1:-1] = xy[2:, 0] - xy[:-2, 0]
    dy[1:-1] = xy[2:, 1] - xy[:-2, 1]
    dx[0] = xy[1, 0] - xy[0, 0]
    dy[0] = xy[1, 1] - xy[0, 1]
    dx[-1] = xy[-1, 0] - xy[-2, 0]
    dy[-1] = xy[-1, 1] - xy[-2, 1]

    heading = np.arctan2(dy, dx)
    return heading


def _compute_curvature(heading: np.ndarray, s: np.ndarray) -> np.ndarray:
    """Signed curvature kappa = d(heading)/ds via central differences."""
    n = len(heading)
    kappa = np.zeros(n)
    if n < 3:
        return kappa

    # Unwrap heading for continuity
    h = np.unwrap(heading)

    # Central differences
    ds = np.diff(s)
    ds_safe = np.where(ds > 1e-6, ds, 1e-6)

    dh = np.diff(h)
    # kappa at midpoints
    kappa_mid = dh / ds_safe

    # Assign to interior points (average of adjacent midpoints)
    kappa[1:-1] = 0.5 * (kappa_mid[:-1] + kappa_mid[1:])
    kappa[0] = kappa_mid[0] if len(kappa_mid) > 0 else 0.0
    kappa[-1] = kappa_mid[-1] if len(kappa_mid) > 0 else 0.0

    return kappa


@dataclass
class FrenetFrame:
    """Track-relative coordinate frame based on a centerline.

    Attributes
    ----------
    centerline_xy : (M, 2) centerline points in world metres.
    s_grid : (M,) cumulative arc length at each point.
    heading_rad : (M,) tangent angle at each point.
    curvature_1pm : (M,) signed curvature [1/m].
    total_length_m : total lap distance.
    """
    centerline_xy: np.ndarray
    s_grid: np.ndarray
    heading_rad: np.ndarray
    curvature_1pm: np.ndarray
    total_length_m: float
    _tree: Any = field(default=None, repr=False)

    @classmethod
    def from_centerline(cls, xy: np.ndarray) -> FrenetFrame:
        """Build a Frenet frame from (M, 2) centerline points."""
        if len(xy) < 3:
            raise ValueError("Centerline needs at least 3 points, got %d" % len(xy))

        s = _compute_arc_lengths(xy)
        heading = _compute_heading(xy)
        curvature = _compute_curvature(heading, s)
        total = float(s[-1])

        tree = None
        try:
            from scipy.spatial import cKDTree
            tree = cKDTree(xy)
        except ImportError:
            logger.debug("scipy unavailable, Frenet projection will use brute force")

        return cls(
            centerline_xy=xy,
            s_grid=s,
            heading_rad=heading,
            curvature_1pm=curvature,
            total_length_m=total,
            _tree=tree,
        )

    @property
    def n_points(self) -> int:
        return len(self.s_grid)

    def _nearest_indices(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Find nearest centerline index for each query point."""
        pts = np.column_stack([x, y])
        if self._tree is not None:
            _, idx = self._tree.query(pts)
            return idx.astype(int)
        # Brute force fallback
        idx = np.empty(len(pts), dtype=int)
        for i, p in enumerate(pts):
            dists = np.sum((self.centerline_xy - p) ** 2, axis=1)
            idx[i] = int(np.argmin(dists))
        return idx

    def xy_to_sn(
        self, x: np.ndarray, y: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Project world (x, y) to track coordinates (s, n).

        Parameters
        ----------
        x, y : arrays of world coordinates in metres.

        Returns
        -------
        (s, n) where s is arc-length along centerline and n is signed
        lateral offset (positive = left of centerline in travel direction).
        """
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)

        idx = self._nearest_indices(x, y)
        n_pts = self.n_points

        # Vector from centerline point to query point
        dx = x - self.centerline_xy[idx, 0]
        dy = y - self.centerline_xy[idx, 1]

        # Tangent direction at nearest centerline point
        cos_h = np.cos(self.heading_rad[idx])
        sin_h = np.sin(self.heading_rad[idx])

        # s-offset along tangent (for sub-segment interpolation)
        ds_along = dx * cos_h + dy * sin_h

        # n = signed perpendicular distance
        # Positive when the point is to the LEFT of the travel direction
        n = -dx * sin_h + dy * cos_h

        # Refine s by adding ds_along to the grid s value
        s = self.s_grid[idx] + ds_along

        # Wrap s to [0, total_length_m) for closed circuits
        if self.total_length_m > 0:
            s = s % self.total_length_m

        return s, n

    def sn_to_xy(
        self, s: np.ndarray, n: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Convert track coordinates (s, n) back to world (x, y).

        Parameters
        ----------
        s : arc-length along centerline [m].
        n : lateral offset [m] (positive = track left).

        Returns
        -------
        (x, y) world coordinates in metres.
        """
        s = np.asarray(s, dtype=np.float64)
        n = np.asarray(n, dtype=np.float64)

        # Interpolate centerline position and heading at arbitrary s
        x_c = np.interp(s % self.total_length_m, self.s_grid, self.centerline_xy[:, 0])
        y_c = np.interp(s % self.total_length_m, self.s_grid, self.centerline_xy[:, 1])
        h = np.interp(s % self.total_length_m, self.s_grid, self.heading_rad)

        # Normal direction: 90 degrees CCW from tangent (points track-left)
        nx = -np.sin(h)
        ny = np.cos(h)

        x = x_c + n * nx
        y = y_c + n * ny
        return x, y

    def effective_curvature(
        self, s: np.ndarray, n: np.ndarray,
    ) -> np.ndarray:
        """Curvature at lateral offset n from centerline.

        For small n relative to radius, the effective curvature is:
            kappa_eff = kappa_center / (1 + n * kappa_center)
        """
        s = np.asarray(s, dtype=np.float64)
        n = np.asarray(n, dtype=np.float64)

        kappa_c = np.interp(s % self.total_length_m, self.s_grid, self.curvature_1pm)
        denom = 1.0 + n * kappa_c
        # Avoid division by zero for extreme offsets
        denom = np.where(np.abs(denom) < 0.01, np.sign(denom) * 0.01, denom)
        return kappa_c / denom
