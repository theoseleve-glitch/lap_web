# Corner Timeline + MRP Detector + Event Extractor — Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` corner analysis pipeline

## Problem

1. **Fixed phase splitting** — Current corner analysis splits corners into fixed 20%/60%/20% entry/mid/exit zones. Real corners have physics-defined events (braking point, end-of-braking, max rotation, throttle-on) at variable positions.
2. **No rotation analysis** — No detection of the Max Rotation Point (MRP = peak yaw rate), which is the key skill marker for cornering technique.
3. **No mistake classification** — No systematic detection of technique errors like "power before rotation" or "late rotation".
4. **No event stability** — No tracking of whether a driver's braking point or rotation point is consistent lap-to-lap.

## Architecture

### 1. CornerEvent + CornerTimeline Dataclasses (`corner_analysis.py`)

```python
@dataclass
class CornerEvent:
    event_type: str           # "BP"|"EOB"|"MRP"|"MIN_SPEED"|"APEX"|"THROTTLE_ON"|"TRACK_OUT"
    s_position: float         # distance along lap [m]
    confidence: float         # 0-1 (channel quality + detection quality)
    source_channel: str       # which channel detected it ("accel_long"|"yaw_rate"|"speed"|"position")
    value: float              # the signal value at that point
    available: bool           # False if channel missing

    def to_dict(self) -> dict: ...

@dataclass
class CornerTimeline:
    corner_id: int
    events: list[CornerEvent]          # ordered by s_position
    segment_losses_s: dict[str, float] # "BP_EOB", "EOB_MRP", "MRP_THROTTLE_ON", "THROTTLE_ON_TRACK_OUT"
    segment_confidences: dict[str, float]
    mistakes: list[dict]               # [{"type": str, "severity": float, "evidence": dict}]
    mrp_strength: float                # peak prominence of yaw_rate
    mrp_stability_std_m: float         # lap-to-lap std-dev of MRP s-position
    event_stability: dict[str, float]  # std-dev per event type across laps

    def to_dict(self) -> dict: ...
```

### 2. Event Detection (`corner_analysis.py`)

New function `detect_corner_events()`:

```
detect_corner_events(
    corner: dict,
    lap_df: pd.DataFrame,
    theoretical_df: pd.DataFrame | None = None,
    data_quality: float = 1.0,
) -> CornerTimeline
```

For each corner `[s_start, s_end]` with `search_margin_m=50` before entry:

| Event | Primary Detection | Fallback | Skip Condition |
|-------|-------------------|----------|----------------|
| **BP** | `accel_long < -threshold` sustained 2+ samples, scanning backward from s_start | Always available (accel_long is derived) | Never |
| **EOB** | First point after BP where `accel_long > -threshold` with hysteresis (must stay above for `min_duration_m=5m`) | Same | Never |
| **MRP** | Peak `abs(yaw_rate)` within `[s_start, s_end]` with prominence > 0.5 deg/s | Approximate from `heading` derivative if yaw_rate absent; if neither, mark unavailable | No yaw_rate AND no heading |
| **MIN_SPEED** | `argmin(speed)` within corner | Always available | Never |
| **APEX** | Innermost lateral position relative to reference line | Skip if no XY position data | No position data |
| **THROTTLE_ON** | First point after min-speed where `accel_long > +traction_threshold` sustained with hysteresis (stay above for `min_duration_m=5m`) | Always available | Never |
| **TRACK_OUT** | Point where lateral position returns to track edge, or s_end as fallback | s_end if no position data | Never (uses s_end fallback) |

**Hysteresis parameters** (change-point detection):
- `bp_threshold_mps2 = -1.0`
- `eob_threshold_mps2 = -0.5` (less aggressive than BP to avoid re-triggering)
- `traction_threshold_mps2 = 0.5`
- `min_sustained_m = 5.0` (minimum distance the signal must stay past threshold)
- `min_event_separation_m = 3.0` (prevent duplicate events)

### 3. MRP Analysis + Mistake Detection (`corner_analysis.py`)

New function `detect_corner_mistakes()`:

```
detect_corner_mistakes(
    timeline: CornerTimeline,
    lap_df: pd.DataFrame,
    corner: dict,
) -> list[dict]
```

Mistake classifiers:

| Mistake | Condition | Severity Formula |
|---------|-----------|------------------|
| `no_clear_mrp` | MRP confidence < 0.3 or MRP unavailable | 0.5 (medium) |
| `mrp_plateau` | MRP prominence < 1.0 deg/s (flat yaw profile) | `1.0 - prominence` |
| `mrp_drift` | MRP stability std > 10m across laps | `min(1.0, std_m / 20.0)` |
| `mrp_after_apex` | MRP s_position > APEX s_position + 5m | `min(1.0, delta_m / 15.0)` |
| `power_before_rotation` | THROTTLE_ON s_position < MRP s_position AND yaw_rate at throttle_on > 50% of peak | `min(1.0, yaw_ratio * 0.8)` |
| `rotation_too_late` | MRP s_position > EOB s_position + 30% of corner length | `min(1.0, delta_pct / 0.5)` |

Each mistake returns:
```python
{
    "type": "power_before_rotation",
    "severity": 0.7,        # 0-1
    "evidence": {
        "throttle_on_s": 145.3,
        "mrp_s": 152.1,
        "yaw_at_throttle": 8.5,  # deg/s
        "peak_yaw": 12.3,        # deg/s
        "estimated_time_cost_s": 0.15,
    }
}
```

### 4. Segment Loss Attribution (`corner_analysis.py`)

New function `compute_segment_losses()`:

```
compute_segment_losses(
    timeline: CornerTimeline,
    driver_df: pd.DataFrame,
    theoretical_df: pd.DataFrame,
) -> dict[str, float]
```

For each segment pair (BP→EOB, EOB→MRP, MRP→ThrottleOn, ThrottleOn→TrackOut):
- Integrate time delta = Σ(1/v_actual - 1/v_theoretical) × ds
- Store per-segment with confidence based on channel availability

### 5. Multi-Lap Stability (`corner_analysis.py`)

New function `compute_event_stability()`:

```
compute_event_stability(
    corners: list[dict],
    all_lap_dfs: list[pd.DataFrame],
    data_quality: float = 1.0,
) -> dict[int, dict[str, float]]    # corner_id → {event_type → std_dev_m}
```

For each corner, detects events on every lap, computes std-dev of each event's s_position. Feeds `mrp_stability_std_m` and `event_stability` on CornerTimeline.

### 6. Confidence Gating

Confidence per event = `channel_confidence × detection_confidence × data_quality`

| Channel | Present | Absent |
|---------|---------|--------|
| `accel_long_mps2` | 1.0 | 0.0 (BP/EOB/ThrottleOn unavailable) |
| `yaw_rate_dps` | 1.0 | heading derivative → 0.6; neither → 0.0 |
| `speed_mps` | 1.0 | 0.0 (MIN_SPEED unavailable) |
| XY position | 1.0 | 0.0 (APEX/TRACK_OUT use fallback) |

`data_quality` comes from `DataQualityReport.overall_confidence`.

### 7. Pipeline Integration

**Stage 6**: No change — corner detection stays as-is.

**Stage 10c**: After existing `analyze_corners()`, call:
```python
# For best lap
timelines = [detect_corner_events(c, best_lap_df, theo, dq) for c in corners]
# Multi-lap stability
stability = compute_event_stability(corners, all_lap_dfs, dq)
# Merge stability into timelines
# Detect mistakes
for tl in timelines:
    tl.mistakes = detect_corner_mistakes(tl, best_lap_df, corner)
    tl.segment_losses_s = compute_segment_losses(tl, best_lap_df, theo)
```

Store in `summary["corner_timelines"]`.

**Stage 10d**: Per-lap timeline detection (reuse `detect_corner_events` per lap).

### 8. API Extensions

**`/corners`** endpoint gains per-corner:
```json
{
    "timeline": {
        "events": [...],
        "segment_losses_s": {...},
        "mistakes": [...],
        "mrp_strength": 8.5,
        "mrp_stability_std_m": 3.2,
        "event_stability": {...}
    }
}
```

Existing fields unchanged — `timeline` is additive.

### 9. Reporting

`_build_corner_table_html()` gains:
- "Events" column showing colored dots for each detected event on a mini s-axis SVG
- "Mistakes" column listing top mistake per corner with severity badge
- Existing columns unchanged

### 10. Improvement Ranking

`rank_improvement_opportunities()` updated to weight by:
- `time_loss_s` (existing, weight 0.6)
- `sum(mistake_severities)` (new, weight 0.2)
- `mrp_stability_std_m` (new, weight 0.1, inverted: unstable = higher priority)
- `segment_losses_s` max segment (new, weight 0.1)

### 11. Files Touched

| File | Change |
|------|--------|
| `telemetry_tool/corner_analysis.py` | `CornerEvent`, `CornerTimeline`, `detect_corner_events()`, `detect_corner_mistakes()`, `compute_segment_losses()`, `compute_event_stability()`, update `rank_improvement_opportunities()` |
| `telemetry_tool/pipeline.py` | Wire stage 10c timeline + mistakes + stability |
| `telemetry_tool/reporting_html.py` | Event dots SVG, mistakes column |
| `telemetry_tool/web/routes/data_v2.py` | Extend `/corners` with timeline data |
| `telemetry_tool/tests/test_corner_timeline.py` | 8 tests |

### 12. Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| No yaw_rate AND no heading | MRP unavailable, skip rotation mistakes |
| No XY position | APEX/TRACK_OUT use min-speed/s_end fallback |
| No accel_long | BP/EOB/ThrottleOn unavailable (shouldn't happen — always derived) |
| < 3 laps | Stability metrics skipped |
| data_quality < 0.3 | All confidence scores halved |

### 13. Tests

1. **Synthetic braking signal** — Ramp-down accel → correct BP/EOB positions
2. **Synthetic yaw peak** — Single clean peak → correct MRP with high confidence
3. **Noisy yaw** — Gaussian noise on yaw → MRP still detected, lower confidence
4. **Multiple yaw peaks** — Two peaks in corner → selects dominant (highest prominence)
5. **Missing yaw channel** — No yaw_rate column → MRP marked unavailable, no crash
6. **Power before rotation** — ThrottleOn before MRP → mistake detected
7. **Event stability** — 5 laps with varying BP → std-dev computed correctly
8. **Segment losses** — Known speed profiles → correct per-segment time attribution
