# Universal Telemetry Adapter + Progressive Physics Engine

**Date**: 2026-03-02
**Status**: Approved
**Scope**: Multi-format telemetry ingestion, 7 new visualizations, 3-tier progressive physics engine

## Problem

The system only accepts RaceChrono/RaceBox CSV with ~44 column variants. The theoretical engine operates on GPS+speed data alone, inferring brake/throttle/steering from longitudinal acceleration (10-30% error margin). Sim racing platforms (iRacing, ACC, F1 games) and professional data acquisition (MoTeC, AiM) export 100+ channels including throttle position, brake pressure, tire temperatures, wheel speeds, and slip angles — none of which can be ingested today.

## Solution Overview

**Approach B: Format Adapter Layer + Channel Registry**

1. Universal channel registry (100+ channels, 5 tiers)
2. Per-format adapter modules (9 adapters)
3. Progressive physics engine (3 tiers, auto-selected)
4. 7 new visualization components
5. Tier-aware scoring enhancements

## 1. Channel Registry & Canonical Schema

File: `telemetry_tool/channel_registry.py`

Every telemetry channel the system could encounter, organized by data tier:

### Tier 1 — Essential (GPS loggers)

| Channel | Unit | Description |
|---------|------|-------------|
| `time_s` | s | Sample timestamp |
| `speed_mps` | m/s | Vehicle speed |
| `lat_deg` | deg | Latitude |
| `lon_deg` | deg | Longitude |
| `distance_m` | m | Cumulative distance |
| `lap_number` | int | Lap identifier |
| `altitude_m` | m | Elevation |

### Tier 2 — Standard (phone accelerometer)

| Channel | Unit | Description |
|---------|------|-------------|
| `accel_long_mps2` | m/s² | Longitudinal acceleration |
| `accel_lat_mps2` | m/s² | Lateral acceleration |
| `yaw_rate_dps` | deg/s | Yaw rate |
| `heading_deg` | deg | Compass bearing |
| `combined_g` | G | Total G-force |

### Tier 3 — Controls (OBD-II / sim racing basic)

| Channel | Unit | Description |
|---------|------|-------------|
| `throttle_pct` | % | Throttle position 0-100 |
| `brake_pct` | % | Brake position/pressure 0-100 |
| `steering_angle_deg` | deg | Steering wheel angle |
| `rpm` | rev/min | Engine RPM |
| `gear` | int | Current gear (0=N, -1=R) |
| `clutch_pct` | % | Clutch position |

### Tier 4 — Advanced (sim racing full / AiM / MoTeC)

| Channel | Unit | Description |
|---------|------|-------------|
| `tire_temp_fl` / `fr` / `rl` / `rr` | °C | Tire temperatures (4 corners) |
| `tire_temp_fl_i` / `_m` / `_o` | °C | Tire temps inner/mid/outer (12 zones) |
| `tire_pressure_fl` / `fr` / `rl` / `rr` | kPa | Tire pressures |
| `tire_wear_fl` / `fr` / `rl` / `rr` | % | Tire wear 0-100 |
| `brake_temp_fl` / `fr` / `rl` / `rr` | °C | Brake disc temperatures |
| `wheel_speed_fl` / `fr` / `rl` / `rr` | m/s | Individual wheel speeds |

### Tier 5 — Professional (full data acquisition)

| Channel | Unit | Description |
|---------|------|-------------|
| `damper_pos_fl` / `fr` / `rl` / `rr` | mm | Damper/shock travel |
| `ride_height_f` / `ride_height_r` | mm | Ride height front/rear |
| `fuel_kg` | kg | Fuel remaining |
| `fuel_consumption_rate` | kg/s | Fuel flow |
| `oil_temp` / `water_temp` | °C | Engine temps |
| `oil_pressure` | kPa | Oil pressure |
| `boost_pressure` | kPa | Turbo/supercharger boost |
| `slip_angle_fl` / `fr` / `rl` / `rr` | deg | Tire slip angles |
| `slip_ratio_fl` / `fr` / `rl` / `rr` | - | Tire slip ratios |
| `lambda_afr` | - | Air-fuel ratio |
| `egt_1` .. `egt_n` | °C | Exhaust gas temps |
| `aero_drs` | bool | DRS active |
| `ers_deploy_pct` | % | ERS deployment |

### Channel Metadata

Each channel entry includes:
- `name`: Canonical string identifier
- `unit`: SI unit string
- `tier`: 1-5
- `category`: position / motion / controls / tires / brakes / engine / aero / fuel
- `valid_range`: (min, max) for sanity checks
- `derivation_sources`: List of (channel_set, function) pairs for computing if absent
- `description`: Human-readable explanation

### Auto-Detection

After parsing, the system determines the highest tier fully available:
- Tier 1: time + speed + position
- Tier 2: Tier 1 + acceleration data (raw or derivable)
- Tier 3: Tier 2 + any two of {throttle, brake, steering, RPM}
- Tier 4: Tier 3 + any tire temperature or wheel speed data
- Tier 5: Tier 4 + slip data or damper data or fuel data

Partial tier coverage is supported — individual models activate per-channel, not per-tier.

## 2. Format Adapters

Package: `telemetry_tool/adapters/`

### Base Interface

```python
class BaseAdapter:
    @staticmethod
    def detect(file_path: str) -> float:
        """Return confidence 0.0-1.0 that this adapter can handle the file."""

    def parse(self, file_path: str, progress_cb=None) -> pd.DataFrame:
        """Parse file → canonical DataFrame with registry column names."""

    def metadata(self) -> dict:
        """Session metadata: car, track, date, driver, conditions."""

    def available_channels(self) -> list[str]:
        """Which canonical channels are present after parsing."""

    def data_tier(self) -> int:
        """Highest complete tier (1-5)."""
```

### Adapter Inventory

| Adapter | File Types | Detection Method | Parser |
|---------|-----------|------------------|--------|
| `racechrono_adapter.py` | `.csv` | Header sentinels (`Time (s)`, `Time`, `UTC Time`) | Refactored from `io_racechrono.py` |
| `iracing_adapter.py` | `.ibt`, `.csv` | IBT magic bytes `0x00 0x01 0x01` / header `Lap` + `Speed` + `Throttle` | `irsdk` / `pyibt` library for binary; CSV column mapping |
| `acc_adapter.py` | `.csv`, `.json` | Header contains `Physics.SpeedKmh` or `gas` + `brake` + `steerAngle` | Column mapping; shared memory dump JSON parsing |
| `motec_adapter.py` | `.ld`, `.ldx`, `.csv` | MoTeC binary header magic / CSV with `Beacon`, `Lap_Number`, `Engine_RPM` | `ldparser` library for binary; CSV column mapping |
| `aim_adapter.py` | `.xrk`, `.drk`, `.csv` | AiM binary header / CSV with `RPM`, `GPS_Speed`, `G_Force_Lat` | CSV column mapping (binary deferred) |
| `f1_game_adapter.py` | `.csv`, `.json` | Header contains `m_speed` + `m_throttle` + `m_steer` (EA UDP format) | Column mapping from UDP capture tools |
| `obd_adapter.py` | `.csv` | Header contains `Engine RPM` or `Vehicle Speed` + OBD PID names | Column mapping for Torque Pro, OBD Fusion, ScanMyTesla |
| `vbox_adapter.py` | `.vbo`, `.csv` | VBO header `[header]` block / Racelogic column names | Text parser for VBO format sections |
| `generic_csv_adapter.py` | `.csv` | Fallback — fuzzy column name matching against registry | Heuristic matching with confidence scores |

### Format Detection Pipeline

```
1. Check binary signatures (IBT, MoTeC LD, AiM XRK)
2. Check file extension (.vbo → VBOX, .ibt → iRacing)
3. Read first 100 lines, run all CSV adapter detect() methods
4. Rank by confidence score
5. Use highest confidence adapter (threshold > 0.5)
6. Fallback to generic_csv_adapter if no match > 0.5
```

### iRacing IBT Format Details

The `.ibt` file contains:
- **Header**: Session info (track, car, driver, weather)
- **Var headers**: Channel definitions (name, type, unit, count)
- **Data rows**: Binary float32/int32 at 60Hz typically

Key channels (200+ available, we map ~40):
- `Speed`, `Throttle`, `Brake`, `Clutch`, `Gear`, `RPM`
- `SteeringWheelAngle`, `SteeringWheelTorque`
- `LFtempCL/CM/CR`, `RFtempCL/CM/CR`, `LRtempCL/CM/CR`, `RRtempCL/CM/CR` (12-zone tire temps)
- `LFpressure`, `RFpressure`, `LRpressure`, `RRpressure`
- `LFwearL/M/R` ... (12-zone tire wear)
- `LFspd`, `RFspd`, `LRspd`, `RRspd` (wheel speeds)
- `LFrideHeight`, `RFrideHeight`, `LRrideHeight`, `RRrideHeight`
- `Lat`, `Lon`, `Alt`, `VelocityX/Y/Z`
- `YawRate`, `Pitch`, `Roll`
- `LapDist`, `LapDistPct`, `Lap`, `LapBestLapTime`, `LapLastLapTime`
- `FuelLevel`, `FuelUsePerHour`
- `AirTemp`, `TrackTemp`, `WindDir`, `WindVel`
- `dcDRS` (DRS), `dcERSDeployMode`

### MoTeC LD Format Details

The `ldparser` Python library reads `.ld` files:
- Channel list with name, unit, sample rate, data type
- Data as time-series per channel (not tabular — different channels may have different sample rates)
- Requires resampling to common timebase

Common channels: `Engine RPM`, `Throttle Position`, `Brake Pressure`, `Steering Angle`, `Ground Speed`, `Lat Accel`, `Long Accel`, `GPS Latitude`, `GPS Longitude`, tire temps per corner, wheel speeds, damper positions, oil/water/EGT temperatures.

## 3. Progressive Physics Engine

### Tier 1 — GPS-Only (Unchanged)

Current model. Friction ellipse from GPS-derived accelerations. Power envelope from speed profile. GPS correction +20%. Forward-backward point-mass simulation.

### Tier 2 — Controls Available

New file: `telemetry_tool/physics/controls_physics.py`

**When activated**: throttle_pct + brake_pct available (+ optionally steering, RPM, gear).

Enhancements:
- **Brake model**: Brake initiation from actual brake_pct signal (not a_long < -1.0 threshold). Measures brake application rate, peak pressure, release profile. Trail braking quantified as brake_pct > 5% while |steering| > 10deg.
- **Throttle model**: Throttle application rate on corner exit. Hesitation detection (throttle < 20% when accel demand available). Coasting detection (throttle = 0, brake = 0). Partial throttle zones.
- **Steering model**: Required steering from curvature vs actual steering. Over/understeer coefficient = (actual_yaw - expected_yaw_from_steering) / speed. Correction frequency.
- **Shift analysis**: RPM at upshift/downshift points. Rev-matching quality on downshifts. Optimal shift RPM from power curve.
- **Friction model upgrade**: GPS correction reduced to +5% (pedal data confirms actual grip usage vs driver choice). Friction ellipse can separate "driver limited" from "grip limited" events.
- **Power curve**: Fitted from RPM × throttle × speed (not just speed alone). Engine torque map.

### Tier 3 — Full Telemetry

New files:
- `telemetry_tool/physics/tire_thermal.py`
- `telemetry_tool/physics/slip_model.py`
- `telemetry_tool/physics/fuel_model.py`
- `telemetry_tool/physics/brake_thermal.py`

**When activated**: tire temps OR wheel speeds available.

Enhancements:
- **Tire thermal model**: `grip_factor(T) = 1.0 - k_cold * max(0, T_opt - T) - k_hot * max(0, T - T_opt)`. Optimal temp window detected from peak-grip correlation. Three-zone model (inner/mid/outer) for camber analysis: if inner >> outer, excess camber; if outer >> inner, insufficient camber.
- **Wheel slip model**: `slip_ratio = (wheel_speed - vehicle_speed) / max(wheel_speed, vehicle_speed)`. Lockup events: slip_ratio < -0.15. Wheelspin: slip_ratio > 0.10. Traction circle uses actual slip data for grip boundary.
- **Load transfer model**: Weight distribution from 4-corner wheel speed differentials under lateral load. Load sensitivity: `mu_eff = mu_base * (1 - k_load * delta_Fz / Fz_ref)` — k_load fitted from data (currently hardcoded at 0.08 but unused).
- **Fuel correction**: `corrected_lap_time = raw_time - (fuel_start - fuel_end) * time_per_kg`. Fuel weight effect on grip and acceleration.
- **Brake thermal model**: Brake temp rise per braking event. Cooling rate between events. Fade detection: if peak_brake_decel decreases as brake_temp increases.
- **Aero enhancement**: If ride_height available: downforce map from ride_height vs speed². DRS effect: quantify delta in aero balance.

### Fallback Chain

```
For each physics model independently:
  if tier_3_channels available → use tier 3 model
  elif tier_2_channels available → use tier 2 model
  else → use tier 1 model (current)

Models are composable — can mix tier 3 tire thermal with tier 2 brake with tier 1 power.
```

## 4. New Visualizations

7 new React canvas chart components in `lap-website/src/components/shared/charts/`:

### PedalTraceChart

- **Channels**: throttle_pct, brake_pct, steering_angle_deg
- **Display**: Three overlaid traces on distance X-axis. Brake in red (0-100%), throttle in green (0-100%), steering in blue (±deg, separate Y-axis right side).
- **Features**: Trail braking zones highlighted (brake+steering overlap). Coasting zones dimmed. Corner markers from corner detection.
- **Hover sync**: Full integration with `useChartHoverStore`.

### TireHeatmapChart

- **Channels**: tire_temp_{fl,fr,rl,rr} (4-corner) or tire_temp_{fl,fr,rl,rr}_{i,m,o} (12-zone)
- **Display**: 4-tire grid layout (2x2 matching car orientation). Each tire shows color gradient from blue (cold, <60°C) → green (optimal) → yellow → red (overheating, >120°C). If 12-zone, show inner/mid/outer strips per tire.
- **Features**: Optimal temperature window highlighted. Cross-car balance indicators (L-R delta, F-R delta). Lap selector to see thermal evolution.

### WheelSlipChart

- **Channels**: wheel_speed_{fl,fr,rl,rr}, speed_mps (for slip ratio); slip_angle if available
- **Display**: 4 traces on distance axis showing slip ratio per wheel. Lockup events (ratio < -0.15) highlighted red. Wheelspin (ratio > 0.10) highlighted orange. Zero-slip line.
- **Features**: ABS cycling visible as rapid oscillation. TC intervention visible as wheelspin capping.

### RPMGearChart

- **Channels**: rpm, gear, speed_mps
- **Display**: RPM trace colored by current gear (each gear a different color). Shift points marked with vertical lines. Horizontal line at optimal shift RPM (from peak power). Speed overlay as thin gray line on right Y-axis.
- **Features**: Upshift/downshift quality scoring. Money shifts detected (downshift causing over-rev).

### BrakeAnalysisChart

- **Channels**: brake_pct, brake_temp_{fl,fr,rl,rr} (optional)
- **Display**: Brake pressure/position trace on distance. If brake temps available: 4 brake temp traces below. Fade detection: zones where peak decel drops despite max brake input highlighted.
- **Features**: Trail braking score per corner. Brake bias balance (front vs rear temp delta).

### FuelStrategyChart

- **Channels**: fuel_kg, fuel_consumption_rate (optional), lap_number
- **Display**: Fuel remaining vs lap number. Consumption rate per lap as bar chart. Projected fuel-out lap (linear extrapolation).
- **Features**: Pit stop optimal window. Fuel-saving vs pushing strategy comparison.

### LiveFrictionCircle

- **Channels**: accel_lat_mps2, accel_long_mps2, throttle_pct (optional), brake_pct (optional)
- **Display**: G-G scatter plot with points colored by input: green=throttle, red=brake, yellow=combined, blue=coast. Theoretical grip circle overlaid. Grip usage percentage = (actual_G / max_available_G) * 100.
- **Features**: Per-corner filtering. Grip utilization heatmap mode. Distance-based animation (hover on speed trace → dot moves on friction circle).

### Channel Availability Behavior

All charts check available channels before rendering:
- If required channels missing: Show placeholder card with message like "Throttle & brake data required — available in iRacing, ACC, and MoTeC formats"
- If partial channels: Render what's available (e.g., PedalTraceChart with only throttle+brake, no steering)

## 5. Scoring Enhancements

### Tier-Aware Scoring Table

| Category | Tier 1 (GPS) | Tier 2 (Controls) | Tier 3 (Full) |
|----------|-------------|-------------------|----------------|
| **Pace (25)** | Theory gap ±1.5s | Theory gap ±0.8s (real power curve) | Theory gap ±0.3s (fuel+tire corrected) |
| **Consistency (25)** | Lap time CV only | + pedal consistency per corner | + tire temp consistency + fuel-normalized CV |
| **Execution (20)** | Inferred from accel | + trail braking from brake_pct, throttle smoothness, shift quality | + slip-based grip usage %, tire management |
| **Robustness (15)** | Lap time fade | + brake fade from brake data | + tire thermal degradation + fuel weight correction |
| **Adaptation (15)** | Grip trend only | + throttle adaptation rate | + tire management strategy score |

### New Execution Sub-Scores (Tier 2+)

- **Trail Braking Score**: % of corner entry where brake_pct > 5% AND |steering| > 10deg, vs theoretical optimal overlap
- **Throttle Application Score**: Time from apex to 100% throttle vs optimal (from grip available)
- **Brake Modulation Score**: Variance in brake_pct profiles across identical corners (lower = more consistent)
- **Shift Quality Score**: RPM at shift point vs optimal shift RPM; rev-match smoothness on downshifts

### New Tier 3 Sub-Scores

- **Tire Management Score**: Rate of tire_temp increase over stint vs baseline. Lower rate = better management.
- **Grip Utilization Score**: Average (actual_slip / optimal_slip) across all corners. Closer to 1.0 = better.
- **Fuel Efficiency Score**: Fuel consumption vs lap time curve — is driver efficient at similar pace?

## 6. Data Endpoints

New API endpoints in `data_v2.py`:

| Endpoint | Channels Required | Returns |
|----------|------------------|---------|
| `GET /sessions/{id}/pedals?lap=N` | throttle, brake, steering | `{distances, throttle, brake, steering}` |
| `GET /sessions/{id}/tire-temps?lap=N` | tire_temp_* | `{distances, fl, fr, rl, rr}` (each has i/m/o if 12-zone) |
| `GET /sessions/{id}/wheel-slip?lap=N` | wheel_speed_* | `{distances, fl_ratio, fr_ratio, rl_ratio, rr_ratio}` |
| `GET /sessions/{id}/rpm-gear?lap=N` | rpm, gear | `{distances, rpm, gear, speeds}` |
| `GET /sessions/{id}/brake-temps?lap=N` | brake_temp_* | `{distances, fl, fr, rl, rr}` |
| `GET /sessions/{id}/fuel?lap=N` | fuel_kg | `{laps, fuel_remaining, consumption_rate}` |
| `GET /sessions/{id}/channels` | — | `{available: [...], tier: N}` |

All endpoints return `{available: false}` when required channels are absent.

## 7. Database Changes

### Sessions Table

New columns:
- `data_tier` INTEGER DEFAULT 1 — highest complete tier (1-5)
- `available_channels` JSONB DEFAULT '[]' — list of canonical channel names present
- `source_format` VARCHAR(32) DEFAULT 'racechrono' — adapter that parsed this session
- `source_metadata` JSONB DEFAULT '{}' — format-specific metadata (car name, track name from sim, etc.)

### Alembic Migration

Migration 017: `add_telemetry_channels_columns`

## 8. File Structure

```
telemetry_tool/
├── adapters/
│   ├── __init__.py
│   ├── base.py                    # BaseAdapter ABC
│   ├── registry.py                # Format detection pipeline
│   ├── racechrono_adapter.py      # Current CSV (refactored)
│   ├── iracing_adapter.py         # .ibt + CSV
│   ├── acc_adapter.py             # ACC CSV/JSON
│   ├── motec_adapter.py           # .ld/.ldx + CSV
│   ├── aim_adapter.py             # AiM CSV
│   ├── f1_game_adapter.py         # EA F1 CSV/JSON
│   ├── obd_adapter.py             # OBD-II CSV
│   ├── vbox_adapter.py            # Racelogic .vbo
│   └── generic_csv_adapter.py     # Fuzzy fallback
├── channel_registry.py            # Canonical schema + tier detection
├── physics/
│   ├── __init__.py
│   ├── controls_physics.py        # Tier 2: brake/throttle/steering models
│   ├── tire_thermal.py            # Tier 3: tire temperature model
│   ├── slip_model.py              # Tier 3: wheel slip model
│   ├── fuel_model.py              # Tier 3: fuel load correction
│   └── brake_thermal.py           # Tier 3: brake fade model

lap-website/src/components/shared/charts/
├── PedalTraceChart.tsx
├── TireHeatmapChart.tsx
├── WheelSlipChart.tsx
├── RPMGearChart.tsx
├── BrakeAnalysisChart.tsx
├── FuelStrategyChart.tsx
└── LiveFrictionCircle.tsx
```

## 9. Dependencies

### Python (backend)

- `pyibt` or `irsdk` — iRacing IBT parser (pip installable)
- `ldparser` — MoTeC LD parser (pip installable)
- No new deps for CSV-based formats (pandas handles everything)

### Frontend

- No new npm dependencies (all charts are pure canvas, same as DeltaTimeChart)

## 10. Implementation Priority

1. Channel registry + base adapter interface
2. RaceChrono adapter (refactor existing code)
3. iRacing adapter (largest sim user base, richest data)
4. Generic CSV adapter (catches many sim exports)
5. PedalTraceChart + RPMGearChart (most impactful visuals)
6. Tier 2 physics (controls-based models)
7. TireHeatmapChart + LiveFrictionCircle
8. MoTeC + ACC + F1 game adapters
9. Tier 3 physics (thermal + slip models)
10. Remaining charts + adapters + scoring enhancements
