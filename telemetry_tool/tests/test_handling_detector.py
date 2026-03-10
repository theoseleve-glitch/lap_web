"""Tests for understeer/oversteer handling detector with causal attribution."""

import sys
from pathlib import Path

import numpy as np
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.handling_detector import (
    BasicHandlingDetector,
    HandlingEvent,
    detect_handling,
)

# ---------------------------------------------------------------------------
# Helpers — build synthetic corner telemetry
# ---------------------------------------------------------------------------

def _make_corner(
    n_points: int = 100,
    radius: float = 50.0,
    speed: float = 20.0,
    yaw_scale: float = 1.0,
    accel_long: float | None = None,
    geometric_apex_frac: float = 0.5,
):
    """Build synthetic corner arrays.

    ``yaw_scale`` controls actual-vs-expected yaw ratio:
      1.0 → clean corner
      <1.0 → understeer (turning less than expected)
      >1.0 → oversteer (turning more than expected)

    Returns dict of keyword args suitable for ``detect_handling()``.
    """
    corner_length = radius * (np.pi / 2)  # 90-degree corner
    distances = np.linspace(0, corner_length, n_points)
    speeds = np.full(n_points, speed)
    # Constant curvature for the reference
    reference_curvature = np.full(n_points, 1.0 / radius)
    # Expected heading change per step = curvature * ds
    ds = distances[1] - distances[0]
    expected_heading_change = ds / radius
    # Actual headings: integrate yaw_scale * expected yaw
    headings = np.cumsum(
        np.full(n_points, expected_heading_change * yaw_scale)
    )
    headings = np.insert(headings[:-1], 0, 0.0)  # start at 0

    geometric_apex_m = distances[int(n_points * geometric_apex_frac)]

    kwargs = dict(
        corner_id=1,
        distances=distances,
        speeds=speeds,
        reference_curvature=reference_curvature,
        actual_headings=headings,
        dt=0.01,
        geometric_apex_m=geometric_apex_m,
    )
    if accel_long is not None:
        kwargs["accel_long"] = np.full(n_points, accel_long)
    return kwargs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_understeer_detected():
    """Understeer detected when actual yaw rate < expected yaw rate."""
    kw = _make_corner(yaw_scale=0.70)  # 30% less turning
    events = detect_handling(**kw)
    assert len(events) >= 1
    assert any(e.event_type == "understeer" for e in events)


def test_oversteer_detected():
    """Oversteer detected when actual yaw rate > expected yaw rate."""
    kw = _make_corner(yaw_scale=1.35)  # 35% more turning
    events = detect_handling(**kw)
    assert len(events) >= 1
    assert any(e.event_type == "oversteer" for e in events)


def test_severity_mild():
    """Deviation <15% -> mild severity."""
    kw = _make_corner(yaw_scale=0.90)  # 10% under
    events = detect_handling(**kw)
    assert len(events) >= 1
    assert all(e.severity == "mild" for e in events)


def test_severity_moderate():
    """Deviation 15-30% -> moderate severity."""
    kw = _make_corner(yaw_scale=0.78)  # ~22% under
    events = detect_handling(**kw)
    assert len(events) >= 1
    assert any(e.severity == "moderate" for e in events)


def test_severity_severe():
    """Deviation >30% -> severe severity."""
    kw = _make_corner(yaw_scale=0.60)  # 40% under
    events = detect_handling(**kw)
    assert len(events) >= 1
    assert any(e.severity == "severe" for e in events)


def test_causal_throttle_understeer():
    """Understeer + positive longitudinal accel -> 'early_throttle' cause."""
    kw = _make_corner(yaw_scale=0.70, accel_long=2.0)
    events = detect_handling(**kw)
    us = [e for e in events if e.event_type == "understeer"]
    assert len(us) >= 1
    assert us[0].cause == "early_throttle"


def test_causal_trail_brake_oversteer():
    """Oversteer + hard braking -> 'trail_brake_too_deep' cause."""
    kw = _make_corner(yaw_scale=1.35, accel_long=-3.0)
    events = detect_handling(**kw)
    os_events = [e for e in events if e.event_type == "oversteer"]
    assert len(os_events) >= 1
    assert os_events[0].cause == "trail_brake_too_deep"


def test_causal_power_oversteer():
    """Oversteer + throttle at exit -> 'power_oversteer' cause."""
    # Build a corner where oversteer happens only in the exit phase
    n = 100
    radius = 50.0
    speed = 20.0
    corner_length = radius * (np.pi / 2)
    distances = np.linspace(0, corner_length, n)
    speeds = np.full(n, speed)
    reference_curvature = np.full(n, 1.0 / radius)
    ds = distances[1] - distances[0]
    expected_dh = ds / radius

    # Clean entry+mid, oversteer at exit (last 30%)
    yaw_scales = np.ones(n)
    exit_start = int(n * 0.7)
    yaw_scales[exit_start:] = 1.35

    headings = np.cumsum(expected_dh * yaw_scales)
    headings = np.insert(headings[:-1], 0, 0.0)

    # Positive accel (throttle) everywhere — but oversteer only at exit
    accel_long = np.full(n, 2.0)

    events = detect_handling(
        corner_id=1,
        distances=distances,
        speeds=speeds,
        reference_curvature=reference_curvature,
        actual_headings=headings,
        accel_long=accel_long,
        dt=0.01,
        geometric_apex_m=distances[n // 2],
    )
    os_events = [e for e in events if e.event_type == "oversteer"]
    assert len(os_events) >= 1
    assert os_events[0].cause == "power_oversteer"
    assert os_events[0].corner_phase == "exit"


def test_clean_corner_no_events():
    """Clean corner (actual ~ expected) -> no handling events."""
    kw = _make_corner(yaw_scale=1.0)
    events = detect_handling(**kw)
    assert events == []


def test_time_cost_estimated():
    """Handling events have estimated time cost."""
    kw = _make_corner(yaw_scale=0.65)
    events = detect_handling(**kw)
    assert len(events) >= 1
    for e in events:
        assert e.time_cost_s is not None
        assert e.time_cost_s > 0.0
