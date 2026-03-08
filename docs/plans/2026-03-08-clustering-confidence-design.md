# Condition Clustering + Confidence Score Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` pipeline

## Problem

1. **Blended envelopes**: All learning laps feed into one envelope regardless of grip level, weather, or session phase. A session with 5 dry laps and 5 greasy laps produces a fictional average envelope that matches neither condition.

2. **No unified confidence**: Advanced outputs (theoretical lap, coaching, corners) lack a trust signal. Users don't know if results are reliable or what's limiting quality.

3. **No actionable guidance**: When results are low-confidence, users don't know what to fix — more laps? Better sensor? Drier conditions?

## Approach

### 1. Condition Clustering Module (`telemetry_tool/condition_clustering.py`)

**Per-lap condition features**:

| Feature | Source | Computation |
|---------|--------|-------------|
| `grip_proxy` | Lateral accel vs curvature | `max(\|a_lat\|)` in corners, normalized by curvature |
| `pace_band` | Lap times | z-score from median: fast (<-0.5σ), normal, slow (>+0.5σ) |
| `traffic_score` | traffic_detection | Already computed, 0–1 |
| `coverage_quality` | Channel NaN fractions | `1 - max(speed_nan_frac, accel_nan_frac)` |
| `wet_proxy` | Reduced accel envelope | `median(\|a_lat\|) / expected_dry_lat`, < 0.7 suggests wet |
| `session_phase` | Lap position | `lap_index / n_laps` |

**Rule-based clustering** (deterministic):

```
1. Split by grip regime:
   - high_grip: grip_proxy >= p60 of all laps
   - low_grip:  grip_proxy < p60

2. Within each grip group, split by pace:
   - fast: pace_band == "fast"
   - normal: pace_band == "normal"
   - slow: pace_band == "slow"

3. Merge tiny clusters: if cluster has < 3 laps, merge into nearest by grip centroid

4. Select best cluster: highest grip_proxy median among clusters with >= 3 laps
```

**Optional k-means** (when `n_laps >= 12`):
- Features: `[grip_proxy_norm, pace_norm, wet_proxy_norm]`
- `k = min(4, n_laps // 4)`, seed=42
- Select cluster with highest grip centroid

**Data model**:

```python
@dataclass
class LapConditionFeatures:
    lap_number: int
    grip_proxy: float
    pace_band: str           # "fast" | "normal" | "slow"
    traffic_score: float
    coverage_quality: float
    wet_proxy: float
    session_phase: float

@dataclass
class ConditionCluster:
    cluster_id: int
    lap_numbers: list[int]
    grip_median: float
    pace_median_s: float
    wet_proxy_median: float
    n_laps: int

@dataclass
class ClusteringResult:
    features: list[LapConditionFeatures]
    clusters: list[ConditionCluster]
    selected_cluster_id: int
    purity_score: float       # 1.0 = all laps same cluster
    method: str               # "rule_based" | "kmeans"
    fallback: bool            # True if too few laps
```

### 2. Unified Confidence Score (`telemetry_tool/confidence.py`)

**Components** (weighted):

| Component | Weight | Source | Score 0–1 |
|-----------|--------|--------|-----------|
| `distance_quality` | 15% | distance_quality.status | good=1.0, degraded=0.3, failed=0.0 |
| `data_quality` | 20% | DataQualityReport.overall_confidence | Direct |
| `lap_count` | 15% | n_learning_laps | ramp: 1→0, 3→0.3, 5→0.5, 10→0.8, 20→1.0 |
| `cluster_purity` | 10% | ClusteringResult.purity_score | Direct |
| `channel_coverage` | 15% | Per-channel NaN fraction | 1 - max(nan_fracs) |
| `solver_convergence` | 10% | Simulation method | hybrid=1.0, physics=0.8, envelope=0.5 |
| `curvature_reliability` | 10% | curvature_quality | Direct or 0.5 |
| `fusion_confidence` | 5% | EKF confidence | Direct or 0.5 |

**confidence_score** = `round(weighted_sum * 100)`, integer 0–100.

**confidence_reasons[]**: Components below 0.5 → reason string, sorted by impact (weight × deficit).

```python
@dataclass
class ConfidenceAssessment:
    confidence_score: int            # 0–100
    confidence_level: str            # "high" | "medium" | "low"
    confidence_reasons: list[str]
    component_scores: dict[str, float]
    recommended_next_action: str     # top actionable fix
```

**recommended_next_action** examples:
- "Record at least 10 clean laps for reliable results"
- "Add an IMU sensor for better acceleration data"
- "Run on a drier session for consistent grip"

### 3. Pipeline Integration

**Stage 9.8** — after traffic/inclusion (9.5), before theoretical (10):

```python
_clustering_result = cluster_laps(resampled_laps, lap_times, _traffic_result, _inclusion_policy)
summary["clustering"] = _clustering_result.to_dict()
```

**Stage 10** — filter `laps_for_theo` by selected cluster's `lap_numbers` (intersected with `learning_laps`). Fallback if < 3 laps survive.

**Stage 10b** — after theoretical metrics:

```python
_confidence = compute_confidence(summary, _clustering_result, _inclusion_policy, data_quality_rpt)
summary["theoretical_metrics"]["confidence"] = _confidence.to_dict()
```

### 4. Reporting

**Confidence panel** in HTML report:

```
┌─ Confidence: 72/100 (Medium) ──────────────────┐
│  Top blockers:                                   │
│  1. Only 5 laps — need 10+ for reliable envelope │
│  2. No yaw rate channel — curvature less precise │
│  3. Mixed grip — cluster purity 0.6              │
│  → Record at least 10 clean laps                 │
└──────────────────────────────────────────────────┘
```

### 5. API

Existing `/api/v1/sessions/<id>/scores` response gains `confidence_score`, `confidence_level`, `confidence_reasons`, `recommended_next_action` from `theoretical_metrics`.

### 6. Files Touched

| File | Change |
|------|--------|
| `telemetry_tool/condition_clustering.py` | New |
| `telemetry_tool/confidence.py` | New |
| `telemetry_tool/pipeline.py` | Modified — stages 9.8, 10, 10b |
| `telemetry_tool/reporting_html.py` | Modified — confidence panel |
| `telemetry_tool/web/routes/data_v2.py` | Modified — confidence in scores |
| `telemetry_tool/tests/test_condition_clustering.py` | New |
| `telemetry_tool/tests/test_confidence.py` | New |
| `telemetry_tool/tests/test_clustering_pipeline.py` | New |

No database migration needed — clustering and confidence live in summary JSON.
