# Corner Diagnosis Redesign

**Date**: 2026-03-12
**Status**: Draft
**Scope**: New lightweight per-lap corner classifier + rewire V3 deep coaching to user corners

## Problem

Two disconnected coaching paths exist in the pipeline:

- **V2 path** (S10g): Uses user-selected corners from `user_corners` table, but only basic MRP/handling analysis.
- **V3 path** (S13e): Rich 6-analyzer physics engine (trail brake, traction budget, exit cascade, weight transfer) but uses auto-detected corners from step 06b and only the best lap.

Neither produces what we need: a per-lap diagnosis grid across all valid laps for user-selected corners, plus a deep coaching report for the best lap.

## Solution

One unified coaching path producing two outputs:

1. **`corner_labels`** — flat grid `{lap_number: {corner_id: label}}` for ALL valid laps x user-selected corners. One dominant label per cell. Lightweight numpy classifier with threshold comparisons.
2. **`coaching_v3`** — deep report for BEST LAP only, using existing V3 analyzers rewired to user-selected corners.

```
                         user_corners (from DB)
                                |
              +-----------------+-----------------+
              |                 |                  |
         all valid laps    best lap only     theoretical lap
              |                 |                  |
     +--------v--------+  +----v----------+       |
     | Lightweight      |  | Deep V3       |       |
     | Classifier       |  | Analyzers     |<------+
     | (numpy, per-lap) |  | (per-corner)  |
     +--------+--------+  +----+----------+
              |                 |
              v                 v
     corner_labels grid    coaching_v3 report
     {lap: {cid: label}}   (trail brake, traction
                            budget, exit cascade,
                            weight transfer, drills)
```

## Output Shapes

### Output A: `analysis_json["corner_labels"]`

```json
{
  "2": {"1": "entry_overspeed", "3": "good", "5": "late_throttle"},
  "3": {"1": "entry_understeer", "3": "exit_oversteer", "5": "good"},
  "5": {"1": "good", "3": "coast_hesitation", "5": "early_apex"}
}
```

Keys are lap numbers (strings), values are `{corner_id: label}`. One dominant label per cell. `null` when data insufficient.

### Output B: `analysis_json["coaching_v3"]`

Existing `SessionCoaching` model structure, unchanged. Now sourced from user corners instead of auto-detected corners.

## Label Taxonomy (23 labels)

### Entry Phase (s_entry -> s_apex) - 8 labels

| Label | Meaning | GPS-only | +Accel | +Pedals |
|-------|---------|----------|--------|---------|
| `entry_overspeed` | Too fast into corner | v_entry - v_theo > 3 km/h | same | same |
| `entry_underspeed` | Over-slowed on entry | v_theo - v_entry > 5 km/h | same | same |
| `late_braking` | Brake zone too deep | -- | lon_g < -0.3g past s_apex | brake% > 20 past s_apex |
| `early_braking` | Brake too early | -- | lon_g < -0.3g starts >15m before theoretical decel onset | brake% > 10 starts >15m before theoretical decel onset |
| `entry_understeer` | Front not gripping on turn-in | yaw_residual < -10 dps sustained 5+ samples | lat_g dropping while curvature increasing | same + brake < 5% |
| `entry_oversteer` | Rear slides on entry | yaw_residual > +10 dps sustained 5+ samples | lat_g spike + lon_g jerk | same + snap brake release |
| `insufficient_trail_brake` | Off brakes before turn-in | -- | -- | brake to 0 before turn-in or first 10% of corner |
| `excessive_trail_brake` | Still heavy braking at apex | -- | lon_g < -0.2g at s_apex | brake% > 30 at s_apex |

### Apex / Mid-Corner Phase (s_apex +/- 15%) - 6 labels

| Label | Meaning | GPS-only | +Accel | +Pedals |
|-------|---------|----------|--------|---------|
| `low_min_speed` | Apex speed below theoretical | v_theo_min - v_min > 4 km/h | same | same |
| `early_apex` | Min-speed point before user apex | s_vmin < s_apex - 5m | same | same |
| `late_apex` | Min-speed point after user apex | s_vmin > s_apex + 5m | same | same |
| `mid_corner_understeer` | Front washing out mid-corner | yaw_residual < -10 dps in apex zone | lat_g plateau while speed > v_min | same + throttle present |
| `mid_corner_oversteer` | Rear breaks loose mid-corner | yaw_residual > +10 dps in apex zone | lat_g spike > 1.1x zone mean | same |
| `coast_hesitation` | Dead zone, no input | smoothed speed derivative (3-pt Gaussian) in [-0.5, +0.5] m/s^2 for >coast_gap between decel and accel phases | abs(lon_g) < 0.05g for >coast_gap between decel and accel | brake < 5% AND throttle < 10% for >coast_gap |

### Exit Phase (s_apex -> s_exit) - 6 labels

| Label | Meaning | GPS-only | +Accel | +Pedals |
|-------|---------|----------|--------|---------|
| `exit_understeer` | Front washing wide on power | yaw_residual < -8 dps post-apex | lat_g dropping faster than speed rising | same + throttle > 60% |
| `exit_oversteer` | Power oversteer / snap | yaw_residual > +10 dps post-apex | lat_g spike + speed drop | same + throttle lift follows |
| `early_throttle` | On power before rotation done | -- | -- | throttle > 50% before MRP + 2m (falls back to v_min when MRP unavailable) |
| `late_rotation` | Peak rotation much later than intended apex | mrp_apex_delta_m > 8m (car) / 4m (kart) | same | same |
| `late_throttle` | Hesitating on power | -- | -- | s_throttle - s_apex > 0.4 * (s_exit - s_apex) |
| `throttle_lift` | Forced to lift after initial application | -- | -- | throttle drops >20% abs before s_exit |

### Overall - 3 labels

| Label | Meaning | Detection |
|-------|---------|-----------|
| `good` | Within tolerance | All delta-v < threshold AND no yaw anomaly AND corner time within 0.15s |
| `slow_exit` | Exit deficit, no deeper cause | v_theo_exit - v_exit > 5 km/h AND no entry/apex cause |
| `scrappy` | Multiple corrections | >2 yaw sign-reversals OR >2 throttle modulations |

## Yaw Residual Detection

The core insight enabling GPS-only diagnosis: **yaw residual = yaw_measured - yaw_expected**, where `yaw_expected = v * kappa * (180/pi)`.

- `yaw_measured` derived from `d(Bearing)/dt` with 0/360 wrap handling (already implemented in `derived_channels.py:compute_yaw_rate_from_heading`)
- `kappa` (curvature) derived from GPS XY via Frenet-Serret formula (already implemented in `derived_channels.py` and `reference_line.py`). Note: `kappa` is **signed** — positive for left turns, negative for right turns.
- Sign-reversals in residual = **countersteer events**

This works on any logger that has GPS coordinates and bearing/heading.

### Direction-normalised residual

Raw `yaw_residual = yaw_measured - yaw_expected` is direction-dependent: in a left turn (kappa > 0), oversteer produces a positive residual; in a right turn (kappa < 0), oversteer produces a negative residual.

To make thresholds work uniformly regardless of corner direction, we **normalise** by the sign of curvature:

```python
yaw_residual_norm = (yaw_measured - yaw_expected) * sign(kappa)
```

After normalisation:
- **Positive** `yaw_residual_norm` = **oversteer** (car rotating more than geometry demands) — regardless of left/right turn
- **Negative** `yaw_residual_norm` = **understeer** (car not rotating enough) — regardless of left/right turn

All threshold comparisons in the label tables use `yaw_residual_norm`, not raw residual. This is consistent with the approach already used in `kart_envelope/coaching/driver_diagnostics.py` (line 299-324) where `yaw_expected = v * kappa * (180/pi)` and residual sign is interpreted relative to expected.

### Source priority for yaw_rate_dps

1. Direct sensor: `"Yaw rate (deg/s)"` from RaceChrono IMU
2. Derived: `d(Bearing)/dt` with Gaussian smoothing + speed gate (zeroed < 2 m/s)
3. Bearing from GPS — virtually all loggers (RaceChrono, RaceBox) output this

## MRP Integration

The Maximum Rotation Point (MRP) — the position of peak yaw rate in a corner — is already computed at S10g2 via `mrp_detector.py` and stored in `summary["mrp_events_v2"]`. Currently `CornerEvents` is a plain `@dataclass` with **no `to_dict()` method**, and `run_mrp_detection_v2()` in s10b_corners.py line 688 uses `ev.to_dict() if hasattr(ev, 'to_dict') else ev` — which falls through to the raw dataclass instance. **Prerequisite**: add a `to_dict()` method to the `CornerEvents` dataclass in `mrp_detector.py` (using `dataclasses.asdict` or a manual method). This ensures `summary["mrp_events_v2"]` values are plain dicts, and the classifier accesses MRP data via dict key access (e.g. `mrp_event["mrp_m"]`, `mrp_event["mrp_apex_delta_m"]`).

The classifier uses MRP data for two purposes:

1. **`early_throttle` reference**: `coaching_advanced.py` already uses MRP (not v_min) as the throttle timing reference. The classifier mirrors this: throttle > 50% before `mrp_event["mrp_m"] + 2m` triggers `early_throttle`. Falls back to v_min when MRP is unavailable.
2. **`late_rotation` label**: When `mrp_event["mrp_apex_delta_m"]` (= mrp_m - geometric_apex_m) exceeds 8m (car) or 4m (kart), the driver's peak rotation is significantly late. This is a GPS-tier label (yaw rate is derived from heading). Cannot fire when `mrp_events` is None.

### MRP key mapping: user corners → MRP events

MRP events are keyed by `section_id` from `_user_corners_to_sections()` (s10b_corners.py line 606), which assigns `section_id = i + 1` (1-based, in insertion order). The `user_corner_rows` from `_fetch_user_corners()` are sorted by `corner_index` ascending. The mapping is therefore **positional**: sort user corners by `corner_index`, sort MRP dict keys numerically, and zip them together. If the counts don't match (e.g. MRP detection skipped a corner due to insufficient data), fall back to a spatial match: find the MRP event whose `[s_start, s_end]` range overlaps with the user corner's `[s_entry, s_exit]`. If neither positional nor spatial matching produces a hit, MRP features are silently skipped for that corner.

### Coupled failure mode

`summary["mrp_events_v2"]` is only set when `v2_sections` is truthy (orchestrator lines 969-979). When `v2_sections` is empty (track decomposition returned nothing), MRP data is absent AND user corners are likely also absent (the same `_user_corners_to_sections()` feeds both). The classifier handles both cases identically: `mrp_events=None` → MRP-dependent labels (`late_rotation`, MRP-based `early_throttle`) cannot fire; `user_corner_rows=None` → `corner_labels = None` and the pipeline skips the grid entirely.

## Detection Tiers

The classifier auto-detects available channels and adjusts:

| Tier | Available Channels | Detectable Labels |
|------|-------------------|-------------------|
| `gps` | Speed, Bearing -> yaw_rate, lat/lon -> curvature | `entry_overspeed`, `entry_underspeed`, `entry_understeer`, `entry_oversteer`, `low_min_speed`, `early_apex`, `late_apex`, `mid_corner_understeer`, `mid_corner_oversteer`, `coast_hesitation`, `late_rotation` (if MRP), `good`, `slow_exit`, `scrappy`. Note: exit-phase yaw labels (`exit_understeer`, `exit_oversteer`) excluded — GPS bearing too noisy post-apex under power |
| `accel` | Above + lat_g, lon_g | All above + friction circle, combined G, braking from lon_g |
| `full` | Above + brake %, throttle % | All 23 labels |

Tier detection:
```python
tier = "full"  if has_brake_or_throttle else
       "accel" if has_lat_or_lon_g else
       "gps"
```

## Causal Chain Resolution

When multiple labels apply, report the root cause, not the symptom:

```
entry_overspeed -> entry_understeer -> early_apex -> slow_exit -> throttle_lift
entry_overspeed -> mid_corner_understeer -> slow_exit
late_braking -> excessive_trail_brake -> entry_oversteer
insufficient_trail_brake -> entry_understeer
early_throttle -> exit_understeer OR exit_oversteer
late_rotation -> slow_exit (rotation delay costs exit speed)
early_apex -> slow_exit (always)
coast_hesitation -> late_throttle -> slow_exit
```

Priority when no causal link:
1. Safety signals: `exit_oversteer`, `entry_oversteer` (spin risk)
2. Biggest time-loss phase: compare delta-t per phase
3. `scrappy` if multiple small issues
4. `good` if all within tolerance

## Vehicle Class Thresholds

| Parameter | Kart | Car |
|-----------|------|-----|
| v_entry delta | 2 km/h | 3 km/h |
| v_min delta | 2 km/h | 3 km/h |
| v_exit delta | 3 km/h | 5 km/h |
| Coast gap | 0.2s | 0.3s |
| Yaw residual threshold | 8 dps | 10 dps |
| "good" time tolerance | 0.10s | 0.15s |
| late_rotation delta | 4m | 8m |

## Classifier Architecture

### New file: `telemetry_tool/coaching/corner_diagnosis.py` (~300 lines)

Named `corner_diagnosis.py` (not `corner_classifier.py`) to avoid confusion with the existing `telemetry_tool/corner_classifier.py` which classifies corner **geometry types** (hairpin, fast_sweeper, chicane). This module classifies corner **driving symptoms** per lap.

Single public function:

```python
def classify_all_corners(
    resampled_laps: dict[int, pd.DataFrame],
    theoretical_lap: pd.DataFrame | None,
    user_corners: list[dict],
    vehicle_class: str,
    valid_lap_numbers: list[int],
    curvature_profile: pd.DataFrame | None = None,
    mrp_events: dict[int, dict] | None = None,
) -> dict[str, dict[str, str]]:
    """Returns {lap_num: {corner_id: label}} for all valid laps x user corners.

    curvature_profile: pd.DataFrame from S09b with columns distance_m,
    curvature_1pm (signed, 1/m), and optionally grade.
    mrp_events: from summary["mrp_events_v2"], keyed by section_id.
    Values are serialised CornerEvents dicts (requires to_dict() prerequisite).
    Used for early_throttle (MRP as throttle timing reference) and
    late_rotation (mrp_apex_delta_m threshold). When None, early_throttle
    falls back to v_min point, late_rotation cannot fire.
    """
```

The `curvature_profile` parameter is a `pd.DataFrame` from `s09_physics.run_curvature()` (S09b), with columns `distance_m` (float, monotonic), `curvature_1pm` (signed curvature in 1/m), and optionally `grade`. It is NOT a column in the per-lap resampled DataFrames.

Internal structure:
- `_extract_corner_segment(lap_df, corner, curvature_profile)` — slice DataFrame by s_entry/s_exit. Also interpolates `kappa_sign` from `curvature_profile` at `s_apex` distance via `np.interp(s_apex, curvature_profile["distance_m"].values, curvature_profile["curvature_1pm"].values)` and takes `np.sign()`. Fallback when `curvature_profile` is None: compute sign from GPS heading change across the segment using wrap-safe angular difference:
```python
delta = (bearing_exit - bearing_entry + 180) % 360 - 180  # wrap to [-180, +180]
kappa_sign = np.sign(delta)  # positive = left turn (CCW bearing increase), matches Frenet-Serret convention
```
- `_detect_candidates(metrics, tier, thresholds)` — returns list[Candidate(label, priority, confidence)]
  - `_check_entry_phase()`
  - `_check_apex_phase()`
  - `_check_exit_phase()`
  - `_check_overall()`
- `_resolve_causal_chain(candidates)` — walk up root-cause chains
- `_pick_dominant(candidates)` — highest priority or "good"

## Pipeline Integration

### Loading user corners into the pipeline

The orchestrator already loads user corners for the V2 coaching path at S10g via `run_track_decomposition_v2()` which calls `_user_corners_to_sections()`. However, the raw corner rows are not currently retained as a local variable.

Add a fetch early in the pipeline (after session_id is known, around the S10 block):

```python
# Fetch user corners from DB (already have conn + session_id at this point)
user_corner_rows, _err = _safe_step(
    "S10h_fetch_user_corners",
    lambda: _fetch_user_corners(_v2_conn, str(meta.get("session_id", ""))),
)
```

Where `_fetch_user_corners()` is a ~15-line helper:
```python
def _fetch_user_corners(conn, session_id):
    if conn is None or session_id is None:
        return None
    cursor = conn.execute(
        "SELECT corner_index, s_entry, s_apex, s_exit, lat_entry, lon_entry, "
        "lat_apex, lon_apex, lat_exit, lon_exit FROM user_corners WHERE session_id = ?",
        (session_id,),
    )
    rows = [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]
    return rows  # [] when no corners saved (success), None only from outer guard
```

Uses positional `?` param style to match existing `s10b_corners.py` convention (line 563). `sql_compat` handles PG translation automatically.

Return semantics: returns `[]` (empty list) when the query succeeds but finds zero rows — this is the success path for sessions with no saved corners. Returns `None` only when `conn` or `session_id` is missing. For any DB exception (missing table, bad column, connection error), the `_safe_step()` wrapper catches and returns `(None, error_msg)`.

### New step S10h in orchestrator.py

Inserted after S10g (V2 coaching), before S13e (V3 deep coaching):

```python
corner_labels, _err = _safe_step(
    "S10h corner_labels",
    lambda: classify_all_corners(
        resampled_laps=resampled_laps,
        theoretical_lap=theoretical_lap,  # already a DataFrame local from S10a
        user_corners=user_corner_rows,
        vehicle_class=meta.get("vehicle_class", "car"),
        valid_lap_numbers=[k for k in resampled_laps if k not in excluded_laps],
        curvature_profile=curvature_profile,  # pd.DataFrame from S09b
        mrp_events=summary.get("mrp_events_v2"),  # from S10g2
    ),
)
if corner_labels is not None:
    analysis_json["corner_labels"] = corner_labels
```

Note: `theoretical_lap` is the DataFrame local variable already unpacked from `run_theoretical()` output. `_v2_conn` is the DB connection available at the S10g block (lines 953-956). `excluded_laps` is the set built at line 653. `meta.get("vehicle_class", "car")` is the existing source — kart sessions processed through `kart_envelope/pipeline.py` have their own coaching; this classifier runs in the `telemetry_tool` pipeline only for car sessions (kart support is a future extension).

### Rewire V3 deep coaching block (S13e through S13g2) to user corners

The V3 coaching block (4 steps: S13e analyzers, S13f multi-session, S13g assembly, S13g2 persist) currently consumes `corner_performances` from auto-detected corners. Other consumers (scoring at line 1037, driving_style at line 1057, coaching_guide at line 1068, coaching_v2 at line 1080, HTML report at line 1238) also read `corner_performances`.

**Do NOT mutate `corner_performances`**. Instead, create a separate local variable that only feeds the V3 block:

```python
# Before the V3 block (line ~1100):
v3_corner_perfs = (
    _build_corner_perfs_from_user_corners(user_corner_rows, best_lap_df, _sim_result)
    if user_corner_rows
    else corner_performances  # fall back to auto-detected
)

# Then pass v3_corner_perfs (not corner_performances) to S13e, S13f, S13g, S13g2:
analyzer_bundle = run_coaching_analyzers(v3_corner_perfs, best_lap_df, ...)
driver_history = run_multi_session_lookup(
    driver_id=_drv_id if '_drv_id' in dir() else None,
    track_id=meta.get("track_id"),
    corner_ids=[c["corner_id"] for c in (v3_corner_perfs or [])])
coaching_v3 = run_enhanced_coaching(v3_corner_perfs, ...)
persist_coaching_v3(coaching_v3, ..., corner_coaching=...)
```

All other consumers (scoring, coaching_v2, driving_style, HTML report) continue to receive the original `corner_performances` from auto-detected corners — unchanged.

`_build_corner_perfs_from_user_corners()` is a ~40-line adapter converting user_corner rows to the corner_perf dict format V3 analyzers expect. **Key mapping**: `s_entry` -> `s_start`, `s_exit` -> `s_end`, `s_apex` passes through unchanged, `corner_index` -> `corner_id`. Additional keys (`braking_decel_mps2`, `cornering_accel_mps2`, `exit_accel_mps2`, `vehicle_class`) are extracted from the best lap segment for each corner. When `_sim_result` is None or lacks per-corner data, fallback defaults are used: `braking_decel_mps2=6.0`, `cornering_accel_mps2=5.0`, `exit_accel_mps2=3.0` — matching the existing fallbacks in `run_coaching_analyzers` at lines 95-97 of `s13_coaching_v3.py` (`abs(cp.get("braking_decel_mps2", 0) or 6.0)`). Note: the `or` coercion means a value of exactly `0.0` also triggers the fallback — this matches the existing V3 behavior. `v3_corner_perfs` may be `None` (not just empty list) when both user corners and auto-detected corners are absent — downstream code uses `(v3_corner_perfs or [])` guards. This rename is critical — `_get_corner_lap_slice()` in `s13_coaching_v3.py` reads `s_start`/`s_end`, not `s_entry`/`s_exit`.

### Fallback behavior

- No user corners (either `None` from DB failure or `[]` from no corners placed) -> `corner_labels = None`, V3 block continues with auto-detected `corner_performances` (current behavior preserved). Frontend should prompt user to place corners to unlock the diagnosis grid.
- No theoretical lap -> all labels `null`, deep report uses V2 coaching
- Single lap session -> grid has one row, deep report still runs
- Classifier crash -> `_safe_step()` catches, pipeline continues

## What Doesn't Change

- Theoretical engine (S10a)
- V2 coaching path (S10g) — stays for backward compat
- S13g session assembly — unchanged structure, but receives user-corner-based inputs when available
- `corner_analysis.py` — still used for auto-detected corner time decomposition
- DB schema — no new tables, no migrations

## Performance

- ~1,000 iterations max (50 corners x 20 laps)
- Each iteration: numpy slice + ~15 threshold comparisons = <1ms
- Total: <1 second, no parallelism needed

## Files Changed

| File | Action | Estimated Lines |
|------|--------|-----------------|
| `telemetry_tool/mrp_detector.py` | EDIT | ~5 lines (add `to_dict()` method to `CornerEvents` dataclass) |
| `telemetry_tool/coaching/corner_diagnosis.py` | NEW | ~300 |
| `telemetry_tool/pipeline/orchestrator.py` | EDIT | ~60 lines changed (fetch user corners, S10h step, rewire V3 block, adapter function) |
| `telemetry_tool/tests/test_corner_diagnosis.py` | NEW | ~250 |

No new dependencies. No new DB tables. No migration.

## Testing Strategy

### Unit tests (test_corner_diagnosis.py)

1. **Synthetic segments** with known profiles -> expected labels:
   - v_entry +5 km/h above theoretical -> `entry_overspeed`
   - yaw_residual +15 dps sustained in entry -> `entry_oversteer`
   - v_min point 8m before s_apex -> `early_apex`
   - Throttle gap >0.4s -> `coast_hesitation`
   - All within tolerance -> `good`
   - 3 countersteer events -> `scrappy`
   - MRP 10m past geometric apex -> `late_rotation` (car)
   - Throttle at 60% 3m before MRP -> `early_throttle`

2. **Tier degradation** — same corner with full/accel/gps columns:
   - GPS-only: `late_braking` can't fire, `entry_oversteer` detected via yaw
   - Accel: `insufficient_trail_brake` can't fire, `excessive_trail_brake` via lon_g
   - Full: all labels available

3. **Causal chains**:
   - `entry_overspeed` + `mid_corner_understeer` -> reports `entry_overspeed`
   - `early_apex` + `slow_exit` -> reports `early_apex`

4. **Vehicle class** — same segment, different thresholds for kart vs car

5. **Edge cases**: empty laps, no corners, no theoretical, sparse data, NaN columns

### Integration test

Full pipeline on `seeded_db` fixtures, verify `analysis_json["corner_labels"]` populated and well-formed.

## Book Sources

Label definitions and detection logic informed by:
- "Going Faster" by Carl Lopez — corner phases, multiple-event corners, exit speed priority
- "Ultimate Speed Secrets" + "Speed Secrets 365" by Ross Bentley — phase-specific understeer/oversteer causes, trail brake diagnostics, throttle hesitation
- "The Motor Racing Book Vol 1 - Car Handling" by Suellio Almeida — 4 corner phases (early/late entry, early/late exit), MRP concept, rotation management
- "Outdoor Rental Karting Advanced Driving Guide" — traction circle, trail braking for karts
- "Instructor Manifesto" by Ross Bentley — coaching methodology
