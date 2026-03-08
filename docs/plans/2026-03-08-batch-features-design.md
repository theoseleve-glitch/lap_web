# Batch Features Design — Drills, Endurance, Boundaries, Raceline, Replay, Snapshots

**Date**: 2026-03-08
**Status**: Approved
**Scope**: 6 features spanning analysis, coaching, geometry, optimization, and testing

## Feature 1: Drills Layer

**New file**: `telemetry_tool/drills.py`

### Data Structures

```python
@dataclass
class Drill:
    drill_id: str              # "brake_release_progressive"
    title: str
    goal: str
    setup: str
    execution: str
    success_criteria: dict     # {"release_linearity_r2": ">0.8"}
    required_channels: list    # ["Brake (%)"]
    issue_types: list          # ["over_drop", "late_release"]

    def to_dict(self) -> dict: ...

@dataclass
class PracticePlan:
    warmup: dict               # {"laps": 3, "focus": "baseline pace"}
    drills: list[dict]         # [{drill_id, corner_ids, reps, target_metric}]
    evaluation: dict           # {"laps": 2, "compare_to": "baseline"}
    reflection: str
    channel_warnings: list     # ["needs brake sensor for X"]
    provenance_ref: dict       # lightweight provenance

    def to_dict(self) -> dict: ...
```

### Drill Registry

8 drills mapped from detected issues:

| Drill ID | Issue Types | Required Channels |
|----------|-------------|-------------------|
| `brake_release_progressive` | over_drop, late_release | Brake (%), accel_long |
| `trail_brake_hold` | under_rotation | Brake (%), yaw_rate |
| `rotation_timing` | power_before_rotation, rotation_too_late | yaw_rate, accel_long |
| `mrp_consistency` | mrp_drift, mrp_plateau | yaw_rate |
| `compound_rhythm` | compound_setup_error | speed, accel_long |
| `kink_sacrifice` | kink_trap | speed, position |
| `line_precision` | line_variance | position |
| `exit_commitment` | early_lift, traction_limited | accel_long, speed |

### Functions

```python
DRILL_REGISTRY: list[Drill]  # module-level constant

def map_issues_to_drills(coaching_v2: dict, available_channels: list[str]) -> list[dict]:
    """Select drills measurable with available channels."""

def generate_practice_plan(coaching_v2: dict, available_channels: list[str], max_drills: int = 2) -> PracticePlan:
    """Build session plan: warmup + drills + evaluation + reflection."""
```

### Pipeline

Step 13d after coaching_v2. Store in `summary["practice_plan"]`.

---

## Feature 2: Endurance Analytics

**Extend**: `telemetry_tool/stint_analysis.py` (already has `detect_stints()`, `compute_stint_metrics()`, pace fade, tyre cliff)

### New Functions

```python
def detect_traffic_losses(lap_df, reference_df, corners):
    """Detect micro-lifts (accel drops > 0.5 m/s² for < 1s outside braking zones)
    and delta spikes (> 50ms in 10m window). Returns traffic_loss_s per corner."""

def classify_risk_reward_passes(corner_performances, all_lap_dfs, corners):
    """Classify corners where attempted gains increase variance/risk.
    High variance + small net delta = risky. High variance + large gain = rewarding."""

def generate_team_coaching(stint_metrics, driver_style_per_stint=None):
    """Identify weakest stint/driver, generate 3 objectives in CoachingV2 format."""
```

### Pipeline

Step 10e (after corner analysis). Store in `summary["endurance"]`.

---

## Feature 3: Boundary Estimation

**Extend**: `telemetry_tool/reference_line.py` (already has `compute_track_width_estimate()`)

### Data Structure

```python
@dataclass
class TrackBoundaries:
    distance_m: np.ndarray
    left_offset_m: np.ndarray
    right_offset_m: np.ndarray
    confidence: np.ndarray       # 0-1 per bin
    sample_count: np.ndarray

    def to_dict(self) -> dict: ...
```

### Function

```python
def estimate_track_boundaries(
    resampled_laps: dict, ref_line: pd.DataFrame,
    percentile: float = 95, min_width_m: float = 4.0, max_width_m: float = 20.0,
    smooth_window: int = 15,
) -> TrackBoundaries:
    """Estimate L/R boundaries from perpendicular offsets of all lap XY traces.
    Smooth with Savitzky-Golay. Clamp to [min_width, max_width].
    Confidence = min(1.0, sample_count / 5)."""
```

### Pipeline

Step 9b (after reference line). Store in `summary["track_boundaries"]`.
API: `GET /sessions/<id>/boundaries`.

---

## Feature 4: Raceline Optimizer

**New file**: `telemetry_tool/raceline_optimizer.py`

### Data Structures

```python
@dataclass
class LineVariant:
    variant_id: str            # "C3_late_apex"
    corner_id: int
    apex_type: str             # "early" | "neutral" | "late"
    offset_profile_m: list     # lateral offset at each s-bin
    estimated_time_s: float
    delta_vs_baseline_s: float
    constraints_hit: list

    def to_dict(self) -> dict: ...

@dataclass
class RacelineResult:
    corner_results: dict       # corner_id → LineVariant (best)
    total_delta_s: float
    n_variants_evaluated: int

    def to_dict(self) -> dict: ...
```

### Functions

```python
def generate_line_variants(corner, ref_line, boundaries, n_variants=3):
    """Generate early/neutral/late apex via curvature shaping within boundaries."""

def simulate_variant_time(curvature_profile, speed_at_entry, friction_mu):
    """Point-mass sim: v_max = sqrt(mu*g/kappa), forward/backward integration."""

def optimize_corner_lines(corners, ref_line, boundaries, friction_model, compound_groups=None):
    """Pick min-time variant per corner. Joint optimization for compounds."""
```

### Pipeline

Step 10f (after boundaries). Gated by `enable_raceline_optimizer` config flag (default False).
Store in `summary["raceline_optimization"]`.

---

## Feature 5: Replay Consistency — Master Distance Grid

**Extend**: `telemetry_tool/resampling.py`

### New Functions

```python
def build_master_grid(resampled_laps: dict, n_points: int = 1000) -> np.ndarray:
    """Canonical distance grid from median of all lap ranges."""

def align_to_grid(data: np.ndarray, data_dist: np.ndarray, master_grid: np.ndarray) -> np.ndarray:
    """Align any distance-indexed array to master grid via np.interp."""

def event_to_grid_index(s_position: float, master_grid: np.ndarray) -> int:
    """Convert s_position to nearest grid index via searchsorted."""
```

### API Changes

All replay endpoints use `build_master_grid()` + `align_to_grid()`. Event markers returned as `{s_position, grid_index}`.

---

## Feature 6: Golden Snapshot Tests

**New file**: `telemetry_tool/tests/test_golden_snapshots.py`

Self-consistency tests (run pipeline twice with deterministic=True, compare JSON). Covers:
- Speed trace arrays
- Corner analysis + events + coaching
- Theoretical envelope + metrics
- Coaching V2 output

CI gate: snapshot changes require intentional update.

---

## Files Touched

| File | Changes |
|------|---------|
| `drills.py` (NEW) | Drill registry, issue→drill mapping, practice plan generator |
| `stint_analysis.py` | traffic_losses, risk_reward_passes, team_coaching |
| `reference_line.py` | TrackBoundaries, estimate_track_boundaries() |
| `raceline_optimizer.py` (NEW) | LineVariant, RacelineResult, optimize_corner_lines() |
| `resampling.py` | build_master_grid(), align_to_grid(), event_to_grid_index() |
| `pipeline.py` | Wire steps 9b, 10e, 10f, 13d |
| `reporting_html.py` | Practice plan, endurance, boundaries, raceline sections |
| `web/routes/data_v2.py` | /boundaries endpoint, replay alignment, coaching_v2 |
| `tests/test_drills.py` (NEW) | Drill mapping + plan generation tests |
| `tests/test_endurance.py` (NEW) | Traffic + risk/reward + team coaching tests |
| `tests/test_boundaries.py` (NEW) | Synthetic scatter boundary tests |
| `tests/test_raceline.py` (NEW) | Toy track late-apex test |
| `tests/test_replay_grid.py` (NEW) | Array alignment + index consistency tests |
| `tests/test_golden_snapshots.py` (NEW) | Self-consistency snapshot tests |

## Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| No XY position | F3 boundaries + F4 raceline skipped |
| No brake channel | Drills → channel_warnings |
| Single stint | F2 → single-stint summary |
| < 3 laps | F2 traffic + F3 boundaries → low confidence |
| No theoretical | F4 uses friction model only |
| enable_raceline_optimizer=False | F4 skipped |
| No coaching_v2 | F1 drills skipped |
