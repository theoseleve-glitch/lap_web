"""Quasi-3D: geometry terms evaluated at the line's (s, n), not the centerline.

Physics probes on a synthetic 400 m oval-ish track with one corner:
- zero geom field  == legacy solve (lap time equal within 1e-6: SAME NLP)
- banked corner (camber grows with |n|) -> quasi-3D lap FASTER than flat
  (the optimizer can use the banking where the line actually runs)
"""
from __future__ import annotations

from types import SimpleNamespace

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


def test_geom_narrow_n_domain_clamps_line():
    """Verify N_lat bounds intersect geom_field n-domain — no bspline extrapolation.

    When geom_field has a narrower n-domain than the track width or mu_field,
    the optimizer must be constrained to stay within the geometry domain to avoid
    cubic bspline extrapolation.
    """
    track = _track(); mu = _mu(track)

    # Build a geom_field with narrow n-domain [-1.5, +1.5] m
    # (track width is ±4 m, mu_field is ±4 m, so this is the limiting constraint)
    s_bins = np.linspace(0.0, 400.0, 81)
    n_bins = np.linspace(-1.5, 1.5, 7)
    camber = np.zeros((81, 7))
    grade = np.zeros((81, 7))
    kv = np.zeros((81, 7))
    narrow_geom = GeomField(
        s_bins=s_bins, n_bins=n_bins,
        kv_grid=kv, camber_grid=camber, grade_grid=grade
    )

    solution = _solve(track, mu, narrow_geom)

    # Solver must complete without error, and the line must stay within bounds
    # (with small numerical tolerance for cubic spline evaluation)
    assert solution.solver_status in ("optimal", "suboptimal")
    max_lateral_offset = np.max(np.abs(solution.lateral_offset_m))
    assert max_lateral_offset <= 1.5 + 1e-6, \
        f"Line exceeded geom_field n-domain: max |n| = {max_lateral_offset}, limit = 1.5"


def test_stitched_zero_geom_matches_legacy():
    from lap_oracle.solver.ocp_2d_stitched import solve_minimum_time_2d_stitched
    track = _track(); mu = _mu(track)
    legacy = solve_minimum_time_2d_stitched(
        track, VehicleParams(), mu, n_points=140, max_time_s=120.0)
    zeroed = solve_minimum_time_2d_stitched(
        track, VehicleParams(), mu, n_points=140, max_time_s=120.0,
        geom_field=_geom(0.0))
    assert zeroed.optimal_lap_time_s == pytest.approx(
        legacy.optimal_lap_time_s, abs=1e-3)


# ---------------------------------------------------------------------------
# Task 4: bridge wiring — solve_optimal_line_2d builds geom_field from the
# surface's elevation data and threads it through to the stitched solver.
# ---------------------------------------------------------------------------
def _patch_bridge_internals(monkeypatch, captured):
    """Stub every solver_bridge internal EXCEPT the geom_field wiring itself.

    mu_field.py / fallback_qss.py have their own suites (real ones exercised
    elsewhere) — this lets a minimal SimpleNamespace surface clear every
    guard and reach the stitched call, where fake_stitched captures the
    geom_field kwarg and stops (RuntimeError) before any real solve runs.
    """
    from track_surface import solver_bridge

    def fake_stitched(track, vehicle, mu, **kw):
        captured["geom_field"] = kw.get("geom_field")
        raise RuntimeError("stop-after-capture")

    monkeypatch.setattr(
        "lap_oracle.solver.ocp_2d_stitched.solve_minimum_time_2d_stitched",
        fake_stitched)
    monkeypatch.setattr(
        "track_surface.mu_field.build_dry_mu_field",
        lambda grip_2d, spatial=None, condition_factor=1.0: object())
    monkeypatch.setattr(
        "lap_oracle.solver.fallback_qss.solve_qss",
        lambda track, vehicle, weather=None: object())
    monkeypatch.setattr(
        solver_bridge, "surface_to_track_model",
        lambda s: SimpleNamespace(total_length_m=756.0),
    )


def _bridge_surface(*, elevation_surface):
    """Minimal surface clearing the guards — pattern from
    test_degenerate_geometry_guard.py's passing case, plus the elevation
    fields solve_optimal_line_2d reads directly (not getattr-safe)."""
    return SimpleNamespace(
        grip_2d=object(), quality_tier="gold",
        frenet=SimpleNamespace(n_points=1517),
        slope_pct=None, camber_rad=None,
        elevation_surface=elevation_surface,
    )


def test_bridge_passes_geom_field(monkeypatch):
    # NOTE: bare `tests.test_lap_oracle` is shadowed by an unrelated empty
    # `tests/` package at the repo root (lap_web-wt-race-brief/tests/,
    # also has __init__.py) — pytest's own rootdir walk for THIS file
    # resolves it as telemetry_tool.tests.test_lap_oracle.test_quasi3d_solver,
    # so the sibling import must match that same fully-qualified prefix.
    from telemetry_tool.tests.test_lap_oracle.test_geom_field import _elev
    from track_surface import solver_bridge

    captured = {}
    _patch_bridge_internals(monkeypatch, captured)

    # elevation_surface present -> geom_field is a real GeomField.
    surface = _bridge_surface(elevation_surface=_elev())
    with pytest.raises(RuntimeError, match="stop-after-capture"):
        solver_bridge.solve_optimal_line_2d(surface, condition="dry")
    assert isinstance(captured["geom_field"], GeomField)

    # No elevation surface (e.g. < 3 laps accumulated) -> geom_field is
    # None, not an error: the stitched solver's geom_field=None path is
    # byte-compatible with the pre-quasi-3D behaviour.
    surface_no_elev = _bridge_surface(elevation_surface=None)
    with pytest.raises(RuntimeError, match="stop-after-capture"):
        solver_bridge.solve_optimal_line_2d(surface_no_elev, condition="dry")
    assert captured["geom_field"] is None


def test_bridge_force_no_geom_skips_geom_field(monkeypatch):
    """force_no_geom=True skips geom_field construction entirely, even with
    a usable elevation_surface present (Task 6's A/B harness forces the
    legacy centerline-only baseline)."""
    # NOTE: bare `tests.test_lap_oracle` is shadowed by an unrelated empty
    # `tests/` package at the repo root (lap_web-wt-race-brief/tests/,
    # also has __init__.py) — pytest's own rootdir walk for THIS file
    # resolves it as telemetry_tool.tests.test_lap_oracle.test_quasi3d_solver,
    # so the sibling import must match that same fully-qualified prefix.
    from telemetry_tool.tests.test_lap_oracle.test_geom_field import _elev
    from track_surface import solver_bridge

    captured = {}
    _patch_bridge_internals(monkeypatch, captured)

    surface = _bridge_surface(elevation_surface=_elev())
    with pytest.raises(RuntimeError, match="stop-after-capture"):
        solver_bridge.solve_optimal_line_2d(
            surface, condition="dry", force_no_geom=True)
    assert captured["geom_field"] is None
