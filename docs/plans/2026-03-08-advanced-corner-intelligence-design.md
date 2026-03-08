# Advanced Corner Intelligence — Unified Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` corner analysis pipeline — 9 features

## Features (Dependency Order)

### Feature 1: Corner Taxonomy

Classify corners from curvature profile + length + entry speed into types that tune detection thresholds and coaching templates.

**Types:**
| Type | Criteria | Coaching Bias |
|------|----------|---------------|
| `hairpin` | curvature > 0.05 rad/m, length < 60m, min_speed < 40 km/h | rotation, trail braking |
| `medium` | curvature 0.02-0.05, length 40-120m | balanced entry/exit |
| `fast` | curvature < 0.02, length > 80m, min_speed > 80 km/h | commitment, line precision |
| `chicane` | alternating direction within 80m, 2+ direction changes | rhythm, positioning |
| `kink` | curvature < 0.015, length < 40m, speed_loss < 10% | line placement only |
| `compound_member` | set by compound detection (Feature 4) | propagation-aware |
| `setup` | kink preceding heavy braking (Feature 5) | sacrifice for next corner |

**Implementation:** New function `classify_corner_type()` in `corner_detection.py`.

**Input:** Corner dict + resampled lap DataFrame (for speed/curvature at corner).

**Output:** Adds `corner_type: str` field to corner dict.

**Threshold Tuning:** Dict `_TYPE_THRESHOLDS` mapping corner_type → {bp_threshold, eob_threshold, traction_threshold, min_sustained_m} passed into `detect_corner_events()`.

### Feature 2: Brake Release Quality

Per-corner brake release metrics from brake pressure channel (or accel fallback).

**Data Structure:**
```python
@dataclass
class BrakeReleaseMetrics:
    peak_decel_mps2: float          # peak longitudinal deceleration
    peak_brake_pressure: float      # raw brake pressure if available
    brake_zone_length_m: float      # BP → EOB distance
    brake_zone_time_s: float        # time in brake zone
    release_slope: float            # d(brake)/ds at release (steeper = more abrupt)
    release_linearity: float        # R² of brake trace from peak to EOB (1.0 = perfectly linear)
    over_drop: bool                 # pressure drops > 40% before EOB
    over_drop_severity: float       # 0-1
    late_release_risk: bool         # high brake retained into low-speed region
    late_release_severity: float    # 0-1
    terminal_trail_pct: float       # brake pressure at THROTTLE_ON as % of peak (T%)
    source: str                     # "brake_pressure" | "accel_inferred"
    confidence: float               # 1.0 for pressure, 0.6 for inferred
```

**Detection Logic:**
- If `Brake (%)` or `Brake Pressure (bar)` column exists → use directly, confidence=1.0
- Else → infer from `accel_long_mps2` negative phase + speed derivative, confidence=0.6, label as "inferred"
- Over-drop: brake signal drops > 40% of peak before reaching EOB s_position
- Late release: decel magnitude > 60% of peak when speed < 50% of entry speed
- Release linearity: fit line from peak_decel point to EOB, compute R²
- Terminal trail T%: brake value at THROTTLE_ON s_position / peak value × 100

**Quality filter:** Skip if data_quality < 0.4 or brake zone < 3 samples.

**File:** New function `compute_brake_release_metrics()` in `corner_analysis.py`. Channel detection helper in `derived_channels.py`.

### Feature 3: Brake-Yaw Coupling Scores

Correlation/lag between brake release and yaw response within EOB window.

**Data Structure:**
```python
@dataclass
class BrakeYawCoupling:
    coupling_score: float           # correlation magnitude (0-1)
    lag_m: float                    # distance lag: +ve = yaw lags brake release
    pattern: str                    # "well_coupled"|"under_rotation"|"over_rotation"|"unavailable"
    terminal_trail_pct: float       # T% (first-class feature)
    coaching_action: str            # specific action string
    confidence: float               # 0-1
```

**Detection:**
- Window: EOB → THROTTLE_ON (the rotation/trail-braking zone)
- Compute: cross-correlation of d(brake)/ds vs yaw_rate within window
- Under-rotation: curvature demand high (from corner geometry) but yaw response weak while brake released early
- Over-rotation: yaw spikes while brake still high (decel > 50% peak at yaw peak)
- Terminal Trail T%: brake value at first positive accel point / peak brake × 100

**Coaching Actions:**
- Under-rotation: "hold {T%}% trail until yaw reaches {threshold} deg/s"
- Over-rotation: "release brake {X}m earlier, reduce trail to {T%}%"
- Well-coupled: "rotation timing is good"

**Graceful Degradation:**
- No yaw_rate AND no heading → skip coupling, mark unavailable
- No brake channel → skip coupling, mark unavailable
- Corner window < 10 samples → skip, mark low confidence

**File:** New function `compute_brake_yaw_coupling()` in `corner_analysis.py`.

### Feature 4: Compound Corner System

Link consecutive corners with short/no straight between them.

**Detection:**
- S-gap between corner_i.s_end and corner_{i+1}.s_start < `compound_gap_m` (default 50m)
- OR curvature between them never drops below `curvature_floor` (default 0.005 rad/m)
- Group into `compound_id` sequences

**Propagation Metrics:**
```python
@dataclass
class CompoundCornerMetrics:
    compound_id: int
    corner_ids: list[int]
    propagation_scores: dict[int, float]  # corner_id → upstream_dependency (0-1)
    blame_attribution: dict[int, float]   # corner_id → fraction of compound time_loss
    leverage_corner_id: int               # earliest corner with highest impact
    coaching: str                         # targets the leverage point
```

- Upstream dependency: correlation between corner_i exit speed and corner_{i+1} entry speed across laps
- Blame attribution: if corner_i exit_speed deficit causes corner_{i+1} entry_speed deficit proportionally
- Leverage corner: earliest corner with dependency_score > 0.5

**File:** New function `detect_compound_corners()` in `corner_detection.py`, `compute_compound_metrics()` in `corner_analysis.py`.

### Feature 5: Setup Corner Detection

Identify kinks that exist primarily to position the car for the next heavy braking zone.

**Detection:**
- Corner classified as `kink` (Feature 1)
- Next corner has BP within `setup_gap_m` (default 80m) of kink s_end
- Next corner has peak decel > 2× kink peak decel

**Scoring:**
- Line deviation at kink apex vs reference line → did driver take outside line?
- Entry positioning proxy: lateral position at next-corner BP
- Braking efficiency: actual vs theoretical BP at next corner

**Output:**
```python
{
    "is_setup_corner": True,
    "target_corner_id": 5,
    "sacrifice_score": 0.7,      # 0-1: how well driver sacrificed kink for next corner
    "coaching": "Do not apex kink — prioritize outside placement for C5 braking zone",
    "line_deviation_m": 1.2,     # actual vs optimal line at kink
}
```

**File:** Integrated into `classify_corner_type()` in `corner_detection.py`, scoring in `corner_analysis.py`.

### Feature 6: Theoretical Per-Corner Targets

Based on theoretical lap + event detector, compute target event positions and speeds.

**Output per corner:**
```python
@dataclass
class CornerTargets:
    corner_id: int
    target_events: list[CornerEvent]  # theoretical event positions
    target_speeds: dict[str, float]   # event_type → target speed_mps
    priority: str                     # "entry"|"exit"|"balanced"
    priority_reason: str              # "long straight follows"|"hairpin requires rotation"
    recommended_changes: list[dict]   # [{"event": "BP", "delta_m": -3.2, "delta_kmh": +2.1}]
    confidence: float
```

**Priority logic:**
- Next straight > 200m → "exit" (maximize exit speed)
- Previous straight > 200m → "entry" (maximize entry speed)
- Hairpin → "entry" (rotation-dependent)
- Default → "balanced"

**Recommended changes:** Compare driver's best lap event positions to theoretical event positions: `delta_m = theoretical_s - actual_s`, `delta_kmh = (theoretical_speed - actual_speed) * 3.6`.

**File:** New function `compute_corner_targets()` in `corner_analysis.py`.

### Feature 7: Target Validation Layer

Check targets against solver feasibility constraints.

**Validation rules:**
1. THROTTLE_ON must not occur before MRP (can't power out while still rotating)
2. Target speed at any event must not exceed solver v_opt at that s_position
3. BP must occur before corner entry (can't brake inside the corner and hit apex)
4. EOB must occur before MRP (can't still be braking at max rotation)
5. Exit speed target must be achievable given traction limit from apex speed

**On violation:**
- Downgrade target confidence by 0.3
- Adjust target conservatively (clamp to feasible)
- Add warning string to target

**File:** New function `validate_corner_targets()` in `corner_analysis.py`.

### Feature 8: Driver Style Profile

Compute per-session driver style vector from corner analysis data.

**Style Vector:**
```python
@dataclass
class DriverStyleProfile:
    brake_aggressiveness: float     # mean peak_decel / available_decel (0-1)
    trail_length_score: float       # mean terminal_trail_pct (0-100)
    mrp_timing: float               # mean MRP position relative to corner (0=early, 1=late)
    exit_priority_score: float      # fraction of corners where exit loss < entry loss
    line_variance: float            # std-dev of lateral position at apex across laps
    style_labels: list[str]         # ["late braker", "exit-focused", "smooth"]
    confidence: float
```

**Label Rules:**
- `brake_aggressiveness > 0.8` → "aggressive braker"
- `brake_aggressiveness < 0.4` → "conservative braker"
- `trail_length_score > 30` → "trail braker"
- `exit_priority_score > 0.6` → "exit-focused"
- `exit_priority_score < 0.4` → "entry-focused"
- `line_variance < 0.5` → "consistent"
- `line_variance > 2.0` → "variable line"

**Coaching Personalization:** Style labels modify coaching phrasing (not facts):
- "aggressive braker" + "brake earlier" → "Your commitment is great — try braking just 2m earlier to carry more mid-corner speed"
- "conservative braker" + "brake later" → "You have margin to brake 5m later here"

**File:** New function `compute_driver_style()` in `features.py`, integration in `corner_analysis.py` coaching.

### Feature 9: Corner Risk Score

Penalize unstable gains in improvement recommendations.

**Risk Signals:**
```python
@dataclass
class CornerRiskScore:
    corner_id: int
    risk_index: float               # 0-1 composite
    yaw_spike_risk: float           # std-dev of peak yaw across laps / mean
    mrp_plateau_risk: float         # 1.0 - mrp_strength (from timeline)
    line_deviation_risk: float      # std-dev of apex lateral position
    accel_oscillation_risk: float   # frequency of sign changes in accel during corner
    brake_release_instability: float # std-dev of release_linearity across laps
    confidence: float
```

**Risk Index Formula:**
```
risk_index = 0.25 * yaw_spike_risk + 0.20 * line_deviation_risk +
             0.20 * brake_release_instability + 0.20 * accel_oscillation_risk +
             0.15 * mrp_plateau_risk
```

**Integration into ranking:**
Updated `rank_improvement_opportunities()`:
```
priority = time_loss_s * 0.5 + mistake_severity * 0.15 +
           mrp_stability * 0.05 + max_segment_loss * 0.1 +
           (1.0 - risk_index) * 0.2   # prefer stable gains
```

**File:** New function `compute_corner_risk()` in `corner_analysis.py`.

## Pipeline Integration

**Stage 6b (corner detection):**
```python
corners = detect_corners(...)
# NEW: classify + compound + setup
classify_corner_types(corners, resampled_lap)
compounds = detect_compound_corners(corners, resampled_lap)
# Mark setup corners
identify_setup_corners(corners, resampled_lap)
```

**Stage 10c-iii (after timeline detection):**
```python
# Brake release metrics
for tl in timelines:
    tl.brake_release = compute_brake_release_metrics(tl, best_lap_df, corner)
    tl.brake_yaw_coupling = compute_brake_yaw_coupling(tl, best_lap_df, corner)

# Per-corner targets
targets = compute_corner_targets(corners, timelines, theoretical_result, best_lap_df)
validate_corner_targets(targets, solver_result)

# Compound metrics
compound_metrics = compute_compound_metrics(compounds, timelines, all_lap_dfs)

# Risk scores
risk_scores = compute_corner_risk_scores(timelines, all_lap_dfs)

# Driver style
driver_style = compute_driver_style(timelines, corner_performances, best_lap_df)
```

**Store in summary:**
```python
summary["corner_taxonomy"] = [c["corner_type"] for c in corners]
summary["compound_corners"] = compound_metrics
summary["corner_targets"] = targets
summary["driver_style"] = driver_style.to_dict()
summary["corner_risk_scores"] = risk_scores
```

## API Extensions

**`/corners`** gains per-corner:
```json
{
    "corner_type": "hairpin",
    "brake_release": {...},
    "brake_yaw_coupling": {...},
    "targets": {...},
    "risk_index": 0.35,
    "compound_id": 2,
    "is_setup_corner": false
}
```

**New endpoint `GET /sessions/<id>/driver-style`:**
```json
{
    "brake_aggressiveness": 0.72,
    "trail_length_score": 25.3,
    "style_labels": ["aggressive braker", "exit-focused"],
    "confidence": 0.85
}
```

## Reporting

Corner table gains columns: Type, Brake Release, Risk.
New "Driver Style" badge in report header.
Compound corners shown with linked bracket in table.

## Files Touched

| File | Changes |
|------|---------|
| `corner_detection.py` | `classify_corner_type()`, `detect_compound_corners()`, `identify_setup_corners()` |
| `corner_analysis.py` | `BrakeReleaseMetrics`, `BrakeYawCoupling`, `CornerTargets`, `CornerRiskScore`, `compute_brake_release_metrics()`, `compute_brake_yaw_coupling()`, `compute_corner_targets()`, `validate_corner_targets()`, `compute_corner_risk()`, `compute_compound_metrics()`, update `rank_improvement_opportunities()` |
| `derived_channels.py` | `detect_brake_channel()` helper |
| `features.py` | `DriverStyleProfile`, `compute_driver_style()` |
| `pipeline.py` | Wire stages 6b taxonomy + 10c-iii advanced analysis |
| `web/routes/data_v2.py` | Extend `/corners`, add `/driver-style` |
| `reporting_html.py` | Type/Risk/Brake columns, style badge, compound brackets |
| `tests/test_corner_taxonomy.py` | Corner type classification tests |
| `tests/test_brake_release.py` | Brake release + coupling tests |
| `tests/test_compound_corners.py` | Compound + setup tests |
| `tests/test_corner_targets.py` | Target generation + validation tests |
| `tests/test_driver_style.py` | Style profile tests |
| `tests/test_corner_risk.py` | Risk score tests |

## Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| No brake channel | Infer from accel, confidence=0.6, label "inferred" |
| No yaw_rate AND no heading | Skip coupling, MRP, rotation mistakes |
| No XY position | Skip line_deviation_risk, apex lateral position |
| < 3 laps | Skip stability metrics, risk scores, style profile |
| data_quality < 0.3 | All confidence scores halved |
| Corner window < 10 samples | Skip brake release + coupling |
| No theoretical result | Skip targets, skip compound blame |
