"""Persistence of `boundary_source` and the GPS projection reference through
the track-model store.

Regression guard for the Phase-0 onboarding-loop finding: a track built with
gt-anchored boundaries (`boundary_source="gt_anchored_native"`) and a GPS
projection reference (`proj_lat_ref`/`proj_lon_ref`) lost both on the
save -> load round-trip through the Parquet sidecar, silently downgrading the
reloaded surface and making downstream tier/geometry logic that inspects
`boundary_source` inert. This suite locks the round-trip: bootstrap save ->
load reconstructs both fields; an absent value on the saved surface loads
back as None (backward-compatible with pre-persistence tracks).
"""
from __future__ import annotations

import numpy as np
import pytest

from track_surface import store
from track_surface.frenet import FrenetFrame
from track_surface.model import TrackSurface


def _valid_frenet() -> FrenetFrame:
    """A closed ~628 m circle — passes the geometry gates (arc, closure, monotonic s)."""
    th = np.linspace(0.0, 2.0 * np.pi, 400, endpoint=False)
    xy = np.column_stack([100 * np.cos(th), 100 * np.sin(th)])
    xy = np.vstack([xy, xy[0] + 0.01])
    return FrenetFrame.from_centerline(xy)


def _surface(
    boundary_source: str | None,
    proj_lat_ref: float | None,
    proj_lon_ref: float | None,
    track_id: str = "t-boundary-source",
) -> TrackSurface:
    fr = _valid_frenet()
    n = fr.n_points
    surf = TrackSurface(
        track_id=track_id,
        frenet=fr,
        n_laps=3,
        sim_sources=[],
        boundary_source=boundary_source,
        proj_lat_ref=proj_lat_ref,
        proj_lon_ref=proj_lon_ref,
    )
    surf.width_left = np.full(n, 4.0)
    surf.width_right = np.full(n, 4.0)
    return surf


def test_boundary_source_and_projref_survive_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_default_sidecar_root", lambda: tmp_path)
    s = _surface(
        boundary_source="gt_anchored_native",
        proj_lat_ref=0.7351,
        proj_lon_ref=0.0456,
    )
    ok = store.merge_track_model(
        s.track_id, s, vehicle_class="generic", condition="dry",
    )
    assert ok

    loaded = store.load_track_model(
        s.track_id, vehicle_class="generic", condition="dry",
    )
    assert loaded is not None
    assert loaded.boundary_source == "gt_anchored_native"
    assert loaded.proj_lat_ref == pytest.approx(s.proj_lat_ref)
    assert loaded.proj_lon_ref == pytest.approx(s.proj_lon_ref)


def test_absent_boundary_source_and_projref_load_as_none(tmp_path, monkeypatch):
    """A track saved without a boundary_source / proj-ref (legacy /
    data_derived / non-GPS) loads back as None — no false provenance."""
    monkeypatch.setattr(store, "_default_sidecar_root", lambda: tmp_path)
    s = _surface(
        boundary_source=None,
        proj_lat_ref=None,
        proj_lon_ref=None,
        track_id="t-boundary-source-absent",
    )
    ok = store.merge_track_model(
        s.track_id, s, vehicle_class="generic", condition="dry",
    )
    assert ok

    loaded = store.load_track_model(
        s.track_id, vehicle_class="generic", condition="dry",
    )
    assert loaded is not None
    assert loaded.boundary_source is None
    assert loaded.proj_lat_ref is None
    assert loaded.proj_lon_ref is None
