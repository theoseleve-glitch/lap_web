# Solver Explainability + Uncertainty Bands + Corner Coaching Labels

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` optimal solver pipeline

## Problem

1. **No per-point explanation**: The solver produces `v_opt(s)` but users cannot see *why* a given point is at its speed — is it cornering grip, braking distance, traction, or a speed cap?

2. **Single-number overconfidence**: `v_opt(s)` is a single trace with no uncertainty bounds. Users get a precise-looking result even when grip data is sparse or noisy.

3. **Generic coaching**: Corner coaching hints are purely speed-delta-based ("you're 3 kph slow at apex") without referencing the physics constraint or corner priority (entry vs exit).

## Approach

### 1. Per-Point Limiting Factor (`optimal_solver.py`)

Extend `solve_optimal_speed()` to classify each s-bin:

```
limiting_factor[i] = argmin(v_corner[i], v_fwd[i], v_bwd[i], v_cap[i])
```

Labels: `"cornering"`, `"traction"`, `"braking"`, `"cap"`.

Logic (deterministic, after final iteration):
- If `v_opt[i] ≈ v_corner[i]` (within tolerance) → `"cornering"`
- Else if `v_opt[i] ≈ v_fwd[i]` → `"traction"` (forward pass = acceleration limited)
- Else if `v_opt[i] ≈ v_bwd[i]` → `"braking"` (backward pass = deceleration limited)
- Else → `"cap"` (v_cap speed ceiling)

Priority: cornering > braking > traction > cap (when multiple match within tolerance).

**New field on `OptimalResult`**:
```python
limiting_factor: np.ndarray    # str per point: "cornering"|"traction"|"braking"|"cap"
```

### 2. Per-Corner Saturation Metrics

New function `compute_corner_saturation(result, corners)`:

```python
@dataclass
class CornerSaturation:
    corner_id: int
    s_start: float
    s_end: float
    cornering_pct: float      # fraction of bins cornering-limited
    traction_pct: float       # fraction of bins traction-limited
    braking_pct: float        # fraction of bins braking-limited
    cap_pct: float            # fraction of bins cap-limited
    dominant_factor: str       # most frequent label
    saturation_98pct: float   # fraction of bins at >98% of active constraint
```

For each corner `[s_start, s_end]`:
- Count factor distribution from `limiting_factor` array
- Compute saturation: for each bin, ratio `v_opt[i] / v_constraint[i]` where `v_constraint` is the active limit (v_corner, v_fwd, or v_bwd)

### 3. Uncertainty Bands

**New function** `solve_optimal_speed_with_bands(caps, caps_low, caps_high)`:
- Runs solver 3× (nominal, pessimistic, optimistic)
- Returns extended result with `v_opt_low_mps`, `v_opt_high_mps`, `lap_time_low_s`, `lap_time_high_s`

**Cap producers build low/high variants**:
- `caps_from_percentile_envelope()` → `speed_percentile_low=90`, `speed_percentile_high=99.5`
- `caps_from_vehicle_model()` → `mu_low = mu * 0.85`, `mu_high = mu * 1.05` (or grip_map p50/p99)

**Band width auto-scales with data quality**:
- Grip map variance propagates naturally (sparse data → wider p50-to-p99 gap → wider bands)
- Fewer than 3 laps → `mu ± 0.25` (wide uncertainty)
- No grip map → `mu ± 0.15` (moderate uncertainty)

```python
@dataclass
class OptimalResultWithBands(OptimalResult):
    v_opt_low_mps: np.ndarray
    v_opt_high_mps: np.ndarray
    lap_time_low_s: float
    lap_time_high_s: float
```

### 4. Per-Corner Coaching Labels (`corner_analysis.py`)

**New fields on `CornerPerformance`**:
```python
limiting_factor: str = ""        # dominant factor from solver
corner_priority: str = ""        # "entry" | "exit" | "balanced"
coaching_text: str = ""          # physics-aware coaching sentence
```

**Priority logic**:
```
next_straight_m = distance to next corner start (or lap end)
dominant = most frequent limiting_factor in corner bins

if dominant == "braking" AND next_straight_m > 100:
    priority = "entry"   # late braking pays off before long straight
elif dominant == "traction" AND next_straight_m > 80:
    priority = "exit"    # traction exit feeds straight speed
elif dominant == "cornering":
    priority = "balanced" # grip-limited throughout
else:
    priority = "exit"     # default: exit speed matters more
```

**Coaching templates** reference the physics:
- `"cornering" + "balanced"` → "Grip-limited through corner {id}. Focus on racing line to increase minimum speed."
- `"traction" + "exit"` → "Traction-limited on exit of corner {id}. Prioritize rotation before throttle — the {straight_m:.0f}m straight amplifies exit speed gain."
- `"braking" + "entry"` → "Braking-limited into corner {id}. Brake {delta_m:.0f}m later — entry speed directly feeds the {straight_m:.0f}m straight."
- `"cap" + "exit"` → "Near vehicle limit through corner {id}. Focus on consistency."

### 5. Reporting (`reporting_html.py`)

**Explainability panel** (new section):
- Inline SVG stacked bar: lap-wide % cornering / traction / braking / cap
- Per-corner breakdown table with saturation percentages and dominant factor

**Uncertainty sparkline** (new section):
- SVG showing v_opt (solid blue), v_opt_low/v_opt_high (shaded band)
- Lap time shown as interval: "45.2s [44.8 – 45.9]"

**Corner coaching columns**: Extend existing corner table with `Priority` and `Why` columns.

### 6. API (`data_v2.py`)

**`/sessions/<id>/optimal-v2`** gains:
```json
{
  "limiting_factor": ["cornering", "traction", ...],
  "corner_saturation": [...],
  "v_opt_low_mps": [...],
  "v_opt_high_mps": [...],
  "lap_time_low_s": 44.8,
  "lap_time_high_s": 45.9
}
```

**`/sessions/<id>/corners`** gains per-corner:
```json
{
  "limiting_factor": "traction",
  "corner_priority": "exit",
  "coaching_text": "Traction-limited on exit..."
}
```

**Speed-trace `?version=v2`** gains `speeds_low` and `speeds_high`.

### 7. Files Touched

| File | Change |
|------|--------|
| `telemetry_tool/optimal_solver.py` | `limiting_factor` array, `CornerSaturation`, `solve_optimal_speed_with_bands()` |
| `telemetry_tool/theoretical_engine.py` | `caps_from_percentile_envelope()` low/high variants |
| `telemetry_tool/lap_simulation.py` | `caps_from_vehicle_model()` mu_low/mu_high |
| `telemetry_tool/corner_analysis.py` | `limiting_factor`, `corner_priority`, `coaching_text` fields |
| `telemetry_tool/pipeline.py` | Wire bands + saturation into optimal_v2 stage |
| `telemetry_tool/reporting_html.py` | Explainability panel, uncertainty sparkline, coaching columns |
| `telemetry_tool/web/routes/data_v2.py` | Extend optimal-v2 + corners + speed-trace |
| `telemetry_tool/tests/test_optimal_solver.py` | Explainability + bands tests |
| `telemetry_tool/tests/test_corner_coaching.py` | Corner priority + coaching text tests |

### 8. Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| No grip map | Bands use mu ± 0.15 |
| < 3 laps | Bands use mu ± 0.25 |
| No curvature | limiting_factor = "cap" everywhere |
| No corners detected | Saturation + coaching skipped |
| OPTIMAL_V2 off | All new fields absent |
| Friction envelope sparse | Bands widen but never absent |
