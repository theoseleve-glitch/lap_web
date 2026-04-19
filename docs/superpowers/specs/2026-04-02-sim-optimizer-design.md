# Sim Racing Lap Time Optimizer — Design Spec

**Date**: 2026-04-02
**Status**: Approved
**Branch**: `feat/sim-optimizer` (from main)

## Goal

Build a theoretical perfect lap for a given car, setup, and track conditions using identified physics parameters from the data logger's raw telemetry capture. Compare the driver's actual throttle/brake/steering traces against the theoretical to show exactly where and why they're losing time.

Two deliverables:
1. **Post-session optimizer** (webapp) — full physics pipeline producing theoretical input traces + per-corner coaching
2. **Live detectors** (logger overlay) — lightweight event detectors for real-time coaching pop-ups

## System Architecture

```
LOGGER (Desktop)                         WEBAPP (Flask API)
                                         
Sim Adapter (iRacing/ACC/AC/LMU)         POST /api/v1/sessions/upload
  |                                        |
  +-> Normalized samples -> Parquet        +-> Sim Optimizer Pipeline
  +-> Raw samples -> raw sidecar Parquet   |   1. Ingest & validate raw channels
  |                                        |   2. Unpack 360Hz _ST arrays
  +-> Live Detectors (~60Hz)               |   3. Filter segments (grass/draft/yellow)
       +-- OversteerDetector               |   4. Lap split & classification
       +-- UndersteerDetector              |   5-9. Parameter Identification
       +-- BrakePointDetector              |   10. Assemble VehicleModel
       +-- MinSpeedDetector                |   11. Track geometry from world_pos
       |                                   |   12. QSS min-time speed profile
       +-> Overlay pop-up coaching notes   |   13. Reconstruct theoretical inputs
                                           |   14. Delta analysis + corner coaching
Session finalize -> bundle upload          |
                                           GET /api/v1/sessions/:id/theoretical
                                           GET /api/v1/sessions/:id/theoretical/delta
                                           GET /api/v1/sessions/:id/theoretical/corners
```

## Layer 1: Parameter Identification

Extracts the car's actual physics from ~180 raw telemetry channels. Each sub-model is identified independently and assembled into a `VehicleModel`.

### 1a. Tyre Model

**Input channels**: Per-wheel slip ratio (derived from `LFspeed`/`RFspeed`/`LRspeed`/`RRspeed` vs ground `Speed`), sideslip angle (from `VelocityX`/`VelocityY` body-frame + `YawRate`), tyre load (from `LFshockDefl` x spring rate), 3-zone temps (`LFtempCL`/`CM`/`CR` x4), 3-zone wear (`LFwearL`/`M`/`R` x4), cold pressure (`LFcoldPressure` x4), tyre odometer (`LFodometer` x4), `PlayerTrackSurface`/`PlayerTrackSurfaceMaterial`, `BrakeABSactive` (lock limit detection).

**High-rate data**: `LatAccel_ST[6]`, `LongAccel_ST[6]`, `VelocityX_ST[6]`/`VelocityY_ST[6]`, `YawRate_ST[6]` at 360Hz for transient events (trail braking, kerb strikes).

**Method**: Simplified Pacejka fit per wheel:
```
F_x = mu_x(temp, wear, pressure) * F_z * D * sin(C * arctan(B * slip_ratio))
F_y = mu_y(temp, wear, pressure) * F_z * D * sin(C * arctan(B * slip_angle))
```
B, C, D identified from clean-lap data. mu() scaling captures thermal/degradation effects.

**Sim-aware constraint**: Identified grip coefficient mu clamped to plausible range (0.8-1.8) to prevent learning driver habits as car limits.

**Fallback**: If raw data unavailable, fall back to kart_envelope-style quantile extraction from aggregate G.

### 1b. Aero Model

**Input channels**: `Speed`, `LongAccel`, `AirDensity` (direct from iRacing), `WindVel` + `WindDir`, `Pitch`, ride height (from `LFshockDefl`/`RFshockDefl`/`LRshockDefl`/`RRshockDefl`), `CarDistAhead` (draft flag).

**Method**:
1. Find coast-down segments (throttle ~ 0, brake ~ 0, straight)
2. Exclude segments with `CarDistAhead < threshold` (drafting)
3. Fit CdA from `a_drag = 0.5 * rho * CdA * v^2 / m` using actual `AirDensity`
4. Fit ClA from speed-dependent increase in cornering capability + ride height drop with speed

**LMU bonus**: `mDrag`, `mFrontDownforce`, `mRearDownforce` exposed directly.

**Sim-aware constraint**: CdA/ClA bounded per car class.

### 1c. Powertrain Model

**Input channels**: `RPM`, `Engine0_RPM`, `Gear`, `Throttle`, `ThrottleRaw`, `LongAccel`, `Speed`, `FuelLevel`, `FuelUsePerHour`, `dcFuelMixture`, `PlayerCarPowerAdjust` (BOP), `PlayerCarSLShiftRPM`/`SLBlinkRPM` (shift points).

**Method**: At each gear, collect (RPM, acceleration) pairs during full-throttle segments. Back-calculate wheel torque, subtract drag, build torque-vs-RPM curve per gear. Model fuel consumption rate for mass decrease.

**Extends**: kart_envelope's `PowertrainRuntime` with multi-gear + BOP + engine map support.

### 1d. Brake Model

**Input channels**: `Brake`, `BrakeRaw` (difference = ABS intervention amount), `BrakeABSactive`, `LFbrakeLinePress`/`RFbrakeLinePress`/`LRbrakeLinePress`/`RRbrakeLinePress` (per-wheel, bar), `dcBrakeBias`, `LongAccel`, `Speed`.

**Method**: Fit `a_brake = f(brake_pressure, speed, brake_temp, bias)`. Captures:
- Brake fade (decel drops as temp rises)
- ABS intervention threshold (when `BrakeABSactive` = true, tyre is at lock limit)
- Front/rear distribution from `dcBrakeBias` + per-wheel line pressure
- `BrakeRaw` vs `Brake` delta quantifies ABS correction magnitude

### 1e. Suspension Model

**Input channels**: `LFshockDefl`/`RFshockDefl`/`LRshockDefl`/`RRshockDefl` + `_ST[6]` 360Hz variants (48 columns), `LFshockVel`/`RFshockVel`/`LRshockVel`/`RRshockVel` + `_ST[6]` 360Hz, `RollRate` + `RollRate_ST[6]`, `PitchRate` + `PitchRate_ST[6]`, `VertAccel` + `VertAccel_ST[6]`.

**Method**:
- Identify spring rate from quasi-static deflection vs load (calculated from G)
- Identify damper characteristic from shock velocity vs force (from 360Hz data)
- Per-wheel load at every sample = shock_defl x spring_rate
- Load transfer rate from 360Hz damper response
- Validate against calculated load transfer from `LatAccel * mass * CG_height / track_width`

### 1f. Mass Model

**Input channels**: `FuelLevel`, `FuelUsePerHour`, `PlayerCarWeightPenalty` (BOP ballast), `LongAccel`, `Speed`, `Throttle`.

**Method**: Estimate base mass from F=ma during known-torque full-throttle events. Track fuel burn: `mass(t) = base_mass + BOP_penalty + fuel_level(t) * fuel_density`. Feed decreasing mass into all other models throughout session.

### 1g. VehicleModel Assembly

```python
@dataclass
class VehicleModel:
    tyre: TyreModel
    aero: AeroModel
    powertrain: PowertrainModel
    brake: BrakeModel
    suspension: SuspensionModel
    mass: MassModel

    # FrictionLike protocol (compatible with kart_envelope solver)
    def max_lateral_g(self, speed_mps: float) -> float: ...
    def max_traction_g(self, speed_mps: float, gear: int) -> float: ...
    def max_braking_g(self, speed_mps: float) -> float: ...
    def combined_limit(self, ax: float, ay: float, speed: float) -> bool: ...
```

Satisfies the same `FrictionLike` protocol as kart_envelope's `CapabilityEnvelope`.

## Layer 2: Enhanced QSS Solver

### Enhancements over kart_envelope QSS

| Aspect | kart_envelope | Sim optimizer |
|--------|---------------|---------------|
| Grip source | CapabilityEnvelope (quantile from G) | VehicleModel.tyre (identified Pacejka) |
| Combined slip | Single p-norm | Asymmetric, load-dependent (inner/outer wheel) |
| Aero | Optional CdA/Cl, conservative caps | Identified CdA/ClA, AirDensity, wind |
| Powertrain | Single-gear or torque curve | Multi-gear torque map + shift strategy |
| Braking | Envelope max decel | Pressure-limited, fade, ABS |
| Load transfer | Telemetry surrogate | Measured from suspension model |
| Track geometry | GPS reference line | world_pos_x/y/z (higher precision) |

### Solver flow

```
Track geometry kappa(s) + VehicleModel
  |
  v
1. v_corner_max(s) at each distance:
   - lateral grip >= centripetal need
   - with aero downforce at speed
   - with load transfer (inner unloads, outer loads)

2. Forward pass (traction-limited):
   - a_max = min(powertrain.torque_limited, combined_limit)
   - subtract drag, rolling resistance, gradient
   - shift gears at optimal RPM

3. Backward pass (braking-limited):
   - a_max = min(brake.pressure_limited, combined_limit)
   - add drag (helps braking)

4. Merge: v*(s) = min(v_corner, v_forward, v_backward)

5. lap_time = integral(ds / v*(s))
```

### Output: TheoreticalResult

Same dataclass as kart_envelope: `speed_profile_mps`, `distance_m`, `accel_profile_mps2`, `lap_time_s`, `cornering_limited`, `accel_limited`, `braking_limited`.

## Layer 3: Input Reconstruction

Given v*(s) from the solver and VehicleModel, reconstruct driver inputs at each distance step.

### Steering

```
a_lat_required = v*^2 * kappa(s)
slip_angle = VehicleModel.tyre.inverse_lateral(a_lat_required, F_z_front)
steering_deg = slip_angle + ackermann_correction(kappa, wheelbase)
```

### Throttle / Brake

```
a_long_required = dv*/ds * v*
a_drag = VehicleModel.aero.drag_accel(v*)
a_rr = VehicleModel.powertrain.rolling_resistance(v*)

if accelerating:
    a_wheel = a_long_required + a_drag + a_rr
    throttle = VehicleModel.powertrain.inverse_torque(a_wheel, v*, gear)
    brake = 0.0
else:  # braking
    a_wheel = a_long_required + a_drag + a_rr
    brake = VehicleModel.brake.inverse_pressure(a_wheel, v*)
    throttle = 0.0
```

### Trail braking zones

Combined-slip limit splits available grip between braking and cornering:
```
|a_lat / a_lat_max|^p + |a_long / a_long_max|^p = 1
```
Produces natural trail-braking traces where brake releases as steering increases.

### Gear selection

```
gear = VehicleModel.powertrain.optimal_gear(v*, rpm)
```

### Output: TheoreticalInputTrace

```python
@dataclass
class TheoreticalInputTrace:
    distance_m: np.ndarray
    speed_mps: np.ndarray
    throttle_pct: np.ndarray      # 0.0-1.0
    brake_pct: np.ndarray         # 0.0-1.0
    steering_deg: np.ndarray      # signed
    gear: np.ndarray              # integer
    limit_type: np.ndarray        # "traction" | "braking" | "cornering"
    corners: list[CornerTheoretical]
```

## Delta Analysis & Coaching

### Distance-aligned comparison

```python
@dataclass
class LapDelta:
    distance_m: np.ndarray
    time_delta_s: np.ndarray        # cumulative, positive = driver slower
    speed_delta_mps: np.ndarray     # theoretical - actual
    throttle_delta_pct: np.ndarray
    brake_delta_pct: np.ndarray
    steering_delta_deg: np.ndarray
    corners: list[CornerDelta]
```

### Per-corner coaching

Each `CornerDelta` includes:
- Time lost/gained
- Root cause: "braked 18m too late" / "apex speed 4 km/h too low" / "throttle 0.3s late" / "understeer at exit"
- Which input trace diverged and where

### Validation

Cross-check theoretical lap time against `LapDeltaToOptimalLap` (iRacing's own sector-composite optimal). Our theoretical should be at least as fast.

## Live Detectors (Logger Side)

Lightweight pattern detectors running every sample (~60Hz). No solver, no model. Compare current state to best-lap reference.

| Detector | Trigger | Pop-up |
|----------|---------|--------|
| Oversteer | yaw_rate deviates from expected (speed * curvature), rear slip > front | "Oversteer - earlier throttle?" |
| Understeer | steering increasing but lat_g plateaus/drops | "Understeer - less speed in" |
| Late brake | brake point > best lap + margin | "Braked late - 12m past ref" |
| Early brake | brake point < best lap - margin | "Braked early - 15m before ref" |
| Low min-speed | apex speed < best lap - margin | "Apex +4 km/h possible" |

Implementation: Each detector is a class with `check(sample, best_lap_ref) -> Optional[CoachingNote]`. Uses existing `live_lap_compare.py` infrastructure.

## Data Channel Coverage (iRacing)

~180 of 332 IRSDK variables used for physics. Remaining ~150 are metadata/UI/replay/other-cars.

### By sub-model

| Sub-model | Key channels | Column count |
|-----------|-------------|--------------|
| Tyre | wheel speeds, body velocities (sideslip), shock defl (load), 3-zone temps x4, 3-zone wear x4, cold pressure x4, odometer x4, ABS active, track surface | ~50 |
| Aero | speed, long accel, AirDensity, WindVel/Dir, Pitch, ride heights, CarDistAhead | ~20 |
| Powertrain | RPM, Gear, Throttle/Raw, FuelLevel, FuelUsePerHour, dcFuelMixture, BOP adjust, shift RPMs | ~12 |
| Brake | Brake/Raw, ABS active, 4x brake line press, dcBrakeBias | ~12 |
| Suspension | 4x shock defl + vel + all _ST 360Hz, RollRate, PitchRate, VertAccel | ~60 |
| Mass | FuelLevel, BOP penalty, LongAccel | ~4 |
| Environment | AirTemp, TrackTemp, AirDensity, AirPressure, WindVel/Dir, TrackWetness, Humidity | ~8 |
| Validation | LapDeltaToOptimalLap, SessionFlags, TrackSurface, IsOnTrack | ~4 |
| Track geometry | Lat, Lon, Alt, LapDist, LapDistPct, Speed | ~6 |
| Driver inputs (comparison target) | Throttle, Brake, Steering, Gear, Clutch | ~5 |

### 360Hz high-rate channels used

`LatAccel_ST[6]`, `LongAccel_ST[6]`, `VertAccel_ST[6]`, `VelocityX_ST[6]`, `VelocityY_ST[6]`, `VelocityZ_ST[6]`, `YawRate_ST[6]`, `RollRate_ST[6]`, `PitchRate_ST[6]`, `SteeringWheelTorque_ST[6]`, `LFshockDefl_ST[6]` (x4 wheels), `LFshockVel_ST[6]` (x4 wheels) = 108 columns at 360Hz.

## File Structure

```
telemetry_tool/
  sim_optimizer/
    __init__.py
    pipeline.py                    # 14-step orchestrator
    config.py                      # SimOptimizerConfig
    ingest/
      raw_channels.py              # Extract ~180 channels from raw sidecar
      highrate.py                  # Unpack _ST[6] -> 360Hz timeseries
      segment_filter.py            # Flag grass/draft/yellow segments
      lap_align.py                 # Distance-align for per-lap analysis
    param_id/
      tyre_model.py                # Pacejka fit
      aero_model.py                # CdA/ClA identification
      powertrain_model.py          # Torque curves
      brake_model.py               # Pressure/temp/bias model
      suspension_model.py          # Spring/damper identification
      mass_model.py                # Base + fuel + BOP
      vehicle_model.py             # VehicleModel assembly
    solver/
      qss_enhanced.py              # Enhanced QSS with VehicleModel
      load_transfer.py             # Per-wheel load calculation
    reconstruction/
      input_trace.py               # Theoretical inputs from v*(s)
      trail_brake.py               # Combined-slip zone splitting
    analysis/
      delta.py                     # Actual vs theoretical
      corner_coaching.py           # Per-corner root cause + text
      validation.py                # Cross-check vs iRacing optimal
    output/
      traces.py                    # Serialize for frontend
      summary.py                   # Session summary JSON
  tests/
    test_sim_optimizer/
      test_raw_channels.py
      test_tyre_model.py
      test_aero_model.py
      test_powertrain_model.py
      test_brake_model.py
      test_suspension_model.py
      test_qss_enhanced.py
      test_input_reconstruction.py
      test_delta_analysis.py
      test_live_detectors.py
      test_pipeline_e2e.py
  web/
    routes/
      theoretical.py               # 3 new API endpoints

# Logger repo (datalogger)
lap_coach_logger/
  core/
    live_detectors.py              # 5 detector classes
    detector_models.py             # CoachingNote, DetectorConfig
```

## API Endpoints

```
GET /api/v1/sessions/:id/theoretical
  -> { speed_profile, input_traces, vehicle_model_summary, lap_time_s }

GET /api/v1/sessions/:id/theoretical/delta?lap=N
  -> { distance_m[], time_delta_s[], speed_delta[], throttle_delta[],
       brake_delta[], steering_delta[] }

GET /api/v1/sessions/:id/theoretical/corners
  -> { corners: [{ id, time_loss_s, root_cause, coaching_text,
                    brake_point_delta_m, apex_speed_delta_kph,
                    exit_throttle_delta_pct }] }
```

## Frontend Integration

Theoretical traces overlay on existing vanilla JS chart modules:
- **Speed trace**: theoretical as dashed line over actual
- **Input traces**: new chart panels — actual vs theoretical throttle/brake/steering
- **Delta bar**: cumulative time delta against theoretical
- **Corner table**: ranked by time loss with root cause column

Uses existing `useVanillaChart` hook and distance-based hover sync store.

## Testing Strategy

| Layer | Approach | Key assertion |
|-------|----------|---------------|
| Raw channels | Unit: recorded Parquet | 180 channels present, _ST unpacked |
| Tyre model | Unit: synthetic Pacejka data | B/C/D within 5% of ground truth |
| Aero model | Unit: synthetic coast-down | CdA within 10% |
| QSS solver | Integration: known geometry + model | Lap time within 0.5s analytical |
| Input reconstruction | Integration: roundtrip | Speed profile error < 1% |
| Delta analysis | Integration: known delta | Corner deltas sum to +/-0.1s of total |
| Live detectors | Unit: synthetic events | Detect within 2 samples of onset |
| Full pipeline | E2E: recorded iRacing bundle | Valid report, plausible lap time |

Test fixtures: 2-3 recorded iRacing sessions (different cars/tracks) with raw capture enabled.

## Graceful Degradation

Each pipeline step wrapped in `_safe_step()`. Fallback chain:
- Tyre model fails -> kart_envelope quantile envelope
- Aero model fails -> config defaults (CdA=0.8, Cl=0)
- Powertrain fails -> peak power estimate from max speed
- Brake fails -> envelope max decel from observed data
- Suspension fails -> static load transfer calculation
- Input reconstruction fails -> speed profile + delta still available (no input traces)
- Validation fails -> skip cross-check

## Size Estimates

| Component | Files | Lines |
|-----------|-------|-------|
| sim_optimizer package | ~15 | ~3000 |
| Live detectors | 2 | ~300 |
| API endpoints | 1 | ~200 |
| Frontend overlays | 3 | ~400 |
| Tests | 11 | ~1500 |
| **Total** | **~32** | **~5400** |
