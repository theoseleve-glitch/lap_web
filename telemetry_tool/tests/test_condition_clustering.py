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
