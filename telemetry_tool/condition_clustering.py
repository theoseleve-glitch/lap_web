"""
condition_clustering.py
-----------------------
Cluster laps by driving conditions before theoretical generation.

Derives per-lap condition features (grip proxy, pace band, wet proxy,
etc.) and groups laps into condition clusters so envelopes are not
blended across incompatible conditions. Rule-based clustering is
deterministic; optional k-means activates when enough laps are present.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field

import numpy as np

logger = logging.getLogger(__name__)

# ── Column constants ─────────────────────────────────────────────
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_ACCEL_LAT = "Lateral acceleration (G) *calc"
_COL_ACCEL_LAT_ALT = "accel_lat_mps2"
_COL_ACCEL_LONG = "accel_long_mps2"

# ── Clustering thresholds ────────────────────────────────────────
_PACE_FAST_ZSCORE = -0.5
_PACE_SLOW_ZSCORE = 0.5
_MIN_CLUSTER_SIZE = 3
_KMEANS_MIN_LAPS = 12
_KMEANS_SEED = 42


@dataclass
class LapConditionFeatures:
    """Per-lap condition features for clustering."""
    lap_number: int
    grip_proxy: float
    pace_band: str
    traffic_score: float
    coverage_quality: float
    wet_proxy: float
    session_phase: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConditionCluster:
    """A group of laps sharing similar conditions."""
    cluster_id: int
    lap_numbers: list[int]
    grip_median: float
    pace_median_s: float
    wet_proxy_median: float
    n_laps: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ClusteringResult:
    """Result of condition-based lap clustering."""
    features: list[LapConditionFeatures]
    clusters: list[ConditionCluster]
    selected_cluster_id: int
    purity_score: float
    method: str
    fallback: bool

    def to_dict(self) -> dict:
        return {
            "features": [f.to_dict() for f in self.features],
            "clusters": [c.to_dict() for c in self.clusters],
            "selected_cluster_id": self.selected_cluster_id,
            "purity_score": round(self.purity_score, 3),
            "method": self.method,
            "fallback": self.fallback,
        }
