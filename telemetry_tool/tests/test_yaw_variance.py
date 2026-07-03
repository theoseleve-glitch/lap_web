"""Yaw-variance primitive: GPS heading → per-lap/per-stint variance."""
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scoring.yaw import lap_yaw_variance, stint_yaw_variances


def _straight_line(n=50):
    lats = [45.0 + i * 1e-4 for i in range(n)]
    lons = [5.0] * n
    return lats, lons


def _wobbly_line(n=50, amp=5e-4):
    lats = [45.0 + i * 1e-4 for i in range(n)]
    lons = [5.0 + (amp if i % 2 else -amp) for i in range(n)]
    return lats, lons


def test_straight_line_has_near_zero_variance():
    lats, lons = _straight_line()
    v = lap_yaw_variance(lats, lons)
    assert v is not None
    assert v < 1e-3


def test_wobbly_line_has_higher_variance_than_straight():
    v_straight = lap_yaw_variance(*_straight_line())
    v_wobbly = lap_yaw_variance(*_wobbly_line())
    assert v_wobbly > v_straight


def test_too_few_points_returns_none():
    assert lap_yaw_variance([45.0, 45.1], [5.0, 5.0]) is None
    assert lap_yaw_variance([], []) is None


def test_stint_variances_split_early_late_thirds():
    gps = {}
    for lap in range(1, 10):            # laps 1-3 wobbly (early), 7-9 straight (late)
        gps[lap] = _wobbly_line() if lap <= 3 else _straight_line()
    early, late, basis = stint_yaw_variances(gps, list(range(1, 10)))
    assert basis == "gps_heading"
    assert early is not None and late is not None
    assert early > late


def test_stint_variances_insufficient_gps():
    early, late, basis = stint_yaw_variances({}, [1, 2, 3])
    assert (early, late) == (None, None)
    assert basis == "insufficient_gps"


# --- Task 2: yaw variance wired into stint scoring ---------------------------
from endurance_scoring import compute_stint_scores


def _laps(start, end):
    return [
        {"lap_number": i, "lap_time_s": 60.0 + (i % 3) * 0.1, "is_valid": True}
        for i in range(start, end + 1)
    ]


def test_stint_scores_without_gps_flags_yaw_unavailable():
    stint = {"stint_number": 1, "start_lap": 1, "end_lap": 9}
    out = compute_stint_scores(_laps(1, 9), stint, "dry")
    assert out["yaw_basis"] == "insufficient_gps"


def test_stint_scores_with_gps_uses_measured_yaw():
    stint = {"stint_number": 1, "start_lap": 1, "end_lap": 9}
    # early laps wobbly, late laps straight -> stability improves, basis measured
    gps = {}
    for lap in range(1, 10):
        gps[lap] = _wobbly_line() if lap <= 3 else _straight_line()
    out = compute_stint_scores(_laps(1, 9), stint, "dry", gps_by_lap=gps)
    assert out["yaw_basis"] == "gps_heading"
