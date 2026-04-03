# Lap Oracle — Autonomous 48-Hour Optimal Lap Time System

**Date:** 2026-04-03
**Status:** Draft
**Sims:** Assetto Corsa, ACC, Le Mans Ultimate, iRacing, F1 25

---

## 1. Goal

Build a fully autonomous system that, once launched, runs for 48 hours on a single machine (RTX 3070 Ti 8GB, 64GB RAM, good CPU) and produces:

1. **Optimal lap database** — physics-computed fastest laps for every discoverable car/track/condition combination across 5 sims
2. **Setup optimizer** — given (car, track, weather) → recommended setup with predicted lap time
3. **Neural oracle** — instant prediction model for any combo without re-solving
4. **AC RL driver** — autonomous agent that drives in Assetto Corsa to collect training data and validate models
5. **Per-corner coaching** — detailed breakdown of where time is gained/lost and why

## 2. Existing Infrastructure (Reuse)

### 2.1 Datalogger Adapters (`datalogger/src/lap_coach_logger/adapters/`)

| Adapter | File | Channels | Write-back |
|---------|------|----------|------------|
| **AC** | `assetto_corsa_adapter.py` | Physics SHM (speed, g-force, inputs, tyres, fuel, temps) + Graphics (session/lap) + Static (car/track) | Possible via SHM write |
| **ACC** | `acc_adapter.py` | Same 3-SHM layout (physics/graphics/static), GT3-specific fields | Read-only |
| **LMU** | `lmu_adapter.py` | `SharedMemoryLayout` with `TelemInfoV01` + `VehicleScoringInfoV01` | Read-only |
| **iRacing** | `iracing_adapter.py` | Full SDK vars + raw capture + session info YAML | Read-only (TOS) |

All normalize to `TelemetrySample` schema (40+ channels): speed, throttle, brake, steering, gear, RPM, g-forces, tyre temps, fuel, world position, orientation, track/car names.

### 2.2 Sim Optimizer (`telemetry_tool/sim_optimizer/`)

| Module | What It Does | Reuse |
|--------|-------------|-------|
| `param_id/mass_model.py` | Mass estimation from acceleration data | Direct |
| `param_id/aero_model.py` | Aero coefficient fitting (Cd, Cl) | Direct |
| `param_id/tyre_model.py` | Tyre grip model fitting | Direct — extend with Pacejka |
| `param_id/suspension_model.py` | Suspension parameter identification | Direct |
| `param_id/powertrain_model.py` | Engine/drivetrain model | Direct |
| `param_id/brake_model.py` | Brake performance model | Direct |
| `solver/qss_enhanced.py` | Quasi-steady-state lap solver | Foundation — replace with CasADi OCP |
| `solver/load_transfer.py` | Load transfer calculations | Direct |
| `reconstruction/input_trace.py` | Reconstruct driver inputs from telemetry | Direct |
| `reconstruction/trail_brake.py` | Trail braking analysis | Direct |
| `analysis/delta.py` | Time delta between laps | Direct |
| `analysis/corner_coaching.py` | Per-corner coaching insights | Direct |
| `analysis/validation.py` | Solution validation | Direct |
| `pipeline.py` | Full sim optimizer pipeline orchestration | Extend |
| `config.py` | Configuration dataclasses | Extend |

### 2.3 ML Training Pipeline (`scripts/training/`)

7-stage pipeline already built:
- Stage 1: DTM events extraction → `dtm_events.parquet`
- Stage 2: TUMFTM features → `tumftm_features.parquet`
- Stage 3: F1 features → `f1_features.parquet`
- Stage 4: Motorsport features → `motorsport_features.parquet`
- Stage 5: Kart features → `kart_features.parquet`
- Stage 6: Train models (NB, GMM, RF, Anomaly)
- Stage 7: Report generation

### 2.4 Handling Detection (`telemetry_tool/handling/`)

- 16-detector Bayesian fusion system
- Setup recommender with kart + car knowledge bases
- Vehicle class calibration from TUMFTM data
- Cross-session track profiles
- Learned detector weights

### 2.5 Available Data

| Dataset | Location | Size | Key Fields |
|---------|----------|------|------------|
| **Dallara 100K** | `data/external/kaggle_dallara/dallara_100k.csv` | 100K laps | Setup params, aero config, tyre compound, weather, lap/sector times per circuit |
| **TUMFTM sims** | `data/external/tumftm/*.csv` | 16 files, 100Hz | vx, vy, dpsi, ax, ay, steering, full vehicle state |
| **TUMFTM tracks** | `data/external/tumftm_tracks/` | 4 tracks | Berlin, Modena, handling_track, rounded_rectangle |
| **F1 telemetry** | `data/external/f1_tracing/*.json` | VER/HAM/NOR qualifying | Speed, accel, position, throttle, brake per lap |
| **FastF1** | `data/external/fastf1_*.csv` | 7 sessions | Melbourne, Monza, Silverstone, Spa qualifying |
| **OpenF1** | `data/external/openf1/` | Multiple races | Car data at high frequency |
| **Setup correlations** | `data/external/setup_correlations.json` | Pre-computed | Aero balance vs lap time per circuit |
| **Track profiles** | `data/external/track_profiles.json` | Pre-computed | F1 track handling signatures |
| **Kart sessions** | `data/raw/*.csv` | 28+ sessions | RaceChrono CSV from real kart sessions |
| **iRacing assets** | `artifacts/iracing_*` | Decoded | Variable schemas, session info, track data |
| **Mendeley** | `data/external/mendeley/` | Vehicle dynamics zip | Academic vehicle dynamics dataset |
| **Kaggle motorsport** | `data/external/kaggle_motorsport/` | CSV + metadata | General motorsport telemetry |
| **Kaggle simulated** | `data/external/kaggle_simulated/` | Simulated dataset | Synthetic vehicle dynamics |

### 2.6 iRacing Reverse Engineering (`scripts/`)

- `decode_iracing_bc1_atad.py` — DAT file bitmap extraction
- `decode_iracing_olap.py` — OLAP chunk decoding
- `extract_iracing_dat_assets.py` — Asset extraction from DAT files
- `inspect_iracing_dat.py` — DAT file structure inspector
- `probe_iracing_runtime.py` — Runtime variable probing
- `probe_iracing_track_container.py` — Track data extraction
- Artifacts: `iracing_sim_param_names.json`, `iracing_live_var_schema.json`, session info YAML

## 3. Architecture

### 3.1 System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (main process)                     │
│  - SQLite job queue with priority scoring                        │
│  - Worker lifecycle management (spawn, monitor, restart)          │
│  - Progress dashboard (terminal + JSON log)                      │
│  - Smart scheduling: highest-value-first across all sims         │
│  - Auto-restart on worker failure                                │
│  - 48h countdown with graceful shutdown                          │
└──────────┬───────────────────────────────────────────────────────┘
           │
    ┌──────┴──────────────────────────────────────────────┐
    │              DATA LAKE (local disk)                   │
    │  data/oracle/telemetry/    — raw + processed telemetry│
    │  data/oracle/tracks/       — track geometry models    │
    │  data/oracle/vehicles/     — vehicle physics models   │
    │  data/oracle/solutions/    — OCP optimal laps         │
    │  data/oracle/setups/       — setup sweep results      │
    │  data/oracle/models/       — neural net checkpoints   │
    │  data/oracle/reports/      — generated reports        │
    │  data/oracle/oracle.db     — SQLite job/progress DB   │
    └──────┬──────────────────────────────────────────────┘
           │
  ┌────────┼─────────┬────────────┬───────────────┬──────────────┐
  ▼        ▼         ▼            ▼               ▼              ▼
HARVEST  IDENTIFY  SOLVE       TRAIN          AC DRIVER     SWEEP
Workers  Workers   Workers     Worker         Worker        Workers
(CPU)    (CPU)     (CPU)       (GPU)          (CPU+GPU)     (CPU)
```

### 3.2 Worker Types

#### W1: Harvest Workers (CPU, 2-4 parallel)

**Purpose:** Extract all available data from every source.

**Sim file extraction:**
- **AC:** Parse `content/cars/*/data.acd` (encrypted ZIP) for `car.ini`, `tyres.ini`, `drivetrain.ini`, `suspensions.ini`, `aero.ini`. Parse `content/tracks/*/ai/*.csv` for AI racing line, track boundaries, ideal line.
- **ACC:** Parse setup JSON files from `Documents/Assetto Corsa Competizione/Setups/`. Extract car data from game files where accessible.
- **LMU:** Parse `.veh`, `.hdv` (vehicle), `.tbc` (tyre), `.tgm` (track grip) files from LMU install. rFactor 2 format — well-documented.
- **iRacing:** Use decoded schemas (`artifacts/iracing_sim_param_names.json`, `iracing_live_var_schema.json`), extract track geometry from `.ibt` telemetry files, parse setup files.
- **F1 25:** Parse UDP telemetry packet definitions (CodeMasters format). Setup packets contain: front/rear wing, on/off throttle diff, front/rear camber, front/rear toe, front/rear suspension, front/rear ARB, brake pressure, brake bias, front/rear tyre pressure, ballast, fuel load.

**Existing data integration:**
- Load all `data/external/` datasets (already 200K+ datapoints)
- Process all `data/raw/` kart sessions through handling pipeline
- Import TUMFTM sim data with ground-truth vehicle states
- Load Dallara 100K setup-performance correlations

**Public data scraping (if accessible):**
- Community setup databases (JSON/INI format)
- Track guide data (corner types, speeds, gears)

#### W2: Identify Workers (CPU, 2-4 parallel)

**Purpose:** Fit vehicle dynamics models for each discovered car.

**Vehicle model structure** (extends existing `sim_optimizer/param_id/`):
```python
@dataclass
class VehicleModel:
    # From existing param_id
    mass_kg: float                    # mass_model.py
    aero: AeroParams                  # aero_model.py (Cd, Cl, frontal_area)
    powertrain: PowertrainParams      # powertrain_model.py (torque curve, gear ratios)
    brakes: BrakeParams               # brake_model.py (max decel, bias)
    suspension: SuspensionParams      # suspension_model.py (roll stiffness, ride height)
    
    # New — ported from TUM MVDC
    tyre: PacejkaParams               # Extended Pacejka Magic Formula coefficients
    wheelbase_m: float
    track_width_front_m: float
    track_width_rear_m: float
    cg_height_m: float
    weight_distribution_front: float  # 0-1
    
    # Setup-dependent (varied during sweep)
    setup: SetupParams                # wing angles, ARB, springs, dampers, pressures, camber, toe
```

**Pacejka tyre model** (ported from TUM MVDC):
```
Fy = D * sin(C * arctan(B*alpha - E*(B*alpha - arctan(B*alpha))))
where:
  B = stiffness factor (from tyre data or fitted)
  C = shape factor (~1.3 for lateral)
  D = peak force (mu * Fz)
  E = curvature factor
  alpha = slip angle
```

Combined slip via friction ellipse:
```
Fx_combined = Fx0 * cos(arctan(kappa/alpha))
Fy_combined = Fy0 * sin(arctan(kappa/alpha))
```

**Fitting pipeline per car:**
1. Collect all telemetry for this car (recorded sessions + sim file data)
2. Run existing `param_id` modules for mass, aero, powertrain, brakes
3. Fit Pacejka coefficients from lateral acceleration vs slip angle data
4. If insufficient real data, use sim file values as prior + Bayesian update from any telemetry
5. Save to `data/oracle/vehicles/{sim}_{car_name}.json`

#### W3: Solve Workers (CPU, 2-8 parallel — this is the core)

**Purpose:** Compute minimum-time optimal laps using CasADi + IPOPT.

**Optimal Control Problem (OCP) formulation:**

```
Minimize: T (total lap time)

Subject to:
  # Vehicle dynamics (single-track bicycle model)
  dx/dt = v * cos(psi + beta)
  dy/dt = v * sin(psi + beta)
  dpsi/dt = v * cos(beta) / L_r * tan(delta)
  dv/dt = (Fx - Fd - Fr) / m
  
  # Tyre force limits (Pacejka + friction ellipse)
  (Fx/mu_x*Fz)^2 + (Fy/mu_y*Fz)^2 <= 1
  
  # Track boundaries
  n_min(s) <= n(s) <= n_max(s)   # lateral offset from centerline
  
  # Actuator limits
  0 <= throttle <= 1
  0 <= brake <= 1
  delta_min <= steering <= delta_max
  
  # Power limit
  Fx * v <= P_max(v)             # engine power curve
  
  # Setup-dependent constraints
  Fz_front, Fz_rear from load transfer model
  mu = f(tyre_temp, tyre_pressure, compound, track_grip)
```

**Solver:** CasADi with IPOPT (Interior Point OPTimizer) backend.
- Problem discretized with ~500 collocation points per lap
- Each solve takes 5-60 seconds depending on track complexity
- CPU-parallelizable: multiple tracks/setups solved simultaneously
- 64GB RAM handles dense NLP matrices comfortably

**Track model** (input to solver):
```python
@dataclass
class TrackModel:
    centerline_xy: np.ndarray    # (N, 2) x,y coordinates
    width_left: np.ndarray       # (N,) distance to left boundary
    width_right: np.ndarray      # (N,) distance to right boundary  
    curvature: np.ndarray        # (N,) path curvature
    elevation: np.ndarray        # (N,) elevation profile
    banking: np.ndarray          # (N,) track banking angle
    grip_map: np.ndarray         # (N,) surface grip multiplier
    sector_boundaries: list[int] # indices of sector boundaries
    total_length_m: float
```

**Track extraction sources:**
- AC: `tracks/*/ai/fast_lane.ai.csv` (AI racing line with boundaries)
- ACC: Extracted from telemetry GPS traces (multiple laps → boundary estimation)
- LMU: `.tgm` files contain grip maps; centerline from `*.gdb` files
- iRacing: Extracted from `.ibt` telemetry GPS + `artifacts/iracing_localserver_track_fields.json`
- F1 25: Extracted from UDP position packets over multiple laps
- TUMFTM: Direct from `data/external/tumftm_tracks/*.csv`

#### W4: Train Worker (GPU, 1 process)

**Purpose:** Continuously train neural surrogate from growing solution database.

**Architecture:**
```
Input encoder:
  car_params (50 features) → Linear(50, 128) → ReLU
  track_segment (30 features) → Linear(30, 128) → ReLU
  setup_params (40 features) → Linear(40, 64) → ReLU
  weather (10 features) → Linear(10, 32) → ReLU

Fusion:
  Concat(128+128+64+32 = 352) → Linear(352, 512) → ReLU → Dropout(0.1)
  → Linear(512, 512) → ReLU → Dropout(0.1)
  → Linear(512, 256) → ReLU

Output heads:
  lap_time_head: Linear(256, 1)                    # predicted optimal lap time
  speed_profile_head: Linear(256, N_points)         # optimal speed at each track point
  control_head: Linear(256, N_points * 3)           # throttle, brake, steer per point
  setup_delta_head: Linear(256, 40)                 # recommended setup changes
  sector_times_head: Linear(256, 3)                 # predicted sector times

Total parameters: ~800K (fits in <50MB VRAM)
Training batch size: 2048
```

**Training loop:**
1. Load all completed OCP solutions from `data/oracle/solutions/`
2. Encode each solution as (input_features, target_outputs) pair
3. Train with MSE loss on lap time + speed profile, BCE on control inputs
4. Every 30 minutes: checkpoint model, evaluate on held-out set
5. Every 2 hours: reload new solutions (more data from ongoing solves)
6. Learning rate schedule: cosine annealing over 48h

**Weather encoding:**
```python
weather_features = [
    air_temp_c,           # normalized to [0,1] over [0, 45]
    track_temp_c,         # normalized to [0,1] over [10, 60]
    humidity_pct,         # 0-1
    is_wet,               # binary
    rain_intensity,       # 0-1
    wind_speed_ms,        # normalized
    wind_direction_rad,   # sin/cos encoded
    grip_multiplier,      # derived from conditions
    tyre_deg_rate,        # estimated degradation multiplier
    rubber_buildup,       # session progression factor
]
```

#### W5: AC Driver Worker (CPU + GPU time-shared)

**Purpose:** Autonomously drive in Assetto Corsa to collect targeted data.

**AC shared memory write-back:**
AC exposes `acpmf_physics` for reading. For control injection, two approaches ranked by reliability:

1. **AC Python app API** (preferred) — AC loads Python apps from `apps/python/`. A custom app can call `ac.setSteerAngle()`, `ac.setGas()`, `ac.setBrake()`, `ac.setGear()` to control the car. This is AC's official extension mechanism.
2. **CSP (Custom Shaders Patch) Lua scripting** (fallback) — CSP exposes `ac.setInput()` Lua bindings. More powerful but requires CSP installed.

If neither is available (AC not installed), the RL worker gracefully skips and all other workers continue.

**Gym environment:**
```python
class ACGymEnv(gymnasium.Env):
    observation_space = spaces.Box(shape=(30,))  
    # [speed, lat_accel, lon_accel, yaw_rate, slip_angle,
    #  track_position, track_offset, track_angle,
    #  tyre_temps(4), tyre_slip(4), 
    #  upcoming_curvature(10), sector, fuel_pct]
    
    action_space = spaces.Box(low=[-1, 0, 0], high=[1, 1, 1])
    # [steering, throttle, brake]
    
    reward = (
        progress_reward          # distance gained along track
        - time_penalty           # penalize slow progress
        - off_track_penalty      # large penalty for leaving track
        - smoothness_penalty     # penalize jerky inputs
        + optimal_bonus          # bonus for matching physics-optimal speed
    )
```

**Training strategy:**
- Use PPO (Proximal Policy Optimization) from stable-baselines3
- MLP policy: [256, 256] hidden layers
- Phase 1 (hours 8-20): Explore — learn to complete laps without crashing
- Phase 2 (hours 20-36): Optimize — reward shaped by OCP solutions from W3
- Phase 3 (hours 36-48): Validate — compare RL agent laps against OCP optimal

**Data collection during RL:**
Every completed lap → extract telemetry → feed to W2 (model refinement) and W3 (solution validation). This creates a feedback loop: better models → better solutions → better RL reward shaping.

#### W6: Setup Sweep Workers (CPU, 2-4 parallel)

**Purpose:** Systematically vary setup parameters through the OCP solver to find optima.

**Sweep strategy:**
For each (car, track, weather condition):
1. Start with default/community setup
2. Solve OCP → baseline optimal time
3. Latin Hypercube Sampling over setup parameter space (50-200 samples)
4. Solve OCP for each sample → build response surface
5. Bayesian optimization to find setup that minimizes lap time
6. Refine around best region with dense sampling

**Setup parameters swept** (sim-dependent subset):
```python
setup_params = {
    # Aero
    "front_wing_angle": (min, max, step),
    "rear_wing_angle": (min, max, step),
    
    # Suspension
    "front_spring_rate": (min, max),
    "rear_spring_rate": (min, max),
    "front_arb": (min, max),
    "rear_arb": (min, max),
    "front_ride_height": (min, max),
    "rear_ride_height": (min, max),
    
    # Alignment
    "front_camber": (min, max),
    "rear_camber": (min, max),
    "front_toe": (min, max),
    "rear_toe": (min, max),
    
    # Brakes
    "brake_bias": (min, max),
    "brake_pressure": (min, max),
    
    # Differential
    "diff_preload": (min, max),
    "diff_power_ramp": (min, max),
    "diff_coast_ramp": (min, max),
    
    # Tyres
    "front_pressure": (min, max),
    "rear_pressure": (min, max),
}
```

**How setup affects the OCP:**
Each setup parameter maps to vehicle model changes:
- Wing angles → Cl, Cd changes (aero model)
- Spring rates → roll stiffness (load transfer model)
- Camber → tyre contact patch → peak grip change (Pacejka D parameter)
- Tyre pressure → tyre stiffness → Pacejka B parameter
- Diff settings → traction split model
- ARB → lateral load transfer distribution

### 3.3 F1 25 UDP Adapter (New)

F1 25 uses the same UDP telemetry format as F1 23/24 (CodeMasters/EA):

```python
# UDP packet types (port 20777)
PACKET_MOTION        = 0   # Car position, velocity, g-forces, wheel data
PACKET_SESSION       = 1   # Weather, track, session type
PACKET_LAP_DATA      = 2   # Lap times, sector times, positions  
PACKET_EVENT         = 3   # Events (fastest lap, retirement, etc.)
PACKET_PARTICIPANTS  = 4   # Driver names, teams
PACKET_CAR_SETUPS    = 5   # Full setup data for all cars
PACKET_CAR_TELEMETRY = 6   # Throttle, brake, steer, speed, RPM, DRS, temps
PACKET_CAR_STATUS    = 7   # Tyre compound, fuel, ERS, flags
PACKET_MOTION_EX     = 14  # Extended motion (suspension, wheel speed)
```

**Implementation:** UDP listener that captures packets, normalizes to `TelemetrySample`-compatible format, and writes to Parquet. No write-back possible.

### 3.4 Orchestrator

**Job priority scoring:**
```python
priority = (
    data_availability_score    # more data = higher confidence in solution
    * sim_popularity_weight    # weight sims by user preference
    * track_complexity_score   # complex tracks benefit more from optimization
    * novelty_bonus            # unsolved combos get priority
    - solve_cost_estimate      # deprioritize very expensive solves
)
```

**Phase scheduling:**
```
Phase 1 (hours 0-4):   HARVEST — all harvest workers active, others idle
Phase 2 (hours 4-8):   IDENTIFY — fit vehicle models from harvested data
Phase 3 (hours 8-20):  SOLVE+TRAIN — OCP solving begins, GPU training starts, AC driver begins
Phase 4 (hours 20-36): FULL PARALLEL — all workers active, setup sweeping begins
Phase 5 (hours 36-44): REFINE — re-solve with improved models, deep setup optimization
Phase 6 (hours 44-48): REPORT — generate final reports, save best models
```

**Fault tolerance:**
- Workers catch all exceptions, log, and continue to next job
- Orchestrator monitors worker health (heartbeat every 60s)
- Crashed workers auto-restart with backoff
- All intermediate results persisted to disk (resume-safe)
- SQLite WAL mode for concurrent reads/writes

## 4. Output Artifacts

### 4.1 Optimal Lap Database

`data/oracle/solutions/{sim}/{track}/{car}/optimal_{conditions}.json`:
```json
{
    "sim": "AC",
    "track": "monza",
    "car": "ks_ferrari_488_gt3",
    "conditions": {"air_temp": 25, "track_temp": 35, "grip": 1.0, "weather": "dry"},
    "setup": { /* full setup params */ },
    "optimal_lap_time_s": 108.234,
    "sector_times_s": [34.1, 38.5, 35.6],
    "speed_profile": [ /* speed at each track point */ ],
    "control_inputs": {
        "throttle": [ /* per-point */ ],
        "brake": [ /* per-point */ ],
        "steering": [ /* per-point */ ]
    },
    "corner_analysis": [
        {
            "name": "Turn 1 (Variante del Rettifilo)",
            "entry_speed_kph": 312,
            "apex_speed_kph": 78,
            "exit_speed_kph": 145,
            "brake_point_m": 2847,
            "optimal_line_offset_m": [ /* offset from centerline */ ],
            "time_in_corner_s": 4.2,
            "limiting_factor": "rear_tyre_traction"
        }
    ],
    "vehicle_model_hash": "abc123",
    "solver_time_s": 12.4,
    "solver_status": "optimal"
}
```

### 4.2 Setup Recommendation Database

`data/oracle/setups/{sim}/{track}/{car}/best_setup_{conditions}.json`:
```json
{
    "baseline_setup": { /* default */ },
    "optimal_setup": { /* optimized */ },
    "lap_time_improvement_s": 0.847,
    "parameter_sensitivity": {
        "rear_wing_angle": {"impact_s_per_unit": 0.12, "direction": "lower is faster"},
        "front_arb": {"impact_s_per_unit": 0.04, "direction": "stiffer is faster"}
    },
    "conditions_sensitivity": {
        "rain": {"lap_time_delta_s": +15.2, "setup_changes": {"rear_wing": "+3 clicks"}},
        "hot_track": {"lap_time_delta_s": +0.4, "setup_changes": {"tyre_pressure": "-0.2 psi"}}
    }
}
```

### 4.3 Neural Oracle Model

`data/oracle/models/oracle_v{N}.pt` — PyTorch checkpoint
- Input: encoded (car, track, setup, weather) features
- Output: predicted optimal lap time, speed profile, control inputs, setup deltas
- Inference time: <10ms per prediction
- Accuracy target: within 0.5% of OCP solution

### 4.4 Progress Report

`data/oracle/reports/progress.json` — updated every 5 minutes:
```json
{
    "elapsed_hours": 24.5,
    "remaining_hours": 23.5,
    "combos_solved": 847,
    "combos_remaining": 1203,
    "setups_optimized": 312,
    "neural_oracle_loss": 0.023,
    "ac_rl_best_lap_pct": 108.3,
    "per_sim_progress": {
        "AC": {"tracks": 15, "cars": 42, "solutions": 312},
        "ACC": {"tracks": 8, "cars": 12, "solutions": 96},
        "LMU": {"tracks": 6, "cars": 18, "solutions": 108},
        "iRacing": {"tracks": 22, "cars": 35, "solutions": 287},
        "F1_25": {"tracks": 8, "cars": 2, "solutions": 44}
    }
}
```

## 5. Dependencies

### Python packages (new)

```
casadi>=3.6       # OCP solver (includes IPOPT)
gymnasium>=0.29   # RL environment
stable-baselines3 # PPO/SAC implementations  
torch>=2.0        # Neural surrogate training
tensorboard       # Training monitoring
scipy             # Optimization utilities (already likely installed)
```

### Existing (already available)

```
numpy, pandas, pyarrow   # Data processing
matplotlib               # Visualization (reports)
```

## 6. File Structure (New Code)

```
telemetry_tool/lap_oracle/
├── __init__.py
├── orchestrator.py           # Main 48h runner, job queue, worker management
├── config.py                 # OracleConfig dataclass
├── workers/
│   ├── __init__.py
│   ├── base.py               # BaseWorker ABC
│   ├── harvest.py            # Sim file + data extraction workers
│   ├── identify.py           # Vehicle model fitting workers
│   ├── solve.py              # CasADi OCP solver workers
│   ├── train.py              # Neural surrogate GPU trainer
│   ├── ac_driver.py          # AC RL agent worker
│   └── sweep.py              # Setup sweep workers
├── physics/
│   ├── __init__.py
│   ├── bicycle_model.py      # Single-track vehicle dynamics (from TUM MVDC)
│   ├── pacejka.py            # Pacejka Magic Formula tyre model
│   ├── load_transfer.py      # Extended load transfer (wraps existing)
│   ├── aero.py               # Aero model with setup sensitivity
│   └── powertrain.py         # Engine + drivetrain (wraps existing)
├── track/
│   ├── __init__.py
│   ├── extractor.py          # Track geometry extraction (multi-sim)
│   ├── model.py              # TrackModel dataclass + operations
│   └── grip_map.py           # Surface grip modeling
├── solver/
│   ├── __init__.py
│   ├── ocp.py                # CasADi minimum-time OCP formulation
│   ├── discretization.py     # Collocation point methods
│   └── post_process.py       # Solution extraction + validation
├── neural/
│   ├── __init__.py
│   ├── surrogate.py          # Neural oracle model definition
│   ├── dataset.py            # OCP solution → training data encoding
│   └── trainer.py            # Training loop with checkpointing
├── rl/
│   ├── __init__.py
│   ├── ac_env.py             # AC Gymnasium environment
│   ├── reward.py             # Reward shaping functions
│   └── train_ppo.py          # PPO training pipeline
├── extractors/
│   ├── __init__.py
│   ├── ac_files.py           # AC car/track file parsers
│   ├── acc_files.py          # ACC setup/car data parsers
│   ├── lmu_files.py          # LMU/rF2 vehicle/track file parsers
│   ├── iracing_files.py      # iRacing telemetry + asset parsers
│   └── f125_udp.py           # F1 25 UDP packet capture + parser
├── setup/
│   ├── __init__.py
│   ├── sweep.py              # Latin Hypercube + Bayesian optimization
│   ├── sensitivity.py        # Parameter sensitivity analysis
│   └── mapping.py            # Setup params → vehicle model deltas
├── data_lake.py              # SQLite + Parquet data management
└── report.py                 # Progress + final report generation

scripts/
└── launch_oracle.py          # Entry point: `python scripts/launch_oracle.py --hours 48`
```

## 7. Launch Interface

```bash
# Full 48h autonomous run
python scripts/launch_oracle.py --hours 48

# Quick 4h test run (harvest + identify + solve top-10 combos)
python scripts/launch_oracle.py --hours 4 --quick

# Resume from checkpoint
python scripts/launch_oracle.py --hours 48 --resume

# Specific sim only
python scripts/launch_oracle.py --hours 48 --sims AC,ACC

# With AC RL driving (requires AC running)
python scripts/launch_oracle.py --hours 48 --ac-driver

# Monitor progress (separate terminal)
python scripts/launch_oracle.py --status
```

## 8. Hardware Utilization Plan

| Resource | Phase 1 (0-4h) | Phase 2 (4-8h) | Phase 3 (8-36h) | Phase 4 (36-48h) |
|----------|----------------|----------------|-----------------|-------------------|
| **CPU cores** | Harvest (all) | Identify (all) | Solve (6) + Sweep (2) | Solve (4) + Report (1) |
| **GPU** | Idle | Light (param fitting) | Train (80%) + RL (20%) | Train (100%) |
| **RAM** | ~4GB (data loading) | ~8GB (model fitting) | ~16GB (parallel OCP) | ~12GB (training) |
| **Disk I/O** | Heavy (reading sim files) | Medium | Medium (writing solutions) | Light |

## 9. Success Criteria

After 48 hours, the system should have:

1. **Coverage:** Optimal laps computed for 500+ car/track/condition combinations across all 5 sims
2. **Accuracy:** OCP solutions within 2% of known fastest laps (where reference data exists)
3. **Setup optimization:** For top-50 popular combos, setup recommendations that improve lap time by 0.3-2.0s over default
4. **Neural oracle:** Predictions within 0.5% of OCP solutions on the validation set
5. **AC RL agent:** Completes laps autonomously at 105-115% of optimal pace
6. **Reports:** Per-combo reports with speed trace, racing line, corner coaching, setup recommendations

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| AC not installed / not running | No RL training | RL worker gracefully skips; other workers unaffected |
| Sim files encrypted/inaccessible | Fewer vehicle models | Fall back to telemetry-only param_id + Dallara dataset priors |
| CasADi solve failures | Missing solutions | Log failure, retry with relaxed constraints, fall back to QSS solver |
| GPU OOM during training | Training crashes | Batch size auto-reduction; checkpoint recovery |
| 48h not enough for full coverage | Incomplete database | Priority scheduling ensures highest-value combos solved first |
| Track extraction fails | No track model | Fall back to TUMFTM tracks + recorded GPS traces |
| F1 25 not installed | No F1 25 data | Worker skipped; 4 sims still covered |
