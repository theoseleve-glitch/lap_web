"""Tests for lap inclusion policy."""
import numpy as np
import pandas as pd
import pytest


def test_lap_exclusion_fields():
    """LapExclusion has required fields."""
    from lap_inclusion import LapExclusion

    exc = LapExclusion(
        lap_number=1,
        reasons=["outlap"],
        detail={"lap_time_ratio": 2.1},
    )
    assert exc.lap_number == 1
    assert "outlap" in exc.reasons
    d = exc.to_dict()
    assert "reasons" in d


def test_lap_inclusion_policy_fields():
    """LapInclusionPolicy has learning_laps, display_laps, traffic_masks."""
    from lap_inclusion import LapInclusionPolicy

    policy = LapInclusionPolicy(
        learning_laps=[2, 3, 4],
        display_laps=[1, 2, 3, 4, 5],
        exclusions=[],
        traffic_masks={3: [(100.0, 150.0)]},
    )
    assert 2 in policy.learning_laps
    assert 1 in policy.display_laps
    assert 1 not in policy.learning_laps
    d = policy.to_dict()
    assert "learning_laps" in d
    assert "traffic_masks" in d


def test_policy_label_method():
    """LapInclusionPolicy.label() returns correct label per lap."""
    from lap_inclusion import LapInclusionPolicy, LapExclusion

    policy = LapInclusionPolicy(
        learning_laps=[2, 3, 4],
        display_laps=[1, 2, 3, 4, 5],
        exclusions=[
            LapExclusion(1, ["outlap"], {}),
            LapExclusion(5, ["traffic"], {"traffic_score": 0.6}),
        ],
        traffic_masks={3: [(100.0, 150.0)]},
    )
    assert policy.label(2) == "clean"
    assert policy.label(1) == "outlap"
    assert policy.label(5) == "traffic"
    assert policy.label(3) == "clean"  # masked but still learning


def _make_simple_laps(n_laps=5, n_points=200, speed=20.0):
    """Create simple identical resampled laps."""
    laps = {}
    for i in range(1, n_laps + 1):
        laps[i] = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, n_points),
            "Speed (m/s)": np.full(n_points, speed),
            "accel_long_mps2": np.zeros(n_points),
        })
    return laps


def test_outlap_excluded():
    """First lap with 2x median time -> excluded as outlap."""
    from lap_inclusion import build_inclusion_policy
    from traffic_detection import TrafficResult

    laps = _make_simple_laps(5)
    lap_times = [150.0, 60.0, 61.0, 62.0, 63.0]
    traffic = TrafficResult([], [], {k: 0.0 for k in range(1, 6)}, 0)

    policy = build_inclusion_policy(laps, lap_times, traffic)
    assert 1 not in policy.learning_laps
    assert 1 in policy.display_laps
    assert policy.label(1) == "outlap"


def test_high_traffic_excluded():
    """Lap with traffic_score > 0.5 -> fully excluded from learning."""
    from lap_inclusion import build_inclusion_policy
    from traffic_detection import TrafficResult

    laps = _make_simple_laps(5)
    lap_times = [60.0, 61.0, 62.0, 63.0, 64.0]
    traffic = TrafficResult(
        straights=[{"s_start": 0, "s_end": 200, "length_m": 200}],
        events=[],
        per_lap_score={1: 0.0, 2: 0.0, 3: 0.6, 4: 0.0, 5: 0.0},
        n_laps_affected=1,
    )

    policy = build_inclusion_policy(laps, lap_times, traffic)
    assert 3 not in policy.learning_laps
    assert policy.label(3) == "traffic"


def test_low_traffic_masked():
    """Lap with traffic_score 0.2 -> in learning set but has traffic mask."""
    from lap_inclusion import build_inclusion_policy
    from traffic_detection import TrafficResult, TrafficEvent

    laps = _make_simple_laps(5)
    lap_times = [60.0, 61.0, 62.0, 63.0, 64.0]
    traffic = TrafficResult(
        straights=[{"s_start": 0, "s_end": 200, "length_m": 200}],
        events=[TrafficEvent(2, 50.0, 100.0, 8.0, -1.0)],
        per_lap_score={1: 0.0, 2: 0.2, 3: 0.0, 4: 0.0, 5: 0.0},
        n_laps_affected=1,
    )

    policy = build_inclusion_policy(laps, lap_times, traffic)
    assert 2 in policy.learning_laps  # still in learning set
    assert 2 in policy.traffic_masks  # but has masks
    assert len(policy.traffic_masks[2]) == 1
    assert policy.traffic_masks[2][0] == (50.0, 100.0)


def test_low_channel_coverage_excluded():
    """Lap with >20% NaN speed -> excluded for low coverage."""
    from lap_inclusion import build_inclusion_policy
    from traffic_detection import TrafficResult

    laps = _make_simple_laps(5)
    # Lap 4: 50% NaN speed
    bad_lap = laps[4].copy()
    bad_lap.loc[:99, "Speed (m/s)"] = np.nan
    laps[4] = bad_lap

    lap_times = [60.0, 61.0, 62.0, 63.0, 64.0]
    traffic = TrafficResult([], [], {k: 0.0 for k in range(1, 6)}, 0)

    policy = build_inclusion_policy(laps, lap_times, traffic)
    assert 4 not in policy.learning_laps
    assert policy.label(4) == "low_coverage"
