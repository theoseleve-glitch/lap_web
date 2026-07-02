"""Quasi-3D: geometry terms evaluated at the line's (s, n), not the centerline.

Physics probes on a synthetic 400 m oval-ish track with one corner:
- zero geom field  == legacy solve (lap time equal within 1e-6: SAME NLP)
- banked corner (camber grows with |n|) -> quasi-3D lap FASTER than flat
  (the optimizer can use the banking where the line actually runs)
"""
from __future__ import annotations

import numpy as np
import pytest

ca = pytest.importorskip("casadi")

from lap_oracle.config import TrackModel, VehicleParams
from lap_oracle.solver.ocp_2d import solve_minimum_time_2d
from track_surface.geom_field import GeomField
from track_surface.mu_field import MuField


def _track(n_pts=160, length=400.0) -> TrackModel:
    # stadium: two straights + two 180-degree arcs, closed
    s = np.linspace(0.0, length, n_pts, endpoint=False)
    R = 30.0
    straight = (length - 2 * np.pi * R) / 2.0
    xy, headings = [], []
    for si in s:
        if si < straight:                      # bottom straight ->
            xy.append((si, 0.0))
        elif si < straight + np.pi * R:        # right 180 arc
            th = (si - straight) / R
            xy.append((straight + R * np.sin(th), R - R * np.cos(th)))
        elif si < 2 * straight + np.pi * R:    # top straight <-
            xy.append((straight - (si - straight - np.pi * R), 2 * R))
        else:                                  # left 180 arc
            th = (si - 2 * straight - np.pi * R) / R
            xy.append((-R * np.sin(th), R + R * np.cos(th)))
    xy = np.asarray(xy)
    track = TrackModel(
        centerline_xy=xy,
        width_left=np.full(n_pts, 4.0),
        width_right=np.full(n_pts, 4.0),
    )
    # NOTE (fixture adaptation, brief-authorized): the brief's sketch omits
    # total_length_m. Unlike build_from_xy, TrackModel's plain constructor
    # does not auto-compute it, and solve_minimum_time_2d divides by it
    # (ds_target = total_length_m / n_points) before resample_track — so a
    # 0.0 default makes ds_target=0 and np.arange(0, total, 0) blow up with
    # "Maximum allowed size exceeded". Fill it from the open-chain centerline
    # segment lengths (matches TrackModel.ds / what resample_track itself
    # independently recomputes from centerline_xy).
    track.total_length_m = float(np.sum(track.ds))
    return track


def _mu(track: TrackModel) -> MuField:
    s_bins = np.linspace(0.0, 400.0, 81)
    n_bins = np.linspace(-4.0, 4.0, 9)
    return MuField(s_bins=s_bins, n_bins=n_bins,
                   mu_grid=np.full((81, 9), 0.9))


def _geom(camber_gain=0.0) -> GeomField:
    s_bins = np.linspace(0.0, 400.0, 81)
    n_bins = np.linspace(-4.0, 4.0, 9)
    camber = camber_gain * np.abs(n_bins)[None, :] * np.ones((81, 1))
    zeros = np.zeros((81, 9))
    return GeomField(s_bins=s_bins, n_bins=n_bins, kv_grid=zeros,
                     camber_grid=camber, grade_grid=zeros)


def _solve(track, mu, geom):
    return solve_minimum_time_2d(
        track, VehicleParams(), mu, n_points=140, max_time_s=90.0,
        geom_field=geom,
    )


def test_zero_geom_field_matches_legacy():
    track = _track(); mu = _mu(track)
    legacy = _solve(track, mu, None)
    zeroed = _solve(track, mu, _geom(0.0))
    assert legacy.solver_status in ("optimal", "suboptimal")
    assert zeroed.optimal_lap_time_s == pytest.approx(
        legacy.optimal_lap_time_s, abs=1e-3)


def test_banked_corners_beat_flat():
    track = _track(); mu = _mu(track)
    flat = _solve(track, mu, _geom(0.0))
    banked = _solve(track, mu, _geom(0.08))   # up to ~0.32 rad at |n|=4
    assert banked.solver_status in ("optimal", "suboptimal")
    assert banked.optimal_lap_time_s < flat.optimal_lap_time_s - 0.05
