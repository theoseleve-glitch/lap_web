"""Tests for per-corner coaching analysis."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.sim_optimizer.analysis.corner_coaching import (
    CornerDelta,
    _detect_corners,
    _find_brake_point,
    analyze_corners,
)
from telemetry_tool.sim_optimizer.analysis.delta import LapDelta


# ---------------------------------------------------------------------------
# Synthetic 500m track helper
# ---------------------------------------------------------------------------

def _build_synthetic_track():
    """Build a 500m track with one corner at 200-300m (kappa=0.03).

    Returns distance_m, curvature, and actual/theoretical brake/speed/throttle
    arrays. The actual driver brakes 20m later than theoretical.
    """
    n = 500
    distance_m = np.linspace(0, 500, n, endpoint=False)  # 1m spacing
    ds = distance_m[1] - distance_m[0]

    # Curvature: corner at 200-300m
    curvature = np.zeros(n)
    corner_mask = (distance_m >= 200) & (distance_m < 300)
    curvature[corner_mask] = 0.03

    # --- Theoretical: steady braking into corner, throttle out ---
    theo_speed = np.full(n, 40.0)  # m/s on straights
    # Brake zone: 170-210m, then corner at lower speed
    theo_brake = np.zeros(n)
    brake_start_theo = 170  # index ~170 (distance ~170m)
    brake_end_theo = 210
    for i in range(brake_start_theo, min(brake_end_theo, n)):
        theo_brake[i] = 0.6
    # Speed drops through brake zone and corner
    for i in range(brake_start_theo, n):
        if i < 300:
            theo_speed[i] = max(25.0, theo_speed[i - 1] - 0.15)
        else:
            theo_speed[i] = min(40.0, theo_speed[i - 1] + 0.10)

    theo_throttle = np.zeros(n)
    # Throttle on exit: from apex (~250m) onwards
    for i in range(250, n):
        theo_throttle[i] = min(1.0, (i - 250) * 0.01)

    # --- Actual: brakes 20m later, ends up slower through corner ---
    act_speed = np.full(n, 40.0)
    act_brake = np.zeros(n)
    brake_start_act = 190  # 20m later than theoretical
    brake_end_act = 230
    for i in range(brake_start_act, min(brake_end_act, n)):
        act_brake[i] = 0.7
    # Speed drops later but then must brake harder, ending up slower mid-corner
    for i in range(brake_start_act, n):
        if i < 230:
            act_speed[i] = max(18.0, act_speed[i - 1] - 0.35)
        elif i < 310:
            act_speed[i] = max(18.0, act_speed[i - 1] - 0.05)
        else:
            act_speed[i] = min(40.0, act_speed[i - 1] + 0.06)

    act_throttle = np.zeros(n)
    # Throttle later on exit
    for i in range(280, n):
        act_throttle[i] = min(1.0, (i - 280) * 0.006)

    # Build a LapDelta
    speed_delta = theo_speed - act_speed  # positive = driver slower
    # Cumulative time delta
    dt_act = ds / np.maximum(act_speed, 1.0)
    dt_theo = ds / np.maximum(theo_speed, 1.0)
    time_delta = np.cumsum(dt_act - dt_theo)
    time_delta = np.insert(time_delta[:-1], 0, 0.0)  # align length

    delta = LapDelta(
        distance_m=distance_m,
        time_delta_s=time_delta,
        speed_delta_mps=speed_delta,
        throttle_delta_pct=theo_throttle - act_throttle,
        brake_delta_pct=theo_brake - act_brake,
        steering_delta_deg=np.zeros(n),
        total_time_loss_s=float(time_delta[-1]),
    )

    return {
        "distance_m": distance_m,
        "curvature": curvature,
        "delta": delta,
        "actual_brake": act_brake,
        "theoretical_brake": theo_brake,
        "actual_speed_mps": act_speed,
        "theoretical_speed_mps": theo_speed,
        "actual_throttle": act_throttle,
        "theoretical_throttle": theo_throttle,
    }


@pytest.fixture
def synthetic_track():
    return _build_synthetic_track()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_detects_corner(synthetic_track):
    """_detect_corners finds the 200-300m region."""
    d = synthetic_track
    corners = _detect_corners(d["distance_m"], d["curvature"], min_curvature=0.005)
    assert len(corners) == 1
    entry_idx, apex_idx, exit_idx = corners[0]
    entry_dist = d["distance_m"][entry_idx]
    exit_dist = d["distance_m"][exit_idx]
    # Entry should be around 200m, exit around 300m
    assert 195 <= entry_dist <= 205
    assert 295 <= exit_dist <= 305


def test_identifies_late_brake(synthetic_track):
    """brake_point_delta_m > 0 when actual brakes later."""
    d = synthetic_track
    results = analyze_corners(
        delta=d["delta"],
        curvature=d["curvature"],
        distance_m=d["distance_m"],
        actual_brake=d["actual_brake"],
        theoretical_brake=d["theoretical_brake"],
        actual_speed_mps=d["actual_speed_mps"],
        theoretical_speed_mps=d["theoretical_speed_mps"],
        actual_throttle=d["actual_throttle"],
        theoretical_throttle=d["theoretical_throttle"],
        min_curvature=0.005,
    )
    assert len(results) >= 1
    corner = results[0]
    # Actual braked ~20m later than theoretical -> positive delta
    assert corner.brake_point_delta_m > 0
    assert corner.root_cause == "braked_late"


def test_coaching_text_nonempty(synthetic_track):
    """All corners have non-empty coaching_text."""
    d = synthetic_track
    results = analyze_corners(
        delta=d["delta"],
        curvature=d["curvature"],
        distance_m=d["distance_m"],
        actual_brake=d["actual_brake"],
        theoretical_brake=d["theoretical_brake"],
        actual_speed_mps=d["actual_speed_mps"],
        theoretical_speed_mps=d["theoretical_speed_mps"],
        actual_throttle=d["actual_throttle"],
        theoretical_throttle=d["theoretical_throttle"],
    )
    for corner in results:
        assert isinstance(corner.coaching_text, str)
        assert len(corner.coaching_text) > 0


def test_time_loss_positive_when_slower(synthetic_track):
    """Corner with slower actual has time_loss > 0."""
    d = synthetic_track
    results = analyze_corners(
        delta=d["delta"],
        curvature=d["curvature"],
        distance_m=d["distance_m"],
        actual_brake=d["actual_brake"],
        theoretical_brake=d["theoretical_brake"],
        actual_speed_mps=d["actual_speed_mps"],
        theoretical_speed_mps=d["theoretical_speed_mps"],
        actual_throttle=d["actual_throttle"],
        theoretical_throttle=d["theoretical_throttle"],
    )
    assert len(results) >= 1
    # The actual driver is slower through the corner, so time_loss should be positive
    assert results[0].time_loss_s > 0


def test_corner_sorted_by_time_loss():
    """Corners returned sorted by |time_loss| descending."""
    # Build a track with TWO corners — one with more time loss than the other
    n = 1000
    distance_m = np.linspace(0, 1000, n, endpoint=False)
    ds = distance_m[1] - distance_m[0]

    curvature = np.zeros(n)
    # Corner 1 at 200-300m (mild)
    c1_mask = (distance_m >= 200) & (distance_m < 300)
    curvature[c1_mask] = 0.01

    # Corner 2 at 600-700m (sharp)
    c2_mask = (distance_m >= 600) & (distance_m < 700)
    curvature[c2_mask] = 0.04

    # Theoretical: uniform speed
    theo_speed = np.full(n, 35.0)
    theo_brake = np.zeros(n)
    theo_throttle = np.full(n, 0.5)

    # Actual: much slower through corner 2
    act_speed = np.copy(theo_speed)
    act_speed[c1_mask] -= 2  # small loss at corner 1
    act_speed[c2_mask] -= 10  # big loss at corner 2
    act_brake = np.zeros(n)
    act_throttle = np.copy(theo_throttle)

    # Build delta
    speed_delta = theo_speed - act_speed
    dt_act = ds / np.maximum(act_speed, 1.0)
    dt_theo = ds / np.maximum(theo_speed, 1.0)
    time_delta = np.concatenate(([0.0], np.cumsum(dt_act[1:] - dt_theo[1:])))

    delta = LapDelta(
        distance_m=distance_m,
        time_delta_s=time_delta,
        speed_delta_mps=speed_delta,
        throttle_delta_pct=theo_throttle - act_throttle,
        brake_delta_pct=theo_brake - act_brake,
        steering_delta_deg=np.zeros(n),
        total_time_loss_s=float(time_delta[-1]),
    )

    results = analyze_corners(
        delta=delta,
        curvature=curvature,
        distance_m=distance_m,
        actual_brake=act_brake,
        theoretical_brake=theo_brake,
        actual_speed_mps=act_speed,
        theoretical_speed_mps=theo_speed,
        actual_throttle=act_throttle,
        theoretical_throttle=theo_throttle,
    )

    assert len(results) == 2
    # Should be sorted by |time_loss| descending — corner 2 has bigger loss
    assert abs(results[0].time_loss_s) >= abs(results[1].time_loss_s)
