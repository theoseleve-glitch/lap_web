"""Tests for running corner_diagnosis on AUTO-detected corners with the real
curvature profile.

Phase 2 of LAP coaching: the corner-diagnosis classifier previously only ran for
operator-drawn ``user_corners`` (orchestrator S10h), so sessions without operator-drawn
corners -- i.e. most customers -- never got a diagnosis at all, and it was never passed
the real ``curvature_profile``. ``run_corner_diagnosis`` extracts a pure, testable
wrapper that runs on the AUTO-detected ``corners`` (``run_corner_detection`` output)
instead, shimming their ``corner_id``/``s_start``/``s_end`` keys onto the classifier's
``corner_index``/``s_entry``/``s_exit`` contract.

Brief: coach-sdd/p2-task-2-brief.md
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.stages.s10h_diagnosis import run_corner_diagnosis


def _make_auto_corner(corner_id=1, s_start=50.0, s_apex=100.0, s_end=150.0, direction="L"):
    """Build an auto-detected corner dict, shaped like ``corner_detection.detect_corners``
    output (``corner_id``/``s_start``/``s_apex``/``s_end``/``direction``) -- NOT the
    classifier's ``corner_index``/``s_entry``/``s_exit`` keys.
    """
    return {
        "corner_id": corner_id,
        "s_start": s_start,
        "s_apex": s_apex,
        "s_end": s_end,
        "direction": direction,
    }


def _make_lap_df(
    n=100, s_start=50.0, s_end=150.0,
    v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0,
):
    """Build a minimal resampled-lap DataFrame spanning the corner segment."""
    dist = np.linspace(s_start, s_end, n)
    mid = n // 2
    speed = np.concatenate([
        np.linspace(v_entry_mps, v_min_mps, mid),
        np.linspace(v_min_mps, v_exit_mps, n - mid),
    ])
    heading = np.linspace(0.0, np.pi / 2, n)
    return pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "Heading (rad)": heading,
    })


def test_runs_on_auto_corners_without_user_corners():
    corners = [_make_auto_corner()]
    laps = {1: _make_lap_df()}

    out = run_corner_diagnosis(
        corners, laps, curvature_profile=None,
        theoretical_lap=None, vehicle_class="kart", valid_lap_numbers=[1],
    )

    assert "1" in out
    assert str(corners[0]["corner_id"]) in out["1"]
    cell = out["1"][str(corners[0]["corner_id"])]
    assert set(cell) >= {"label", "confidence"}  # the P2-Task-1 shape


def test_runs_with_real_curvature_profile():
    """Passing the real curvature profile is the whole point of the honesty gate --
    confirm it flows through to the classifier without error."""
    corners = [_make_auto_corner()]
    laps = {1: _make_lap_df()}
    curvature = pd.DataFrame({
        "distance_m": np.linspace(0.0, 200.0, 200),
        "curvature_1pm": np.full(200, 0.01),
    })

    out = run_corner_diagnosis(
        corners, laps, curvature_profile=curvature,
        theoretical_lap=None, vehicle_class="kart", valid_lap_numbers=[1],
    )

    cell = out["1"][str(corners[0]["corner_id"])]
    assert set(cell) >= {"label", "confidence"}


def test_shim_preserves_native_classifier_keys():
    """A corner dict that already carries the classifier's native keys (e.g. an
    operator-drawn user_corners row) must pass through unshimmed."""
    corner = {"corner_index": 7, "s_entry": 50.0, "s_apex": 100.0, "s_exit": 150.0}
    laps = {1: _make_lap_df()}

    out = run_corner_diagnosis([corner], laps, None, None, "car", [1])

    assert "7" in out["1"]


def test_empty_corners_returns_empty_dict():
    assert run_corner_diagnosis([], {1: _make_lap_df()}, None, None, "car", [1]) == {}


def test_empty_laps_returns_empty_dict():
    corners = [_make_auto_corner()]
    assert run_corner_diagnosis(corners, {}, None, None, "car", [1]) == {}


def test_empty_valid_lap_numbers_returns_empty_dict():
    corners = [_make_auto_corner()]
    laps = {1: _make_lap_df()}
    assert run_corner_diagnosis(corners, laps, None, None, "car", []) == {}
