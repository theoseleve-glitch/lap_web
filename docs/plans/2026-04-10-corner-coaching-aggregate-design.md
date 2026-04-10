# Per-Corner Aggregate Coaching — Design Spec

**Date**: 2026-04-10
**Status**: Approved
**Depends on**: Track surface system (migration 047, track_surface.py, step 09j pipeline wiring)

## Goal

For each detected corner, compare the driver's performance to the track's proven physical limits (aggregated from all sessions) and generate natural language coaching narratives explaining what to change and why.

## Architecture

A new backend module `corner_coaching_aggregate.py` runs after corner detection and grip map computation. For each corner it:

1. Pulls aggregate track surface mu_p95(d) for the corner's distance range
2. Computes proven limits (entry/apex/exit speed, brake point) from the aggregate
3. Compares the current session's corner performance to those limits
4. Classifies the root cause of any delta
5. Generates a template-based natural language coaching narrative

## Data Flow

```
Corner detection (s10b) → corner boundaries [s_start, s_apex, s_end]
Aggregate track surface → mu_p95(d) for each corner range
Session speed trace → actual entry/apex/exit speeds
Handling events → understeer/oversteer at corner
      ↓
Delta classification → what's wrong and why
      ↓
Narrative generator → "You're losing 0.3s in T4 because..."
```

## Corner Metrics

Per corner, computed from the aggregate track surface and session data:

| Metric | Source | Method |
|--------|--------|--------|
| `proven_entry_kph` | track_surfaces | p95 speed at `s_start` across all sessions |
| `proven_apex_kph` | track_surfaces | p95 speed at `s_apex` |
| `proven_exit_kph` | track_surfaces | p95 speed at `s_end` |
| `proven_brake_point_m` | track_surfaces | distance where decel first exceeds 0.3g threshold before corner |
| `actual_entry_kph` | session speed trace | speed at `s_start` for this lap |
| `actual_apex_kph` | session speed trace | speed at `s_apex` |
| `actual_exit_kph` | session speed trace | speed at `s_end` |
| `actual_brake_point_m` | session speed trace | same 0.3g threshold detection |
| `time_loss_s` | speed delta integral | `∫(1/v_actual - 1/v_proven) ds` over corner range |

Proven speeds are derived from aggregate grip: `v_proven = sqrt(mu_p95 * g / kappa)` at the relevant distance, cross-checked against the p95 of actual observed speeds in that distance bin.

## Root Cause Classification

For each corner where `time_loss_s > 0.05s`:

| Pattern | Detection | Key |
|---------|-----------|-----|
| Late/early braking | `abs(brake_point_delta) > 3m` | `early_brake` / `late_brake` |
| Apex speed deficit | `apex_delta > 2kph`, entry OK | `apex_deficit` |
| Early throttle lift | throttle drops before apex, speed drops mid-corner | `early_lift` |
| Entry too hot | entry speed > proven AND understeer/oversteer event | `entry_too_hot` |
| Exit under-application | exit deficit, no handling event, grip headroom > 10% | `exit_under_application` |
| Consistency gap | CV of apex speed across laps > 5% | `consistency_gap` |

Multiple causes can co-exist per corner. The narrative addresses the primary cause (highest time contribution) first.

## Narrative Generation

Template-based with physics values. Not LLM-generated. Each corner gets 2-3 sentences.

### Templates

**early_brake**:
> You're braking {brake_delta_m:.0f}m too early for {corner_name}. The track supports {proven_apex_kph:.0f}kph at the apex across {n_sessions} sessions — you have margin to brake at the {proven_brake_m:.0f}m mark instead of {actual_brake_m:.0f}m. This costs {time_loss_s:.2f}s per lap.

**apex_deficit**:
> Your entry speed is right at {actual_entry_kph:.0f}kph, but you're scrubbing {apex_delta:.0f}kph at the {corner_name} apex. The track supports {proven_apex_kph:.0f}kph here. {cause_detail}. Hold more speed through the mid-corner — the grip is there.

Where `cause_detail` is one of:
- "You're lifting throttle {lift_dist:.0f}m before the apex" (if early_lift co-detected)
- "Your steering input shows you're running a wider line than needed" (if line deviation detected)
- "Trail-brake deeper into the corner to maintain speed" (default)

**early_lift**:
> You're lifting throttle {lift_dist_m:.0f}m before the {corner_name} apex, causing a {speed_drop:.0f}kph scrub. The aggregate shows drivers carrying throttle to within {proven_lift_dist:.0f}m of the apex. Hold throttle {time_delta:.1f}s longer through the turn-in.

**entry_too_hot**:
> You're carrying {entry_excess:.0f}kph too much into {corner_name}, which triggered {event_type} at the apex. The proven entry is {proven_entry_kph:.0f}kph — fast enough to set up a {proven_apex_kph:.0f}kph apex without losing the rear. Scrub {entry_excess:.0f}kph on approach.

**exit_under_application**:
> You have {headroom_pct:.0f}% grip headroom at the {corner_name} exit but only reaching {actual_exit_kph:.0f}kph vs the {proven_exit_kph:.0f}kph the track supports. Get on throttle {earlier_m:.0f}m earlier — the surface can take it.

**consistency_gap**:
> {corner_name} is your biggest consistency issue: your best lap hits {best_apex_kph:.0f}kph at the apex, but {n_bad}/{n_total} laps drop to {worst_apex_kph:.0f}kph. This variance costs {avg_time_loss:.2f}s on average. Focus on repeating your best approach.

## API Endpoint

```
GET /api/v1/sessions/{id}/corner-coaching-v4?lap=N
```

Response:
```json
{
  "corners": [
    {
      "corner_id": 4,
      "corner_name": "T4",
      "direction": "R",
      "radius_m": 85.2,
      "time_loss_s": 0.31,
      "proven": {
        "entry_kph": 105.2,
        "apex_kph": 78.1,
        "exit_kph": 92.4,
        "brake_point_m": 234.0
      },
      "actual": {
        "entry_kph": 105.0,
        "apex_kph": 72.3,
        "exit_kph": 88.1,
        "brake_point_m": 229.0
      },
      "root_causes": ["early_brake", "apex_deficit"],
      "narrative": "You're braking 5m too early for T4. The track supports 78kph at the apex across 12 sessions...",
      "aggregate_sessions": 12,
      "grip_headroom_pct": 8.1
    }
  ],
  "summary": {
    "total_time_loss_s": 1.42,
    "top_3_corners": [4, 7, 1],
    "aggregate_sessions": 12,
    "narrative": "You're leaving 1.42s on the table across 8 corners. Focus on T4 (0.31s), T7 (0.28s), and T1 (0.24s) — these three account for 58% of your total loss."
  }
}
```

## Backend Module

New file: `telemetry_tool/corner_coaching_aggregate.py`

Functions:
- `compute_proven_limits(aggregate_grip, corners, speed_trace_data)` — for each corner, compute proven entry/apex/exit/brake from aggregate surface
- `compute_actual_metrics(speed_trace, accel_trace, corners, lap)` — extract actual speeds and brake points for a specific lap
- `classify_root_cause(proven, actual, handling_events)` — returns list of cause keys
- `generate_narrative(corner_name, direction, proven, actual, causes, n_sessions)` — template-based string
- `compute_corner_coaching_v4(conn, track_id, analysis_json, corners, lap)` — orchestrator: ties everything together, returns full response dict

## Pipeline Integration

Two options:
1. **Compute on-demand** in the API endpoint (like physics-ceiling) — simpler, no pipeline change
2. **Compute in pipeline** and store in analysis_json — faster API response

**Decision**: Option 1 (on-demand). The computation is lightweight (iterate corners, interpolate aggregate grip, format text). No need to add pipeline complexity. The aggregate data is already in PG and fast to read.

## Frontend

Extend or sit alongside existing `CornerCoachingTable.tsx`. Per corner row:
- Corner name badge (direction + number) in `font-monument`
- Time loss in `text-safety-red` with `font-telemetry`
- Proven vs actual: small inline comparison (entry → apex → exit)
- Narrative text in `text-chalk font-body`
- Aggregate sessions count badge in `text-steel bg-steel/10`
- Summary card at top with total time loss and top-3 priority corners

## File Manifest

| File | Action |
|------|--------|
| `telemetry_tool/corner_coaching_aggregate.py` | Create: coaching computation module |
| `telemetry_tool/web/routes/data_v2.py` | Modify: add /corner-coaching-v4 endpoint |
| `telemetry_tool/tests/test_corner_coaching_aggregate.py` | Create: tests for classification + narrative |
| `lap-website/src/components/shared/charts/CornerCoachingV4.tsx` | Create: aggregate coaching UI component |
| `lap-website/src/app/app/sessions/[id]/page.tsx` or analytics tab | Modify: wire in CornerCoachingV4 component |

## Out of Scope
- Racing line optimization (sub-project #2)
- Setup recommendations
- Weather-adjusted coaching
- Cross-driver comparison
- LLM-generated narratives (templates are deterministic and debuggable)
