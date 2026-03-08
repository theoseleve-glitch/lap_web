# Distance Integrity Preflight Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` pipeline (14-stage → 15-stage)

## Problem

The pipeline has no quality gate on `distance_m` before resampling. `resampling.py:95` silently sorts non-monotonic distance via `argsort(kind="stable")`, destroying temporal sequence. `validate_lap_consistency()` repairs negative jumps but doesn't enforce monotonicity. No gate blocks downstream processing when distance is unreliable, causing silent errors in theoretical lap, coaching, and sensitivity analysis.

## Approach: Validate → Repair → Re-validate → Gate

### 1. Data Model (`telemetry_tool/distance_integrity.py`)

```python
@dataclass
class LapDistanceMetrics:
    lap_number: int
    monotonic_ratio: float      # fraction of samples where d[i+1] > d[i]
    jump_count: int             # number of backward jumps (d[i+1] < d[i])
    compression_ratio: float    # std(diff) / mean(diff), measures uniformity
    lap_length: float           # max(distance_m) - min(distance_m)
    lap_length_zscore: float    # z-score vs median lap length

@dataclass
class DistanceQuality:
    status: str                 # "ok" | "repaired" | "degraded"
    repair_method: str | None   # "xy_rebuild" | "isotonic_regression" | None
    laps_repaired: list[int]    # which laps were repaired
    laps_degraded: list[int]    # which laps failed even after repair
    metrics: list[dict]         # LapDistanceMetrics as dicts
    gate_advanced: bool         # True = block theoretical/coaching/sensitivity
    message: str                # user-facing explanation
```

**Thresholds** (configurable):
- `monotonic_ratio < 0.95` → needs repair
- `jump_count > 5` → needs repair
- `lap_length_zscore > 3.0` → outlier lap, flag but don't gate
- After repair: `monotonic_ratio < 0.99` → gate advanced outputs

### 2. Pipeline Integration

Insert as **stage 6.5** — after derived channels (which compute distance_m), before resampling (stage 7).

```python
distance_quality = _safe_step("distance_integrity",
    run_distance_integrity, df, config, summary)
```

**Gating**: `distance_quality.gate_advanced` checked before stages 10 (theoretical), 11 (coaching_v2), and sensitivity. When gated, those stages return `None` with reason logged.

**Summary**: `summary["distance_quality"] = distance_quality.to_dict()`

### 3. Repair Strategies

**XY Rebuild** (preferred when lat/lon or x/y available):
```
distance_m[i] = cumsum(sqrt(dx² + dy²))
```
Uses Haversine for lat/lon, Euclidean for projected x/y.

**Isotonic Regression Fallback** (when no coordinates):
```python
from sklearn.isotonic import IsotonicRegression
ir = IsotonicRegression(increasing=True)
distance_m = ir.fit_transform(np.arange(len(d)), d)
```
Forces monotonicity while preserving relative spacing.

### 4. API & UI

**API**: `GET /api/v1/sessions/<id>/distance-quality` in `data_v2.py`
- Returns `DistanceQuality.to_dict()` from summary JSON
- Also included in session detail response as `distance_quality` field

**UI Badges** (data contract; frontend implementation deferred):
- `status: "ok"` → no badge
- `status: "repaired"` → yellow badge "Distance Repaired"
- `status: "degraded"` → red badge "Advanced Analysis Disabled"

**Report Debug Section** (`reporting_html.py`):
- Lap length histogram (bar chart of per-lap distances)
- Distance quality summary table (metrics per lap)
- Repair method annotation if applied

### 5. Files Touched

| File | Change |
|------|--------|
| `telemetry_tool/distance_integrity.py` | New — metrics, repair, gating |
| `telemetry_tool/pipeline.py` | Modified — insert stage 6.5, gate stages 10-11 |
| `telemetry_tool/web/routes/data_v2.py` | Modified — distance-quality endpoint |
| `telemetry_tool/reporting_html.py` | Modified — debug section |
| `telemetry_tool/tests/test_distance_integrity.py` | New — unit tests |
| `telemetry_tool/tests/test_distance_gate.py` | New — integration gate tests |

No database migration needed — `DistanceQuality` lives in the summary JSON.
