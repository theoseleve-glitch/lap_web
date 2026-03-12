# Theoretical Engine V2: Optimal Control Solver

> **Status**: Approved design
> **Date**: 2026-03-12
> **Goal**: Replace the QSS forward-backward solver with a CasADi/IPOPT optimal control solver that produces genuinely accurate theoretical lap times, especially in corners and transitions.

## Problem

The current theoretical engine (3-tier cascade: QSS -> hybrid physics -> percentile envelope) consistently predicts lap times that are **too slow** compared to the driver's actual best lap. The main error zones are:

1. **Corners**: Theoretical apex speeds are too low — the model underestimates available grip
2. **Transitions**: Braking zones and corner exits are wrong — the model brakes too early and gets on throttle too late

Root causes:
- **Point-mass assumption**: No load transfer modeling. Under braking, weight shifts forward giving the front tires MORE grip; the current model ignores this.
- **Constant friction coefficient**: `mu_max` is the same everywhere. Real tires produce less total grip under heavy load (load sensitivity), which changes corner-by-corner behavior.
- **QSS steady-state**: The forward-backward sweep assumes steady-state at each point. Transitions (braking-to-cornering, cornering-to-acceleration) are inherently transient.

## Solution: Optimal Control via Direct Collocation

Solve for the minimum-time speed profile as a nonlinear programming (NLP) problem using CasADi + IPOPT.

### Compute Budget

No time constraint. The solver runs as a Celery background job. Target: 2-10 minutes per lap. The existing QSS result is served immediately during upload; the OCP result upgrades it when ready.

## Design

### 1. Vehicle Dynamics Model

Enhanced point-mass with load transfer, replacing the simple point-mass assumption. (Not a bicycle/single-track model — there is no lateral position, heading, or yaw rate state. The 1D speed-along-centerline formulation is extended with load transfer effects on grip.)

**State**: Speed `v(s)` as a function of distance along the track centerline.

**Load transfer**:
- Longitudinal: `delta_Fz_front = m * a_long * h_cg / wheelbase`
  - Braking shifts weight forward -> more front grip, less rear grip
- Lateral: `delta_Fz_outer = m * a_lat * h_cg / track_width`
  - Cornering shifts weight to outside tires
- Combined: both effects simultaneous in transitions

**Vehicle parameters** (inferred from session data, with class defaults):

| Parameter | Symbol | Kart Default | Car Default | Source |
|-----------|--------|-------------|-------------|--------|
| Mass | m | 160 kg | 1200 kg | User-supplied or class default |
| CG height | h_cg | 0.25 m | 0.45 m | Class default |
| Wheelbase | L | 1.05 m | 2.6 m | Class default |
| Track width | tw | 1.2 m | 1.55 m | Class default |
| Frontal area | A | 0.5 m^2 | 2.0 m^2 | Class default |
| Drag coefficient | Cd | 0.5 | 0.35 | Class default |
| Downforce coefficient | Cl | 0 | 0.1 | Class default (0 for karts) |
| Air density | rho | 1.225 kg/m^3 | 1.225 kg/m^3 | Standard atmosphere (or from existing `aero_drag_factor_est`) |
| Rolling resistance | Cr | 0.015 | 0.012 | Class default (or from existing `rolling_resistance_est`) |
| Peak power | P_max | extracted | extracted | Session data: peak a_long * m * v |
| Peak brake force | F_brake_max | extracted | extracted | Session data: peak braking decel * m |
| Peak traction force | F_drive_max | extracted | extracted | Session data: peak positive a_long * m (low speed, traction-limited) |
| Reference friction | mu_ref | extracted | extracted | Session data: peak lateral g |

**Relationship to existing `telemetry_tool/vehicle_model.py`**: The existing `VehicleParameters` dataclass and `classify_vehicle()` function are reused by `param_extractor.py` for initial classification. The new `solver/vehicle_params.py` (note: NOT `vehicle_model.py`, to avoid name conflict) extends these with load-transfer-specific fields (h_cg, wheelbase, track_width). It imports from the existing module, not duplicates it.

### 2. Tire Model

Load-sensitive grip with combined-slip friction ellipse.

**Grip vs. load**:
```
mu(Fz) = mu_ref * (Fz / Fz_ref) ^ sensitivity
```
- `mu_ref`: extracted from driver's peak lateral g in their best corners
- `Fz_ref`: static vertical load per axle
- `sensitivity`: load sensitivity exponent (negative — grip coefficient drops as load increases)
  - Kart: -0.08
  - Car (slicks): -0.12
  - Car (road tires): -0.15

**Note on sign convention**: `sensitivity` is negative. The formula produces `mu < mu_ref` when `Fz > Fz_ref` (more load = less grip coefficient). This is the standard tire load sensitivity effect.

**Combined slip (friction ellipse)**:
```
(Fx / Fx_max(Fz))^2 + (Fy / Fy_max(Fz))^2 <= 1
```
where:
- `Fx_max(Fz) = mu(Fz) * Fz` — max longitudinal force at current vertical load
- `Fy_max(Fz) = mu(Fz) * Fz` — max lateral force at current vertical load (symmetric for simplicity)
- `mu(Fz)` is the load-sensitive coefficient from above

Enforced as an inequality constraint at every collocation node.

**Acceleration-domain equivalent** (used in OCP constraints, Section 3):
```
a_long_max(Fz) = mu(Fz) * (Fz / m_total) = mu(Fz) * g * (Fz / Fz_static)
a_lat_max(Fz)  = mu(Fz) * (Fz / m_total) = mu(Fz) * g * (Fz / Fz_static)
```
where `Fz` is the current vertical load including load transfer effects (computed from `a_long` and `a_lat` at that node via Section 1's load transfer equations). This creates an implicit coupling: the grip limit depends on the acceleration, which depends on the grip limit — resolved by the NLP solver simultaneously.

**Why this fixes corner speeds**: In a fast sweeper (low lateral load transfer), total grip is higher than in a tight hairpin (high lateral load transfer). The tire model captures this automatically. Trail braking benefits are modeled because longitudinal deceleration + lateral grip interaction is physically correct.

### 3. Optimal Control Formulation

**Objective**: Minimize lap time
```
minimize T = integral(1 / v(s), ds) over track length S
```

**Decision variables** at each of N collocation nodes:
- `v[i]`: speed (m/s)
- `u_throttle[i]`: throttle fraction [0, 1]
- `u_brake[i]`: brake fraction [0, 1]

**Dynamics constraints** (adjacent nodes):
```
v[i+1]^2 = v[i]^2 + 2 * a_net[i] * ds[i]
```
where:
```
a_net = a_drive - a_brake - a_drag - a_rolling
a_drive = min(u_throttle * P_max / (m * v), F_drive_max / m)   # power-limited OR traction-limited
a_brake = u_brake * F_brake_max / m
a_drag = 0.5 * rho * Cd * A * v^2 / m                         # rho, Cd, A from vehicle params table
a_rolling = Cr * g                                              # Cr from vehicle params table
a_lat = v^2 * kappa(s)   (imposed by track curvature)
```

**Grip constraint** (friction ellipse at each node):
```
(a_long / a_long_max(Fz))^2 + (a_lat / a_lat_max(Fz))^2 <= 1
```
where `a_long_max` and `a_lat_max` are load-dependent via the tire model.

**Complementarity** (no simultaneous throttle + brake):
The hard constraint `u_throttle * u_brake = 0` is non-smooth and will cause IPOPT convergence issues. Instead, use a relaxed formulation:
```
u_throttle * u_brake <= epsilon   (epsilon = 1e-4)
```
This is a smooth inequality that IPOPT handles well. In practice, the optimal solution naturally avoids simultaneous throttle+brake because it wastes energy, so the relaxation rarely activates.

**Boundary**: `v[0] = v[N]` (lap continuity for circuit tracks).

### 4. Adaptive Mesh Refinement

1. **Initial mesh**: 500 nodes, uniform spacing
2. **Solve** with IPOPT
3. **Identify high-gradient regions**: where `|dv/ds|` exceeds threshold (corners, braking zones)
4. **Refine**: double node density in those regions
5. **Re-solve** with warm start from previous solution
6. **Converge**: stop when max speed change between refinements < 0.05 km/h
7. Typically 2-3 passes, final mesh ~1000-1500 nodes

### 5. Data Tier System

The solver adapts to available telemetry channels.

**Tier 1 — GPS + Accelerometer (baseline)**:
- Track geometry: curvature kappa(s) from GPS heading
- Vehicle params: extracted from peak lateral g, peak longitudinal accel, peak braking decel
- Friction calibration: mu_ref anchored to driver's best corner performance
- **Understeer/oversteer detection** from yaw rate residual (no steering data needed):
  - `yaw_expected = v * kappa(s)` (what curvature demands)
  - `yaw_measured = d(heading)/dt` (from GPS heading changes)
  - `residual = (yaw_measured - yaw_expected) * sign(kappa)`
  - Positive = oversteer (more rotation than geometry requires), Negative = understeer (less rotation)
  - Same approach as `corner_diagnosis.py`'s `_compute_yaw_residual()`
  - Per-corner understeer/oversteer classification included in OCP result
- Output: optimal speed profile v(s) + per-corner handling balance

**Tier 2 — GPS + Accel + Throttle/Brake**:
- All of Tier 1, plus:
- Power model refinement from actual throttle trace (non-linear power delivery, turbo lag, two-stroke powerband)
- Brake model refinement from actual brake data
- Output adds: optimal throttle/brake traces for overlay comparison

**Tier 3 — GPS + Accel + Pedals + Steering**:
- All of Tier 2, plus:
- **Refined understeer/oversteer** from actual slip angles:
  - Front slip angle: `alpha_f = steering_angle / steering_ratio - atan(v * kappa * L_front / v)`
  - Understeer gradient: `K_us = (alpha_f - alpha_r) / a_lat` — a true vehicle dynamics measurement
  - Replaces Tier 1's yaw-residual approximation with a physics-grounded slip angle calculation
- Tire model parameter refinement from estimated slip angles (Pacejka curve fitting)
- Output adds: per-corner understeer gradient, slip angle estimates, refined tire model parameters

**Tier detection**: Auto-detected from available DataFrame columns (same approach as corner_diagnosis.py `_detect_tier`).

**Constraint**: Tier 1 must produce an accurate result on its own. Tiers 2-3 refine but are not required.

### 6. Calibration Loop

Anchors the model to the driver's actual vehicle performance.

1. Extract driver's peak capabilities from session data:
   - `mu_ref` = max observed lateral g across all corners
   - `P_max` = max observed (a_long * m * v) on straights
   - `F_brake_max` = max observed braking decel * m
2. Solve OCP with these parameters
3. Compare theoretical to actual across three dimensions:
   - **Grip check**: Compare theoretical apex speeds to driver's actual best-corner apex speeds. If systematically off → adjust `mu_ref`
   - **Power check**: Compare theoretical straight-end speeds to actual. If off → adjust `P_max`
   - **Brake check**: Compare theoretical braking distances to actual. If off → adjust `F_brake_max`
4. Adjustment: scale each parameter by the ratio `actual / theoretical` for the relevant metric
5. Re-solve with updated parameters
6. Typically converges in 1-2 passes. If residual > 3% after 3 passes, accept and flag in `solver_meta`

**Note**: This is an acceptable simplification — the three parameters are largely orthogonal (grip dominates corners, power dominates straights, braking dominates entry zones). A full coupled calibration is out of scope.

### 7. Pipeline Integration

**New module structure**:
```
telemetry_tool/solver/
    __init__.py
    vehicle_params.py     — Extended vehicle params (imports from existing vehicle_model.py, adds h_cg/wheelbase/tw)
    load_transfer.py      — Longitudinal + lateral load transfer computations
    tire_model.py         — Load-sensitive grip, friction ellipse
    track_model.py        — Curvature profile -> collocation mesh (adaptive); reuses existing curvature_1pm column
    ocp_solver.py         — CasADi problem formulation + IPOPT solve (warm_start_init_point='yes')
    calibrator.py         — Multi-parameter calibration loop (mu_ref, P_max, F_brake_max)
    param_extractor.py    — Extract vehicle params from session DataFrame
    result.py             — TheoreticalResult dataclass
```

**Note on `track_model.py`**: Reuses the existing `curvature_1pm` column from the curvature profile DataFrame (computed in `s10_theoretical.py`). Does NOT recompute curvature from GPS.

**Stage 10 cascade** (updated):
```
OCP (background, Celery) -> QSS (sync, immediate) -> hybrid -> percentile
```

- Upload triggers synchronous pipeline as today (QSS result served immediately)
- OCP job queued to Celery `pipeline` queue
- When OCP completes: stores result in `analysis_json["theoretical_ocp"]`
- Frontend detects `theoretical_ocp` and uses it over QSS
- If OCP fails: QSS result remains, no regression

**Celery job flow**:
1. Extract vehicle params from session data
2. Build adaptive track mesh from curvature profile
3. Solve OCP (warm-started from QSS speed profile)
4. Calibration pass if error > 1%
5. Store result in DB (`analysis_json["theoretical_ocp"]`)

**Result schema** (stored in `analysis_json["theoretical_ocp"]`):
```json
{
  "lap_time_s": 62.3,
  "speed_profile": [{"distance_m": 0, "speed_mps": 25.1, "a_long": 0.3, "a_lat": 0.1}, ...],
  "corner_times": [{"corner_id": 1, "entry_speed_mps": 30.2, "apex_speed_mps": 22.1, "exit_speed_mps": 28.5, "time_s": 3.2}, ...],
  "vehicle_params_used": {"mass": 160, "mu_ref": 1.15, "P_max": 22000, ...},
  "calibration": {"mu_ref_initial": 1.2, "mu_ref_final": 1.15, "passes": 1, "residual_pct": 0.8},
  "solver_meta": {"nodes": 1200, "iterations": 142, "converged": true, "wall_time_s": 185.3},
  "tier": 1
}
```

### 8. Dependencies

- **CasADi**: `pip install casadi` (pin version, e.g., `casadi>=3.6,<4.0`) — includes bundled IPOPT solver, no separate install
- Added to `requirements.txt` and Dockerfile
- No other new dependencies
- **IPOPT solver options** (set in `ocp_solver.py`):
  - `warm_start_init_point`: `'yes'` (required for QSS warm-start to work)
  - `print_level`: `0` (suppress IPOPT output in production; set to `5` for debugging)
  - `max_iter`: `2000` (generous upper bound)
  - `tol`: `1e-6` (convergence tolerance)
  - `acceptable_tol`: `1e-4` (acceptable convergence for difficult problems)

### 9. No Breaking Changes

- Existing QSS path completely untouched
- OCP is purely additive: new Celery job + new key in analysis_json
- Feature-flagged: `THEORETICAL_OCP=1` env var (default ON, set =0 to disable)
- Frontend: check for `theoretical_ocp` key; if absent, use existing QSS data

### 10. Data API Changes

The existing `GET /api/v1/sessions/<id>/speed-trace` endpoint (in `routes/data_v2.py`) currently serves `analysis_json["optimal_v2"]`. Changes needed:

1. **Speed-trace endpoint**: Add `?source=ocp` query parameter. When present AND `analysis_json["theoretical_ocp"]` exists, serve the OCP speed profile. Default behavior unchanged (serves QSS/optimal_v2).
2. **Session detail endpoint**: Include `theoretical_ocp_available: true/false` in the session detail response, so the frontend knows whether to request OCP data.
3. **Corners endpoint**: When OCP data available, overlay OCP per-corner speeds alongside QSS in the existing corner data response.
4. **No new endpoints** — extend existing ones with backward-compatible additions.

## Testing Strategy

### Unit Tests

| Module | Test | Assertion |
|--------|------|-----------|
| vehicle_model | Known mass/CG/accel -> load transfer | Hand-calculable delta_Fz values |
| tire_model | Load-sensitive grip at Fz_ref | mu = mu_ref exactly |
| tire_model | Grip at 2x Fz_ref | mu < mu_ref (diminishing returns) |
| tire_model | Friction ellipse boundary | Combined (Fx, Fy) on ellipse = 1.0 |
| track_model | Simple oval curvature mesh | Correct kappa values, nodes denser in corners |
| ocp_solver | Constant-radius circle | Optimal speed = sqrt(mu * g * R) within 0.1% |
| calibrator | Synthetic session with peak g = 1.2 | mu_ref set to 1.2 |
| param_extractor | Known session data | Correct P_max, mu_ref, F_brake_max |

### Integration Test

- **Synthetic oval**: 500m track, two 50m-radius semicircles (R=50m), two ~93m straights
- Known vehicle: 1200kg, 150kW, mu=1.0, no aero, no rolling resistance (Cd=0, Cr=0)
- **Point-mass analytical reference** (no load transfer, used as a sanity bound):
  - Corner speed: `v_corner = sqrt(mu * g * R) = sqrt(1.0 * 9.81 * 50) = 22.15 m/s`
  - Corner time: `t_corner = pi * R / v_corner = 7.09s` per semicircle
  - Straights: accelerate from v_corner to power-limited top speed, brake back to v_corner
  - The OCP result WITH load transfer should produce a lap time **slightly faster** than this point-mass reference (load transfer redistributes but the NLP optimizes through it)
- **Tolerance**: OCP lap time must be within 1.0s of the point-mass analytical reference
- This is the regression gate — if the solver produces a time MORE than 1.0s slower than point-mass, something is wrong

### Validation (Manual)

- Run OCP on 3-5 existing sessions
- Compare: OCP theoretical vs. QSS theoretical vs. actual best lap
- Success: OCP within 1-2% of actual best lap time
- Per-corner: OCP apex speeds within 3 km/h of driver's actual best apex speed

### Convergence Monitoring

- `solver_meta` stored with every result
- Non-convergence > 10% of sessions -> investigate
- Non-convergence falls back to QSS (no user-visible error)

## Out of Scope

- Tire thermal model (temperature effects on grip)
- Aerodynamic map (downforce vs. speed curve beyond linear Cl)
- Track surface grip variation (wet patches, grip changes by corner)
- Multi-line optimization (choosing different racing lines)
- Real-time solver (this is batch/background only)
- Coaching re-run with OCP result (future enhancement — requires pipeline context that isn't available in a standalone Celery job)
- Frontend UI changes (frontend reads the new data via existing endpoints with minor additions; visual changes are a separate task)
