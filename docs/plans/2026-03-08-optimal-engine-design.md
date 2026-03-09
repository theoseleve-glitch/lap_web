# Unified Optimal Lap Engine Design

**Date**: 2026-03-08
**Status**: Approved
**Scope**: `telemetry_tool` pipeline stage 10

## Problem

Three independent paths produce theoretical speed traces with no shared solver:
1. **kart_envelope adapter** → QSS solver → `v_env_mps` array
2. **lap_simulation** → forward-backward point-mass solver → `speed_profile` array
3. **theoretical_engine** → percentile envelope → `v_env_mps` array

Each outputs the same columns (`distance_m`, `v_env_mps`, `accel_max_mps2`, `brake_max_mps2`) but via different physics/statistics. No guarantee the same caps produce the same trace. Method provenance is a single string — no per-point source tracking.

## Approach

### 1. Unified Input Contract (`telemetry_tool/optimal_solver.py`)

All three cap sources produce a single `OptimalCaps` object:

```python
@dataclass
class OptimalCaps:
    distance_m: np.ndarray       # shared distance grid [m]
    v_cap: np.ndarray            # max speed at each point [m/s]
    ax_accel: np.ndarray         # max traction accel [m/s^2] per point
    ax_brake: np.ndarray         # max braking decel [m/s^2] per point (positive)
    curvature: np.ndarray        # curvature [1/m] at each point
    mu: np.ndarray | None        # friction coefficient per point (optional)
    cap_source: list[str]        # per-point provenance tag
    solver_version: str          # "optimal_v2_1.0"
```

**`cap_source` per-point tags**: `"envelope_p98"`, `"physics_hybrid"`, `"kart_qss"`, `"grip_map"`, `"friction_clamp"`.

### 2. Cap Producers (Modified Existing Modules)

Each producer fills `OptimalCaps` but does NOT run a solver:

**theoretical_engine** → `caps_from_percentile_envelope()`:
- Runs `compute_speed_percentile_envelope()` → fills `v_cap`
- Runs `compute_accel_envelope()` → fills `ax_accel`, `ax_brake`
- Sets `cap_source = ["envelope_pXX"] * n`

**lap_simulation** → `caps_from_vehicle_model()`:
- Fits `VehicleModel` from telemetry → fills `ax_accel`, `ax_brake` (speed-dependent)
- Computes `v_corner(s) = sqrt(mu * g / |curvature(s)|)` → fills `v_cap`
- Sets `cap_source = ["physics_hybrid"] * n`

**theoretical_adapter** → `caps_from_kart_envelope()`:
- Trains envelope → infers scalars → fills all caps from envelope limits
- Sets `cap_source = ["kart_qss"] * n`

### 3. Shared Forward-Backward Feasibility Solver

`solve_optimal_speed(caps: OptimalCaps) -> OptimalResult`:

Standard quasi-steady-state forward-backward algorithm:
1. **Cornering pass**: `v_corner[i] = min(v_cap[i], sqrt(mu[i] * g / |curvature[i]|))`
2. **Forward pass**: `v[i+1] = sqrt(v[i]^2 + 2 * ax_accel[i] * ds)`, capped by `v_corner[i+1]`
3. **Backward pass**: `v[i] = sqrt(v[i+1]^2 + 2 * ax_brake[i+1] * ds)`, capped by `v_corner[i]`
4. **Final**: `v_opt = min(forward, backward, v_corner)` per point

```python
@dataclass
class OptimalResult:
    distance_m: np.ndarray
    v_opt_mps: np.ndarray        # canonical optimal speed trace
    accel_profile_mps2: np.ndarray
    lap_time_s: float
    cornering_limited: np.ndarray  # bool per point
    accel_limited: np.ndarray
    brake_limited: np.ndarray
    cap_source: list[str]
    solver_version: str
    n_iterations: int
```

### 4. Migration-Safe Rollout

**Feature flag**: `OPTIMAL_V2` env var, default OFF.

**When OFF** (default):
- Pipeline runs exactly as before (existing 3-path cascade)
- `summary["theoretical_metrics"]` unchanged

**When ON**:
- After existing theoretical lap computation, run the new solver
- Store result as `summary["optimal_v2"]` alongside `summary["theoretical_metrics"]`
- Add `optimal_v2` to DB writes (new JSON column or extend `analysis_json`)
- API exposes `optimal_v2` via new endpoint + flag in scores

**Backward compatibility**:
- `summary["theoretical_metrics"]` always populated (legacy)
- `summary["optimal_v2"]` only when flag ON
- Speed-trace endpoint gains `?version=v2` parameter
- No existing endpoint breaks

### 5. Files Touched

| File | Change |
|------|--------|
| `telemetry_tool/optimal_solver.py` | New — OptimalCaps, OptimalResult, solve_optimal_speed() |
| `telemetry_tool/theoretical_engine.py` | Modified — caps_from_percentile_envelope() |
| `telemetry_tool/lap_simulation.py` | Modified — caps_from_vehicle_model() |
| `telemetry_tool/theoretical_adapter.py` | Modified — caps_from_kart_envelope() |
| `telemetry_tool/pipeline.py` | Modified — stage 10 unified solver, feature flag |
| `telemetry_tool/web/routes/data_v2.py` | Modified — optimal_v2 endpoint |
| `telemetry_tool/tests/test_optimal_solver.py` | New |
| `telemetry_tool/tests/test_optimal_pipeline.py` | New |

### 6. Output Schema

```json
{
  "optimal_v2": {
    "distance_m": [...],
    "v_opt_mps": [...],
    "lap_time_s": 45.23,
    "solver_version": "optimal_v2_1.0",
    "cap_source_summary": {"envelope_p98": 650, "grip_map": 350},
    "method": "percentile_envelope",
    "cornering_limited_frac": 0.35,
    "accel_limited_frac": 0.25,
    "brake_limited_frac": 0.40
  }
}
```
