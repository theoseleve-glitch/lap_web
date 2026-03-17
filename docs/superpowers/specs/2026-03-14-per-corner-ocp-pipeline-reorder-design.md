# Per-Corner OCP Solver + Pipeline Reorder — Design Spec

**Date:** 2026-03-14
**Status:** Draft
**Scope:** Backend — `kart_envelope/solver/`, `telemetry_tool/pipeline/stages/`, `telemetry_tool/coaching/`

## Overview

Reverse the pipeline order so per-corner OCP runs BEFORE full-lap OCP. Build a per-corner mini-solver that produces optimal speed profiles and 3 ranked actionables per corner. The full-lap solver then composes per-corner solutions into an absolute optimal lap.

## Current Architecture (What Changes)

```
Current:  S10 full-lap OCP → S10c per-corner comparison (no solve)
Target:   S10a per-corner OCP (solve each corner) → S10b full-lap composition (learns from per-corner)
```

## Pipeline Stages (New Order)

### Stage S10a: Per-Corner OCP Solve

**Runs after:** S09 (physics models — curvature, friction, envelope, vehicle params)
**Runs before:** S10b (full-lap composition)

**Input:**
- `corners` — list of corner definitions (s_start, s_end, s_apex, direction)
- `track_geometry` — TrackGeometry from curvature profile
- `capability_envelope` — CapabilityEnvelope trained on all valid laps
- `session_scalars` — mu, p, b from envelope inference
- `best_lap_df` — driver's best lap DataFrame (for boundary speed estimates)
- `resampled_laps` — all laps dict (for per-lap comparison)

**Process (Two-Pass approach):**

**Pass 1 — Independent corner solves:**
For each corner, extract the geometry segment (s_start → s_end with ±50m margin for approach/exit), estimate entry/exit speeds from the driver's best lap at those distances, then solve a mini-OCP:

```python
def solve_corner_ocp(
    geometry_segment: TrackGeometry,   # curvature from s_start-50m to s_end+50m
    envelope: CapabilityEnvelope,
    entry_speed_mps: float,            # from best lap at s_start-50m
    exit_speed_mps: float,             # from best lap at s_end+50m
    scalars: SessionScalars,
) -> CornerOCPResult:
    """Solve min-time speed profile through one corner segment."""
```

The mini-solver uses the same QSS forward/backward sweep as the full-lap solver, but on a shorter segment with fixed boundary speeds. This is the existing `_qss_forward_backward()` logic applied to a sub-track.

**Pass 2 — Boundary reconciliation:**
After all corners are solved independently, reconcile boundaries:
- If corner N's optimal exit speed ≠ corner N+1's optimal entry speed, adjust using the higher constraint (the corner that demands the lower speed wins, since that's the physical limit).
- Compute straight segments between corners using simple acceleration from exit to entry.

**Output per corner:**
```python
@dataclass
class CornerOCPResult:
    corner_id: int
    distances: list[float]           # distance axis through corner
    optimal_speeds: list[float]      # min-time speed profile (m/s)
    optimal_apex_speed: float        # apex speed from OCP
    optimal_entry_speed: float       # entry speed from OCP
    optimal_exit_speed: float        # exit speed from OCP
    optimal_time_s: float            # OCP time through corner
    actual_apex_speed: float         # driver's best lap apex
    actual_entry_speed: float        # driver's best lap entry
    actual_exit_speed: float         # driver's best lap exit
    actual_time_s: float             # driver's time through corner
    time_delta_s: float              # actual - optimal (positive = time lost)
    speed_delta_apex: float          # actual - optimal apex (negative = slower)
    actionables: list[CornerActionable]  # exactly 3
```

### Stage S10a-coaching: Per-Corner Actionable Generation

Immediately after each corner solve, generate 3 ranked actionables by comparing the driver's actual behavior to the OCP solution:

```python
@dataclass
class CornerActionable:
    rank: int                    # 1, 2, or 3
    action: str                  # e.g., "Brake 5m later at the 50m board"
    impact_ms: float             # estimated time saving in ms
    category: str                # "braking" | "apex_speed" | "exit_traction" | "line" | "throttle"
    phase: str                   # "entry" | "mid" | "exit"
```

**Actionable derivation logic:**

The system compares driver vs OCP at three phases and ranks by time impact:

1. **Entry phase** — compare brake point distance and entry speed. If driver brakes too early/late → "Brake Xm earlier/later" with ms impact.
2. **Mid/apex phase** — compare apex speed. If driver's apex is slower → "Carry X km/h more through the apex" with ms impact.
3. **Exit phase** — compare exit speed and throttle application point. If driver gets on throttle late → "Get on throttle Xm earlier" with ms impact.

Sort by `impact_ms` descending, take top 3. Each actionable must be concrete and immediately executable — no abstract advice like "improve technique."

**Actionable text templates:**

| Category | Template | Example |
|----------|----------|---------|
| braking | "Brake {delta}m {earlier/later}" | "Brake 5m later" |
| apex_speed | "Carry {delta} km/h more through the apex" | "Carry 3.2 km/h more through the apex" |
| exit_traction | "Get on throttle {delta}m earlier" | "Get on throttle 8m earlier" |
| entry_speed | "Enter {delta} km/h {faster/slower}" | "Enter 4.1 km/h faster" |
| line | "Tighten apex by {delta}m" | "Tighten apex by 2m" |
| trail_brake | "Trail brake {delta}m deeper into the corner" | "Trail brake 12m deeper" |

### Stage S10b: Full-Lap Composition

**Runs after:** S10a (per-corner OCP)
**Input:** All `CornerOCPResult` + `track_geometry` + `capability_envelope`

**Process:**
1. Collect per-corner optimal speed profiles
2. Compute straight segments between corners using envelope acceleration limits
3. Stitch into a full-lap speed profile
4. Run a final full-lap OCP pass using the stitched profile as **warm-start initialization** — this lets the solver find a globally optimal solution that respects inter-corner dynamics while "learning" from the per-corner solutions
5. Output: `theoretical_lap` DataFrame (same format as current S10 output)

**Key insight:** The full-lap solver runs the same CasADi/QSS code as today, but initialized with per-corner solutions instead of a cold start. This should converge faster and produce better results because the warm start is already near-optimal at every corner.

**Output:**
- `theoretical_lap` — DataFrame with distance, speed, time columns (full lap)
- `sim_method` — "per_corner_composed" or "per_corner_warm_ocp"
- `corner_coaching` — list of CornerOCPResult.to_dict() for each corner
- `delta_map` — distance-aligned delta (same as current)
- `session_scalars` — mu, p, b (same as current)

### Stage S10c: Per-Corner Analysis (Unchanged)

Stays the same — compares driver actual vs theoretical at each corner. But now the theoretical reference comes from the composed full-lap result (which was informed by per-corner solves).

### Stage S13: Coaching Summary

Consumes the per-corner actionables to produce session-level coaching:
- Aggregates all per-corner actionables
- Ranks by total time impact across the lap
- Produces session-level focus areas from the most impactful categories

---

## New Files

| File | Purpose | Est. Lines |
|------|---------|------------|
| `kart_envelope/solver/corner_solver.py` | Per-corner QSS mini-solver | ~200 |
| `telemetry_tool/pipeline/stages/s10a_corner_ocp.py` | Pipeline stage: per-corner OCP orchestrator | ~180 |
| `telemetry_tool/pipeline/stages/s10a_actionables.py` | 3-actionable generation per corner | ~150 |
| `telemetry_tool/coaching/models.py` (modify) | Add `CornerOCPResult`, `CornerActionable` dataclasses | ~40 |
| `telemetry_tool/pipeline/stages/s10_theoretical.py` (modify) | Rename to S10b, accept warm-start from per-corner | ~30 changed |
| `telemetry_tool/pipeline/orchestrator.py` (modify) | Reorder S10a → S10b → S10c | ~20 changed |
| **Total new** | | **~530** |
| **Total modified** | | **~90** |

## Data Storage

Per-corner OCP results stored in `theoretical_data.corner_coaching_json` (same field, richer schema):

```json
[
  {
    "corner_id": 1,
    "optimal_speeds": [18.2, 17.8, 15.1, 14.3, 15.9, 17.2],
    "distances": [994.0, 1010.5, 1027.0, 1043.5, 1060.0, 1076.5],
    "optimal_apex_speed": 14.3,
    "optimal_entry_speed": 18.2,
    "optimal_exit_speed": 17.2,
    "optimal_time_s": 4.82,
    "actual_apex_speed": 12.8,
    "actual_time_s": 5.16,
    "time_delta_s": 0.34,
    "actionables": [
      {"rank": 1, "action": "Brake 5m later", "impact_ms": 180, "category": "braking", "phase": "entry"},
      {"rank": 2, "action": "Carry 3.2 km/h more through the apex", "impact_ms": 95, "category": "apex_speed", "phase": "mid"},
      {"rank": 3, "action": "Get on throttle 8m earlier", "impact_ms": 65, "category": "exit_traction", "phase": "exit"}
    ]
  }
]
```

## Frontend Changes

### Corner Detail View — VerdictSection

Replace current single `coaching_hint` with the **3 ranked actionables**:

```
  -0.34s          1. Brake 5m later                    -180ms
  Time Lost       2. Carry 3.2 km/h more at apex        -95ms
                  3. Get on throttle 8m earlier          -65ms
```

### Corner Detail View — TheoreticalBestPanel

Chart now shows:
- **White solid**: driver's selected lap (lap selector)
- **Green dashed**: per-corner OCP optimal speed trace (from `optimal_speeds`)
- X-axis: corner zone distances
- Delta shading between the two

### Corners & Coaching Tab — Below Track Map

Add a **full optimal lap speed trace** (from S10b composition) as an overlay on the track map or as a separate mini-chart showing the full theoretical lap.

### Overview Tab

Show top 3 session-level actionables (aggregated from per-corner, ranked by total impact).

## Solver Approach: QSS on Sub-Track

The per-corner solver reuses the existing QSS forward/backward sweep but on a shorter track segment:

```python
def solve_corner_qss(
    curvature: np.ndarray,       # curvature values for corner segment
    distances: np.ndarray,       # distance axis
    envelope: CapabilityEnvelope,
    v_entry: float,              # entry speed boundary condition
    v_exit: float,               # exit speed boundary condition
    mu: float,                   # friction coefficient
) -> tuple[np.ndarray, float]:   # (speeds, time)
    """QSS forward/backward sweep on corner sub-track.

    Forward pass: start at v_entry, brake/coast as curvature demands.
    Backward pass: start at v_exit, reverse-accelerate.
    Take minimum of forward/backward at each point.
    """
```

This is identical to `_qss_forward_backward()` in `kart_envelope/solver/min_time.py` but with explicit boundary speeds instead of wrap-around lap closure.

## Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| Corner solver fails | Skip that corner, mark `actionables: []`, continue with remaining corners |
| All corners fail | Fall back to current full-lap-only OCP (S10 as-is) |
| No envelope data | Fall back to percentile theoretical (Priority 2) |
| Fewer than 3 actionable deltas | Pad with "No additional improvement identified" |
| Full-lap warm-start fails | Fall back to cold-start full-lap OCP |

## Testing

- Unit test: `corner_solver.py` with synthetic straight + hairpin geometry
- Unit test: `s10a_actionables.py` with known speed deltas → verify 3 ranked outputs
- Integration test: full pipeline run with a session that has corners → verify per-corner results appear in `theoretical_data.corner_coaching_json`
- Regression test: existing full-lap theoretical results should not change significantly (warm-start should produce equal or better results)

## Out of Scope

- CasADi per-corner solver (use QSS only for now — simpler, faster)
- Optimal racing line (lateral position optimization) — only speed profile
- Multi-session trend learning in the solver
- Real-time / live coaching
