"""Persistence of the 2D elevation surface z(s,n) through the track-model store.

Regression guard for the B1 program finding: the ElevationSurface (the source
of the quasi-3D geometry field) was built in-session but never persisted, so
the solver always honest-fell-back to 2D on loaded / prod tracks. This suite
locks the round-trip: bootstrap save -> load reconstructs the surface; an
absent sidecar -> None (backward-compatible with pre-persistence tracks);
merge accumulates the grids.
"""
from __future__ import annotations

import numpy as np

from track_surface import store
from track_surface.elevation import ElevationSurface
from track_surface.frenet import FrenetFrame
from track_surface.model import TrackSurface


def _valid_frenet() -> FrenetFrame:
    """A closed ~628 m circle — passes the geometry gates (arc, closure, monotonic s)."""
    th = np.linspace(0.0, 2.0 * np.pi, 400, endpoint=False)
    xy = np.column_stack([100 * np.cos(th), 100 * np.sin(th)])
    xy = np.vstack([xy, xy[0] + 0.01])
    return FrenetFrame.from_centerline(xy)


def _elev_surface(M: int = 10, K: int = 5) -> ElevationSurface:
    s_bins = np.linspace(0.0, 600.0, M)
    n_bins = np.linspace(-4.0, 4.0, K)
    z_grid = np.arange(M * K, dtype=float).reshape(M, K) * 0.01
    kv_grid = np.full((M, K), 0.002)
    count_grid = np.full((M, K), 5, dtype=int)
    confidence = np.clip(count_grid / 20.0, 0.0, 1.0)
    return ElevationSurface(s_bins=s_bins, n_bins=n_bins, z_grid=z_grid,
                            kv_grid=kv_grid, count_grid=count_grid, confidence=confidence)


def _surface(es: ElevationSurface | None, n_laps: int = 3) -> TrackSurface:
    fr = _valid_frenet()
    n = fr.n_points
    surf = TrackSurface(track_id="t-elev", frenet=fr, n_laps=n_laps, sim_sources=[])
    surf.width_left = np.full(n, 4.0)
    surf.width_right = np.full(n, 4.0)
    surf.elevation_m = np.zeros(n)
    surf.elevation_surface = es
    return surf


def test_bootstrap_persists_and_loads_elevation_surface(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_default_sidecar_root", lambda: tmp_path)
    es = _elev_surface()
    ok = store.merge_track_model("t-elev", _surface(es),
                                 vehicle_class="generic", condition="dry")
    assert ok

    loaded = store.load_track_model("t-elev", vehicle_class="generic", condition="dry")
    assert loaded is not None
    assert loaded.elevation_surface is not None, \
        "elevation surface must survive the store round-trip (quasi-3D source)"
    got = loaded.elevation_surface
    np.testing.assert_allclose(got.z_grid, es.z_grid, atol=1e-9)
    np.testing.assert_allclose(got.kv_grid, es.kv_grid, atol=1e-9)
    np.testing.assert_allclose(got.s_bins, es.s_bins, atol=1e-9)
    np.testing.assert_allclose(got.n_bins, es.n_bins, atol=1e-9)
    np.testing.assert_array_equal(got.count_grid, es.count_grid)


def test_absent_elevation_surface_loads_as_none(tmp_path, monkeypatch):
    """A track saved without an elevation surface loads with None — the
    quasi-3D solver then honestly falls back to 2D (byte-compatible)."""
    monkeypatch.setattr(store, "_default_sidecar_root", lambda: tmp_path)
    ok = store.merge_track_model("t-noelev", _surface(es=None),
                                 vehicle_class="generic", condition="dry")
    assert ok

    loaded = store.load_track_model("t-noelev", vehicle_class="generic", condition="dry")
    assert loaded is not None
    assert loaded.elevation_surface is None


def test_merge_accumulates_elevation_surface(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_default_sidecar_root", lambda: tmp_path)
    store.merge_track_model("t-elev-merge", _surface(_elev_surface()),
                            vehicle_class="generic", condition="dry")
    store.merge_track_model("t-elev-merge", _surface(_elev_surface()),
                            vehicle_class="generic", condition="dry")

    loaded = store.load_track_model("t-elev-merge", vehicle_class="generic", condition="dry")
    assert loaded.elevation_surface is not None
    # Two aligned sessions of count 5 each accumulate to 10 where the grids overlap.
    assert int(loaded.elevation_surface.count_grid.max()) >= 10
