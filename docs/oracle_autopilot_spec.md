# Oracle Autopilot — AC Telemetry Collection System Spec

## Goal

Autonomous data collection from Assetto Corsa: cycle through car/track/AI/weather combinations, record 60Hz telemetry from all AI cars, post-process with data-driven human driving model and labeled driving events.

## Architecture

```
generate_ac_jobs.py -> ac_jobs.lua (job queue)
                          |
oracle_autopilot.py -> Content Manager UI -> Assetto Corsa
                          |                      |
                     (car/track select     (Lua app records
                      + Go! click)          AI cars at 60Hz)
                          |                      |
                     ac_state.lua <---- lap_oracle.lua
                          |
                     postprocess_ac_telemetry.py
                          |
                     human_driving_model.py (data-driven from TUMFTM + kaggle)
                          |
                     driving_events.py (10 event types, labeled)
```

## Components

### 1. Job Queue Generator (scripts/generate_ac_jobs.py)

Generates data/oracle/ac_jobs.lua -- Lua table of job specs:
- Discovers installed AC cars + tracks automatically
- Matrix: car x track x AI level x weather preset
- Each job: {car, track, ai_level, opponents, laps, weather, weather_gfx, temp_ambient, temp_track, wind_min, wind_max}

```bash
python scripts/generate_ac_jobs.py --max-cars 10 --ai-levels "80,100" --weather "clear_hot,heavy_rain"
```

### 2. Autopilot (scripts/oracle_autopilot.py)

Minimal UI automation approach -- user pre-configures CM once, autopilot only does:

**Pre-requisites (ONE-TIME manual setup):**
1. Open Content Manager -> DRIVE -> QUICK -> single
2. Click RACE tab
3. Set opponents count, AI level, Grid: Same car
4. Leave CM open

**Per-job automation (4 steps):**
1. Change car: click car image -> filter by name -> double-click match -> Back
2. Change track: click track image -> click track in list -> OK
3. Click Go! -> AC launches
4. After AC loads: press Escape (dismiss overlays) -> click Drive button (steering wheel icon at y=165 on 3840x2160) -> Ctrl+C (autopilot)

**Between jobs:**
- Kill AC process
- Collect telemetry files from Lua output dir
- Post-process (smooth inputs + event labels)
- Advance job index

**Safety:**
- Square key (French keyboard, scan code 41) = emergency kill all
- CM never auto-launched -- waits for user
- Stops when CM dies instead of burning through jobs

### 3. CSP Lua App (D:/SteamLibrary/.../apps/lua/lap_oracle/lap_oracle.lua)

Runs inside AC, records ALL AI cars at 60Hz.

**Phases:** init -> warmup (wait for AI to reach 10km/h) -> driving (sample all cars) -> saving -> restart

**Per batch:** 5 laps x N AI cars, then ac.tryToRestartSession() for next batch. 10 batches per session.

**Humanization of AI (in-game):**
- physics.setExtraAIGrip(i, 1.0) -- remove 120% grip advantage
- AI level spread: session AI +/-15% per car
- Random aggression, spline offset, steering imprecision, caution
- Periodic mistake injection: brake lockup (5%), traction (3%), line shift (2%)

**Data columns (32):**
```
session_id, car_index, timestamp, lap, spline_pos, speed_ms, gas, brake, steer,
gear, rpm, pos_x, pos_y, pos_z, vel_x, vel_y, vel_z, g_lat, g_lon,
tyre_fl_temp, tyre_fr_temp, tyre_rl_temp, tyre_rr_temp, lap_time_ms,
car_name, track_name, ai_level, weather, temp_ambient, temp_track,
rain_intensity, wind_kmh, batch
```

**State file:** Documents/Assetto Corsa/lap_oracle/ac_state.lua
```lua
return {batch=3, lapsDone=2, car="bmw_m3_e30", track="magione"}
```

**Telemetry output:** .lua files wrapping CSV (CSP sandbox blocks .csv writes)
```lua
-- telemetry data
return [[
session_id,car_index,timestamp,...
data,rows,here,...
]]
```

**Known CSP sandbox limitations:**
- io.save() works for .lua files only
- Large files (>100KB) may silently fail -- needs testing with chunked writes
- Path traversal (../) blocked -- must stay within AC Documents or app folder

### 4. Post-Processor (scripts/postprocess_ac_telemetry.py)

Three-stage pipeline per car:

**Stage 1: Optimal input reconstruction** (reconstruct_optimal_inputs)
- Physics -> inputs: g_lon -> throttle/brake, g_lat + speed -> steering
- 2-second zero-phase smoothing (coaching-quality)
- Trail-brake overlap blending
- Output: opt_throttle, opt_brake, opt_steer (EVENTLESS clean reference)

**Stage 2: Data-driven human model** (human_driving_model.py)
- Trained from 553K samples of real racing data (TUMFTM + kaggle_motorsport)
- Spectral shaping: noise matches real human PSD (97% below 1Hz for throttle, 100% below 2Hz for steering)
- Asymmetric rate limiting: throttle applies slow / lifts fast (ratio 0.76), brake presses fast / releases slow (ratio 1.22 = trail-brake)
- Micro-corrections in steering every 20-40ms
- Throttle-brake overlap constrained to ~4.3%
- Output: human_throttle, human_brake, human_steer, driver_skill

**Stage 3: Event labels** (driving_events.py)
- Corner detection from speed/g-force data
- 10 event types: understeer, oversteer, late/early brake, late/early turn-in, slow/fast correction, throttle hesitation, brake lockup
- Lap structure: warmup -> building -> REFERENCE -> event_mild -> event_hard
- Output: event_type, event_id, event_severity, event_phase, lap_type, corner_id

### 5. Human Driving Model (scripts/human_driving_model.py)

**Training data:**
- TUMFTM (TU Munich): 1.7M samples, steering (rad) + brake pressure (bar), ~50Hz, real test track
- kaggle_motorsport: 286K samples, throttle (0-100) + brake pressure, 50Hz, real racing at Ales circuit

**Learned fingerprint:**

| Property | Value | Source |
|----------|-------|--------|
| Throttle press rate | 0.0106/sample | kaggle |
| Throttle release rate | 0.0139/sample | kaggle |
| Throttle press:release | 0.76 | kaggle |
| Brake press rate | 0.0356/sample | TUMFTM |
| Brake release rate | 0.0292/sample | TUMFTM |
| Brake press:release | 1.22 (trail-brake) | TUMFTM |
| Steering rate | 0.000472 rad/sample | TUMFTM |
| Steering corrections | 26Hz (every 20-40ms) | TUMFTM |
| Throttle power <1Hz | 97.1% | kaggle |
| Brake power <1Hz | 95.8% | TUMFTM |
| Steering power <2Hz | 100% | TUMFTM |
| Throttle-brake overlap | 4.3% | kaggle |

**Saved model:** data/oracle/human_model.npz (numpy arrays, no pickle)

### 6. Driving Events Library (scripts/driving_events.py)

**Event types:**

| Event | What happens | Duration |
|-------|-------------|----------|
| understeer | Extra steering lock + throttle lift | 0.5-2.0s |
| oversteer | Counter-steer + throttle lift + brake tap | 0.3-1.5s |
| late_brake | Brake point shifted later, higher pressure | 0.3-0.5s |
| early_brake | Brake earlier, lower pressure | 0.2-0.4s |
| late_turnin | Delayed steering, aggressive correction | 0.2-0.5s |
| early_turnin | Premature steering, wide exit | 0.3-0.6s |
| slow_correction | 300-500ms response delay to slide | 0.5-1.0s |
| fast_correction | 100-200ms snap response | 0.2-0.4s |
| throttle_hesitation | Pulse/lift before committing on exit | 0.3-0.8s |
| brake_lockup | Overpress -> release -> reapply | 0.3-0.6s |

**Lap structure (5 laps):**
1. Warmup -- conservative (slight delays, earlier braking)
2. Building -- approaching optimal
3. REFERENCE -- cleanest, near-optimal (eventless baseline)
4. Event mild -- 1-3 events, severity 0.3-0.55
5. Event hard -- 2-4 events, severity 0.55-0.92

**Labels per sample:** event_type, event_id, event_severity, event_phase (onset/peak/recovery), lap_type, corner_id

## File Locations

| File | Purpose |
|------|---------|
| scripts/oracle_autopilot.py | Main autopilot loop |
| scripts/generate_ac_jobs.py | Job queue generator |
| scripts/postprocess_ac_telemetry.py | Post-processing pipeline |
| scripts/human_driving_model.py | Data-driven human model |
| scripts/driving_events.py | Event library + corner detection |
| D:/.../apps/lua/lap_oracle/lap_oracle.lua | CSP Lua app (runs inside AC) |
| D:/.../apps/lua/lap_oracle/manifest.ini | Lua app manifest |
| data/oracle/ac_jobs.lua | Job queue (Lua table) |
| data/oracle/autopilot_progress.json | Current job index |
| data/oracle/human_model.npz | Trained human driving model |
| Documents/Assetto Corsa/lap_oracle/ac_state.lua | Lua app state (batch/laps) |
| Documents/Assetto Corsa/lap_oracle/batch_NN.lua | Telemetry output (.lua wrapping CSV) |
| data/oracle/telemetry/ac/ | Collected raw CSVs |
| data/oracle/telemetry/processed/ | Post-processed CSVs |

## Proven Working (tested 2026-04-09)

- Car selection via pywinauto filter + double-click
- Track selection via text click in CM list
- Go! button click
- AC launches in ~5s
- Drive button click at y=165 (after Escape to dismiss overlays)
- Lua app records 10 batches x 5 laps x 7 AI cars
- State file updates correctly
- acmanager://race/config URL launches AC with opponents on grid

## Known Issues

1. **CSP io.save() blocks CSV writes** -- workaround: write as .lua files (untested for large data)
2. **Track change unreliable** -- CM sometimes keeps previous track
3. **23 opponents may crash AC** -- 7 opponents stable, untested above that
4. **CM window title varies** -- connect by process ID as fallback
5. **abarth500 (non-ks_ cars) may crash** -- use ks_ prefixed cars for stability

## Quick Start

```bash
# Generate job queue
python scripts/generate_ac_jobs.py --max-cars 10 --ai-levels "80,100" --weather "clear_hot,heavy_rain"

# Open CM manually: DRIVE -> QUICK -> single -> RACE -> 7 opponents -> AI 80%

# Run overnight
python scripts/oracle_autopilot.py

# Or test one job
python scripts/oracle_autopilot.py --test-one

# Post-process (if not auto-run)
python scripts/postprocess_ac_telemetry.py --incremental

# Train human model from real data
python -c "from scripts.human_driving_model import HumanDrivingModel; m = HumanDrivingModel.from_real_data(); m.save('data/oracle/human_model.npz')"
```
