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
from dataclasses import asdict, dataclass, field

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


import math


def _get_lat_accel(df: "pd.DataFrame") -> np.ndarray:
    """Extract lateral acceleration in G from a lap DataFrame."""
    import pandas as pd

    for col in [_COL_ACCEL_LAT, _COL_ACCEL_LAT_ALT]:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").values
            if np.isfinite(vals).sum() > 10:
                if col == _COL_ACCEL_LAT_ALT:
                    vals = vals / 9.81
                return vals
    return np.zeros(len(df))


def _compute_grip_proxy(df: "pd.DataFrame") -> float:
    """Compute grip proxy: p95 of |a_lat| in G."""
    a_lat = _get_lat_accel(df)
    finite = a_lat[np.isfinite(a_lat)]
    if len(finite) < 5:
        return 0.0
    return float(np.percentile(np.abs(finite), 95))


def _compute_wet_proxy(df: "pd.DataFrame", expected_dry_g: float = 1.2) -> float:
    """Compute wet proxy: median |a_lat| / expected dry. Below 0.7 suggests wet."""
    a_lat = _get_lat_accel(df)
    finite = a_lat[np.isfinite(a_lat)]
    if len(finite) < 5 or expected_dry_g <= 0:
        return 0.5
    return float(np.median(np.abs(finite)) / expected_dry_g)


def _compute_coverage_quality(df: "pd.DataFrame") -> float:
    """Compute channel coverage quality: 1 - max(NaN fractions)."""
    import pandas as pd

    nan_fracs = []
    for col in [_COL_SPEED, _COL_ACCEL_LONG]:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce")
            nan_fracs.append(float(vals.isna().mean()))
    if not nan_fracs:
        return 0.5
    return max(0.0, 1.0 - max(nan_fracs))


def extract_condition_features(
    resampled_laps: dict[int, "pd.DataFrame"],
    lap_times: list[float],
    traffic_scores: dict[int, float],
) -> list[LapConditionFeatures]:
    """Extract per-lap condition features for clustering."""
    sorted_keys = sorted(resampled_laps.keys())
    n_laps = len(sorted_keys)

    key_to_time: dict[int, float] = {}
    for i, k in enumerate(sorted_keys):
        if i < len(lap_times) and math.isfinite(lap_times[i]):
            key_to_time[k] = lap_times[i]

    finite_times = [t for t in key_to_time.values()]
    if len(finite_times) >= 2:
        mean_t = float(np.mean(finite_times))
        std_t = float(np.std(finite_times))
        if std_t < 0.01:
            std_t = 1.0
    else:
        mean_t = finite_times[0] if finite_times else 60.0
        std_t = 1.0

    features: list[LapConditionFeatures] = []
    for idx, k in enumerate(sorted_keys):
        df = resampled_laps[k]
        grip = _compute_grip_proxy(df)
        wet = _compute_wet_proxy(df)
        coverage = _compute_coverage_quality(df)

        t = key_to_time.get(k, mean_t)
        z = (t - mean_t) / std_t
        if z < _PACE_FAST_ZSCORE:
            pace_band = "fast"
        elif z > _PACE_SLOW_ZSCORE:
            pace_band = "slow"
        else:
            pace_band = "normal"

        session_phase = idx / max(1, n_laps - 1)

        features.append(LapConditionFeatures(
            lap_number=k,
            grip_proxy=round(grip, 4),
            pace_band=pace_band,
            traffic_score=round(traffic_scores.get(k, 0.0), 3),
            coverage_quality=round(coverage, 3),
            wet_proxy=round(wet, 4),
            session_phase=round(session_phase, 3),
        ))

    return features


def _rule_based_cluster(
    features: list[LapConditionFeatures],
    lap_times_map: dict[int, float],
) -> list[ConditionCluster]:
    """Cluster laps by grip regime and pace band."""
    grips = [f.grip_proxy for f in features]
    if not grips:
        return []

    grip_threshold = float(np.percentile(grips, 60))

    assignments: dict[tuple[str, str], list[int]] = {}
    for f in features:
        grip_regime = "high" if f.grip_proxy >= grip_threshold else "low"
        key = (grip_regime, f.pace_band)
        if key not in assignments:
            assignments[key] = []
        assignments[key].append(f.lap_number)

    feat_map = {f.lap_number: f for f in features}
    clusters: list[ConditionCluster] = []
    for cid, ((grip_regime, pace), lap_nums) in enumerate(sorted(assignments.items())):
        grips_in = [feat_map[ln].grip_proxy for ln in lap_nums]
        times_in = [lap_times_map.get(ln, 60.0) for ln in lap_nums]
        wets_in = [feat_map[ln].wet_proxy for ln in lap_nums]
        clusters.append(ConditionCluster(
            cluster_id=cid,
            lap_numbers=sorted(lap_nums),
            grip_median=round(float(np.median(grips_in)), 4),
            pace_median_s=round(float(np.median(times_in)), 2),
            wet_proxy_median=round(float(np.median(wets_in)), 4),
            n_laps=len(lap_nums),
        ))

    # Merge tiny clusters
    merged = True
    while merged:
        merged = False
        tiny = [c for c in clusters if c.n_laps < _MIN_CLUSTER_SIZE]
        big = [c for c in clusters if c.n_laps >= _MIN_CLUSTER_SIZE]
        if not big and tiny:
            all_laps = []
            for c in tiny:
                all_laps.extend(c.lap_numbers)
            grips_all = [feat_map[ln].grip_proxy for ln in all_laps]
            times_all = [lap_times_map.get(ln, 60.0) for ln in all_laps]
            wets_all = [feat_map[ln].wet_proxy for ln in all_laps]
            clusters = [ConditionCluster(
                cluster_id=0, lap_numbers=sorted(all_laps),
                grip_median=round(float(np.median(grips_all)), 4),
                pace_median_s=round(float(np.median(times_all)), 2),
                wet_proxy_median=round(float(np.median(wets_all)), 4),
                n_laps=len(all_laps),
            )]
            break
        for tc in tiny:
            best_dist = float("inf")
            best_target = None
            for bc in big:
                d = abs(tc.grip_median - bc.grip_median)
                if d < best_dist:
                    best_dist = d
                    best_target = bc
            if best_target is not None:
                merged_laps = sorted(best_target.lap_numbers + tc.lap_numbers)
                grips_m = [feat_map[ln].grip_proxy for ln in merged_laps]
                times_m = [lap_times_map.get(ln, 60.0) for ln in merged_laps]
                wets_m = [feat_map[ln].wet_proxy for ln in merged_laps]
                best_target.lap_numbers = merged_laps
                best_target.n_laps = len(merged_laps)
                best_target.grip_median = round(float(np.median(grips_m)), 4)
                best_target.pace_median_s = round(float(np.median(times_m)), 2)
                best_target.wet_proxy_median = round(float(np.median(wets_m)), 4)
                clusters.remove(tc)
                merged = True
                break

    for i, c in enumerate(clusters):
        c.cluster_id = i
    return clusters


def _select_best_cluster(clusters: list[ConditionCluster]) -> int:
    """Select best cluster: highest grip_median among those with >= 3 laps."""
    viable = [c for c in clusters if c.n_laps >= _MIN_CLUSTER_SIZE]
    if not viable:
        viable = clusters
    if not viable:
        return -1
    best = max(viable, key=lambda c: c.grip_median)
    return best.cluster_id


def _compute_purity(clusters: list[ConditionCluster]) -> float:
    """Purity score: fraction of laps in the largest cluster."""
    if not clusters:
        return 0.0
    total = sum(c.n_laps for c in clusters)
    if total == 0:
        return 0.0
    largest = max(c.n_laps for c in clusters)
    return round(largest / total, 3)


def cluster_laps(
    resampled_laps: dict[int, "pd.DataFrame"],
    lap_times: list[float],
    traffic_scores: dict[int, float],
    *,
    learning_laps: "list[int] | None" = None,
) -> ClusteringResult:
    """Cluster laps by conditions for theoretical generation."""
    sorted_keys = sorted(resampled_laps.keys())

    if learning_laps is not None:
        learning_set = set(learning_laps)
        sorted_keys = [k for k in sorted_keys if k in learning_set]

    if len(sorted_keys) < _MIN_CLUSTER_SIZE:
        features = extract_condition_features(
            {k: resampled_laps[k] for k in sorted_keys},
            [lap_times[i] for i, k in enumerate(sorted(resampled_laps.keys()))
             if k in set(sorted_keys)] if lap_times else [],
            traffic_scores,
        )
        return ClusteringResult(
            features=features,
            clusters=[ConditionCluster(
                0, sorted_keys, 0.0, 0.0, 0.0, len(sorted_keys),
            )] if sorted_keys else [],
            selected_cluster_id=0 if sorted_keys else -1,
            purity_score=1.0, method="rule_based", fallback=True,
        )

    restricted_laps = {k: resampled_laps[k] for k in sorted_keys}
    all_sorted = sorted(resampled_laps.keys())
    restricted_times = [
        lap_times[i] for i, k in enumerate(all_sorted)
        if k in set(sorted_keys) and i < len(lap_times)
    ]

    features = extract_condition_features(
        restricted_laps, restricted_times, traffic_scores,
    )

    key_to_time: dict[int, float] = {}
    for i, k in enumerate(sorted_keys):
        if i < len(restricted_times) and math.isfinite(restricted_times[i]):
            key_to_time[k] = restricted_times[i]

    clusters = _rule_based_cluster(features, key_to_time)
    selected_id = _select_best_cluster(clusters)
    purity = _compute_purity(clusters)

    logger.info(
        "Condition clustering [rule_based]: %d clusters, selected=%d, purity=%.2f, %d laps.",
        len(clusters), selected_id, purity, len(sorted_keys),
    )

    return ClusteringResult(
        features=features, clusters=clusters,
        selected_cluster_id=selected_id, purity_score=purity,
        method="rule_based", fallback=False,
    )
