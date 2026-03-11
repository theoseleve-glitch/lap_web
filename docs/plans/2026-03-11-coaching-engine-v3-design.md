# Coaching Engine V3 — Design Specification

**Date**: 2026-03-11
**Branch**: TBD (feature/coaching-engine-v3)
**Status**: Approved
**Scope**: Full-stack (Python backend + Next.js frontend + Alembic migration)

## 1. Problem Statement

The current coaching engine (`coaching_engine.py`, 602 lines) produces technically accurate but insufficiently actionable feedback. Comparing against motorsport coaching literature (10 reference books in `docs/coaching books/`) reveals gaps in:

- **Prescriptive coaching**: Says "early braking" but not "move brake point from 200m board to 150m board"
- **Progressive methodology**: Gives endpoint targets instead of 3-step progressions
- **Root cause diagnosis**: Attributes by metrics, not by symptoms (e.g., steering increasing past apex = early turn-in)
- **Exit speed emphasis**: Books say 70-80% of lap time is exits+straights, but exit coaching is weighted equally
- **Information overload**: Up to 5 focus areas per session vs. coaching books' "one thing at a time"
- **Driver psychology**: No confidence-based framing, no mental imagery, no warm-up protocols
- **Multi-session tracking**: Each session standalone, no progression trends across sessions

An audit identified 24 specific improvements across 6 categories (A-F) with a P0-P4 priority matrix.

## 2. Approach

**Coaching Module Extraction** (Approach 2 from brainstorming). Create a new `telemetry_tool/coaching/` package mirroring the existing `scoring/` package pattern. The current `coaching_engine.py` stays functional as fallback until the new package is proven.

Key design decisions:
- **Rich template system** (not LLM): Extensive parameterized template library. Deterministic, testable, no API dependency.
- **Config-driven cause taxonomy**: ~40 causes in JSON, not hardcoded Python strings.
- **Multi-session DB persistence**: New `corner_progression` table with RLS for workspace isolation.
- **Vehicle-class-aware**: Templates and thresholds differ for kart vs car.
- **Backward-compatible API**: New fields are additive. New `coaching/models.py` defines its own `to_dict()` covering all fields. Old engine fallback returns a dict WITHOUT new optional fields; frontend handles absence gracefully (all new keys checked with optional chaining).
- **Analyzer persistence**: Pipeline stores `AnalyzerBundle` as JSON in `analysis_json["coaching_v3"]`; GET endpoint reads it and passes to session_composer. Old fallback path skips V3 fields entirely.
- **Vehicle class resolution**: (1) `session_meta["vehicle_class"]`, (2) `meta["kart_id"]` presence → "kart", (3) default "car".
- **Focus area cap**: `focus_areas` now contains max 2 items (was up to 5). Remaining items in `deferred_focus_areas`. Frontend updated to handle both.

## 3. Package Structure

```
telemetry_tool/coaching/
├── __init__.py                    # Public API: generate_session_coaching()
│
├── models.py                      # Extended dataclasses
│   ├── SessionCoaching            # Existing 8 fields + 7 new Optional fields
│   ├── FocusArea                  # + progressive_steps, symptom_diagnosis
│   ├── Drill                      # + difficulty_progression, success_criteria
│   ├── ProgressionInsight         # Unchanged
│   ├── CornerCoachingDetail       # NEW: rich per-corner coaching
│   ├── TrailBrakeAssessment       # NEW: 4-block braking breakdown
│   ├── BrakingBlock               # NEW: single braking block
│   ├── TractionBudget             # NEW: friction circle budget
│   ├── ExitSpeedCascade           # NEW: exit→straight time gain
│   ├── MultiSessionTrend          # NEW: cross-session corner trends
│   ├── CornerTrend                # NEW: per-corner trend data
│   ├── ThrottleLiftEvent          # NEW: mid-corner throttle lift
│   ├── WeightTransferInsight      # NEW: load transfer data
│   ├── SymptomDetection           # NEW: detected symptoms
│   ├── Symptom                    # NEW: single symptom
│   └── WarmUpProtocol             # NEW: pre-session protocol
│
├── taxonomy/
│   ├── causes.py                  # CauseTaxonomy class, loads causes.json
│   ├── causes.json                # ~40 causes: symptom, diagnosis, root_cause, thresholds
│   └── symptoms.py                # Symptom→cause mapping rules
│
├── templates/
│   ├── corner_tips.py             # ~300+ templates by (cause, severity, vehicle_class)
│   ├── drills.py                  # ~20 drill types with 3 difficulty levels each
│   ├── narratives.py              # Session narratives by (grade_band, cause_category, trend)
│   ├── symptoms.py                # Symptom diagnosis text templates
│   ├── progression.py             # Multi-session trend coaching text
│   ├── confidence_frames.py       # Strength-based framing templates
│   ├── mental_imagery.py          # Pre-session visualization prompts
│   └── reference_points.py        # Track-landmark coaching text
│
├── analyzers/
│   ├── trail_brake.py             # 4-block braking analysis
│   ├── exit_speed.py              # Exit→straight cascade calculator
│   ├── traction_budget.py         # Friction circle budget
│   ├── symptom_detector.py        # Steering/lateral symptom diagnosis
│   ├── throttle_lift.py           # Abrupt throttle-lift detection
│   └── weight_transfer.py         # Weight transfer coaching data
│
├── composers/
│   ├── corner_composer.py         # Builds CornerCoachingDetail per corner
│   ├── session_composer.py        # Builds SessionCoaching from all inputs
│   ├── focus_limiter.py           # Max 2 focus areas per session
│   ├── progressive_coach.py       # Scaffolded goals, brake-point stepping
│   └── confidence_framer.py       # Strength-based confidence framing
│
└── persistence/
    ├── models.py                  # corner_progression table definition
    ├── queries.py                 # Store/retrieve corner trends
    └── migration.py               # Alembic migration helper
```

## 4. Data Model

### 4.1 Extended SessionCoaching (backward-compatible)

New fields are all `Optional` with `None` defaults:

```python
@dataclass
class SessionCoaching:
    # Existing (unchanged)
    session_theme: str
    narrative: str
    strengths: list[str]
    weaknesses: list[str]
    focus_areas: list[FocusArea]
    drills: list[Drill]
    progression: list[ProgressionInsight]
    next_session_goals: list[str]
    confidence: float

    # New (Optional, backward-compatible)
    corner_coaching: list[CornerCoachingDetail] | None = None
    trail_brake_assessment: list[TrailBrakeAssessment] | None = None
    traction_budgets: list[TractionBudget] | None = None
    exit_speed_cascades: list[ExitSpeedCascade] | None = None
    multi_session_trends: list[MultiSessionTrend] | None = None
    mental_imagery_prompts: list[str] | None = None
    warm_up_protocol: dict | None = None
    vehicle_class: str | None = None
```

### 4.2 CornerCoachingDetail

```python
@dataclass
class CornerCoachingDetail:
    corner_id: int
    corner_name: str
    # Diagnosis
    primary_cause: str                      # From taxonomy
    cause_severity: str                     # mild | moderate | severe
    cause_root: str                         # technique | confidence | line | etc.
    symptom_evidence: list[str]
    diagnosis_text: str
    # Coaching
    coaching_tip: str
    progressive_steps: list[str]            # 3 steps
    symptom_check: str
    # Quantified impact
    time_loss_corner_s: float
    time_loss_cascade_s: float
    exit_speed_target_kmh: float | None     # None when theoretical unavailable
    apex_speed_target_kmh: float | None     # None when theoretical unavailable
    entry_speed_target_kmh: float | None    # None when theoretical unavailable
    braking_point_target_description: str
    # Physics context
    traction_budget: TractionBudget | None
    trail_brake: TrailBrakeAssessment | None
    exit_cascade: ExitSpeedCascade | None
    weight_transfer_insight: str | None
    # Multi-session trend
    trend: CornerTrend | None
```

### 4.3 TrailBrakeAssessment (4-block model)

```python
@dataclass
class BrakingBlock:
    block_id: int                           # 1-4
    name: str                               # throttle_to_brake | straight_line_decel | trail_brake | brake_to_throttle
    s_start: float
    s_end: float
    duration_s: float
    peak_decel_mps2: float | None
    overlap_m: float | None                 # Block 3: brake+steer overlap
    trail_pct_at_turnin: float | None       # Block 3: % brake at turn-in
    release_rate_mps3: float | None         # Block 3: jerk
    release_linearity: float | None         # Block 3: 1.0=linear, 0=step
    transition_duration_s: float | None     # Block 4: brake→throttle gap

@dataclass
class TrailBrakeAssessment:
    corner_id: int
    blocks: list[BrakingBlock]
    overall_score: float                    # 0-100
    has_trail_braking: bool
    theoretical_overlap_m: float
    actual_overlap_m: float
    time_loss_from_no_trail_s: float
    primary_issue: str | None
```

Detection logic:
- Block 1: Throttle <10% → brake >5%. Duration = transition gap.
- Block 2: Brake >5% AND steering <2° (straight-line).
- Block 3: Brake >5% AND steering >2° (overlap = trail-braking).
- Block 4: Brake <5% → throttle >10°.
- Fallback (no throttle/brake channels): Infer from lon-accel + lat-accel. Block 3 = negative lon-accel AND lat-accel >1.5 m/s².

### 4.4 ExitSpeedCascade

```python
@dataclass
class ExitSpeedCascade:
    corner_id: int
    actual_exit_speed_mps: float
    theoretical_exit_speed_mps: float
    exit_speed_delta_mps: float
    straight_length_m: float
    straight_end_speed_actual_mps: float
    straight_end_speed_theoretical_mps: float
    time_loss_in_corner_s: float
    time_loss_on_straight_s: float
    total_cascade_time_s: float
    exit_gain_needed_kmh: float
    straight_gain_resulting_kmh: float
    cascade_ratio: float
```

Physics: Full numerical integration `delta_t = L/v_actual - L/v_theoretical` under constant acceleration on the straight. The first-order approximation `delta_t ≈ L * delta_v / v_exit^2` is only used for display when `delta_v < 10% of v_exit`. For karts with low exit speeds (v_exit < 10 m/s), always use full integration to avoid >20% error.

### 4.5 TractionBudget

```python
@dataclass
class TractionBudget:
    corner_id: int
    # At 3 points: entry, apex, exit
    entry_lateral_pct: float
    entry_longitudinal_pct: float
    entry_total_pct: float
    entry_remaining_pct: float
    apex_lateral_pct: float
    apex_longitudinal_pct: float
    apex_total_pct: float
    apex_remaining_pct: float
    exit_lateral_pct: float
    exit_longitudinal_pct: float
    exit_total_pct: float
    exit_remaining_pct: float
    theoretical_apex_total_pct: float       # = sqrt(theo_lat^2 + theo_lon^2) / friction_max at s_apex from theoretical_lap DataFrame
    grip_headroom_pct: float                # Driver's remaining % vs theoretical's remaining %
```

### 4.6 ThrottleLiftEvent

```python
@dataclass
class ThrottleLiftEvent:
    corner_id: int
    s_position: float
    throttle_before_pct: float
    throttle_after_pct: float
    drop_pct: float
    drop_duration_s: float
    lateral_grip_at_lift_pct: float
    weight_shift_estimate_kg: float
    yaw_rate_change_dps: float | None
    resulted_in_correction: bool
    severity: str                           # benign | risky | dangerous
```

Severity: benign (<20% lift OR <40% lat grip), risky (20-50% AND 40-70%), dangerous (>50% AND >70%).

### 4.7 SymptomDetection

```python
@dataclass
class Symptom:
    symptom_id: str
    description: str
    evidence: dict[str, float]
    confidence: float

@dataclass
class SymptomDetection:
    corner_id: int
    symptoms: list[Symptom]
```

Channel tier fallback:
- Tier 1 (Steering+Throttle+Brake+GPS+IMU): All symptoms
- Tier 2 (GPS+accel only): early_apex, understeer_entry, accel changes
- Tier 3 (GPS only): early_apex (via position), basic line

### 4.8 WeightTransferInsight

```python
@dataclass
class WeightTransferInsight:
    corner_id: int
    entry_front_load_pct: float
    entry_rear_load_pct: float
    front_grip_bonus_pct: float
    trail_brake_front_bonus_pct: float
    exit_rear_load_pct: float
    rear_grip_bonus_pct: float
    insight_text: str
```

Vehicle defaults when session scalars unavailable: kart (wb=1.04m, cg_h=0.25m, mass=165kg), car (wb=2.5m, cg_h=0.45m, mass=750kg). Mass required for weight_shift_estimate_kg calculation.

### 4.9 Database: corner_progression

```sql
CREATE TABLE corner_progression (
    id SERIAL PRIMARY KEY,
    workspace_id UUID NOT NULL,
    driver_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    corner_id INTEGER NOT NULL,
    session_date TIMESTAMP NOT NULL,
    apex_speed_mps REAL,
    entry_speed_mps REAL,
    exit_speed_mps REAL,
    braking_point_m REAL,
    time_loss_s REAL,
    grip_utilisation_pct REAL,
    trail_brake_score REAL,
    primary_cause TEXT,
    theoretical_apex_mps REAL,
    theoretical_entry_mps REAL,
    theoretical_exit_mps REAL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_corner_prog_driver_track
    ON corner_progression(driver_id, track_id, corner_id);
ALTER TABLE corner_progression ENABLE ROW LEVEL SECURITY;
CREATE POLICY corner_progression_workspace_isolation
    ON corner_progression
    FOR ALL
    USING (workspace_id = current_setting('app.workspace_id')::uuid)
    WITH CHECK (workspace_id = current_setting('app.workspace_id')::uuid);
```

## 5. Cause Taxonomy

### 5.1 Structure

JSON file at `coaching/taxonomy/causes.json` with ~40 causes across 5 categories:

**Categories**: braking, cornering, exit, consistency, vehicle_management

**Each cause has** (all required, validated by Pydantic at import time):
- `symptom`: Observable behavior in data
- `diagnosis`: Root explanation for the driver
- `root_cause`: One of: technique, confidence, line, balance, aggression, fitness, management, awareness, fear
- `severity_thresholds`: {mild, moderate, severe} with metric thresholds
- `unit`: Measurement unit for thresholds

**Validation**: `CauseTaxonomy.__init__()` loads and validates `causes.json` using a Pydantic v2 model. Missing/malformed fields raise `ValueError` at import time, not during analysis.

### 5.2 Cause List

**Braking (7 causes)**:
- `early_braking_confidence`: Consistent early brake, low variance → confidence-limited
- `early_braking_reference`: High variance early brake → no visual reference
- `late_braking_overshoot`: Past theoretical + understeer/wide exit → overdriving
- `insufficient_threshold_braking`: Peak decel <80% theoretical → not reaching limit
- `poor_trail_brake_release`: Abrupt release (>2 m/s² drop in <0.1s) → losing front load
- `no_trail_braking`: Braking ends >15m before turn-in → no brake-turn overlap
- `incomplete_heel_toe`: Rear chirp on downshift → rev-match incomplete

**Cornering (7 causes)**:
- `early_apex`: Steering increases past apex + road unused at exit
- `late_apex_excessive`: Apex >20% past center, very low entry speed
- `low_apex_speed_grip`: Speed 5%+ below theoretical, traction <70% used
- `low_apex_speed_line`: Low speed AND >1m off reference line
- `understeer_entry`: Lat-accel plateaus while steering increases
- `oversteer_entry`: Yaw spike >2sigma, possible correction
- `mid_corner_lift`: Throttle drops >50% for <0.3s mid-corner

**Exit (5 causes)**:
- `late_throttle_application`: Throttle-on >10m past theoretical
- `abrupt_throttle_application`: 0→80%+ in <0.2s, traction event follows
- `early_throttle_understeer`: Power before apex, car pushes wide
- `poor_exit_line`: Doesn't reach track-out, >1m unused
- `trailing_throttle_oversteer`: Lift >30% while >70% lat grip, yaw spike

**Consistency (4 causes)**:
- `brake_point_scatter`: Std-dev >5m across laps
- `apex_speed_scatter`: CV >8% at same corner
- `line_scatter`: Lateral position std-dev >0.8m at apex
- `lap_time_degradation`: Times rising >0.5%/lap in last third

**Vehicle Management (3 causes)**:
- `thermal_fade_brakes`: Braking distance +10% in laps 15+
- `tire_degradation`: Lateral grip peak drops >5% over session
- `fuel_load_unadapted`: Brake points/exit speeds don't improve as fuel burns

## 6. Template Library

### 6.1 Corner Tips (~300+ templates)

Keyed by `(cause, severity, vehicle_class)`. Each template contains:
- `tip`: Primary coaching tip with parameterized placeholders
- `progressive_steps`: 3-step session-to-session progression
- `symptom_check`: Self-diagnosis instruction for the driver

Example:
```python
("early_braking_confidence", "mild", "kart"): {
    "tip": "You're braking {delta_m:.0f}m early at {corner_name}. Your consistency is excellent ({variance_m:.1f}m std-dev) — that means you have the skill. Next session, move your brake point {step_m:.0f}m later.",
    "progressive_steps": [
        "Session 1: Brake at {current_m:.0f}m. Nail the same point every lap.",
        "Session 2: Move to {step1_m:.0f}m. If you hit apex cleanly 3/5 laps, lock it in.",
        "Session 3: Move to {step2_m:.0f}m. Within {target_delta_m:.0f}m of theoretical."
    ],
    "symptom_check": "If you add steering past the apex, you've gone too far — step back 3m."
}
```

### 6.2 Drill Library (~20 types, 3 difficulty levels each)

Each drill:
- `title`, `vehicle_classes`, `applicable_causes`
- `difficulty_levels`: beginner, intermediate, advanced
- Each level: `description`, `success_criteria`, `lap_count`, `focus_corners`

Drill types include: brake_point_precision, trail_brake_introduction, exit_speed_focus, late_apex_reset, consistency_metronome, traction_sensing, throttle_progression, line_finding, reference_point_locking, mental_imagery_practice, weight_transfer_awareness, heel_toe_practice, fuel_adaptation, tire_management, understeer_recovery, oversteer_control, corner_linking, straight_line_braking, warm_up_routine, cool_down_routine.

### 6.3 Session Narratives

Keyed by `(grade_band, primary_cause_category, trend)`:
- Grade bands: "S-A", "B-C", "D-F"
- Cause categories: braking, cornering, exit, consistency, vehicle_management, None
- Trends: improving, stable, degrading

Each entry is a list of variant templates for natural variation.

### 6.4 Confidence Frames

Templates for transforming raw strengths into actionable statements:
```python
("trail_braking", "strong"):
    "Your trail-braking at {strong_corner} is in the top {percentile:.0f}% of your laps — build on this by extending the overlap zone {extension_m:.0f}m deeper into {weak_corner}."
```

### 6.5 Mental Imagery Prompts

One per major cause category. Sensory-rich (not just visual): brake pedal feel, weight loading, car rotation, throttle progression.

### 6.6 Reference Point Templates

Track-landmark descriptions:
1. Priority: Track DB landmarks ("3m past the 100m board")
2. Fallback: Distance from corner entry ("25m before the turn-in kerb")
3. Last resort: Raw distance with context ("At the 187m mark")

## 7. Analyzers

Six new analysis modules in `coaching/analyzers/`. Each receives existing pipeline data, each wrapped in `_safe_step()` for graceful degradation.

### 7.1 trail_brake.py
- Detects 4 braking blocks per corner
- Scores trail-brake quality (overlap distance, release linearity)
- Falls back to lon-accel + lat-accel when no throttle/brake channels

### 7.2 exit_speed.py
- Computes exit speed → straight speed cascade per corner
- Uses constant-acceleration model: `delta_t ≈ L * delta_v / v_exit^2`
- Identifies highest-cascade corners (corner before longest straight)

### 7.3 traction_budget.py
- Computes friction circle utilization at entry/apex/exit
- Source: lat-accel, lon-accel, friction_model.lateral_max(speed)
- Highlights "grip you're NOT using"

### 7.4 symptom_detector.py
- Rule-based detection of coaching-book symptoms
- 3-tier channel fallback (full→GPS+accel→GPS only)
- Cross-references symptoms to taxonomy causes

### 7.5 throttle_lift.py
- Detects abrupt throttle lifts while cornering
- Classifies severity: benign/risky/dangerous
- Estimates weight transfer consequence

### 7.6 weight_transfer.py
- Surfaces load transfer physics from vehicle params
- Uses session scalars or class defaults
- Generates human-readable insight text

## 8. Composers

Five modules that assemble analyzed data into coaching output.

### 8.1 corner_composer.py
- Combines all analyzer outputs per corner + taxonomy + templates
- Cause attribution: symptoms first (highest confidence), then speed/braking deltas
- Cross-references: symptom root cause overrides CornerPerformance cause
- Generates reference point descriptions for brake targets

### 8.2 session_composer.py (orchestrator)
Assembly order:
1. corner_composer → CornerCoachingDetail per corner
2. Rank corners by cascade_time_loss (not just corner loss)
3. Map to focus areas via taxonomy
4. focus_limiter → max 2 focus areas
5. Select drills from library matching focus area causes
6. confidence_framer → rewrite strengths
7. progressive_coach → goals + warm_up_protocol
8. late_apex_reset check
9. Select narrative template
10. Fill all placeholders
11. Generate mental imagery prompts
12. Assemble SessionCoaching

### 8.3 focus_limiter.py
- Max 2 focus areas per session
- #2 must be >= 30% of #1's time loss to qualify
- Same root_cause → merge into one area
- Remaining areas returned as `deferred_focus_areas`

### 8.4 progressive_coach.py
- 3 goals: primary focus + maintain strength + consistency target
- References previous session goals when available
- Late apex reset: if >50% corners show early_apex, recommend full reset
- Warm-up protocol: 3 phases (sighting, build, push)

### 8.5 confidence_framer.py
- Transforms generic strengths into corner-specific, actionable statements
- For confidence-limited causes: "Your consistency proves the skill — extend by X"
- Each strength suggests extending to a weaker corner

## 9. Pipeline Integration

### 9.1 New Stages

No existing stages removed. New stages inserted:

**Note**: Existing pipeline has stages up through 13d (practice_plan) and 14a-14c (reports).
New stages use next available labels to avoid collision:

```
Existing S13d (practice_plan) → ...

NEW S13e: run_coaching_analyzers(corner_perfs, best_lap_df, theoretical_result,
          friction_model, resampled_laps, available_columns)
    → AnalyzerBundle
    Each analyzer wrapped in _safe_step(); partial results on failure.

NEW S13f: run_multi_session_lookup(driver_id, track_id, corner_ids)
    → dict[corner_id → list[row]] | None   (PG-only)
    driver_id resolved from summary["driver_id"] (set after DB lookup in orchestrator).
    Returns None when: USE_PG=0, driver_id is None, or track_id is "unknown_track".

NEW S13g: run_enhanced_coaching(corner_perfs, coaching_v2, scores,
          lap_metrics, driving_style, analyzer_bundle, driver_history,
          vehicle_class, previous_goals, taxonomy)
    → SessionCoaching.to_dict()   (new models.py to_dict() covers ALL fields)
    Fallback: old coaching_engine.generate_session_coaching() (returns dict without V3 fields)

NEW S13g2: persist_coaching_v3(coaching_dict, analysis_json)
    → Writes coaching_dict to analysis_json["coaching_v3"] for GET endpoint retrieval.
    Also persists per-corner metrics to corner_progression table (PG-only).

Existing S14a-S14c (reports) → unchanged
```

### 9.2 Orchestrator Wiring

```python
# driver_id must be resolved before S13f. Add to summary after DB lookup:
summary["driver_id"] = _drv_id  # Already computed in orchestrator

analyzer_bundle = self._safe_step("S13e_analyzers", run_coaching_analyzers, ...)
driver_history = self._safe_step("S13f_multi_session", run_multi_session_lookup,
    summary.get("driver_id"), summary.get("track_id"),
    [c["corner_id"] for c in (corner_perfs or [])])
coaching = self._safe_step("S13g_coaching_v3", run_enhanced_coaching, ...)
self._safe_step("S13g2_persist_coaching", persist_coaching_v3, coaching, analysis_json)
```

### 9.2.1 GET Endpoint Data Flow

The `GET /api/v1/sessions/{id}/coaching` endpoint currently calls `coaching_engine.generate_session_coaching()` at request time. Under V3:

1. Pipeline stores full V3 coaching output in `analysis_json["coaching_v3"]`
2. GET endpoint checks for `analysis_json["coaching_v3"]` first
3. If present: return it directly (already serialized by `to_dict()`)
4. If absent (old session / V3 disabled): fall back to existing `coaching_engine.generate_session_coaching()`

This ensures old sessions still work and new sessions serve V3 data without re-computation.

### 9.3 Feature Flag

`COACHING_V3` env var, default ON. Set `=0` to use legacy `coaching_engine.py`.

## 10. API Changes

### 10.1 Endpoint: GET /api/v1/sessions/{id}/coaching

Response extended with new optional fields. Existing fields keep same shape but richer content.

New top-level fields:
- `corner_coaching`: list of CornerCoachingDetail dicts
- `deferred_focus_areas`: focus areas beyond top 2
- `mental_imagery_prompts`: list of strings
- `warm_up_protocol`: {phase_1_laps, phase_1_instruction, phase_2_laps, phase_2_instruction, phase_3_instruction}
- `vehicle_class`: "kart" | "car"
- `late_apex_reset`: string or null

Extended existing fields:
- `focus_areas[].progressive_steps`: list of 3 strings
- `focus_areas[].symptom_diagnosis`: string
- `drills[].difficulty`: "beginner" | "intermediate" | "advanced"
- `drills[].success_criteria`: string
- `drills[].difficulty_progression`: {beginner: {...}, intermediate: {...}, advanced: {...}}

## 11. Frontend Components

```
lap-website/src/components/app/coaching/
├── CoachingPanel.tsx              # Main container
├── SessionTheme.tsx               # Grade + theme + narrative
├── FocusAreaCard.tsx              # Focus area with progressive steps accordion
├── DrillCard.tsx                  # Drill with difficulty tabs
├── CornerCoachingCard.tsx         # Per-corner detail (expandable)
│   ├── SymptomEvidence.tsx        #   Symptom badges with evidence
│   ├── SpeedTargets.tsx           #   Entry/Apex/Exit target vs actual bars
│   ├── TractionBudgetViz.tsx      #   Friction circle SVG
│   ├── TrailBrakeTimeline.tsx     #   4-block timeline
│   ├── ExitCascadeViz.tsx         #   Corner→straight cascade arrows
│   └── CornerTrendChart.tsx       #   Apex speed sparkline across sessions
├── WarmUpProtocol.tsx             # Pre-session card
├── MentalImageryPrompt.tsx        # Visualization card
├── NextSessionGoals.tsx           # Goals with previous-session reference
├── DeferredAreas.tsx              # "For later" collapsed section
└── StrengthsList.tsx              # Confidence-framed strengths
```

UI patterns:
- Progressive disclosure: Corner cards collapsed by default
- Speed targets as horizontal bar charts (actual vs target)
- Traction budget as small SVG friction circle
- Trail brake as 4-block colored timeline
- Cascade as arrow flow diagram
- Trend as mini sparkline

## 12. Alembic Migration

Migration 040: `corner_progression` table. (Existing head is migration 039.)

```python
def upgrade():
    op.create_table('corner_progression', ...)
    op.create_index('idx_corner_prog_driver_track', ...)
    op.execute("ALTER TABLE corner_progression ENABLE ROW LEVEL SECURITY; ...")

def downgrade():
    op.drop_table('corner_progression')
```

## 13. Testing Strategy

- **Unit tests per analyzer**: Each analyzer gets its own test file with synthetic data
- **Channel tier tests**: Dedicated fixtures for Tier 1 (full channels), Tier 2 (GPS+accel), Tier 3 (GPS only). Verify Tier 2/3 never emit symptoms requiring Tier 1 channels. Verify graceful None returns.
- **Template tests**: Verify all placeholders are filled, no KeyError on any cause×severity×vehicle combination. Exhaustive: iterate all (cause, severity, vehicle_class) combinations.
- **Taxonomy validation**: `causes.py` validates `causes.json` at import time using Pydantic v2 model. Malformed JSON fails at startup, not at corner analysis time.
- **Integration test**: Full pipeline run with sample session → verify SessionCoaching output has all fields
- **Regression test**: Run old coaching_engine and new coaching side-by-side, verify existing fields match. New optional fields present in V3, absent in fallback.
- **Missing theoretical test**: Verify corner_composer produces valid output when theoretical lap is None (speed targets = None, templates that reference targets are skipped)
- **Multi-session trend minimum**: Trend sparkline requires minimum 3 sessions. Below 3, `trend` field is None.
- **Frontend**: Vitest component tests for each new component; Playwright E2E for coaching panel. All new fields tested with optional chaining (absent = no render, no crash).

## 14. Audit Item Mapping

| Item | Description | Module |
|------|-------------|--------|
| A1 | Reference-point coaching | composers/corner_composer.py, templates/reference_points.py |
| A2 | Symptom-based diagnosis | analyzers/symptom_detector.py, taxonomy/symptoms.py |
| A3 | Trail-braking quality metric | analyzers/trail_brake.py |
| A4 | Rich cause taxonomy | taxonomy/causes.json |
| A5 | Exit speed emphasis | analyzers/exit_speed.py, composers/session_composer.py (ranking) |
| B1 | Progressive brake-point movement | templates/corner_tips.py (progressive_steps) |
| B2 | Drill difficulty progression | templates/drills.py (difficulty_levels) |
| B3 | Late apex first guidance | composers/progressive_coach.py (late_apex_reset) |
| B4 | Session pacing advice | composers/progressive_coach.py (WarmUpProtocol) |
| C1 | Time-cascade calculation | analyzers/exit_speed.py |
| C2 | Traction budget visualization | analyzers/traction_budget.py, frontend TractionBudgetViz |
| C3 | Braking in distance units | templates/reference_points.py |
| C4 | Corner-specific speed targets | composers/corner_composer.py (target fields) |
| D1 | Max 2 focus areas | composers/focus_limiter.py |
| D2 | Confidence-building framing | composers/confidence_framer.py |
| D3 | Fear/confidence acknowledgment | taxonomy/causes.json (root_cause: "confidence"/"fear") |
| D4 | Mental imagery prompts | templates/mental_imagery.py |
| E1 | Lower brake threshold | analyzers/trail_brake.py (Block 3 detection) |
| E2 | Weight transfer coaching | analyzers/weight_transfer.py |
| E3 | Tire degradation curve | taxonomy causes: tire_degradation, thermal_fade_brakes |
| E4 | Throttle lift detection | analyzers/throttle_lift.py |
| F1 | Config-driven causes | taxonomy/causes.json |
| F2 | Kart vs car distinction | Templates keyed by vehicle_class |
| F3 | Multi-session trends | persistence/, CornerTrend |
| F4 | Context-aware text | Templates with parameterized placeholders |

## 15. Priority Order (Implementation)

**P0 — Quick wins**: D1 (focus_limiter), C4 (speed targets in corner_composer), A5 (exit cascade ranking)
**P1 — Core coaching**: A1 (reference points), A2 (symptom detector), A3 (trail brake), C1 (exit cascade), A4 (taxonomy)
**P2 — Progressive methodology**: B1 (progressive steps), B2 (drill levels), B3 (late apex reset), D2 (confidence framing)
**P3 — Physics depth**: E1 (brake threshold), E4 (throttle lift), C2 (traction budget), E2 (weight transfer)
**P4 — Architecture**: F1 (causes.json), F3 (corner_progression DB + trends), F4 (full template library)
**Frontend**: Parallel track after backend P1 complete

## 16. Spec Review Log

### Review 1 (2026-03-11) — All issues resolved

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| B1 | BLOCKER | Migration numbered 017, actual head is 039 | Changed to migration 040 |
| B2 | BLOCKER | Analyzer output has no persistence path; GET can't serve V3 | Added `analysis_json["coaching_v3"]` persistence in S13g2; GET endpoint reads it first, falls back to old engine |
| B3 | BLOCKER | Old `to_dict()` drops new fields on fallback | New `coaching/models.py` defines own `to_dict()`. Fallback path returns dict without V3 fields; frontend handles absence via optional chaining |
| W1 | WARNING | Stage S13d/S13e/S14 collide with existing | Renumbered to S13e/S13f/S13g/S13g2 |
| W2 | WARNING | driver_id unavailable in pipeline context | Resolved by setting `summary["driver_id"] = _drv_id` after DB lookup; S13f returns None when unavailable |
| W3 | WARNING | Exit cascade formula degrades at low kart speeds | Changed to full numerical integration; first-order approximation only for display when delta_v < 10% of v_exit |
| W4 | WARNING | theoretical_apex_total_pct undefined source | Documented: sqrt(lat^2 + lon^2) / friction_max at s_apex from theoretical_lap DataFrame |
| W5 | WARNING | RLS policy missing WITH CHECK | Added FOR ALL + WITH CHECK clause |
| W6 | WARNING | focus_areas silently capped to 2 | Explicitly documented: max 2 in focus_areas, rest in deferred_focus_areas; frontend updated |
| W7 | WARNING | Speed targets undefined when theoretical unavailable | Changed to `float | None`; corner_composer gates on presence before filling templates |
| S1 | SUGGESTION | Vehicle class resolution undefined | Added resolution order: session_meta → kart_id presence → default "car" |
| S2 | SUGGESTION | No causes.json schema validation | Added Pydantic v2 validation at import time in CauseTaxonomy |
| S3 | SUGGESTION | No minimum session count for trend sparkline | Minimum 3 sessions; below that trend = None |
| S4 | SUGGESTION | weight_shift needs vehicle mass | Added mass defaults: kart 165kg, car 750kg |
| S5 | SUGGESTION | No tier fallback tests | Added Tier 1/2/3 channel fixtures to testing strategy |
