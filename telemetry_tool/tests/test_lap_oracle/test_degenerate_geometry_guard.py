"""Regression: solve_optimal_line_2d must fail cleanly on degenerate geometry.

Some tracks carry a valid 2D grip field but a coincident / zero-length
centerline (the frenet has points yet ~0 m arc length). Building the OCP on
such a track collapses the curvature-rate constraint to a constant and trips
casadi's "you passed a constant to subject_to" assertion — an unhandled
RuntimeError rather than a solve failure. The guard converts that into a
ValueError so compute_racing_lines records status=failed with a legible reason.

Discovered by the Lane 2 real-data gate: track 6e862d59 has 606 laps of grip
but a 0 m centerline and crashed casadi. No casadi needed for this test — the
guard fires before the solver is constructed.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from track_surface import solver_bridge


def test_solve_optimal_line_2d_rejects_zero_length_track(monkeypatch):
    surface = SimpleNamespace(
        grip_2d=object(),          # passes the "needs 2D grip" guard
        quality_tier="gold",
        frenet=SimpleNamespace(n_points=362),
    )
    # surface_to_track_model yields a ~0 m track model for this surface.
    monkeypatch.setattr(
        solver_bridge, "surface_to_track_model",
        lambda s: SimpleNamespace(total_length_m=0.0),
    )
    with pytest.raises(ValueError, match="degenerate track geometry"):
        solver_bridge.solve_optimal_line_2d(surface, condition="dry")


def test_normal_length_track_passes_the_geometry_guard(monkeypatch):
    """A real-length track must clear the guard (and fail later for other
    reasons here, since we stub the model) — proving the guard is not
    over-eager."""
    surface = SimpleNamespace(
        grip_2d=object(), quality_tier="gold",
        frenet=SimpleNamespace(n_points=1517),
    )
    monkeypatch.setattr(
        solver_bridge, "surface_to_track_model",
        lambda s: SimpleNamespace(total_length_m=756.0),
    )
    # Past the guard, the real solver path runs; we only assert it does NOT
    # raise the degenerate-geometry ValueError.
    try:
        solver_bridge.solve_optimal_line_2d(surface, condition="dry")
    except ValueError as exc:
        assert "degenerate track geometry" not in str(exc)
    except Exception:
        pass  # any non-ValueError (e.g. ImportError/solver error) is fine here
