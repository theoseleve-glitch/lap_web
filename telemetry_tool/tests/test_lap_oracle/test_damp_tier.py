"""Regression: 'damp' is a real solver tier, not a wet alias.

The classifier emits dry/damp/wet/heavy_wet, but compute_racing_lines only ever
solved dry+wet — damp was silently dropped. Now damp loads its own measured grip
sidecar and solves like dry (no rubber-line inversion). These tests lock that the
solver accepts 'damp' and the task loads the real damp sidecar for it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from track_surface import solver_bridge


class _PastGuards(Exception):
    """Sentinel proving execution reached surface_to_track_model (i.e. cleared
    the condition guard)."""


def test_damp_clears_condition_guard_but_greasy_does_not(monkeypatch):
    surface = SimpleNamespace(
        grip_2d=object(), quality_tier="gold",
        frenet=SimpleNamespace(n_points=1000),
    )

    def _raise(_s):
        raise _PastGuards

    monkeypatch.setattr(solver_bridge, "surface_to_track_model", _raise)

    # 'damp' is a valid condition -> passes the guard -> reaches the geometry probe.
    with pytest.raises(_PastGuards):
        solver_bridge.solve_optimal_line_2d(surface, condition="damp")

    # 'greasy' is not modelled -> rejected by the condition guard up front.
    with pytest.raises(ValueError, match="condition must be"):
        solver_bridge.solve_optimal_line_2d(surface, condition="greasy")


def test_sidecar_map_uses_real_damp_grip():
    from tasks.racing_line_tasks import _SIDECAR_FOR

    assert _SIDECAR_FOR["damp"] == "damp"   # damp = its own measured grip
    assert _SIDECAR_FOR["wet"] == "dry"     # wet still derived from dry
    assert set(_SIDECAR_FOR) == {"dry", "damp", "wet"}
