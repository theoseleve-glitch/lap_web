# Lap Oracle — Autonomous 48-Hour Optimal Lap Time System

**Date:** 2026-04-03
**Status:** Draft
**Sims:** Assetto Corsa, ACC, Le Mans Ultimate, iRacing, F1 2021 (CodeMasters UDP)

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

#### W5: AC Driver Worker — FULLY AUTONOMOUS (CPU + GPU time-shared)

**Purpose:** Own the entire AC lifecycle — launch, configure, drive, collect, kill, repeat — for 48 hours unattended.

**The user walks away after pressing "go". No human intervention for 48 hours.**

**AC Process Manager:**
The worker controls AC as a subprocess:
```
Loop (for each car/track combo in priority queue):
  1. Write race.ini → set car model, track, practice session, no opponents
  2. Launch AC via direct exe or Steam CLI
  3. Wait for SHM connection (poll acpmf_physics, timeout 60s)
  4. Wait for session_active (graphics.status == ACC_LIVE)
  5. Drive N laps with RL agent (collect telemetry via SHM read)
  6. Kill AC process (taskkill /F /IM acs.exe)
  7. Process collected telemetry → feed to Identify + Solve workers
  8. Pick next car/track combo from priority queue
  9. Goto 1
```

**race.ini manipulation:**
```ini
; Written by Oracle before each AC launch
[RACE]
MODEL=ks_ferrari_488_gt3    ; car folder name
TRACK=monza                  ; track folder name  
CONFIG_TRACK=                ; track layout variant
AI_LEVEL=0                   ; no AI opponents
SESSION_NAME=practice
LAPS=0                       ; unlimited
TIME=30                      ; 30 min session
```

File location: `C:/Users/Admin/Documents/Assetto Corsa/cfg/race.ini`

**AC launch command:**
```bash
# Direct exe (faster, no Steam overlay)
"C:/Program Files (x86)/Steam/steamapps/common/assettocorsa/AssettoCorsa.exe"

# Or via Steam (ensures proper init)  
start steam://rungameid/244210
```

**Control injection via AC Python app:**
AC loads Python apps from `apps/python/` at startup. We install `lap_oracle_bridge/`:

```
assettocorsa/apps/python/lap_oracle_bridge/
├── lap_oracle_bridge.py    # Main AC app (runs inside AC process)
└── config.ini              # App metadata
```

The bridge app:
1. Starts a TCP server on `localhost:9876` inside AC
2. Receives control commands: `{"throttle": 0.8, "brake": 0.0, "steer": -0.12, "gear": 4}`
3. Applies via `ac.ext_setDriverInput()` (CSP) or native `ac.setInput()` calls
4. Sends back state confirmation

The Oracle connects to this TCP socket after AC launches.

**Fallback if bridge fails:** Pure data collection mode — AC drives with AI, Oracle reads telemetry via SHM. Less useful but still collects vehicle dynamics data.

**Car/track enumeration:**
Oracle scans `C:/Program Files (x86)/Steam/steamapps/common/assettocorsa/content/cars/` and `content/tracks/` to discover all installed cars and tracks. Prioritizes by:
1. Cars with existing telemetry data (can validate models)
2. Popular combos (GT3 cars on racing circuits)
3. Untested combos (exploration for coverage)

**Session flow per combo (~5-10 minutes each):**
- Laps 1-2: Warm-up (conservative driving, tyre temp buildup)
- Laps 3-8: Data collection (RL agent pushes limits, varied lines)
- Laps 9-10: Validation (attempt OCP-optimal trajectory)
- Kill AC, process data, move to next combo

**Throughput estimate (48h):**
- ~7 min per combo (AC launch + 10 laps + kill + process)
- ~8 combos/hour = **~380 car/track combos in 48 hours**
- With 50 cars × 20 tracks = 1000 possible combos
- Priority scheduling ensures highest-value combos first

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

### 3.3 F1 2021 UDP Adapter (New)

**Note:** F1 25 is NOT installed. F1 2021 (`D:/SteamLibrary/steamapps/common/F1 2021/`) uses the same CodeMasters UDP telemetry format:

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

**Phase scheduling (fully autonomous, zero human intervention):**
```
Phase 1 (hours 0-2):   HARVEST — extract all zip files, sim files, iRacing .ibt, F1 telemetry
                        (~18GB of F1 zips + 24GB iRacing .ibt + sim files)
Phase 2 (hours 2-6):   IDENTIFY — fit vehicle models from harvested data
                        AC Driver starts: first car/track combo launched
Phase 3 (hours 6-24):  SOLVE+DRIVE+TRAIN — OCP solving, AC cycling through combos,
                        GPU training starts once first solutions arrive
Phase 4 (hours 24-40): FULL PARALLEL — all workers active, setup sweeping,
                        AC focused on high-value combos, neural net improving
Phase 5 (hours 40-46): REFINE — re-solve with improved models from AC data,
                        deep setup optimization on top-50 combos
Phase 6 (hours 46-48): REPORT — generate final reports, save models, stop AC
```

**Pre-flight (user does ONCE before walking away):**
1. Run `python scripts/setup_oracle.py` — installs AC bridge app, verifies SHM, checks deps
2. Run `python scripts/launch_oracle.py --hours 48` — starts the system
3. Walk away

**Fault tolerance:**
- Workers catch all exceptions, log, and continue to next job
- Orchestrator monitors worker health (heartbeat every 60s)
- Crashed workers auto-restart with backoff
- **AC crash recovery:** if AC hangs or crashes, kill process, wait 30s, relaunch with same or next combo
- **AC launch timeout:** if SHM not connected within 90s of launch, kill and retry (max 3 retries per combo)
- All intermediate results persisted to disk (resume-safe)
- SQLite WAL mode for concurrent reads/writes
- **Power-safe:** checkpoint state every 5 minutes. `--resume` flag picks up where it left off

**Available data for harvest** (from Downloads):
- `2022-main.zip` — 65K F1 telemetry files (3.8 GB)
- `2023-main.zip` — 65K F1 telemetry files (3.8 GB)
- `2024-main.zip` — 73K F1 telemetry files (4.3 GB)
- `2025-main.zip` — 143K F1 telemetry files (5.0 GB), 25 GPs, ~70K laps
- `2026-main.zip` — 20K F1 telemetry files (1.3 GB)
- `raw.zip` — 30 kart session CSVs (649 MB)
- `archive.zip` — Kaggle F1 lap data (20 MB)
- `archive (1).zip` — Dallara 100K (5 MB)
- `archive (2).zip` — Motorsport data (59 MB)
- `archive (3).zip` — Simulated dataset (223 MB)
- iRacing: 100+ .ibt files (24 GB) in `Documents/iRacing/telemetry/`
- Total: **~43 GB of training data**

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
| F1 2021 not running | No F1 UDP data | Worker skipped; 4 sims still covered |

## 11. Discovered Sim Install Paths (from machine scan)

### Assetto Corsa
- **Install:** `C:/Program Files (x86)/Steam/steamapps/common/assettocorsa/` + `D:/SteamLibrary/steamapps/common/assettocorsa/`
- **Car physics:** `content/cars/*/data.acd` (encrypted ZIP with car.ini, tyres.ini, drivetrain.ini, suspensions.ini, aero.ini)
- **Track AI:** `content/tracks/*/ai/fast_lane.ai.csv` (racing line + boundaries)
- **User setups:** `C:/Users/Admin/Documents/Assetto Corsa/setups/` (ferrari_312t, ks_ferrari_sf70h, ks_praga_r1, tatuusfa1, ad_sodi_rt10_gx390, yzd_alpine_a110_1600s)
- **Telemetry:** `C:/Users/Admin/Documents/Assetto Corsa/ctelemetry/` + `aim/telemetry_dump.act` (12.9 MB)

### ACC
- **Install:** `C:/Program Files (x86)/Steam/steamapps/common/Assetto Corsa Competizione/`
- **Track fastlane:** `AC2/Content/Cache/` (AI fastlane data for 24+ tracks: barcelona, monza, spa, silverstone, etc.)
- **User setups:** `C:/Users/Admin/Documents/Assetto Corsa Competizione/Setups/`
- **MoTeC:** `C:/Users/Admin/Documents/Assetto Corsa Competizione/MoTeC/`
- **Results:** `C:/Users/Admin/Documents/Assetto Corsa Competizione/Results/`

### iRacing
- **Telemetry:** `C:/Users/Admin/Documents/iRacing/telemetry/` — **24GB, 100+ .ibt files** (ferrari488gt3, formulair04, ligierjsp320, bmwm2csr, etc.)
- **Setups:** `C:/Users/Admin/Documents/iRacing/setups/` — **108 car directories** (audirs3lms, ferrari488gt3, ferrari499p, formulair04, bmwm4gt3, etc.)
- **Lap files:** `C:/Users/Admin/Documents/iRacing/lapfiles/`
- **Config:** `C:/Users/Admin/Documents/iRacing/app.ini`

### Le Mans Ultimate
- **Install:** `D:/SteamLibrary/steamapps/common/Le Mans Ultimate/`
- **Vehicles:** `Core/Vehicles/` (vehicle physics and models in .mas archives)
- **Locations:** `Core/Locations/` (Commonmaps.mas 212 MB)
- **Weather:** `Core/Shared/WeatherFX.mas` (18.4 MB) + `Weather.mas` (2.2 MB)
- **User setups:** `UserData/Setups/`

### F1 2021
- **Install:** `D:/SteamLibrary/steamapps/common/F1 2021/`
- **No F1 25 found** — F1 2021 is the latest F1 game installed

### Bonus Sims (lower priority)
- **rFactor 2:** `D:/SteamLibrary/steamapps/common/rFactor2/` (shares engine with LMU)
- **RaceRoom:** `D:/SteamLibrary/steamapps/common/raceroom racing experience/` (90+ car folders)
- **Automobilista 2:** `D:/SteamLibrary/steamapps/common/Automobilista 2/`
- **KartKraft:** on D: drive

## 12. TUM MVDC Key Algorithms (Extracted from ZIP)

### Vehicle Model (Single-Track Bicycle)
```
State: [x, y, psi, vx, vy]
Inputs: [dPsi_radps, ax_mps2, ay_mps2]

Longitudinal: vx[k+1] = vx[k] + (ax + dPsi*vy)*Ts
Lateral:      vy[k+1] = vy[k] + (ay - dPsi*vx)*Ts
Yaw:          psi[k+1] = psi[k] + dPsi*Ts
Position:     Heun 2nd-order integration (global frame)
```

### Pacejka Tire Force
```
Fy = C * sin(B * atan(A*alpha - D*(A*alpha - atan(A*alpha))))
Slip angle: alpha = atan2(-vyT, vxT) per tire (rotated by steering)
Long slip:  lambda = 100*(v_wheel - v_ref)/max(v_min, v_ref)
```

### EKF State Estimation
- Prediction: state propagation with Q = B_d*diag(InputCov)*B_d'
- Update: K = P_pred*H_d / (H_d*P_pred*H_d' + R) with outlier rejection
- Fuses: 2 localization sources + 2 velocity sources (selective via bitmask)

### Tube-MPC Trajectory Tracking
- Horizon: N = 40 steps
- Coordinates: curvilinear (arc-length s, lateral offset d, relative heading)
- Solver: OSQP quadratic programming
- Constraints: lateral bounds, friction circle, terminal invariant set

### Online Learning
- **RLS:** Recursive Least Squares for model weight adaptation
- **Disturbance:** Recursive mean + quantile bound estimation
- **Steering:** Gaussian process in (curvature, velocity) space
