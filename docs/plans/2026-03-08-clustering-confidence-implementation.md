# Condition Clustering + Confidence Score Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Cluster laps by grip/pace/weather conditions so theoretical envelopes aren't blended fiction, then attach a unified confidence score (0–100) with actionable reasons to every advanced output.

**Architecture:** New `condition_clustering.py` extracts per-lap condition features and groups laps via rule-based clustering (with optional k-means). New `confidence.py` computes a weighted confidence score from 8 data quality components. Pipeline stage 9.8 runs clustering before theoretical generation; stage 10 filters to selected cluster; stage 10b attaches confidence to theoretical_metrics. Report gets a confidence panel; API scores endpoint gains confidence fields.

**Tech Stack:** Python 3.x, NumPy, pandas, scikit-learn (k-means only), pytest

---

### Task 1: LapConditionFeatures + ConditionCluster + ClusteringResult dataclasses

**Files:**
- Create: `telemetry_tool/condition_clustering.py`
- Create: `telemetry_tool/tests/test_condition_clustering.py`

**Step 1: Write the failing tests**

In `telemetry_tool/tests/test_condition_clustering.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_condition_clustering.py -v`
Expected: FAIL with "cannot import name 'LapConditionFeatures'"

**Step 3: Write minimal implementation**

In `telemetry_tool/condition_clustering.py`:

```python
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
_PACE_FAST_ZSCORE = -0.5       # below this = "fast"
_PACE_SLOW_ZSCORE = 0.5        # above this = "slow"
_MIN_CLUSTER_SIZE = 3           # merge clusters smaller than this
_KMEANS_MIN_LAPS = 12           # activate k-means above this
_KMEANS_SEED = 42               # deterministic clustering


@dataclass
class LapConditionFeatures:
    """Per-lap condition features for clustering."""
    lap_number: int
    grip_proxy: float        # max |a_lat| normalized, higher = more grip
    pace_band: str           # "fast" | "normal" | "slow"
    traffic_score: float     # 0–1 from traffic detection
    coverage_quality: float  # 1 - max(nan fractions)
    wet_proxy: float         # median |a_lat| / expected dry, <0.7 = wet
    session_phase: float     # lap_index / n_laps, 0 = early, 1 = late

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
    selected_cluster_id: int    # -1 if fallback
    purity_score: float         # 1.0 = all laps in one cluster
    method: str                 # "rule_based" | "kmeans"
    fallback: bool              # True if too few laps, used all

    def to_dict(self) -> dict:
        return {
            "features": [f.to_dict() for f in self.features],
            "clusters": [c.to_dict() for c in self.clusters],
            "selected_cluster_id": self.selected_cluster_id,
            "purity_score": round(self.purity_score, 3),
            "method": self.method,
            "fallback": self.fallback,
        }
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_condition_clustering.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/condition_clustering.py telemetry_tool/tests/test_condition_clustering.py
git commit -m "feat(clustering): add LapConditionFeatures, ConditionCluster, ClusteringResult dataclasses"
```

---

### Task 2: Feature extraction — grip_proxy, wet_proxy, pace_band

**Files:**
- Modify: `telemetry_tool/condition_clustering.py` (append)
- Modify: `telemetry_tool/tests/test_condition_clustering.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_condition_clustering.py`:

```python


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
    # With no lat accel, grip_proxy should default to a safe value
    for f in features:
        assert f.grip_proxy >= 0.0
        assert f.wet_proxy >= 0.0
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_condition_clustering.py::test_extract_features_two_regimes -v`
Expected: FAIL

**Step 3: Write implementation**

Append to `telemetry_tool/condition_clustering.py`:

```python
import math


def _get_lat_accel(df: "pd.DataFrame") -> np.ndarray:
    """Extract lateral acceleration in G from a lap DataFrame."""
    import pandas as pd

    for col in [_COL_ACCEL_LAT, _COL_ACCEL_LAT_ALT]:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").values
            if np.isfinite(vals).sum() > 10:
                # If column is in m/s2, convert to G
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
    """Compute wet proxy: median |a_lat| / expected dry.

    Returns value 0–1+. Below 0.7 suggests wet conditions.
    """
    a_lat = _get_lat_accel(df)
    finite = a_lat[np.isfinite(a_lat)]
    if len(finite) < 5 or expected_dry_g <= 0:
        return 0.5  # unknown
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
    """Extract per-lap condition features for clustering.

    Parameters
    ----------
    resampled_laps : lap_number -> DataFrame
    lap_times : lap durations in seconds (aligned with sorted keys)
    traffic_scores : lap_number -> traffic_score from traffic detection

    Returns
    -------
    List of LapConditionFeatures, one per lap.
    """
    sorted_keys = sorted(resampled_laps.keys())
    n_laps = len(sorted_keys)

    # Align lap times
    key_to_time: dict[int, float] = {}
    for i, k in enumerate(sorted_keys):
        if i < len(lap_times) and math.isfinite(lap_times[i]):
            key_to_time[k] = lap_times[i]

    # Compute pace z-scores
    finite_times = [t for t in key_to_time.values()]
    if len(finite_times) >= 2:
        mean_t = float(np.mean(finite_times))
        std_t = float(np.std(finite_times))
        if std_t < 0.01:
            std_t = 1.0  # avoid division by zero
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_condition_clustering.py -v`
Expected: 6 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/condition_clustering.py telemetry_tool/tests/test_condition_clustering.py
git commit -m "feat(clustering): add condition feature extraction (grip, wet, pace)"
```

---

### Task 3: Rule-based clustering + cluster selection

**Files:**
- Modify: `telemetry_tool/condition_clustering.py` (append)
- Modify: `telemetry_tool/tests/test_condition_clustering.py` (append)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_condition_clustering.py`:

```python


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
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_condition_clustering.py::test_rule_based_two_regimes_separated -v`
Expected: FAIL

**Step 3: Write implementation**

Append to `telemetry_tool/condition_clustering.py`:

```python


def _rule_based_cluster(
    features: list[LapConditionFeatures],
    lap_times_map: dict[int, float],
) -> list[ConditionCluster]:
    """Cluster laps by grip regime and pace band.

    1. Split by grip: high (>= p60) vs low (< p60)
    2. Within each grip group, split by pace band
    3. Merge clusters with < MIN_CLUSTER_SIZE laps
    """
    grips = [f.grip_proxy for f in features]
    if not grips:
        return []

    grip_threshold = float(np.percentile(grips, 60))

    # Assign each lap to a group key: (grip_regime, pace_band)
    assignments: dict[tuple[str, str], list[int]] = {}
    for f in features:
        grip_regime = "high" if f.grip_proxy >= grip_threshold else "low"
        key = (grip_regime, f.pace_band)
        if key not in assignments:
            assignments[key] = []
        assignments[key].append(f.lap_number)

    # Build clusters
    feat_map = {f.lap_number: f for f in features}
    clusters: list[ConditionCluster] = []
    for cid, ((grip_regime, pace), lap_nums) in enumerate(
        sorted(assignments.items())
    ):
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

    # Merge tiny clusters into nearest by grip centroid
    merged = True
    while merged:
        merged = False
        tiny = [c for c in clusters if c.n_laps < _MIN_CLUSTER_SIZE]
        big = [c for c in clusters if c.n_laps >= _MIN_CLUSTER_SIZE]
        if not big and tiny:
            # All clusters are tiny — merge everything into one
            all_laps = []
            for c in tiny:
                all_laps.extend(c.lap_numbers)
            grips_all = [feat_map[ln].grip_proxy for ln in all_laps]
            times_all = [lap_times_map.get(ln, 60.0) for ln in all_laps]
            wets_all = [feat_map[ln].wet_proxy for ln in all_laps]
            clusters = [ConditionCluster(
                cluster_id=0,
                lap_numbers=sorted(all_laps),
                grip_median=round(float(np.median(grips_all)), 4),
                pace_median_s=round(float(np.median(times_all)), 2),
                wet_proxy_median=round(float(np.median(wets_all)), 4),
                n_laps=len(all_laps),
            )]
            break

        for tc in tiny:
            # Find nearest big cluster by grip distance
            best_dist = float("inf")
            best_target = None
            for bc in big:
                d = abs(tc.grip_median - bc.grip_median)
                if d < best_dist:
                    best_dist = d
                    best_target = bc
            if best_target is not None:
                # Merge tc into best_target
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

    # Re-number cluster IDs
    for i, c in enumerate(clusters):
        c.cluster_id = i

    return clusters


def _select_best_cluster(clusters: list[ConditionCluster]) -> int:
    """Select best cluster: highest grip_median among those with >= 3 laps."""
    viable = [c for c in clusters if c.n_laps >= _MIN_CLUSTER_SIZE]
    if not viable:
        viable = clusters  # fallback to all
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
    """Cluster laps by conditions for theoretical generation.

    Parameters
    ----------
    resampled_laps : lap_number -> DataFrame
    lap_times : lap durations in seconds (aligned with sorted keys)
    traffic_scores : lap_number -> traffic_score
    learning_laps : optional list of learning-set lap numbers to restrict to

    Returns
    -------
    ClusteringResult with clusters, selected cluster, and purity.
    """
    sorted_keys = sorted(resampled_laps.keys())

    # Restrict to learning laps if provided
    if learning_laps is not None:
        learning_set = set(learning_laps)
        sorted_keys = [k for k in sorted_keys if k in learning_set]

    if len(sorted_keys) < _MIN_CLUSTER_SIZE:
        # Too few laps — fallback
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
            purity_score=1.0,
            method="rule_based",
            fallback=True,
        )

    # Restrict resampled_laps and lap_times
    restricted_laps = {k: resampled_laps[k] for k in sorted_keys}
    all_sorted = sorted(resampled_laps.keys())
    restricted_times = [
        lap_times[i] for i, k in enumerate(all_sorted)
        if k in set(sorted_keys) and i < len(lap_times)
    ]

    features = extract_condition_features(
        restricted_laps, restricted_times, traffic_scores,
    )

    # Build lap_times map
    key_to_time: dict[int, float] = {}
    for i, k in enumerate(sorted_keys):
        if i < len(restricted_times) and math.isfinite(restricted_times[i]):
            key_to_time[k] = restricted_times[i]

    # Rule-based clustering
    clusters = _rule_based_cluster(features, key_to_time)
    method = "rule_based"

    selected_id = _select_best_cluster(clusters)
    purity = _compute_purity(clusters)

    logger.info(
        "Condition clustering [%s]: %d clusters, selected=%d, "
        "purity=%.2f, %d laps.",
        method, len(clusters), selected_id, purity, len(sorted_keys),
    )

    return ClusteringResult(
        features=features,
        clusters=clusters,
        selected_cluster_id=selected_id,
        purity_score=purity,
        method=method,
        fallback=False,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_condition_clustering.py -v`
Expected: 9 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/condition_clustering.py telemetry_tool/tests/test_condition_clustering.py
git commit -m "feat(clustering): add rule-based clustering with merge logic and cluster selection"
```

---

### Task 4: ConfidenceAssessment dataclass + compute_confidence()

**Files:**
- Create: `telemetry_tool/confidence.py`
- Create: `telemetry_tool/tests/test_confidence.py`

**Step 1: Write the failing tests**

In `telemetry_tool/tests/test_confidence.py`:

```python
"""Tests for unified confidence score system."""
import numpy as np
import pandas as pd
import pytest


def test_confidence_assessment_fields():
    """ConfidenceAssessment has all required fields and to_dict()."""
    from confidence import ConfidenceAssessment

    ca = ConfidenceAssessment(
        confidence_score=72,
        confidence_level="medium",
        confidence_reasons=["Only 5 laps"],
        component_scores={"lap_count": 0.5},
        recommended_next_action="Record more laps",
    )
    assert ca.confidence_score == 72
    assert ca.confidence_level == "medium"
    d = ca.to_dict()
    assert "confidence_score" in d
    assert "recommended_next_action" in d


def test_high_confidence_all_good():
    """All components good → high confidence score."""
    from confidence import compute_confidence

    result = compute_confidence(
        n_learning_laps=15,
        data_quality_confidence=0.9,
        distance_quality_status="good",
        cluster_purity=1.0,
        channel_coverage=0.95,
        solver_method="hybrid",
        curvature_reliability=0.9,
        fusion_confidence=0.8,
    )
    assert result.confidence_score >= 75
    assert result.confidence_level == "high"
    assert len(result.confidence_reasons) == 0  # no blockers


def test_low_confidence_bad_data():
    """Low lap count + missing channels → low confidence with reasons."""
    from confidence import compute_confidence

    result = compute_confidence(
        n_learning_laps=2,
        data_quality_confidence=0.3,
        distance_quality_status="degraded",
        cluster_purity=0.5,
        channel_coverage=0.4,
        solver_method="percentile_envelope",
        curvature_reliability=0.3,
        fusion_confidence=-1.0,  # not computed
    )
    assert result.confidence_score < 45
    assert result.confidence_level == "low"
    assert len(result.confidence_reasons) >= 3
    assert result.recommended_next_action != ""


def test_confidence_reasons_sorted_by_impact():
    """Reasons should be sorted by impact (weight * deficit)."""
    from confidence import compute_confidence

    result = compute_confidence(
        n_learning_laps=2,      # weight=0.15, deficit high
        data_quality_confidence=0.1,  # weight=0.20, deficit very high
        distance_quality_status="good",
        cluster_purity=1.0,
        channel_coverage=0.1,   # weight=0.15, deficit very high
        solver_method="percentile_envelope",
        curvature_reliability=0.8,
        fusion_confidence=0.8,
    )
    # Data quality (weight=0.20) should be first or near first
    assert any("data quality" in r.lower() or "quality" in r.lower()
               for r in result.confidence_reasons[:2])
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_confidence.py -v`
Expected: FAIL

**Step 3: Write implementation**

In `telemetry_tool/confidence.py`:

```python
"""
confidence.py
-------------
Unified confidence score for theoretical + coaching outputs.

Computes a single confidence_score (0-100) from 8 weighted data quality
components and generates human-readable reasons explaining what limits
trust, sorted by impact. Includes a recommended_next_action for the
most impactful fix the user can make.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# ── Component weights (must sum to 1.0) ──────────────────────────
_WEIGHTS = {
    "distance_quality":     0.15,
    "data_quality":         0.20,
    "lap_count":            0.15,
    "cluster_purity":       0.10,
    "channel_coverage":     0.15,
    "solver_convergence":   0.10,
    "curvature_reliability": 0.10,
    "fusion_confidence":    0.05,
}

# ── Reason templates ─────────────────────────────────────────────
_REASON_TEMPLATES = {
    "distance_quality": "Distance quality is {status} — lap distances may be inaccurate",
    "data_quality": "Low overall data quality ({score:.0%}) — noisy or missing sensor data",
    "lap_count": "Only {n} learning lap(s) — need 10+ for reliable envelope",
    "cluster_purity": "Mixed driving conditions (purity {score:.0%}) — results blend different grip levels",
    "channel_coverage": "Poor channel coverage ({score:.0%}) — significant data gaps",
    "solver_convergence": "Using {method} solver — less precise than physics-based simulation",
    "curvature_reliability": "Low curvature reliability ({score:.0%}) — corner detection may be imprecise",
    "fusion_confidence": "No IMU sensor fusion — position and speed less precise",
}

# ── Recommended actions (ordered by typical impact) ──────────────
_ACTIONS = {
    "lap_count": "Record at least 10 clean laps for reliable results",
    "data_quality": "Check sensor connections and ensure clean GPS signal",
    "channel_coverage": "Verify all telemetry channels are recording properly",
    "distance_quality": "Ensure GPS antenna has clear sky view for accurate distance",
    "cluster_purity": "Run a session in consistent conditions (same tyre, dry track)",
    "solver_convergence": "Add IMU data for physics-based simulation",
    "curvature_reliability": "Add yaw rate sensor for precise curvature estimation",
    "fusion_confidence": "Add an IMU sensor for better acceleration data",
}


@dataclass
class ConfidenceAssessment:
    """Unified confidence assessment for advanced outputs."""
    confidence_score: int            # 0–100
    confidence_level: str            # "high" | "medium" | "low"
    confidence_reasons: list[str]    # sorted by impact
    component_scores: dict[str, float]  # each 0–1
    recommended_next_action: str     # top actionable fix

    def to_dict(self) -> dict:
        return asdict(self)


def _lap_count_score(n: int) -> float:
    """Ramp: 1→0, 3→0.3, 5→0.5, 10→0.8, 20→1.0."""
    if n <= 1:
        return 0.0
    if n >= 20:
        return 1.0
    # Piecewise linear
    breakpoints = [(1, 0.0), (3, 0.3), (5, 0.5), (10, 0.8), (20, 1.0)]
    for i in range(len(breakpoints) - 1):
        x0, y0 = breakpoints[i]
        x1, y1 = breakpoints[i + 1]
        if x0 <= n <= x1:
            t = (n - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return 1.0


def _solver_score(method: str) -> float:
    """Score solver convergence quality."""
    scores = {
        "hybrid": 1.0,
        "physics": 0.8,
        "percentile_envelope_phase_aware": 0.6,
        "percentile_envelope": 0.5,
    }
    return scores.get(method, 0.3)


def _distance_quality_score(status: str) -> float:
    """Score distance quality status."""
    scores = {"good": 1.0, "degraded": 0.3, "failed": 0.0}
    return scores.get(status, 0.5)


def compute_confidence(
    *,
    n_learning_laps: int,
    data_quality_confidence: float,
    distance_quality_status: str,
    cluster_purity: float,
    channel_coverage: float,
    solver_method: str,
    curvature_reliability: float,
    fusion_confidence: float,
) -> ConfidenceAssessment:
    """Compute unified confidence score from 8 components.

    Parameters
    ----------
    n_learning_laps : number of laps in learning set
    data_quality_confidence : DataQualityReport.overall_confidence (0-1)
    distance_quality_status : "good", "degraded", or "failed"
    cluster_purity : ClusteringResult.purity_score (0-1)
    channel_coverage : 1 - max(nan fractions) (0-1)
    solver_method : simulation method string
    curvature_reliability : curvature quality score (0-1)
    fusion_confidence : EKF fusion confidence (0-1), -1 if not computed

    Returns
    -------
    ConfidenceAssessment with score, level, reasons, and action.
    """
    # Compute component scores
    components = {
        "distance_quality": _distance_quality_score(distance_quality_status),
        "data_quality": max(0.0, min(1.0, data_quality_confidence)),
        "lap_count": _lap_count_score(n_learning_laps),
        "cluster_purity": max(0.0, min(1.0, cluster_purity)),
        "channel_coverage": max(0.0, min(1.0, channel_coverage)),
        "solver_convergence": _solver_score(solver_method),
        "curvature_reliability": max(0.0, min(1.0, curvature_reliability)),
        "fusion_confidence": 0.5 if fusion_confidence < 0 else max(0.0, min(1.0, fusion_confidence)),
    }

    # Weighted sum
    weighted = sum(
        components[k] * _WEIGHTS[k] for k in _WEIGHTS
    )
    score = round(weighted * 100)
    score = max(0, min(100, score))

    # Level
    if score >= 75:
        level = "high"
    elif score >= 45:
        level = "medium"
    else:
        level = "low"

    # Reasons: components below 0.5, sorted by impact (weight * deficit)
    reasons: list[tuple[float, str, str]] = []  # (impact, key, reason)
    for key, val in components.items():
        if val < 0.5:
            deficit = 0.5 - val
            impact = deficit * _WEIGHTS[key]
            template = _REASON_TEMPLATES[key]
            if key == "distance_quality":
                reason = template.format(status=distance_quality_status)
            elif key == "lap_count":
                reason = template.format(n=n_learning_laps)
            elif key == "solver_convergence":
                reason = template.format(method=solver_method)
            else:
                reason = template.format(score=val)
            reasons.append((impact, key, reason))

    reasons.sort(key=lambda x: -x[0])
    reason_strings = [r[2] for r in reasons]

    # Recommended action: from highest-impact blocker
    if reasons:
        top_key = reasons[0][1]
        action = _ACTIONS.get(top_key, "Improve data quality for more reliable results")
    else:
        action = ""

    logger.info(
        "Confidence: score=%d, level=%s, reasons=%d, action=%s",
        score, level, len(reason_strings),
        action[:50] if action else "none",
    )

    return ConfidenceAssessment(
        confidence_score=score,
        confidence_level=level,
        confidence_reasons=reason_strings,
        component_scores={k: round(v, 3) for k, v in components.items()},
        recommended_next_action=action,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_confidence.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/confidence.py telemetry_tool/tests/test_confidence.py
git commit -m "feat(confidence): add ConfidenceAssessment and compute_confidence() with 8 weighted components"
```

---

### Task 5: Pipeline stage 9.8 — clustering integration

**Files:**
- Modify: `telemetry_tool/pipeline.py` (insert between stage 09g and stage 10, around line 1990)
- Create: `telemetry_tool/tests/test_clustering_pipeline.py`

**Step 1: Write the failing test**

In `telemetry_tool/tests/test_clustering_pipeline.py`:

```python
"""Integration tests for condition clustering in the pipeline."""
import numpy as np
import pandas as pd
import pytest


def _make_multi_lap_csv(tmp_path, n_laps=8):
    """Create a CSV with multiple laps."""
    rng = np.random.default_rng(42)
    frames = []
    n_per_lap = 200
    lap_length = 500.0

    for lap in range(1, n_laps + 1):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, lap_length, n_per_lap)
        speed = np.full(n_per_lap, 20.0) + rng.normal(0, 0.3, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)

        df = pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * lap_length,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": rng.normal(0, 0.3, n_per_lap) * 1.2,
        })
        frames.append(df)

    full_df = pd.concat(frames, ignore_index=True)
    csv_path = tmp_path / "cluster_test.csv"
    full_df.to_csv(csv_path, index=False)
    return csv_path


def test_pipeline_has_clustering(tmp_path):
    """Pipeline summary contains clustering key."""
    import pipeline

    csv_path = _make_multi_lap_csv(tmp_path, n_laps=8)
    summary = pipeline.run_full_analysis(str(csv_path), {})

    assert "clustering" in summary
    clustering = summary["clustering"]
    assert "clusters" in clustering
    assert "selected_cluster_id" in clustering
    assert "purity_score" in clustering
    assert "method" in clustering
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_clustering_pipeline.py -v`
Expected: FAIL

**Step 3: Modify pipeline.py**

Read `telemetry_tool/pipeline.py` around line 1990 (after stage 09g traffic/inclusion results are stored, before stage 10). Insert stage 9.8:

```python
    # ====================================================================
    # STEP 09h -- Condition clustering
    # ====================================================================

    _cc_mod = _import("condition_clustering")
    _clustering_result = None

    def _condition_clustering():
        if _cc_mod is None or not resampled_laps:
            return None
        _traffic_scores = {}
        if _traffic_result is not None:
            _traffic_scores = _traffic_result.per_lap_score
        _learning = None
        if _inclusion_policy is not None:
            _learning = _inclusion_policy.learning_laps
        return _cc_mod.cluster_laps(
            resampled_laps, lap_times, _traffic_scores,
            learning_laps=_learning,
        )

    _clustering_raw, err = _safe_step("09h_condition_clustering", _condition_clustering)
    _record("09h_condition_clustering", _clustering_raw, err)
    _fire_progress("09h_condition_clustering")

    if _clustering_raw is not None:
        _clustering_result = _clustering_raw
        summary["clustering"] = _clustering_result.to_dict()
    else:
        summary["clustering"] = None
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_clustering_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_clustering_pipeline.py
git commit -m "feat(clustering): integrate condition clustering as pipeline stage 9.8"
```

---

### Task 6: Stage 10 — filter laps by selected cluster

**Files:**
- Modify: `telemetry_tool/pipeline.py` (~line 2161-2181, the inclusion policy filtering block)

**Step 1: Read current stage 10 code**

Read `telemetry_tool/pipeline.py` lines 2160-2185 to find the inclusion policy filtering block.

**Step 2: Add cluster filtering AFTER inclusion policy filtering**

After the inclusion policy filtering block (around line 2181), add:

```python
            # Filter by selected cluster (if available)
            if _clustering_result is not None and not _clustering_result.fallback:
                _selected = [
                    c for c in _clustering_result.clusters
                    if c.cluster_id == _clustering_result.selected_cluster_id
                ]
                if _selected:
                    _cluster_laps = set(_selected[0].lap_numbers)
                    _cluster_filtered = [
                        (lap, key) for lap, key in zip(laps_for_theo, keys_for_theo)
                        if key in _cluster_laps
                    ]
                    if len(_cluster_filtered) >= 3:
                        laps_for_theo = [x[0] for x in _cluster_filtered]
                        keys_for_theo = [x[1] for x in _cluster_filtered]
                        logger.info(
                            "Theoretical envelope: filtered to %d laps from "
                            "cluster %d (purity=%.2f).",
                            len(laps_for_theo),
                            _clustering_result.selected_cluster_id,
                            _clustering_result.purity_score,
                        )
                    else:
                        logger.warning(
                            "Cluster filtering leaves only %d laps — "
                            "using all %d learning laps.",
                            len(_cluster_filtered), len(laps_for_theo),
                        )
```

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_clustering_pipeline.py telemetry_tool/tests/test_traffic_pipeline.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "feat(clustering): filter theoretical laps by selected condition cluster"
```

---

### Task 7: Stage 10b — attach confidence to theoretical_metrics

**Files:**
- Modify: `telemetry_tool/pipeline.py` (~line 2260-2270, after theo_metrics are computed)

**Step 1: Read pipeline.py lines 2250-2270**

Find where `summary["theoretical_metrics"]` is set.

**Step 2: Add confidence computation after theo_metrics**

After `summary["theoretical_metrics"] = theo_metrics` (around line 2266), insert:

```python
    # ── 10b-ii: Attach confidence assessment ──
    _conf_mod = _import("confidence")

    def _compute_confidence():
        if _conf_mod is None:
            return None

        # Gather inputs
        n_learn = 0
        if _inclusion_policy is not None:
            n_learn = len(_inclusion_policy.learning_laps)
        else:
            n_learn = len(resampled_laps)

        dq_conf = 0.5
        if data_quality_rpt is not None:
            dq_conf = data_quality_rpt.overall_confidence

        dist_status = "good"
        dq = summary.get("distance_quality")
        if dq and isinstance(dq, dict):
            dist_status = dq.get("status", "good")
        elif _distance_quality is not None and hasattr(_distance_quality, 'status'):
            dist_status = _distance_quality.status

        c_purity = 1.0
        if _clustering_result is not None:
            c_purity = _clustering_result.purity_score

        # Channel coverage from data quality or compute
        ch_cov = 0.5
        if data_quality_rpt is not None:
            # Use accel_quality as proxy for coverage
            ch_cov = max(data_quality_rpt.gps_quality, data_quality_rpt.accel_quality)

        solver = _sim_method or "percentile_envelope"

        curv_rel = 0.5
        cq = summary.get("curvature_quality")
        if cq and isinstance(cq, dict):
            curv_rel = cq.get("quality_score", 0.5)

        fuse_conf = -1.0
        sf = summary.get("sensor_fusion")
        if sf and isinstance(sf, dict):
            fuse_conf = sf.get("confidence", -1.0)

        return _conf_mod.compute_confidence(
            n_learning_laps=n_learn,
            data_quality_confidence=dq_conf,
            distance_quality_status=dist_status,
            cluster_purity=c_purity,
            channel_coverage=ch_cov,
            solver_method=solver,
            curvature_reliability=curv_rel,
            fusion_confidence=fuse_conf,
        )

    _confidence, err = _safe_step("10b_confidence", _compute_confidence)
    _record("10b_confidence", _confidence, err)

    if _confidence is not None and theo_metrics is not None:
        theo_metrics["confidence"] = _confidence.to_dict()
        summary["theoretical_metrics"] = theo_metrics
```

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_clustering_pipeline.py telemetry_tool/tests/test_confidence.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "feat(confidence): attach confidence assessment to theoretical_metrics in pipeline"
```

---

### Task 8: Confidence panel in HTML report

**Files:**
- Modify: `telemetry_tool/reporting_html.py`

**Step 1: Read reporting_html.py to find _build_traffic_html location**

Find `_build_traffic_html` (line ~3147). The confidence panel goes right after it.

**Step 2: Add _build_confidence_html helper**

Insert after `_build_traffic_html`:

```python
def _build_confidence_html(theo_metrics: Optional[dict]) -> str:
    """Build HTML for confidence assessment panel."""
    if theo_metrics is None:
        return ""
    confidence = theo_metrics.get("confidence")
    if confidence is None:
        return ""

    score = confidence.get("confidence_score", 0)
    level = confidence.get("confidence_level", "unknown")
    reasons = confidence.get("confidence_reasons", [])
    action = confidence.get("recommended_next_action", "")

    # Color based on level
    color_map = {"high": "#22c55e", "medium": "#f59e0b", "low": "#ef4444"}
    color = color_map.get(level, "#9ca3af")

    parts = [
        '<div class="section confidence-panel" '
        f'style="border-left: 4px solid {color}; padding: 12px; '
        'margin: 16px 0; background: rgba(0,0,0,0.02);">',
        f'<h3>Confidence: {score}/100 '
        f'<span style="color: {color}; text-transform: capitalize;">'
        f'({level})</span></h3>',
    ]

    if reasons:
        parts.append('<p><strong>Top blockers:</strong></p><ol>')
        for reason in reasons[:3]:
            parts.append(f'<li>{reason}</li>')
        parts.append('</ol>')

    if action:
        parts.append(
            f'<p style="margin-top: 8px;"><strong>&rarr;</strong> {action}</p>'
        )

    parts.append('</div>')
    return "\n".join(parts)
```

**Step 3: Call it from generate_report()**

Find where `traffic_html = _build_traffic_html(...)` is called (~line 3458). After it, add:

```python
    confidence_html = _build_confidence_html(summary.get("theoretical_metrics"))
```

Then find where `traffic_html` is injected into the template and add `confidence_html` right after it.

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_clustering_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/reporting_html.py
git commit -m "feat(report): add confidence panel with score, blockers, and recommended action"
```

---

### Task 9: API — confidence fields in scores endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (~line 533-577)

**Step 1: Read data_v2.py lines 530-580**

Find the `get_scores()` function.

**Step 2: Add confidence fields to scores response**

After `scores["badges"] = ...` (around line 575), add:

```python
    # ── confidence: from theoretical_metrics ──
    try:
        theo_data = models.get_theoretical_data(conn, session_id)
        if theo_data and isinstance(theo_data, dict):
            metrics = theo_data.get("theoretical_metrics", {})
            if metrics and "confidence" in metrics:
                conf = metrics["confidence"]
                scores["confidence_score"] = conf.get("confidence_score")
                scores["confidence_level"] = conf.get("confidence_level")
                scores["confidence_reasons"] = conf.get("confidence_reasons", [])
                scores["recommended_next_action"] = conf.get(
                    "recommended_next_action", ""
                )
    except Exception:
        logger.warning(
            "Confidence data unavailable for session %s", session_id,
            exc_info=True,
        )
```

Note: Check if `models.get_theoretical_data()` exists. If not, check what function retrieves the summary/theoretical data. It may be `get_session_summary()` or stored in a JSON column.

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_clustering_pipeline.py telemetry_tool/tests/test_confidence.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat(api): expose confidence fields in scores endpoint"
```

---

### Task 10: Integration test — two-regime session clusters separated

**Files:**
- Modify: `telemetry_tool/tests/test_clustering_pipeline.py` (append)

**Step 1: Write the test**

Append to `telemetry_tool/tests/test_clustering_pipeline.py`:

```python


def test_two_regime_clusters_separated(tmp_path):
    """Session with two grip regimes → clusters separate them.

    Creates a CSV where laps 1-4 have high lateral G (dry) and
    laps 5-8 have low lateral G (greasy). Clustering should separate
    them and select the high-grip cluster for theoretical.
    """
    rng = np.random.default_rng(42)
    frames = []
    n_per_lap = 200
    lap_length = 500.0

    for lap in range(1, 9):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, lap_length, n_per_lap)

        # Two grip regimes
        if lap <= 4:
            grip_factor = 1.5  # high grip
            speed_base = 22.0
        else:
            grip_factor = 0.6  # low grip
            speed_base = 17.0

        speed = np.full(n_per_lap, speed_base) + rng.normal(0, 0.3, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)

        df = pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * lap_length,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": rng.normal(0, 0.3, n_per_lap) * grip_factor,
        })
        frames.append(df)

    full_df = pd.concat(frames, ignore_index=True)
    csv_path = tmp_path / "two_regime_test.csv"
    full_df.to_csv(csv_path, index=False)

    import pipeline

    summary = pipeline.run_full_analysis(str(csv_path), {})

    assert "clustering" in summary
    clustering = summary["clustering"]
    assert clustering is not None
    assert len(clustering["clusters"]) >= 2

    # Selected cluster should be the high-grip one
    selected_id = clustering["selected_cluster_id"]
    selected = [c for c in clustering["clusters"] if c["cluster_id"] == selected_id][0]

    # High-grip laps (1-4) should be in the selected cluster
    # (at least most of them)
    high_grip_in_selected = sum(1 for ln in selected["lap_numbers"] if ln <= 4)
    assert high_grip_in_selected >= 3, (
        f"Expected at least 3 high-grip laps in selected cluster, "
        f"got {high_grip_in_selected}. Selected laps: {selected['lap_numbers']}"
    )
```

**Step 2: Run test**

Run: `pytest telemetry_tool/tests/test_clustering_pipeline.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_clustering_pipeline.py
git commit -m "test(clustering): add two-regime integration test verifying cluster separation"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | Dataclasses: LapConditionFeatures, ConditionCluster, ClusteringResult | 4 |
| 2 | Feature extraction: grip_proxy, wet_proxy, pace_band | 2 |
| 3 | Rule-based clustering + merge + selection | 3 |
| 4 | ConfidenceAssessment + compute_confidence() | 4 |
| 5 | Pipeline stage 9.8 clustering integration | 1 |
| 6 | Stage 10 cluster-filtered lap selection | 0 (existing tests) |
| 7 | Stage 10b confidence in theoretical_metrics | 0 (existing tests) |
| 8 | Confidence panel HTML in report | 0 (existing tests) |
| 9 | API confidence fields in scores endpoint | 0 (existing tests) |
| 10 | Integration: two-regime session clusters separated | 1 |
