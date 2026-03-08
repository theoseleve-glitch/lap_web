# Coaching V2 — Evidence-Based Coaching Generator Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` coaching pipeline — structured, confidence-gated, stability-filtered coaching

## Problem

1. **Template-based coaching** — Current coaching uses 8 fixed text templates mapped by `(limiting_factor, corner_priority)`. No evidence fields, no confidence gating, no stability filtering.
2. **No confirming feedback** — Reports feel like endless criticism. No "what you did well" section.
3. **Oscillating advice** — Noise in lap data can cause contradictory recommendations.
4. **No confidence gating** — Low-confidence features (missing yaw_rate, few samples) still emit coaching text.
5. **No measurable objectives** — Advice is qualitative ("brake later") not quantitative ("brake 3m later into C4, target -0.05s gain").

## Architecture

### Data Structures

```python
@dataclass
class CoachingEvidence:
    delta_time_s: float        # estimated time impact
    s_offset_m: float          # distance position of the event
    metric_values: dict        # {"peak_decel": -8.2, "entry_speed_kmh": 95.3}
    source_events: list[str]   # ["BP", "EOB", "MRP"]
    confidence: float          # evidence-level confidence

@dataclass
class CoachingItem:
    corner_id: int
    category: str              # "confirming" | "corrective"
    text: str                  # human-readable
    evidence: CoachingEvidence
    confidence: float          # 0-1
    stability_score: float     # 0-1
    reason_code: str           # "" if available, else "no_yaw_channel" etc.

@dataclass
class CoachingObjective:
    rank: int                  # 1-3
    text: str                  # "Brake 3m later into C4"
    event_target: str          # "BP" | "EOB" | "MRP" | "THROTTLE_ON"
    change_direction: str      # "later" | "earlier" | "more" | "less"
    measurable_metric: str     # "braking_point_delta_m"
    target_value: float        # -3.0
    current_value: float       # 0.0
    evidence: CoachingEvidence

@dataclass
class CoachingV2:
    confirmations: list[CoachingItem]
    corrections: list[CoachingItem]
    objectives: list[CoachingObjective]
    ratio_target: float        # confirming:corrective target (default 2.0)
    actual_ratio: float        # achieved ratio
    suppressed_count: int      # items suppressed due to noise/confidence
```

## Confirming Feedback

Scan corner performances for corners where:
- `time_loss_s < 0.05` (within 50ms of theoretical)
- `grip_utilisation_pct > 85%`
- Brake release linearity R² > 0.8 (if available)
- No mistakes detected in timeline

Each generates a `CoachingItem(category="confirming")` with evidence.

**Ratio enforcement**: If `len(confirmations) / max(len(corrections), 1) < ratio_target`, promote borderline corners (loss < 0.1s, grip > 75%) until ratio met or candidates exhausted.

## Corrections (Max 1 Per Corner)

For each corner with `time_loss_s > 0.1`, select the single highest-impact correction from:
- Timeline mistakes (power_before_rotation, rotation_too_late, mrp_plateau)
- Brake release issues (over_drop, late_release)
- Coupling issues (under_rotation, over_rotation)
- Event position deltas (BP/EOB too early/late vs theoretical)

Priority: highest `abs(delta_time_s) * confidence`.

## Confidence Gating

| Feature | Min Confidence | Gate Condition |
|---------|---------------|----------------|
| BP/EOB events | 0.5 | Always available (accel always derived) |
| MRP | 0.6 | No yaw_rate AND no heading → unavailable |
| Brake release | 0.4 | < 3 brake zone samples → unavailable |
| Brake-yaw coupling | 0.6 | No yaw AND no brake channel → unavailable |
| Corner targets | 0.5 | No theoretical result → unavailable |

Below threshold → `reason_code` set (e.g. `"no_yaw_channel"`, `"insufficient_samples"`), no actionable text, UI shows "unavailable: {reason}".

## Stability Filtering

For each potential correction, compute `stability_score`:
- Event-position corrections: `stability_score = 1.0 - min(1.0, event_std_m / 15.0)`
- Metric-based corrections: `stability_score = 1.0 - min(1.0, coefficient_of_variation)`

**Thresholds**:
- `stability_score >= 0.5` required
- `abs(delta_time_s) >= 0.03` (30ms minimum time impact)

Below either → suppressed, `suppressed_count` incremented.

## Top 3 Objectives

From all non-suppressed corrections, rank by `abs(delta_time_s) * stability_score * confidence`, take top 3. Hard cap at 3.

Each objective includes:
- `event_target`: which event to change
- `change_direction`: "later"/"earlier"/"more"/"less"
- `measurable_metric`: field to track improvement
- `target_value` + `current_value`: concrete numbers

## Pipeline Integration

New step `13c_coaching_v2` after existing `13b_coaching_guide`:

```python
def _coaching_v2():
    return generate_coaching_v2(
        corner_performances=corner_performances,
        corner_timelines=corner_timelines,
        corners=corners,
        event_stability=summary.get("event_stability"),
        data_quality=dq_score,
        driver_style=summary.get("driver_style"),
        ratio_target=2.0,
    )

cv2_result, err = _safe_step("13c_coaching_v2", _coaching_v2)
summary["coaching_v2"] = cv2_result
```

## API Extensions

**`GET /api/v1/sessions/<id>/detail`** gains:
```json
{
    "coaching_v2": {
        "confirmations": [...],
        "corrections": [...],
        "objectives": [...],
        "ratio_target": 2.0,
        "actual_ratio": 2.5,
        "suppressed_count": 3
    }
}
```

Legacy `coaching_hint`, `coaching_text`, `coaching_guide` fields unchanged.

## HTML Report

New "Coaching Summary" section after corner table:
- Green badges for confirmations ("C3: Great apex speed — within 2 km/h of theoretical")
- Orange cards for corrections ("C7: Brake 3m later — estimated gain 0.08s")
- Numbered objectives checklist ("1. Delay BP into C4 by 3m (current: +0m, target: -3m)")
- "Unavailable" grey badges for gated features

## Persistence

Store as JSON in `summary["coaching_v2"]`. The existing `analysis_json` column in the `sessions` table already stores the full summary, so no new migration needed.

## Files Touched

| File | Changes |
|------|---------|
| `corner_analysis.py` | `CoachingV2`, `CoachingItem`, `CoachingEvidence`, `CoachingObjective` dataclasses, `generate_coaching_v2()`, confidence threshold constants |
| `pipeline.py` | Wire step 13c_coaching_v2 |
| `reporting_html.py` | New coaching summary section |
| `web/routes/data_v2.py` | Extend session detail/corners with `coaching_v2` |
| `tests/test_coaching_v2.py` | 8 tests |

## Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| No corner_timelines | Skip corrections, confirmations only from time_loss |
| No theoretical result | Skip objectives, corrections from timeline only |
| < 3 laps | Stability scores = 0 (all suppressed except high-confidence items) |
| No yaw_rate AND no heading | MRP-based corrections unavailable with reason_code |
| data_quality < 0.3 | All confidence scores halved |
| distance_quality gate | Entire coaching_v2 skipped |
| No corner_performances | Return empty CoachingV2 |

## Tests

1. **Confirming feedback**: Corner with loss < 0.05s → appears in confirmations with evidence
2. **Corrective feedback**: Corner with loss > 0.1s + mistake → correction with evidence
3. **Max 1 correction per corner**: Corner with 2 mistakes → only highest-impact emitted
4. **Confidence gating**: No yaw_rate → MRP correction unavailable with reason_code
5. **Stability filtering**: High event_std → correction suppressed
6. **Minimum time threshold**: delta_time < 30ms → suppressed
7. **Ratio enforcement**: More corrections than confirmations → borderline corners promoted
8. **Objectives**: Top 3 selected by impact * stability * confidence
9. **Snapshot determinism**: Fixed inputs → byte-stable JSON with `deterministic=True`
