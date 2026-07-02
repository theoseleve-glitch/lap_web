"""Gates that make grip-without-geometry impossible (spec A3).

Thresholds are spec-exact; each test isolates one gate with a surface builder
that is valid except for the property under test.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from track_surface.geometry_gates import GateReport, run_geometry_gates


def _circle_surface(radius_m=100.0, n=400, closed=True, **overrides):
    """A healthy closed circular track: ~628 m, 4 m widths, flat."""
    th = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    xy = np.column_stack([radius_m * np.cos(th), radius_m * np.sin(th)])
    if closed:  # append near-start point so closure error is tiny
        xy = np.vstack([xy, xy[0] + 0.01])
    seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    frenet = SimpleNamespace(
        centerline_xy=xy, s_grid=s, total_length_m=float(s[-1]),
    )
    base = dict(
        frenet=frenet,
        width_left=np.full(len(xy), 4.0),
        width_right=np.full(len(xy), 4.0),
        elevation_m=np.zeros(len(xy)),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_healthy_track_passes():
    report = run_geometry_gates(_circle_surface())
    assert isinstance(report, GateReport)
    assert report.passed, [f.message for f in report.failures]


def test_zero_length_centerline_fails_arc_length():
    # The real prod bug: 362 points, all coincident -> ~0 m.
    xy = np.tile([[10.0, 5.0]], (362, 1))
    frenet = SimpleNamespace(
        centerline_xy=xy, s_grid=np.zeros(362), total_length_m=0.0,
    )
    surface = SimpleNamespace(frenet=frenet, width_left=None,
                              width_right=None, elevation_m=None)
    report = run_geometry_gates(surface)
    assert not report.passed
    assert any(f.gate == "arc_length" for f in report.failures)


def test_short_track_fails_arc_length():
    report = run_geometry_gates(_circle_surface(radius_m=10.0))  # ~63 m < 100 m
    assert any(f.gate == "arc_length" for f in report.failures)


def test_non_monotonic_s_fails():
    surface = _circle_surface()
    surface.frenet.s_grid = surface.frenet.s_grid.copy()
    surface.frenet.s_grid[50] = surface.frenet.s_grid[49]  # not strictly increasing
    report = run_geometry_gates(surface)
    assert any(f.gate == "monotonic_s" for f in report.failures)


def test_open_circuit_closure_fails_when_closed_expected():
    th = np.linspace(0.0, 1.5 * np.pi, 300)  # three-quarter circle: ends 141 m apart
    xy = np.column_stack([100 * np.cos(th), 100 * np.sin(th)])
    seg = np.linalg.norm(np.diff(xy, axis=1 if False else 0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    frenet = SimpleNamespace(centerline_xy=xy, s_grid=s, total_length_m=float(s[-1]))
    surface = SimpleNamespace(frenet=frenet, width_left=None,
                              width_right=None, elevation_m=None)
    assert any(f.gate == "closure" for f in run_geometry_gates(surface).failures)
    # And with closed=False the same geometry must NOT fail closure.
    assert not any(f.gate == "closure"
                   for f in run_geometry_gates(surface, closed=False).failures)


def test_self_intersection_fails():
    # Figure-eight: two lobes crossing at the origin.
    t = np.linspace(0.0, 2.0 * np.pi, 400, endpoint=False)
    xy = np.column_stack([80 * np.sin(t), 60 * np.sin(t) * np.cos(t)])
    xy = np.vstack([xy, xy[0] + 0.01])
    seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    frenet = SimpleNamespace(centerline_xy=xy, s_grid=s, total_length_m=float(s[-1]))
    surface = SimpleNamespace(frenet=frenet, width_left=None,
                              width_right=None, elevation_m=None)
    assert any(f.gate == "self_intersection"
               for f in run_geometry_gates(surface).failures)


def test_width_bounds():
    bad_low = _circle_surface(width_left=np.full(401, 0.2))     # < 0.5 m
    bad_high = _circle_surface(width_right=np.full(401, 45.0))  # > 30 m
    assert any(f.gate == "width_bounds" for f in run_geometry_gates(bad_low).failures)
    assert any(f.gate == "width_bounds" for f in run_geometry_gates(bad_high).failures)
    # None widths are allowed (bronze tier tracks) — no width failure.
    none_w = _circle_surface(width_left=None, width_right=None)
    assert not any(f.gate == "width_bounds" for f in run_geometry_gates(none_w).failures)


def test_elevation_gates():
    n = 401
    spike = np.zeros(n); spike[200] = 5.0            # |dz| = 5 m step
    range_bad = np.linspace(0.0, 150.0, n)           # 150 m range
    assert any(f.gate == "elevation_step"
               for f in run_geometry_gates(_circle_surface(elevation_m=spike)).failures)
    assert any(f.gate == "elevation_range"
               for f in run_geometry_gates(_circle_surface(elevation_m=range_bad)).failures)


def test_non_finite_fails():
    surface = _circle_surface()
    surface.frenet.centerline_xy = surface.frenet.centerline_xy.copy()
    surface.frenet.centerline_xy[10, 0] = np.nan
    assert any(f.gate == "finite" for f in run_geometry_gates(surface).failures)


def test_report_details_serializable():
    import json
    report = run_geometry_gates(_circle_surface(radius_m=10.0))
    json.dumps(report.to_details())  # must not raise
