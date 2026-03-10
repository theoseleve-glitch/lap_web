# Corner Detection & Coaching System Rebuild — Design

**Date**: 2026-03-10
**Approach**: Hybrid — New decomposition core, reuse physics + coaching logic

## Problem

The current corner detection (`corner_detection.py`) uses curvature peak detection which produces unreliable corner boundaries. The coaching system has been improved on the backend but the corner selection process remains broken. No corner type classification, no MRP detection, no understeer/oversteer causal analysis, no user-defined corner selection.

## Requirements Summary

- **Two modes**: Autonomous (track decomposition) and User-defined (click-to-select on track map)
- **Race condition**: If user defines corners before pipeline finishes, those are used; otherwise autonomous
- **Every section coached**: Straights, corners, transitions — all get coaching
- **Corner classification**: Geometry + speed-dependent (hairpin, sweeper, kink, compound, chicane, etc.)
- **MRP detection**: Maximum Rotation Point (peak yaw rate / peak steering / min speed / zero net pedal)
- **Two coaching engines**: Basic (GPS-only) and Advanced (rich data with steering/brake/RPM)
- **Understeer/oversteer**: Causal chain detection — detect, quantify severity+duration, attribute cause
- **Optimal line**: Exit-priority weighted per corner + full lap solver when available
- **Corner focus**: Exit importance based on following straight length

## Architecture

### New Modules

| File | Purpose | Lines (est) |
|------|---------|-------------|
| `track_decomposition.py` | Segment track into typed sections | ~500 |
| `corner_classifier.py` | Geometry + speed corner typing | ~300 |
| `mrp_detector.py` | MRP + corner event timeline | ~400 |
| `handling_detector.py` | Understeer/oversteer causal chains | ~500 |
| `coaching_basic.py` | GPS-only coaching engine | ~400 |
| `coaching_advanced.py` | Rich data coaching engine | ~500 |
| `corner_focus.py` | Exit importance scoring | ~100 |

### Reused Modules

| Module | Reused | Replaced |
|--------|--------|----------|
| `corner_analysis.py` | Time-loss decomposition, grip utilisation, `rank_improvement_opportunities()`, `summarize_corner_performances()` | `detect_corner_events()` apex → MRP detector |
| `coaching_engine.py` | `SessionCoaching` synthesis, drill generation, focus areas, narrative | Input format adapts to new `SectionCoaching` |
| `corner_mastery.py` | Brake release dynamics, corner targets | Unchanged |
| `corner_persistence.py` | DB persistence | Updated for new schema |

### Replaced

| Module | Replaced by |
|--------|-------------|
| `corner_detection.py` | `track_decomposition.py` + `corner_classifier.py` |

## Section 1: Track Decomposition Engine

### Algorithm

1. Build reference trace from first 2 valid laps (averaged GPS + speed)
2. Compute continuous curvature-vs-distance profile (smoothed Gaussian window)
3. Classify every point: STRAIGHT (low curvature, sustained >50m), TRANSITION (changing curvature), CORNER (high curvature, sustained)
4. Group adjacent corner+transition segments. Two corners <30m apart merge into compound/chicane
5. Classify each corner (geometry + speed):

| Type | Criteria |
|------|----------|
| Kink | Short (<40m), low curvature, speed drop <10% |
| Fast sweeper | Long (>80m), moderate curvature, min speed >70% of straight speed |
| Simple corner | Single curvature peak, clear entry/apex/exit |
| Hairpin | Tight radius (<25m), direction change >120deg |
| Double apex | Two curvature peaks, same direction |
| Compound | Multiple peaks, direction changes |
| Chicane | Two+ peaks, alternating L/R direction |
| Decreasing radius | Curvature increases through corner |
| Increasing radius | Curvature decreases through corner |

6. Corner focus scoring: straight length after each corner → exit importance 0.0-1.0

### Output

```python
@dataclass
class TrackSection:
    section_id: int
    section_type: str          # "straight" | "corner" | "transition"
    corner_type: str | None    # "hairpin" | "sweeper" | "simple" | etc.
    s_start: float             # distance (m)
    s_end: float
    direction: str | None      # "L" | "R" | None for straights
    geometric_apex: float | None
    exit_importance: float     # 0.0 - 1.0
    sub_corners: list[dict] | None  # for compound/chicane
```

## Section 2: MRP Detector + Corner Event Detection

### MRP Detection

For each corner, find the Maximum Rotation Point (peak direction change):

- **GPS-only**: Point where yaw rate (heading change / dt) is maximum AND speed near minimum. When both agree within ~5m, that's MRP. When they disagree, take yaw rate peak.
- **Rich data**: Peak steering angle as confirmation. All three agreeing = high confidence.
- **Validation**: MRP must fall between entry and exit. Fallback to geometric apex.

### Corner Event Timeline

Ordered events per corner:

| Event | Detection |
|-------|-----------|
| Brake initiation | accel_long < -1.0 m/s² |
| Turn-in | accel_lat exceeds ±0.3g |
| Trail-brake end | accel_long returns to ~0 while accel_lat still high |
| MRP | Peak yaw rate / min speed / zero net pedal |
| Throttle application | accel_long > +0.5 m/s² |
| Track-out | accel_lat drops below threshold |

### Output

```python
@dataclass
class CornerEvents:
    corner_id: int
    brake_point_m: float | None
    turn_in_m: float
    trail_brake_end_m: float | None
    mrp_m: float
    mrp_speed_mps: float
    mrp_yaw_rate: float
    throttle_application_m: float | None
    track_out_m: float
    geometric_apex_m: float
    mrp_apex_delta_m: float  # positive = late rotation
```

## Section 3: Understeer/Oversteer Detector (Causal Chain)

### Basic Engine (GPS-only)

Compare expected yaw rate (speed + reference curvature) vs actual yaw rate (heading change):

- `actual > expected` → oversteer
- `actual < expected` → understeer
- Magnitude: mild (<15%), moderate (15-30%), severe (>30%)
- Duration: contiguous distance/time

Causal attribution (GPS-only):
- Understeer + throttle increase → throttle-induced understeer
- Understeer + braking active → brake-induced understeer
- Oversteer + hard braking → trail-brake oversteer
- Oversteer + throttle → power oversteer
- Oversteer at exit + high speed → snap oversteer

### Advanced Engine (Rich Data)

Adds:
- Steering angle vs cornering radius divergence (slip angle proxy)
- Brake pressure vs deceleration (lock-up detection)
- Steering rate vs yaw response (understeer onset lag)
- RPM drop (wheel spin / traction loss)

### Output

```python
@dataclass
class HandlingEvent:
    corner_id: int
    event_type: str           # "understeer" | "oversteer"
    severity: str             # "mild" | "moderate" | "severe"
    s_start: float
    s_end: float
    duration_s: float
    magnitude: float          # 0.0-1.0
    cause: str                # "early_throttle" | "trail_brake_too_deep" | etc.
    cause_detail: str         # human-readable
    time_cost_s: float | None
    corner_phase: str         # "entry" | "mid" | "exit"
```

## Section 4: Dual Coaching Engines

### Channel Detection

```python
BASIC_CHANNELS = {"Speed (m/s)", "Latitude", "Longitude"}
ADVANCED_CHANNELS = {"Steering", "Brake", "Throttle", "RPM", "Gear"}

def get_coaching_tier(available_columns: set[str]) -> str:
    if len(ADVANCED_CHANNELS & available_columns) >= 3:
        return "advanced"
    return "basic"
```

### Basic Engine (`coaching_basic.py`)

Per section: braking analysis, line analysis, speed analysis (entry/apex/exit vs optimal), corner focus note, optimal line (exit-priority or lap solver), braking trace vs G-G envelope.

### Advanced Engine (`coaching_advanced.py`)

Everything from basic, plus: understeer/oversteer causal chains, throttle timing, steering input quality, gear selection, brake pressure modulation.

### Output

```python
@dataclass
class SectionCoaching:
    section: TrackSection
    events: CornerEvents
    handling: list[HandlingEvent]
    time_loss_total_s: float
    time_loss_braking_s: float
    time_loss_apex_s: float
    time_loss_exit_s: float
    primary_focus: str
    coaching_hints: list[str]
    corner_focus_note: str
    optimal_brake_point_m: float | None
    optimal_entry_speed_mps: float | None
    optimal_apex_speed_mps: float | None
    optimal_exit_speed_mps: float | None
    optimal_line_points: list[tuple[float, float]] | None
    handling_summary: str | None      # advanced only
    throttle_advice: str | None       # advanced only
    steering_advice: str | None       # advanced only
    gear_advice: str | None           # advanced only
```

## Section 5: User-Defined Corner Selection (Frontend)

### Flow

1. Upload starts → pipeline begins. Frontend receives GPS trace from first 2 laps immediately.
2. Track map renders. Banner: "Define your corners now, or let auto-detection handle it."
3. User clicks track → dot appears, prompt for entry/apex/exit (can skip).
4. Corners numbered in track-distance order.
5. "Done" saves via `POST /api/v1/sessions/{id}/user-corners`.

### Race Condition Resolution

Pipeline persist stage checks: user-defined corners exist? If yes → use those. If no → use autonomous.

### Post-Analysis

User can switch between Auto/Custom views, edit corners, re-trigger coaching.

### API Endpoints

- `POST /api/v1/sessions/{id}/user-corners` — save user-defined corners
- `GET /api/v1/sessions/{id}/user-corners` — retrieve
- `POST /api/v1/sessions/{id}/recoach` — re-run coaching with current definitions

### Frontend Component

New `CornerPicker.tsx` — extends GpsTrace canvas with click handlers:
- Click-to-place markers (green=entry, yellow=apex, red=exit)
- Snap-to-nearest-track-point
- Distance validation (entry < apex < exit)
- Corner list sidebar

## Section 6: Pipeline Integration

### Modified Stage s10b_corners.py

```
Step 10c:  track_decomposition.decompose()     → TrackSection list
Step 10c2: mrp_detector.detect_mrp()           → CornerEvents per section
Step 10c3: handling_detector.analyze()          → HandlingEvent list
Step 10d:  coaching_basic/advanced.generate()   → SectionCoaching list
Step 10e:  corner_analysis.rank_opportunities() → priority-ranked (REUSED)
Step 10f:  coaching_engine.synthesize()         → session narrative (REUSED)
```

### Database Schema Changes

Add to `corners` table:
- `corner_type` (text)
- `mrp_distance_m` (real)
- `mrp_speed_mps` (real)
- `mrp_yaw_rate` (real)
- `geometric_apex_m` (real)
- `exit_importance` (real)
- `handling_events_json` (text)
- `is_user_defined` (integer, default 0)
- `section_type` (text)

New table `user_corners`:
- `id`, `session_id`, `corner_index`, `lat_entry`, `lon_entry`, `lat_apex`, `lon_apex`, `lat_exit`, `lon_exit`, `s_entry`, `s_apex`, `s_exit`, `created_at`

## Section 7: Error Handling

Same `_safe_step()` pattern:
- Missing GPS → skip all corner coaching
- GPS but no speed → curvature-only decomposition, no MRP, degraded basic coaching
- No derivable yaw rate → curvature peak as MRP proxy
- Partial rich data → advanced engine runs with available channels, missing = null
- User corners with only click point → auto-detect boundaries from curvature
- Pipeline fails mid-coaching → partial results persisted
