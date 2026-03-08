# Traffic Detection + Lap Inclusion Policy Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` pipeline

## Problem

1. **No traffic detection**: When a driver lifts on a straight to avoid slower traffic, the speed dip contaminates the percentile envelope. The theoretical lap becomes slower than it should be. Coaching and scoring penalize the driver for traffic they couldn't avoid.

2. **No lap inclusion policy**: All resampled laps feed into envelope computation, mu(s) estimation, and calibration equally. Outlaps, inlaps, traffic-affected laps, and degraded-distance laps all pull down the theoretical lap and distort scoring.

3. **No learning/display split**: A lap excluded from learning disappears entirely. Users want to see all laps in the report/replay but only use clean laps for learning.

## Approach

### 1. Traffic Detection Module (`telemetry_tool/traffic_detection.py`)

**Straight detection**: Curvature-based. Compute curvature from smoothed heading derivative, identify segments where `|curvature| < 0.005 1/m` for at least 30m continuous. Returns `StraightSegment(s_start, s_end, length_m)`.

**Per-straight traffic flag**: For each straight segment, across all laps:
1. Build cross-lap speed envelope at p90 on a shared distance grid
2. For each lap on each straight, check two conditions simultaneously:
   - **Speed deficit**: `v_lap < envelope * 0.95` for at least 10m continuous
   - **Unexplained decel**: `a_long < -0.5 m/s²` at any point within the deficit zone, not within 20m of a known corner entry
3. Both must be true → flag that `(lap, straight)` as traffic-affected

**Per-lap traffic_score**: `traffic_score = total_flagged_straight_distance / total_straight_distance`. Range 0–1.

**Data model**:

```python
@dataclass
class TrafficEvent:
    lap_number: int
    s_start: float              # metres
    s_end: float                # metres
    speed_deficit_pct: float    # how much below envelope
    max_decel_mps2: float       # worst a_long in event

@dataclass
class TrafficResult:
    straights: list[dict]           # detected straight segments
    events: list[TrafficEvent]      # all traffic events
    per_lap_score: dict[int, float] # lap_number → traffic_score
    n_laps_affected: int
```

### 2. Lap Inclusion Policy (`telemetry_tool/lap_inclusion.py`)

**Data model**:

```python
@dataclass
class LapExclusion:
    lap_number: int
    reasons: list[str]       # e.g. ["outlap", "traffic"]
    detail: dict             # reason-specific metadata

@dataclass
class LapInclusionPolicy:
    learning_laps: list[int]         # clean laps for envelope/mu/calibration
    display_laps: list[int]          # all laps shown in report/replay
    exclusions: list[LapExclusion]   # why each excluded lap was excluded
    traffic_masks: dict[int, list[tuple[float, float]]]  # lap → [(s_start, s_end)]
```

**Learning set exclusion criteria**:

| Rule | Source | Threshold |
|------|--------|-----------|
| Outlap/inlap | Lap number = first or last, OR lap_time > 2× median | Auto |
| Traffic (full exclude) | traffic_score > 0.5 | Whole lap excluded |
| Traffic (segment mask) | 0 < traffic_score <= 0.5 | Lap included, affected ranges masked |
| Distance quality | distance_quality.laps_degraded | Lap in degraded list |
| Abnormal length | lap_length_zscore > 3.0 | From distance_integrity metrics |
| Low channel coverage | >20% NaN in speed or accel columns | Per-lap check |

**Segment masking**: For laps with `0 < traffic_score <= 0.5`, `traffic_masks[lap]` contains flagged distance ranges. Envelope computation sets these samples to NaN before percentile calculation.

**Display set**: All laps that pass basic validity. Labels: `"clean"`, `"traffic"`, `"outlap"`, `"inlap"`, `"degraded"`.

### 3. Pipeline Integration

**Stage 9.5** — after deltas/data_quality, before theoretical:

```python
_traffic_result = run_traffic_detection(resampled_laps, corner_list)
_inclusion_policy = build_inclusion_policy(
    resampled_laps, lap_times, _traffic_result,
    distance_quality=summary.get("distance_quality"),
)
summary["traffic"] = _traffic_result.to_dict()
summary["lap_inclusion"] = _inclusion_policy.to_dict()
```

**Stage 10 — Theoretical lap**: Filter `laps_list` to `policy.learning_laps`. Pass `policy.traffic_masks` to `compute_speed_percentile_envelope()`. Fallback: if fewer than 3 learning laps, use all laps with warning.

**Stage 13 — Scoring**: `best_lap` from learning set only. Consistency/robustness from learning set. Display set laps shown in per-lap breakdown.

### 4. Theoretical Engine Modification

`compute_speed_percentile_envelope()` gains optional `masks` parameter:

```python
def compute_speed_percentile_envelope(
    laps, percentile=98.0, n_bins=0, smooth_window=5,
    masks: dict[int, list[tuple[float, float]]] | None = None,
)
```

Before percentile computation, for each lap with masks, set `speed_matrix[i, j] = NaN` for distance bins within masked ranges. `np.nanpercentile()` ignores NaN naturally.

### 5. Reporting

Traffic section in HTML report:
- Per-lap traffic badges: lap number, traffic_score, label
- Traffic event list: straight ID, distance range, speed deficit
- Learning vs display summary: "N laps for learning, M displayed, K excluded"

### 6. Files Touched

| File | Change |
|------|--------|
| `telemetry_tool/traffic_detection.py` | New — straight detection, traffic flags, TrafficResult |
| `telemetry_tool/lap_inclusion.py` | New — LapInclusionPolicy, build_inclusion_policy() |
| `telemetry_tool/theoretical_engine.py` | Modified — masks parameter in envelope functions |
| `telemetry_tool/pipeline.py` | Modified — stage 9.5, filter laps at stage 10+13 |
| `telemetry_tool/reporting_html.py` | Modified — traffic badges + learning/display summary |
| `telemetry_tool/tests/test_traffic_detection.py` | New — 4 tests |
| `telemetry_tool/tests/test_lap_inclusion.py` | New — 4 tests |
| `telemetry_tool/tests/test_traffic_pipeline.py` | New — 2 integration tests |

No database migration needed — traffic and inclusion data lives in summary JSON.
