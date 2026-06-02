"""Synthetic unit test for ``_per_vertex_grip_measured`` (per-tile MEASURED
grip, null where undriven — mirrors ``_per_vertex_speed``).

Pure numpy + a straight-line FrenetFrame; no DB, no mocks. On a centreline
laid along +x, s ≈ x and n ≈ y, so we can place driven corridors and mesh
vertices by hand and assert exactly which vertices light up.
"""
import numpy as np

from track_surface.frenet import FrenetFrame
from track_surface import api_edge_payload as A

_G = 9.80665


def _straight_frenet(length: float = 100.0, step: float = 5.0) -> FrenetFrame:
    xs = np.arange(0.0, length + step, step)
    midline = np.column_stack([xs, np.zeros_like(xs)])
    return FrenetFrame.from_centerline(midline)


def _corridor(x0: float, x1: float, n_pts: int, mu: float, speed: float = 20.0):
    """A driven corridor at n=0 with constant |a_lat|/g == mu."""
    x = np.linspace(x0, x1, n_pts)
    y = np.zeros(n_pts)
    a_lat = np.full(n_pts, mu * _G)
    spd = np.full(n_pts, speed)
    return x, y, a_lat, spd


def test_driven_cells_get_mean_mu_undriven_get_none():
    frenet = _straight_frenet()
    # mu=1.0 over s in [20,40]; mu=0.5 over s in [60,70].
    x1, y1, a1, s1 = _corridor(20, 40, 60, 1.0)
    x2, y2, a2, s2 = _corridor(60, 70, 40, 0.5)
    gx = np.concatenate([x1, x2]); gy = np.concatenate([y1, y2])
    al = np.concatenate([a1, a2]); sp = np.concatenate([s1, s2])

    verts = np.array([
        [30.0, 0.0],   # driven  -> mu ~ 1.0
        [65.0, 0.0],   # driven  -> mu ~ 0.5
        [30.0, 6.0],   # undriven laterally (n far from any sample)
        [90.0, 0.0],   # undriven longitudinally (no sample near s=90)
    ])
    out = A._per_vertex_grip_measured(frenet, verts, gx, gy, al, sp)
    assert out is not None
    grip, n_measured = out
    assert len(grip) == 4
    assert grip[0] is not None and abs(grip[0] - 1.0) < 0.05, grip[0]
    assert grip[1] is not None and abs(grip[1] - 0.5) < 0.05, grip[1]
    assert grip[2] is None, grip[2]          # far-n vertex must NOT clip onto driven edge
    assert grip[3] is None, grip[3]
    assert n_measured == 2, n_measured


def test_low_speed_and_out_of_range_mu_are_filtered():
    frenet = _straight_frenet()
    x, y, a, s = _corridor(20, 40, 60, 1.0)
    # Pollute the s=30 cell with two junk samples that must be dropped:
    #   - mu=5.0 at full speed   (outside [0.1, 3.0] grip range)
    #   - mu=0.2 at speed 1 m/s  (below the min-speed gate)
    # If either leaks in, the s=30 cell mean drifts off 1.0.
    gx = np.concatenate([x, [30.0, 30.0]])
    gy = np.concatenate([y, [0.0, 0.0]])
    al = np.concatenate([a, [5.0 * _G, 0.2 * _G]])
    sp = np.concatenate([s, [20.0, 1.0]])
    out = A._per_vertex_grip_measured(frenet, np.array([[30.0, 0.0]]), gx, gy, al, sp)
    assert out is not None
    grip, _ = out
    assert grip[0] is not None and abs(grip[0] - 1.0) < 0.05, grip[0]


def test_too_few_usable_samples_returns_none():
    frenet = _straight_frenet()
    gx = np.array([30.0, 31.0]); gy = np.array([0.0, 0.0])
    al = np.array([1.0 * _G, 1.0 * _G]); sp = np.array([20.0, 20.0])
    out = A._per_vertex_grip_measured(frenet, np.array([[30.0, 0.0]]), gx, gy, al, sp)
    assert out is None


def test_cell_value_is_p95_not_mean():
    # One driven cell at (30, 0): 90 samples at mu=0.5, 10 at mu=1.1.
    # mean ~0.56, p95 ~1.1. Grip semantics = peak sustained lateral load
    # (p95, matching grip_2d.mu_lat_p95), NOT average utilisation (mean).
    frenet = _straight_frenet()
    x = np.full(100, 30.0)
    y = np.zeros(100)
    mu = np.concatenate([np.full(90, 0.5), np.full(10, 1.1)])
    al = mu * _G
    sp = np.full(100, 20.0)
    out = A._per_vertex_grip_measured(frenet, np.array([[30.0, 0.0]]), x, y, al, sp)
    assert out is not None
    grip, _ = out
    assert grip[0] is not None
    assert abs(grip[0] - 1.1) < 0.05, grip[0]            # p95
    assert grip[0] > 0.9, ("reads like mean, not p95", grip[0])
