"""Tests for condition clustering module."""
import numpy as np
import pandas as pd
import pytest


def test_lap_condition_features_fields():
    """LapConditionFeatures has all required fields and to_dict()."""
    from condition_clustering import LapConditionFeatures

    f = LapConditionFeatures(
        lap_number=1,
        grip_proxy=1.2,
        pace_band="fast",
        traffic_score=0.0,
        coverage_quality=0.95,
        wet_proxy=0.85,
        session_phase=0.1,
    )
    assert f.lap_number == 1
    assert f.pace_band == "fast"
    d = f.to_dict()
    assert "grip_proxy" in d
    assert "wet_proxy" in d


def test_condition_cluster_fields():
    """ConditionCluster has required fields and to_dict()."""
    from condition_clustering import ConditionCluster

    c = ConditionCluster(
        cluster_id=0,
        lap_numbers=[1, 2, 3],
        grip_median=1.5,
        pace_median_s=62.0,
        wet_proxy_median=0.9,
        n_laps=3,
    )
    assert c.n_laps == 3
    d = c.to_dict()
    assert "cluster_id" in d
    assert "lap_numbers" in d


def test_clustering_result_fields():
    """ClusteringResult has required fields and to_dict()."""
    from condition_clustering import (
        ClusteringResult, ConditionCluster, LapConditionFeatures,
    )

    feat = LapConditionFeatures(1, 1.0, "normal", 0.0, 0.9, 0.8, 0.5)
    cluster = ConditionCluster(0, [1], 1.0, 60.0, 0.8, 1)
    result = ClusteringResult(
        features=[feat],
        clusters=[cluster],
        selected_cluster_id=0,
        purity_score=1.0,
        method="rule_based",
        fallback=False,
    )
    d = result.to_dict()
    assert d["method"] == "rule_based"
    assert d["purity_score"] == 1.0
    assert "features" in d
    assert "clusters" in d


def test_clustering_result_empty():
    """ClusteringResult with fallback=True when no clusters formed."""
    from condition_clustering import ClusteringResult

    result = ClusteringResult(
        features=[],
        clusters=[],
        selected_cluster_id=-1,
        purity_score=0.0,
        method="rule_based",
        fallback=True,
    )
    d = result.to_dict()
    assert d["fallback"] is True
    assert d["selected_cluster_id"] == -1


def _make_laps_two_regimes(n_laps=10, n_points=200):
    """Create laps with two distinct grip regimes.

    Laps 1-5: high grip (lat accel up to 1.5 G)
    Laps 6-10: low grip (lat accel up to 0.8 G)
    """
    rng = np.random.default_rng(42)
    laps = {}
    lap_times = []
    for i in range(1, n_laps + 1):
        grip_factor = 1.5 if i <= 5 else 0.8
        speed = 20.0 if i <= 5 else 17.0
        lap_time = 60.0 if i <= 5 else 72.0

        laps[i] = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, n_points),
            "Speed (m/s)": np.full(n_points, speed) + rng.normal(0, 0.3, n_points),
            "Lateral acceleration (G) *calc": (
                rng.normal(0, 0.3, n_points) * grip_factor
            ),
            "accel_long_mps2": rng.normal(0, 0.2, n_points),
        })
        lap_times.append(lap_time + rng.normal(0, 1))

    return laps, lap_times


def test_extract_features_two_regimes():
    """Feature extraction distinguishes high-grip from low-grip laps."""
    from condition_clustering import extract_condition_features

    laps, lap_times = _make_laps_two_regimes()
    traffic_scores = {i: 0.0 for i in range(1, 11)}

    features = extract_condition_features(laps, lap_times, traffic_scores)
    assert len(features) == 10

    # High-grip laps (1-5) should have higher grip_proxy than low-grip (6-10)
    high_grips = [f.grip_proxy for f in features if f.lap_number <= 5]
    low_grips = [f.grip_proxy for f in features if f.lap_number > 5]
    assert np.median(high_grips) > np.median(low_grips)

    # High-grip laps should be "fast", low-grip should be "slow"
    fast_laps = [f for f in features if f.pace_band == "fast"]
    slow_laps = [f for f in features if f.pace_band == "slow"]
    assert len(fast_laps) >= 3
    assert len(slow_laps) >= 3


def test_extract_features_missing_accel():
    """Feature extraction handles missing lateral accel gracefully."""
    from condition_clustering import extract_condition_features

    laps = {}
    for i in range(1, 6):
        laps[i] = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, 100),
            "Speed (m/s)": np.full(100, 20.0),
            "accel_long_mps2": np.zeros(100),
        })
    lap_times = [60.0] * 5
    traffic_scores = {i: 0.0 for i in range(1, 6)}

    features = extract_condition_features(laps, lap_times, traffic_scores)
    assert len(features) == 5
    for f in features:
        assert f.grip_proxy >= 0.0
        assert f.wet_proxy >= 0.0


def test_rule_based_two_regimes_separated():
    """Two distinct grip regimes produce separate clusters; best selected."""
    from condition_clustering import cluster_laps

    laps, lap_times = _make_laps_two_regimes(10)
    traffic_scores = {i: 0.0 for i in range(1, 11)}

    result = cluster_laps(laps, lap_times, traffic_scores)
    assert result.method == "rule_based"
    assert len(result.clusters) >= 2
    assert not result.fallback

    # Selected cluster should be the high-grip one
    selected = [c for c in result.clusters if c.cluster_id == result.selected_cluster_id][0]
    other = [c for c in result.clusters if c.cluster_id != result.selected_cluster_id]
    assert selected.grip_median > max(c.grip_median for c in other)

    # High-grip laps (1-5) should be in the selected cluster
    for lap_num in [1, 2, 3, 4, 5]:
        assert lap_num in selected.lap_numbers


def test_uniform_laps_single_cluster():
    """All identical laps → single cluster, purity 1.0."""
    from condition_clustering import cluster_laps

    rng = np.random.default_rng(42)
    laps = {}
    for i in range(1, 8):
        laps[i] = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, 100),
            "Speed (m/s)": np.full(100, 20.0) + rng.normal(0, 0.2, 100),
            "Lateral acceleration (G) *calc": rng.normal(0, 0.3, 100) * 1.2,
            "accel_long_mps2": rng.normal(0, 0.1, 100),
        })
    lap_times = [60.0 + rng.normal(0, 0.5) for _ in range(7)]
    traffic_scores = {i: 0.0 for i in range(1, 8)}

    result = cluster_laps(laps, lap_times, traffic_scores)
    assert len(result.clusters) == 1
    assert result.purity_score == 1.0
    assert not result.fallback


def test_too_few_laps_fallback():
    """Fewer than 3 laps → fallback=True."""
    from condition_clustering import cluster_laps

    laps = {1: pd.DataFrame({
        "Distance (m)": np.linspace(0, 500, 50),
        "Speed (m/s)": np.full(50, 20.0),
        "accel_long_mps2": np.zeros(50),
    })}
    lap_times = [60.0]
    traffic_scores = {1: 0.0}

    result = cluster_laps(laps, lap_times, traffic_scores)
    assert result.fallback is True
    assert result.selected_cluster_id == 0
