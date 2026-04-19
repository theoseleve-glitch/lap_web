# Lap Oracle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully autonomous system that runs for 48 hours unattended, computing physics-optimal lap times across AC/ACC/LMU/iRacing/F1, training a neural surrogate, and driving autonomously in Assetto Corsa.

**Architecture:** Worker pool orchestrator manages 6 worker types (harvest, identify, solve, train, AC driver, sweep) communicating through a Parquet + SQLite data lake. CasADi IPOPT solves minimum-time OCPs, PyTorch trains the neural surrogate on GPU, stable-baselines3 PPO drives in AC via a bridge Python app.

**Tech Stack:** Python 3.11+, CasADi (IPOPT), PyTorch, stable-baselines3, gymnasium, numpy, pandas, pyarrow, scipy

**Spec:** `docs/superpowers/specs/2026-04-03-lap-oracle-design.md`

**Note:** All serialization uses JSON and numpy npz (no pickle). PyTorch model checkpoints use torch.save which uses pickle internally but only for trusted model weights.

---

## Dependencies

Install before starting:
```bash
pip install casadi gymnasium stable-baselines3 torch tensorboard scipy
```

## File Map

All new files under `telemetry_tool/lap_oracle/`. Tests under `telemetry_tool/tests/test_lap_oracle/`.

See spec section 6 for full file tree. 14 tasks, ~30 files.

## Execution Order

```
Task 1 (config) + Task 2 (lake)  [sequential, foundation]
    |
Task 3 (physics) + Task 4 (track)  [parallel]
    |
Task 5 (solver)  [depends on 3+4]
    |
Task 6 (extractors) + Task 9 (neural) + Task 10 (RL env)  [parallel]
    |
Task 7 (harvest) + Task 8 (identify+solve) + Task 11 (AC driver+train) + Task 12 (sweep)  [parallel]
    |
Task 13 (orchestrator) + Task 14 (launch scripts)  [final]
```

---

## Task 1: Config and Data Structures

**Files:**
- Create: `telemetry_tool/lap_oracle/__init__.py`
- Create: `telemetry_tool/lap_oracle/config.py`
- Test: `telemetry_tool/tests/test_lap_oracle/test_config.py`

- [ ] **Step 1: Create package skeleton**

```bash
mkdir -p telemetry_tool/lap_oracle/{physics,track,solver,neural,rl/ac_bridge,extractors,setup,workers}
mkdir -p telemetry_tool/tests/test_lap_oracle
```

Create `__init__.py` in each directory.

- [ ] **Step 2: Write config.py**

Contains frozen/mutable dataclasses: `PacejkaParams`, `SetupParams`, `VehicleParams`, `TrackModel`, `WeatherConditions`, `OCPSolution`, `OracleConfig`. Also `SIM_PATHS` and `DATA_ZIPS` dicts pointing to discovered install locations.

Key types:
- `VehicleParams`: mass, wheelbase, aero (CdA, ClA), Pacejka tyre params, setup, powertrain
- `TrackModel`: centerline_xy, width_left/right, curvature, elevation, banking, grip_map
- `SetupParams`: 19 params with `to_array()`/`from_array()` for optimization
- `OCPSolution`: lap time, speed/throttle/brake/steering profiles, solver metadata

Full implementation in spec section 3.2.

- [ ] **Step 3: Write tests** — roundtrip serialization for VehicleParams, SetupParams array conversion, TrackModel properties, WeatherConditions encoding.

- [ ] **Step 4: Run tests, commit**

```bash
python -m pytest telemetry_tool/tests/test_lap_oracle/test_config.py -v
git commit -m "feat(oracle): config dataclasses and package skeleton"
```

---

## Task 2: Data Lake (SQLite job queue + file storage)

**Files:**
- Create: `telemetry_tool/lap_oracle/data_lake.py`
- Test: `telemetry_tool/tests/test_lap_oracle/test_data_lake.py`

- [ ] **Step 1: Write DataLake class**

SQLite WAL-mode database with tables:
- `jobs`: id, job_type, sim, car, track, status, priority, payload (JSON), result (JSON), timestamps, worker_id, error
- `progress`: timestamp, phase, counters, details

Methods: `add_job()`, `claim_job()` (atomic select+update), `complete_job()`, `count_jobs()`, `job_exists()`.

File storage: `save_vehicle(VehicleParams)` -> JSON, `load_vehicle()`, `save_track(TrackModel)` -> npz, `load_track()`, `save_solution(OCPSolution)` -> JSON + npz, `count_solutions()`, `log_progress()`, `get_progress_summary()`.

- [ ] **Step 2: Write tests** — job lifecycle (add/claim/complete), vehicle roundtrip, track roundtrip, solution save, no-duplicate guard.

- [ ] **Step 3: Run tests, commit**

```bash
python -m pytest telemetry_tool/tests/test_lap_oracle/test_data_lake.py -v
git commit -m "feat(oracle): SQLite job queue and data lake"
```

---

## Task 3: Physics Engine (Pacejka + Bicycle Model)

**Files:**
- Create: `telemetry_tool/lap_oracle/physics/pacejka.py`
- Create: `telemetry_tool/lap_oracle/physics/bicycle_model.py`
- Create: `telemetry_tool/lap_oracle/physics/vehicle.py`
- Test: `telemetry_tool/tests/test_lap_oracle/test_physics.py`

- [ ] **Step 1: Write pacejka.py**

Pacejka Magic Formula (from TUM MVDC):
```
Fy = D * Fz * sin(C * arctan(B*alpha - E*(B*alpha - arctan(B*alpha))))
```

Functions: `lateral_force(slip_angle_rad, fz, params)`, `longitudinal_force(slip_ratio, fz, params)`, `combined_slip(fx0, fy0, kappa, alpha)`, `peak_mu(params)`.

- [ ] **Step 2: Write bicycle_model.py**

Functions:
- `max_lateral_accel(v, vp)`: mu * (mg + aero_downforce) / m
- `max_longitudinal_accel(v, vp, braking)`: min(tyre_limit, power_limit) - drag - RR (or + for braking)
- `corner_speed(curvature, vp)`: solve v^2*kappa = ay_max including aero
- `combined_accel_limit(ax, ay, v, vp)`: friction ellipse check

- [ ] **Step 3: Write vehicle.py** — bridge from existing `sim_optimizer/param_id` results to `VehicleParams`.

- [ ] **Step 4: Write tests** — Pacejka peak at moderate slip, lateral accel increases with speed (aero), corner speed decreases with curvature, braking > accel at high speed.

- [ ] **Step 5: Run tests, commit**

```bash
python -m pytest telemetry_tool/tests/test_lap_oracle/test_physics.py -v
git commit -m "feat(oracle): Pacejka tyre model + bicycle dynamics"
```

---

## Task 4: Track Model Extraction

**Files:**
- Create: `telemetry_tool/lap_oracle/track/model.py`
- Create: `telemetry_tool/lap_oracle/track/extractor.py`
- Test: `telemetry_tool/tests/test_lap_oracle/test_track.py`

- [ ] **Step 1: Write model.py** — `build_from_xy(xy, width, name, sim)` computes curvature via finite differences, total length. `resample_track(tm, ds_target)` resamples to uniform spacing.

- [ ] **Step 2: Write extractor.py** — `extract_ac_track(track_folder)` parses AC AI fast_lane binary/CSV. `extract_from_telemetry_xy(positions)` builds from recorded GPS. `discover_ac_tracks()` scans AC content folders.

- [ ] **Step 3: Write tests** — oval track curvature, resample uniformity, extraction from telemetry.

- [ ] **Step 4: Run tests, commit**

```bash
python -m pytest telemetry_tool/tests/test_lap_oracle/test_track.py -v
git commit -m "feat(oracle): track model extraction from AC AI files and telemetry"
```

---

## Task 5: CasADi OCP Solver

**Files:**
- Create: `telemetry_tool/lap_oracle/solver/ocp.py`
- Create: `telemetry_tool/lap_oracle/solver/fallback_qss.py`
- Test: `telemetry_tool/tests/test_lap_oracle/test_solver.py`

- [ ] **Step 1: Write ocp.py** — `solve_minimum_time(track, vehicle, weather, n_points, max_time_s)`

Spatial OCP formulation:
- Decision variables: V[N] (speed), N_lat[N] (lateral offset), Ax[N-1] (acceleration)
- Objective: minimize sum(ds / v_avg) = total lap time
- Constraints: v_{i+1}^2 = v_i^2 + 2*ax*ds (dynamics), friction ellipse (ax/ax_max)^2 + (ay/ay_max)^2 <= 1, power limit, brake limit, track boundaries
- Periodic boundary: V[0] == V[-1]
- Initial guess from corner_speed() for fast convergence
- Solver: CasADi Opti + IPOPT, max 3000 iterations, print_level=0
- Returns OCPSolution with optimal speed profile, controls, lap time

- [ ] **Step 2: Write fallback_qss.py** — forward/backward integration (existing QSS algorithm) as fallback when CasADi unavailable or solve fails.

- [ ] **Step 3: Write tests** — QSS produces valid time on oval, heavier car slower, wet slower, speed in bounds. CasADi test (skipped if not installed).

- [ ] **Step 4: Run tests, commit**

```bash
python -m pytest telemetry_tool/tests/test_lap_oracle/test_solver.py -v
git commit -m "feat(oracle): CasADi minimum-time OCP solver + QSS fallback"
```

---

## Task 6: Sim File Extractors

**Files:**
- Create: `telemetry_tool/lap_oracle/extractors/ac_files.py`
- Create: `telemetry_tool/lap_oracle/extractors/iracing_ibt.py`
- Create: `telemetry_tool/lap_oracle/extractors/f1_zips.py`
- Create: `telemetry_tool/lap_oracle/extractors/acc_files.py`
- Create: `telemetry_tool/lap_oracle/extractors/lmu_files.py`
- Test: `telemetry_tool/tests/test_lap_oracle/test_extractors.py`

- [ ] **Step 1: Write ac_files.py** — parse car data from `data.acd` (encrypted ZIP), extract mass/aero/tyre from INI files. Discover installed cars.

- [ ] **Step 2: Write iracing_ibt.py** — binary .ibt reader (header struct + channel data). Extract positions, speed, g-forces, setup params.

- [ ] **Step 3: Write f1_zips.py** — traverse 2022-2026 zip archives, extract telemetry JSON, standardize to arrays.

- [ ] **Step 4: Write acc_files.py** — parse ACC setup JSON files from Documents folder.

- [ ] **Step 5: Write lmu_files.py** — parse rFactor 2 format .hdv/.veh vehicle files.

- [ ] **Step 6: Write tests, commit**

```bash
git commit -m "feat(oracle): sim file extractors for AC, ACC, LMU, iRacing, F1"
```

---

## Task 7: Worker Base + Harvest Worker

**Files:**
- Create: `telemetry_tool/lap_oracle/workers/base.py`
- Create: `telemetry_tool/lap_oracle/workers/harvest.py`
- Test: `telemetry_tool/tests/test_lap_oracle/test_workers.py`

- [ ] **Step 1: Write base.py** — `BaseWorker` ABC with `start()`, `stop()`, `tick()`, threaded run loop, heartbeat tracking, crash recovery with backoff.

- [ ] **Step 2: Write harvest.py** — `HarvestWorker` enqueues discovery jobs on first tick, then processes: AC tracks, iRacing .ibt, F1 zips, existing data/external/ files.

- [ ] **Step 3: Write tests, commit**

```bash
git commit -m "feat(oracle): base worker + harvest worker"
```

---

## Task 8: Identify + Solve Workers

**Files:**
- Create: `telemetry_tool/lap_oracle/workers/identify.py`
- Create: `telemetry_tool/lap_oracle/workers/solve.py`

- [ ] **Step 1: Write identify.py** — claims "identify" jobs, runs existing param_id pipeline on telemetry, saves VehicleParams.

- [ ] **Step 2: Write solve.py** — claims "solve" jobs, loads VehicleParams + TrackModel, calls `solve_minimum_time()`, saves OCPSolution. Enqueues new solve jobs when new vehicles/tracks discovered.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(oracle): identify + solve workers"
```

---

## Task 9: Neural Surrogate (PyTorch)

**Files:**
- Create: `telemetry_tool/lap_oracle/neural/surrogate.py`
- Create: `telemetry_tool/lap_oracle/neural/dataset.py`
- Create: `telemetry_tool/lap_oracle/neural/trainer.py`
- Test: `telemetry_tool/tests/test_lap_oracle/test_neural.py`

- [ ] **Step 1: Write surrogate.py** — `LapOracle(nn.Module)` with 4 encoders (car/track/setup/weather), fusion backbone (352->512->512->256), 4 output heads (lap_time, sectors, speed_profile, setup_delta). ~800K params.

- [ ] **Step 2: Write dataset.py** — `OracleDataset(Dataset)` loads solutions from data lake, encodes features.

- [ ] **Step 3: Write trainer.py** — continuous training loop: load data, train, checkpoint every 30 min, reload new solutions every 2 hours.

- [ ] **Step 4: Test forward pass, commit**

```bash
git commit -m "feat(oracle): neural surrogate model + dataset + trainer"
```

---

## Task 10: AC RL Environment + Bridge App

**Files:**
- Create: `telemetry_tool/lap_oracle/rl/ac_env.py`
- Create: `telemetry_tool/lap_oracle/rl/reward.py`
- Create: `telemetry_tool/lap_oracle/rl/ac_bridge/lap_oracle_bridge.py`
- Create: `telemetry_tool/lap_oracle/rl/ac_bridge/config.ini`

- [ ] **Step 1: Write ac_env.py** — `ACGymEnv(gymnasium.Env)` with observation_space (23 features: speed, accels, tyre temps, upcoming curvature, etc.), action_space (steering, throttle, brake). Connects to AC SHM for reading, TCP socket to bridge for writing.

- [ ] **Step 2: Write reward.py** — `compute_reward(obs, action, prev_lap_dist)` with progress reward, speed bonus, smoothness penalty, off-track penalty.

- [ ] **Step 3: Write bridge app** — `lap_oracle_bridge.py` is an AC Python app installed into `apps/python/`. Starts TCP server on port 9876, receives JSON control commands, applies via `ac.ext_setDriverSteer/Gas/Brake()`.

- [ ] **Step 4: Write config.ini** for AC app registration.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(oracle): AC Gym env + reward shaping + bridge app"
```

---

## Task 11: AC Driver Worker + Train Worker

**Files:**
- Create: `telemetry_tool/lap_oracle/workers/ac_driver.py`
- Create: `telemetry_tool/lap_oracle/workers/train.py`

- [ ] **Step 1: Write ac_driver.py** — Full autonomous AC lifecycle:
  1. Scan installed AC cars/tracks
  2. Pick highest-priority combo from queue
  3. Write `race.ini` (car, track, practice, no AI)
  4. Launch `AssettoCorsa.exe`
  5. Wait for SHM connection (timeout 90s)
  6. Drive N laps with PPO agent
  7. Kill AC process (`taskkill /F /IM acs.exe`)
  8. Process collected telemetry -> feed to identify/solve
  9. Repeat

- [ ] **Step 2: Write train.py** — GPU worker: loads OracleDataset, trains LapOracle, checkpoints, reloads data periodically.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(oracle): AC driver worker (autonomous) + GPU train worker"
```

---

## Task 12: Setup Sweep Worker

**Files:**
- Create: `telemetry_tool/lap_oracle/workers/sweep.py`
- Create: `telemetry_tool/lap_oracle/setup/mapping.py`

- [ ] **Step 1: Write mapping.py** — `apply_setup_delta(vehicle, setup)` maps setup params to vehicle model changes (wing -> Cd/Cl, spring -> roll stiffness, camber -> Pacejka D, pressure -> Pacejka B).

- [ ] **Step 2: Write sweep.py** — Latin Hypercube Sampling over setup space (N=100 samples), solve OCP for each, find minimum. Then Bayesian optimization around best region.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(oracle): setup sweep with LHS + Bayesian optimization"
```

---

## Task 13: Orchestrator + Report

**Files:**
- Create: `telemetry_tool/lap_oracle/orchestrator.py`
- Create: `telemetry_tool/lap_oracle/report.py`

- [ ] **Step 1: Write orchestrator.py** — `Orchestrator(config, resume)` with `run()` method:
  - Phase 1 (0-2h): spawn harvest workers
  - Phase 2 (2-6h): spawn identify workers, start AC driver
  - Phase 3 (6-24h): spawn solve workers, start GPU trainer
  - Phase 4 (24-40h): add sweep workers
  - Phase 5 (40-46h): refine mode
  - Phase 6 (46-48h): generate reports, shutdown
  - Monitor heartbeats, restart dead workers, write progress.json every 5 min

- [ ] **Step 2: Write report.py** — `generate_progress_report(lake)` writes JSON + terminal summary. `generate_final_report(lake)` produces markdown with per-sim stats, top solutions, setup recommendations.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(oracle): orchestrator with phase scheduling + reports"
```

---

## Task 14: Launch Scripts

**Files:**
- Create: `scripts/launch_oracle.py`
- Create: `scripts/setup_oracle.py`

- [ ] **Step 1: Write launch_oracle.py** — argparse CLI: `--hours`, `--quick`, `--resume`, `--status`, `--sims`, `--no-ac-driver`, `--no-gpu`. Creates OracleConfig, instantiates Orchestrator, runs with Ctrl+C graceful shutdown.

- [ ] **Step 2: Write setup_oracle.py** — pre-flight checks: verify dependencies (casadi, torch, gymnasium, sb3), check sim install paths, check data zips, install AC bridge app to `apps/python/lap_oracle_bridge/`.

- [ ] **Step 3: Test and commit**

```bash
python scripts/setup_oracle.py
python scripts/launch_oracle.py --status
git commit -m "feat(oracle): launch + setup scripts"
```

---

## Final Integration Test

After all tasks:

```bash
# Quick 5-minute smoke test (no AC, no GPU)
python scripts/launch_oracle.py --hours 0.08 --no-ac-driver --no-gpu

# Check results
python scripts/launch_oracle.py --status
```

Expected: harvest discovers tracks/vehicles, QSS solver produces solutions, progress report shows non-zero counts.
