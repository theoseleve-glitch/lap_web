"""GeomField: (s,n) kv/camber/grade grids derived from ElevationSurface.

Conventions under test: camber = arctan(d z / d n) SIGNED radians;
grade = arctan(d z / d s) radians; kv passthrough; unmeasured cells row-filled
before differentiation (no NaN, no cliff at the measured/unmeasured seam).
"""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.elevation import ElevationSurface
from track_surface.geom_field import GeomField, build_geom_field


def _elev(M=50, K=9, bank_slope=0.10, climb=0.02) -> ElevationSurface:
    """Planar surface z = climb*s + bank_slope*n (constant grade + banking)."""
    s = np.linspace(0.0, 490.0, M)
    n = np.linspace(-4.0, 4.0, K)
    z = climb * s[:, None] + bank_slope * n[None, :]
    return ElevationSurface(
        s_bins=s, n_bins=n, z_grid=z,
        kv_grid=np.full((M, K), 0.01),
        count_grid=np.full((M, K), 5, dtype=int),
        confidence=np.ones((M, K)),
    )


def test_none_and_degenerate_in_none_out():
    assert build_geom_field(None) is None
    tiny = _elev(M=1, K=9)
    assert build_geom_field(tiny) is None


def test_planar_surface_recovers_constant_camber_and_grade():
    gf = build_geom_field(_elev())
    assert isinstance(gf, GeomField)
    # interior cells: camber = arctan(0.10), grade = arctan(0.02)
    assert gf.camber_grid[10:-10, 2:-2] == pytest.approx(np.arctan(0.10), abs=1e-6)
    assert gf.grade_grid[10:-10, 2:-2] == pytest.approx(np.arctan(0.02), abs=1e-6)
    assert gf.kv_grid == pytest.approx(0.01)
    # signed: negative-n side of a positive bank still slopes +dz/dn
    assert np.all(gf.camber_grid > 0)


def test_unmeasured_cells_row_filled_not_nan():
    elev = _elev()
    elev.count_grid[:, 0] = 0            # whole left edge unmeasured
    elev.z_grid[:, 0] = 999.0            # garbage that must be ignored
    gf = build_geom_field(elev, min_count=1)
    assert np.all(np.isfinite(gf.camber_grid))
    assert np.all(np.isfinite(gf.grade_grid))
    # the garbage column must not have created a cliff in camber
    assert np.max(np.abs(gf.camber_grid)) < np.arctan(0.5)


def test_grids_shapes_and_bins_shared():
    gf = build_geom_field(_elev())
    assert gf.kv_grid.shape == gf.camber_grid.shape == gf.grade_grid.shape
    assert len(gf.s_bins) == gf.kv_grid.shape[0]
    assert len(gf.n_bins) == gf.kv_grid.shape[1]
