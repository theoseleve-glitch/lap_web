# Sim Optimizer Solver + Reconstruction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the enhanced QSS solver that uses VehicleModel, reconstruct theoretical throttle/brake/steering traces, compute delta analysis with per-corner coaching, and wire everything into a 14-step pipeline orchestrator.

**Architecture:** Track geometry built from world_pos → enhanced QSS forward/backward sweep using VehicleModel limits → input reconstruction from speed profile → distance-aligned delta comparison → corner-by-corner coaching text. Pipeline orchestrator wraps all steps with `_safe_step()`.

**Tech Stack:** Python 3.13, numpy, pandas, existing kart_envelope TrackGeometry + reference_line modules.

**Spec:** `docs/superpowers/specs/2026-04-02-sim-optimizer-design.md` — Layers 2 + 3 + Delta Analysis + Pipeline.

**Depends on:** `sim_optimizer/ingest/` and `sim_optimizer/param_id/` (Plan 1 — completed).

---

## File Map

| File | Responsibility |
|------|----------------|
| `telemetry_tool/sim_optimizer/ingest/lap_align.py` | Distance-align raw samples for per-lap slicing |
| `telemetry_tool/sim_optimizer/solver/__init__.py` | Sub-package marker |
| `telemetry_tool/sim_optimizer/solver/qss_enhanced.py` | Enhanced QSS solver using VehicleModel |
| `telemetry_tool/sim_optimizer/solver/load_transfer.py` | Per-wheel load from suspension + G-forces |
| `telemetry_tool/sim_optimizer/reconstruction/__init__.py` | Sub-package marker |
| `telemetry_tool/sim_optimizer/reconstruction/input_trace.py` | Theoretical throttle/brake/steering from v*(s) |
| `telemetry_tool/sim_optimizer/reconstruction/trail_brake.py` | Combined-slip zone splitting |
| `telemetry_tool/sim_optimizer/analysis/__init__.py` | Sub-package marker |
| `telemetry_tool/sim_optimizer/analysis/delta.py` | Actual vs theoretical distance-aligned comparison |
| `telemetry_tool/sim_optimizer/analysis/corner_coaching.py` | Per-corner root cause + coaching text |
| `telemetry_tool/sim_optimizer/analysis/validation.py` | Cross-check vs iRacing optimal lap delta |
| `telemetry_tool/sim_optimizer/output/__init__.py` | Sub-package marker |
| `telemetry_tool/sim_optimizer/output/traces.py` | Serialize TheoreticalInputTrace for API/frontend |
| `telemetry_tool/sim_optimizer/output/summary.py` | Session-level summary JSON |
| `telemetry_tool/sim_optimizer/pipeline.py` | 14-step orchestrator with _safe_step() |

---

### Task 1: Lap alignment + solver sub-packages

**Files:**
- Create: `telemetry_tool/sim_optimizer/ingest/lap_align.py`
- Create: `telemetry_tool/sim_optimizer/solver/__init__.py`
- Create: `telemetry_tool/sim_optimizer/reconstruction/__init__.py`
- Create: `telemetry_tool/sim_optimizer/analysis/__init__.py`
- Create: `telemetry_tool/sim_optimizer/output/__init__.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_lap_align.py`

Lap alignment: given raw samples with `lap_dist_m` and `lap` number, slice into per-lap DataFrames resampled to uniform distance spacing.

- [ ] **Step 1: Write failing test**

Test that `align_lap(df, lap_number, ds)` returns a DataFrame with uniform distance grid and interpolated channels.

- [ ] **Step 2: Implement `lap_align.py`**

```python
def align_lap(df: pd.DataFrame, lap_number: int, ds_m: float, 
              dist_col: str, lap_col: str) -> pd.DataFrame | None:
    """Extract one lap and resample to uniform distance grid."""
```

- [ ] **Step 3: Run tests, commit**

---

### Task 2: Enhanced QSS solver

**Files:**
- Create: `telemetry_tool/sim_optimizer/solver/qss_enhanced.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_qss_enhanced.py`

The enhanced QSS uses VehicleModel instead of CapabilityEnvelope. Same forward/backward sweep algorithm as kart_envelope's `_compute_theoretical_lap_qss()` but calling VehicleModel methods.

- [ ] **Step 1: Write failing test — circular track**

A constant-curvature circle (kappa=0.04, 500m). Expected: v_max ≈ sqrt(ay_max/kappa), lap_time ≈ dist/v_max.

- [ ] **Step 2: Write failing test — straight track**

Kappa=0, 500m. Speed limited by power or v_max config.

- [ ] **Step 3: Write failing test — oval (straights + corners)**

Two straights + two corners. Verify braking and accel zones exist.

- [ ] **Step 4: Implement qss_enhanced.py**

Key structures:
```python
@dataclass
class SimTheoreticalResult:
    speed_profile_mps: np.ndarray
    distance_m: np.ndarray
    accel_profile_mps2: np.ndarray
    lap_time_s: float
    cornering_limited: np.ndarray
    accel_limited: np.ndarray
    braking_limited: np.ndarray
    gear_profile: np.ndarray
    method: str = "sim_qss"

def compute_sim_theoretical_lap(
    geometry: TrackGeometry,
    vehicle: VehicleModel,
    *,
    fuel_level_l: float = 30.0,
    config: SimOptimizerConfig | None = None,
) -> SimTheoreticalResult:
```

Algorithm: same forward/backward as kart_envelope but using:
- `vehicle.max_lateral_g(v)` for corner speed
- `vehicle.max_traction_g(v, gear)` for forward pass
- `vehicle.max_braking_g(v)` for backward pass  
- `vehicle.aero.drag_accel(v, m)` for drag
- `vehicle.powertrain.rolling_resistance_accel(v)` for rr
- `vehicle.powertrain.optimal_gear(v, m)` for gear at each point

- [ ] **Step 5: Run tests, commit**

---

### Task 3: Load transfer calculation

**Files:**
- Create: `telemetry_tool/sim_optimizer/solver/load_transfer.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_load_transfer.py`

- [ ] **Step 1: Write failing test**

Given lat/long accel + mass + geometry, compute per-wheel loads. Verify outer wheels load more in corners.

- [ ] **Step 2: Implement**

```python
@dataclass
class WheelLoads:
    lf: float; rf: float; lr: float; rr: float

def compute_wheel_loads(
    lat_accel_mps2: float, long_accel_mps2: float,
    mass_kg: float, *, cg_height_m: float = 0.35,
    track_width_m: float = 1.5, wheelbase_m: float = 2.5,
    weight_dist_front: float = 0.50,
) -> WheelLoads:
```

- [ ] **Step 3: Run tests, commit**

---

### Task 4: Trail braking combined-slip splitting

**Files:**
- Create: `telemetry_tool/sim_optimizer/reconstruction/trail_brake.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_trail_brake.py`

- [ ] **Step 1: Write failing test**

Given p-norm exponent and required lateral accel, compute available longitudinal accel. Verify: at zero lateral, full longitudinal available. At max lateral, zero longitudinal.

- [ ] **Step 2: Implement**

```python
def available_longitudinal(
    ay_required: float, ay_max: float, ax_max: float, p: float,
) -> float:
    """Max |ax| available given ay usage under p-norm combined limit."""

def split_combined(
    a_total_required: float, curvature: float, speed: float,
    vehicle: VehicleModel, *, braking: bool,
) -> tuple[float, float]:
    """Split total accel need into (a_long, a_lat) respecting combined limit."""
```

- [ ] **Step 3: Run tests, commit**

---

### Task 5: Input reconstruction

**Files:**
- Create: `telemetry_tool/sim_optimizer/reconstruction/input_trace.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_input_reconstruction.py`

- [ ] **Step 1: Write failing test — roundtrip**

Reconstruct inputs from a known speed profile, then verify the implied acceleration matches the original.

- [ ] **Step 2: Write failing test — throttle/brake mutual exclusion**

At any distance, throttle > 0 implies brake == 0 and vice versa (except in trail-brake zones where both can be small).

- [ ] **Step 3: Implement**

```python
@dataclass
class TheoreticalInputTrace:
    distance_m: np.ndarray
    speed_mps: np.ndarray
    throttle_pct: np.ndarray
    brake_pct: np.ndarray
    steering_deg: np.ndarray
    gear: np.ndarray
    limit_type: np.ndarray  # string array: "traction"|"braking"|"cornering"

def reconstruct_inputs(
    theoretical: SimTheoreticalResult,
    vehicle: VehicleModel,
    geometry: TrackGeometry,
    *,
    fuel_level_l: float = 30.0,
) -> TheoreticalInputTrace:
```

For each distance step:
- Steering: `atan(curvature * wheelbase)` + slip angle from `vehicle.tyre.inverse_lateral_slip()`
- Gear: `vehicle.powertrain.optimal_gear(speed, mass)`
- If accel > 0: throttle from `vehicle.powertrain.inverse_throttle()`, brake = 0
- If accel < 0: brake from `vehicle.brake.inverse_brake_pct()`, throttle = 0
- limit_type from theoretical result flags

- [ ] **Step 4: Run tests, commit**

---

### Task 6: Delta analysis

**Files:**
- Create: `telemetry_tool/sim_optimizer/analysis/delta.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_delta_analysis.py`

- [ ] **Step 1: Write failing test**

Given actual lap data and theoretical, compute delta. Verify cumulative delta is positive when actual is slower. Verify input deltas have correct signs.

- [ ] **Step 2: Implement**

```python
@dataclass
class LapDelta:
    distance_m: np.ndarray
    time_delta_s: np.ndarray
    speed_delta_mps: np.ndarray
    throttle_delta_pct: np.ndarray
    brake_delta_pct: np.ndarray
    steering_delta_deg: np.ndarray

def compute_lap_delta(
    actual_distance_m: np.ndarray,
    actual_speed_mps: np.ndarray,
    actual_throttle: np.ndarray,
    actual_brake: np.ndarray,
    actual_steering_deg: np.ndarray,
    theoretical: TheoreticalInputTrace,
) -> LapDelta:
```

Interpolate theoretical onto actual distance grid. Time delta = cumulative(ds/v_actual - ds/v_theoretical).

- [ ] **Step 3: Run tests, commit**

---

### Task 7: Corner coaching

**Files:**
- Create: `telemetry_tool/sim_optimizer/analysis/corner_coaching.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_corner_coaching.py`

- [ ] **Step 1: Write failing test**

Given a delta with known time loss at specific corners, verify coaching identifies root cause ("braked too late", "apex speed too low", etc).

- [ ] **Step 2: Implement**

```python
@dataclass
class CornerDelta:
    corner_id: int
    entry_dist_m: float
    apex_dist_m: float
    exit_dist_m: float
    time_loss_s: float
    root_cause: str
    coaching_text: str
    brake_point_delta_m: float
    apex_speed_delta_kph: float
    exit_throttle_delta_pct: float

def analyze_corners(
    delta: LapDelta,
    geometry: TrackGeometry,
    theoretical: TheoreticalInputTrace,
    *,
    min_curvature: float = 0.005,
) -> list[CornerDelta]:
```

Detect corners from curvature peaks. For each corner zone: compare brake point location, apex speed, throttle application point. Generate coaching text ranked by time loss.

- [ ] **Step 3: Run tests, commit**

---

### Task 8: Validation + output serialization

**Files:**
- Create: `telemetry_tool/sim_optimizer/analysis/validation.py`
- Create: `telemetry_tool/sim_optimizer/output/traces.py`
- Create: `telemetry_tool/sim_optimizer/output/summary.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_output.py`

- [ ] **Step 1: Implement validation**

```python
def validate_against_iracing_optimal(
    our_lap_time_s: float,
    iracing_optimal_delta: np.ndarray | None,
) -> dict[str, Any]:
```

- [ ] **Step 2: Implement traces serialization**

```python
def serialize_theoretical_trace(trace: TheoreticalInputTrace) -> dict[str, Any]:
    """Convert to JSON-serializable dict with lists instead of numpy arrays."""

def serialize_lap_delta(delta: LapDelta) -> dict[str, Any]: ...
```

- [ ] **Step 3: Implement summary**

```python
def build_session_summary(
    theoretical: SimTheoreticalResult,
    trace: TheoreticalInputTrace,
    corners: list[CornerDelta],
    vehicle: VehicleModel,
    validation: dict[str, Any],
) -> dict[str, Any]:
```

- [ ] **Step 4: Write tests, run, commit**

---

### Task 9: Pipeline orchestrator

**Files:**
- Create: `telemetry_tool/sim_optimizer/pipeline.py`
- Create: `telemetry_tool/tests/test_sim_optimizer/test_pipeline.py`

- [ ] **Step 1: Write failing test**

Feed synthetic_raw_df through full pipeline, verify it produces a result dict with theoretical lap time, input traces, and corner coaching.

- [ ] **Step 2: Implement pipeline**

```python
@dataclass
class SimOptimizerResult:
    vehicle_model: VehicleModel | None
    theoretical: SimTheoreticalResult | None
    input_trace: TheoreticalInputTrace | None
    delta: LapDelta | None
    corners: list[CornerDelta]
    summary: dict[str, Any]
    errors: list[str]

def _safe_step(name: str, fn, *args, **kwargs):
    """Catch exceptions, log, return None."""

def optimize_session(
    raw_df: pd.DataFrame,
    normalized_df: pd.DataFrame | None = None,
    *,
    config: SimOptimizerConfig | None = None,
) -> SimOptimizerResult:
    """14-step pipeline orchestrator."""
    # 1. Extract raw channels
    # 2. Unpack 360Hz _ST arrays
    # 3. Filter segments
    # 4. Lap split + classification
    # 5-9. Parameter identification (tyre/aero/powertrain/brake/suspension/mass)
    # 10. Assemble VehicleModel
    # 11. Build TrackGeometry from world positions
    # 12. QSS min-time speed profile
    # 13. Reconstruct theoretical inputs
    # 14. Delta analysis + corner coaching
```

- [ ] **Step 3: Run full test suite, commit**

---

### Task 10: Full regression check

- [ ] **Step 1: Run all sim_optimizer tests**
- [ ] **Step 2: Run existing kart_envelope tests** 
- [ ] **Step 3: Final commit**
