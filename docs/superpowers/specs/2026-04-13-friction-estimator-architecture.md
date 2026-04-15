# Friction Estimator Architecture — Force-Envelope Decomposition

## Problem Statement

The current grip model conflates road surface friction, tire state, vehicle dynamics, and measurement uncertainty into a single scalar `mu = F_tang / Fz` per cell. This is physically wrong because:

1. Peak μ decreases with increasing Fz (load sensitivity)
2. Combined slip couples Fx and Fy non-separably
3. Tire transient dynamics mean instantaneous force ≠ steady-state envelope
4. The multiplicative factorization `mu_surface × f_tire × f_terrain` assumes separability that doesn't hold in practice

## Corrected Architecture

### Layer separation (kept from previous design)

```
road_surface_potential(s, n, t)   — what the asphalt offers
tire_state(wheel, t)              — temperature, pressure, wear, compound dynamics
vehicle_state(t)                  — per-wheel loads, slip, orientation
used_force(wheel, t)              — observed (Fx, Fy, Fz) from telemetry
observability(wheel, t)           — can we learn anything from this sample?
uncertainty(s, n)                 — how confident is the surface estimate?
```

### Core correction: force-envelope, not scalar-μ

Replace:
```
available_mu = mu_surface × f_tire × f_terrain   ← WRONG (assumes separability)
```

With:
```python
Fx_cap, Fy_cap = TireModel(
    alpha,     # slip angle
    kappa,     # slip ratio
    Fz,        # normal load (already includes terrain + aero)
    camber,    # wheel camber angle
    T_surface, # tire surface temperature
    T_core,    # tire core temperature
    p_hot,     # hot tire pressure
    wear,      # remaining tread
    params,    # Pacejka/brush model parameters
) * lambda_surface(s, n, t)
```

Where:
- `TireModel(...)` handles load sensitivity, combined slip, camber, pressure, temp
- `lambda_surface(s, n, t)` is the road-side scaling latent (the only unknown the road contributes)
- `Fz` already contains banking, compression, and aero effects from the adaptive rigid-body model

### Surface update: inverse tire problem, not division

```
Given: Fx_obs, Fy_obs, Fz_obs at wheel i (from per-wheel force reconstruction)
Given: alpha_i, kappa_i, camber_i, T_i, p_i, wear_i (from kinematic + tire state model)
Find:  lambda_surface that minimizes
       || (Fx_obs, Fy_obs) - TireModel(...) × lambda ||²
```

This stays valid when the tire model is nonlinear. The division `mu_used / f_tire` is only the linear approximation of this inverse.

---

## 7 Design Requirements

### 1. Force envelope, not scalar μ

The core state is:
```
lambda_surface(s, n, t)           — road surface scaling (≈ 1.0 on clean dry asphalt)
tire_state_i(t)                   — dynamic thermal/wear/pressure per wheel
force_usage_i(t)                  — in combined-slip (Fx, Fy) space
```

Not a single "available μ" number.

### 2. Excitation-gated observability

Do NOT gate updates with `used / available` (circular). Instead use an excitation vector:
- |alpha| above threshold
- |kappa| above threshold
- Normalized force demand sufficient
- State estimate confidence high
- No confounders (wheel lift, ABS chopping, severe transient)
- Sensitivity of lambda_surface to the measurements is sufficient

### 3. Online filtering + offline smoothing

```
Online:  fixed-lag Kalman/EKF per cell — for live coaching
Offline: batch smoother or MHE over full session — for track model accumulation
```

The accumulated track model uses the offline-smoothed version, not the forward pass.

### 4. Spatial correlation in the surface field

Adjacent cells share information via a spatial prior:
```
lambda_surface ~ GP(mean=1.0, kernel=Matern_3/2(lengthscale=5m))
```

Observing grip at one apex cell improves the estimate at nearby cells. Store:
- Local mean
- Local variance
- Spatial kernel hyperparameters
- Evidence count by condition bucket

### 5. Dynamic tire state model

Tire state is a latent dynamical system, not a static lookup:
```
dT_surface/dt = f(heat_generation, convection, conduction_to_core)
dT_core/dt    = f(conduction_from_surface, bulk_cooling)
dp_hot/dt     = f(T_surface, T_core, gas_law)
dwear/dt      = f(slip_energy, temperature, load)
```

Tire thermodynamics matter: a cold tire on lap 1 and a hot tire on lap 20 produce different forces at the same slip conditions. The surface estimator must not attribute this difference to the road.

### 6. Dedicated road state estimator

Separate road bank/grade from chassis roll/pitch:
```
x_road = [bank(s), grade(s), kappa_v(s), roughness(s)]
```

Fuse IMU, orientation, ride height, and shock channels via a dedicated observer (factor graph or EKF). The friction estimator consumes clean road geometry, not raw roll/pitch.

### 7. Uncertainty into the planner

The OCP consumes:
```
lambda_surface_mean(s, n)
lambda_surface_std(s, n)
tire_state_uncertainty
road_state_uncertainty
```

And produces:
- **Nominal line**: best estimate, no margin
- **Robust line**: constraints tightened by σ (covariance-aware)
- **Exploitable line**: where confidence is high, push; where low, leave margin

---

## Implementation Phases

### Phase A — Physically correct estimator

| Module | What | Dependencies |
|--------|------|-------------|
| `wheel_kinematics.py` | Reconstruct slip angle α and slip ratio κ per wheel from velocity, yaw rate, steering, wheel speed | Velocity, steering, yaw rate |
| `combined_slip_tire_model.py` | Pacejka-like combined-slip model with load sensitivity, camber, temp/pressure/wear inputs | Tire state, Fz |
| `road_state_estimator.py` | Separate road bank/grade from chassis roll/pitch via dedicated observer | IMU, ride height, orientation |
| `surface_inverse_solver.py` | Solve for lambda_surface given observed forces and predicted tire capability | Tire model, wheel kinematics, road state |

### Phase B — Statistically honest estimation

| Module | What |
|--------|------|
| `surface_field.py` | Spatial Bayesian field with mean/variance/kernel, not independent cells |
| `observability.py` | Excitation vector, update gating, confidence tracking |
| `condition_bucketing.py` | Separate accumulation by compound/weather/class/stint phase |
| `tire_state_dynamics.py` | Thermal model: T_surface, T_core, p_hot evolution |

### Phase C — Planning under uncertainty

| Module | What |
|--------|------|
| `robust_ocp.py` | Covariance-aware constraint tightening in the CasADi solver |
| `pre_session_uncertainty.py` | Briefing with confidence-weighted advice |
| `line_comparison.py` | Nominal vs robust vs exploitable line outputs |

---

## Critical Physics: Why Division Fails

### Load sensitivity
Peak tire friction decreases with load. For a Pacejka model:
```
Fy_peak(Fz) = D × sin(C × arctan(B × alpha_peak))
where D = d1 × Fz + d2 × Fz²   (D is not proportional to Fz)
```

So `mu_peak = Fy_peak / Fz` is NOT constant — it decreases at higher loads. The "terrain factor" of g_eff/g changes Fz, which changes the peak force non-linearly. A simple `mu / f_terrain` undoes the Fz correctly but mis-attributes the load sensitivity to the surface.

### Combined slip
At combined braking + cornering:
```
Fy = Fy_pure × cos(G_comb)
Fx = Fx_pure × sin(G_comb)
G_comb = f(alpha, kappa)  — nonlinear coupling
```

The combined force magnitude is NOT simply `sqrt(Fx² + Fy²) = μ × Fz`. The coupling depends on the slip state, not just the force magnitude.

### Transient dynamics
Tire force has a relaxation length (~0.5m). During rapid steering inputs, the instantaneous force lags behind the steady-state prediction. Dividing by the steady-state tire model attributes this lag to the road surface (lower apparent lambda_surface during transients).

---

## Data Available in iRacing .ibt

### For slip angle reconstruction (wheel_kinematics.py)
- VelocityX, VelocityY (body frame)
- YawRate
- SteeringWheelAngle + SteeringWheelAngleMax → compute wheel angle
- Speed → longitudinal velocity
- Wheelbase, track widths (from setup YAML in session info)

### For tire state dynamics (tire_state_dynamics.py)
- LFtempCL/CM/CR, RFtempCL/CM/CR, etc. (12 channels, surface temps)
- LFcoldPressure (4 channels, starting pressure)
- LFwearL/M/R (12 channels, tread remaining)
- LFshockDefl/Vel (per-wheel, for load estimation)
- FuelLevel (mass decay over stint)

### For road state (road_state_estimator.py)
- Roll, Pitch, Yaw (car body orientation)
- LatAccel, LongAccel, VertAccel (IMU)
- LFrideHeight...RRrideHeight (per-wheel)
- LFshockDefl...RRshockDefl (per-wheel)

### From setup YAML (ground truth)
- SpringRate per corner (N/mm)
- CornerWeight per corner (N)
- NoseWeight (%)
- CrossWeight (%)
- RideHeight per corner (mm)
- Camber per corner (deg)
- ARB settings
- BrakePads type
- WingAngle
- FuelLevel

---

## Success Criteria

1. **lambda_surface should be ~constant around the track** on clean dry asphalt (within ±0.05 of 1.0). Large spatial variation after tire/load/terrain factoring → model is still conflating.
2. **Tire warm-up should appear in tire_state, not surface field.** If lambda_surface increases over the first 5 laps → tire effects leaking into surface.
3. **Rubber buildup should appear in surface field, not tire_state.** If lambda_surface on the racing line > off-line after 20 laps → correctly attributed.
4. **Excitation-gated updates only.** Cells with no near-limit data should show high variance, not a filled-in point estimate.
5. **Cross-sim validation.** Same track in iRacing vs AC: lambda_surface should be similar (same physical road), tire model parameters should differ (different sim tire models).
6. **Robust OCP should be faster** than nominal OCP around uncertain cells (conservative) but faster at well-observed cells (confident exploitation).
