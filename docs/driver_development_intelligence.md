# Driver Development Intelligence

> Multi-session progression engine. Answers: what are this driver's recurring patterns, what's improving, and what's the highest-value next focus?

## Purpose

Session Compare Studio answers "what happened this lap." Development Intelligence answers "what keeps happening across laps and sessions." It is the difference between reviewing one test and understanding a driver's development arc.

## What it produces

1. **Recurring weakness profile** — behavioral patterns that cost time repeatedly (e.g., "late throttle pickup on slow-corner exits across 4 sessions").
2. **Recurring strength profile** — areas where execution is consistently strong (e.g., "strong braking consistency in medium-speed corners").
3. **Priority training focuses** — ranked by `time_cost x recurrence x confidence x trainability`, capped at 3.
4. **Session-to-session trends** — improving, flat, regressing, unstable, or insufficient evidence per behavior.
5. **Development storyline** — rule-based narrative statements backed by specific evidence.
6. **Overall direction** — improving / consolidating / flat / regressing / insufficient_data.

## How it works

### Input: all-laps analysis

The build pipeline runs the Session Compare engine on every lap (not just best and median) against the session-best reference. This produces ~9 corner packets per lap x 43 laps = ~387 CornerFeatures, each with brake point, min speed, throttle pickup, exit speed, line deviation, and time delta.

### Corner archetypes

Each corner is classified by minimum speed and peak curvature:

| Archetype | Min speed | Peak curvature |
|---|---|---|
| `slow_hairpin` | < 35 kph | > 0.06 1/m |
| `slow_90deg` | 35–45 kph | — |
| `medium_speed` | 45–60 kph | — |
| `fast_corner` | > 60 kph | — |

This classification enables cross-corner pattern detection: if "late throttle pickup" appears on three different slow_90deg corners, it's a driver habit rather than a corner-specific issue.

### Behavioral pattern detection

Seven behaviors are defined with explicit detection tests:

| Behavior | Detection rule | Trainable? |
|---|---|---|
| `late_throttle_pickup` | throttle_pickup_delta > 5 m | Yes (0.9) |
| `early_braking` | brake_point_delta < -5 m | Yes (0.85) |
| `low_minimum_speed` | min_speed_delta < -3 kph | Yes (0.8) |
| `weak_exit_build` | exit_speed_delta < -3 kph | Yes (0.85) |
| `line_deviation` | line_deviation_rms > 0.8 m | Yes (0.7) |
| `strong_braking` | \|brake_delta\| < 3 m AND time_delta < 50 ms | No (strength) |
| `strong_exit` | exit_speed_delta > 2 kph | No (strength) |

A behavior is "recurring" when it appears in ≥ 3 corner features across the dataset.

### Trend computation

For each behavior, per-session median of the defining metric is computed. A linear regression over session index gives a slope:
- slope < -0.5/session (metric getting better) → `improving`
- slope > 0.5/session (metric getting worse) → `regressing`
- std < 1.0 → `flat`
- else → `unstable`
- < 3 session points → `insufficient`

### Priority ranking

`priority = time_cost_s x recurrence_rate x confidence x trainability`

Where `trainability` reflects whether the pattern is realistically improvable by technique (not setup/car). Weaknesses only — strengths don't become training focuses.

### Storyline generation

Rule-based, not generative. Each statement cites specific numbers:
- Best-lap trend across sessions
- Consistency trend (lap-time std)
- Improving behaviors
- Flat/stagnating behaviors
- Top priority with cost estimate
- Evidence warnings when data is sparse

## Sparse-data behavior

| Condition | Behavior |
|---|---|
| 0 laps | Returns empty structure with `insufficient_data` |
| 1–2 laps | Returns with low confidence, no patterns (need ≥ 3 features) |
| 1 session | Patterns detected but trends are `insufficient` |
| 2 sessions | Trends are `insufficient` (need ≥ 3 session points) |
| 3+ sessions | Full analysis with trend detection |
| 1 track only | Portability tagged `unknown (single track dataset)` |

## Portability

With data from multiple corner archetypes, a behavior appearing across ≥ 3 archetypes is tentatively tagged `likely_portable`. With only one track dataset (current state), all behaviors are tagged `unknown (single track dataset)`.

## Known limits

1. **Single track.** All 5 sessions are at Ouest Karting on the same day. Cross-track portability cannot be validated.
2. **No weather/condition metadata.** Cannot separate condition effects from driver effects.
3. **Reference is session-best, not absolute.** A slow session where the driver executes well won't be misclassified as regression (this is correct behavior), but absolute pace claims are limited.
4. **Archetype classification is speed-based.** Without steering data, "chicane" and "direction change" archetypes cannot be reliably identified; the classifier falls back to speed categories.
5. **43 laps / 5 sessions.** Enough for initial pattern detection but borderline for robust trend analysis. More sessions would tighten confidence.

## JSON schema

Under `data.development_intelligence`:

```json
{
  "version": "1.0",
  "sessions_analyzed": 5,
  "laps_analyzed": 43,
  "track_name": "Ouest Karting",
  "analysis_confidence": 0.99,
  "overall_direction": "improving",
  "session_summaries": [{ session_id, n_laps, best_lap_time_s, median_lap_time_s, lap_time_std_s }],
  "recurring_weaknesses": [{
    "behavior_id": "weak_exit_build",
    "label": "Weak exit speed build",
    "occurrence_count": 284,
    "total_laps": 43,
    "sessions_observed": ["OK_FP+Q", "OK_R1", ...],
    "corners_observed": [1, 2, ...],
    "archetypes_observed": ["slow_90deg", "medium_speed"],
    "estimated_time_cost_ms": 407.7,
    "trend": "improving",
    "confidence": 0.72,
    "portability": "unknown (single track dataset)",
    "explanation": "..."
  }],
  "recurring_strengths": [{ same structure }],
  "priority_focuses": [{
    "rank": 1,
    "label": "Weak exit speed build",
    "priority_score": 2.289,
    "time_cost_ms": 407.7,
    "recurrence_rate": 6.60,
    "confidence": 0.72,
    "why_it_matters": "Costs ~408 ms each time...",
    "where_it_shows": "T1, T2, T3, T4, T5",
    "success_next_session": "Reduce occurrences from 284 to <281 laps. Target: reduce median cost by >82 ms."
  }],
  "storyline": [{ "type": "direction", "text": "...", "confidence": 0.9 }]
}
```
