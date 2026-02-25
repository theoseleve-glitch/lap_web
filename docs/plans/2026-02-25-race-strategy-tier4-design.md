# Race Strategy Tier 4 Design: Core Race Mechanics

## Overview

Tier 4 adds fuel-aware ballast calculations, per-stint fuel toggling with downstream cascade recalculation, constraint enforcement hardening, and config field wiring. The central architectural change is a new `RaceStateEngine` that uses an event-driven cascade pattern: every mutation (toggle fuel, change driver, edit duration) triggers downstream recalculation of fuel, ballast, and constraints for all subsequent stints.

## Tier Scope

**Tier 4 — Core Race Mechanics** (this document)
Tier 5 — Pit Windows & Timing + Live Dashboard Enhancements (future)
Tier 6 — Live Race Intelligence + Connectivity (future)

## Feature List

### Enhance Existing

1. **Auto-ballast calculator** — add fuel-burn compensation (base + fuel offset decomposition)
2. **Qualifying fuel bridge** — carry depleted fuel state into race start (enhance existing `refuel_after_quali`)
3. **Weigh-at-pit-exit** — wire existing column into ballast timing logic
4. **Min rest time** — change from warning to violation in optimizer
5. **Min/max cumulative drive time** — add 90% threshold warning
6. **Stint plan import/export** — separate from full race config export

### Build New

7. **Fuel-burn ballast compensation** — static pre-calc per stint + dynamic real-time interpolation
8. **Per-stint fuel toggle** — toggle refuel on/off per pit stop with running refuel count
9. **Downstream recalculation** — toggling fuel on a stint recalculates all subsequent ballast/fuel values
10. **QuickChange pit stop type** — toggle between full/quick pit stops with different durations
11. **Mandatory driver change enforcement** — wire existing column into constraint validation
12. **Config field wiring** — pit_speed_kmh, refueling_allowed, com_channel displayed and used

## Architecture: Event-Driven Cascade

### Approach

Every user action is a **mutation** on the `RaceStateEngine`. Each mutation triggers `_cascade_from(stint_order)` which recalculates fuel state, ballast, and constraint violations for all stints from that point forward. No event bus or pub/sub — just method calls with deterministic cascade.

### RaceStateEngine (`telemetry_tool/race_state_engine.py`)

```
RaceStateEngine
+-- __init__(config, drivers, stints)
|
+-- State:
|   +-- config: dict                      (race_configs row)
|   +-- drivers: list[dict]               (race_drivers rows)
|   +-- stints: list[StintState]          (enriched stint objects)
|   +-- fuel_model: FuelModel             (burn rate, tank capacity)
|
+-- Mutations (each triggers cascade):
|   +-- toggle_fuel(stint_order)          flip refuel on preceding pit stop
|   +-- set_driver(stint_order, driver_id)
|   +-- set_duration(stint_order, seconds)
|   +-- end_stint(stint_order, actual_s)  live: mark stint completed
|   +-- set_pit_type(stint_order, type)   full/quick toggle
|   +-- reoptimize_remaining(elapsed_s)
|
+-- Cascade:
|   +-- _cascade_from(stint_order)
|       +-- _calc_fuel_state(stint)       fuel_at_start, fuel_at_end
|       +-- _calc_ballast(stint)          base + fuel_offset
|       +-- _validate_constraints(stint)  rest, cumulative, driver change, fuel
|
+-- Queries (no mutation, no cascade):
|   +-- current_fuel_kg(elapsed_s)        real-time interpolated fuel
|   +-- current_ballast(elapsed_s)        real-time interpolated ballast
|   +-- stint_plan_export()               stint-only JSON
|   +-- snapshot()                        full state dict for API
|
+-- Persistence:
    +-- save(conn)                        write stints/pit_stops to DB
    +-- load(conn, race_id) -> cls        reconstruct from DB
```

### StintState Dataclass

```python
@dataclass
class StintState:
    stint_order: int
    driver_id: int
    driver_name: str
    planned_duration_s: int
    planned_start_s: int
    planned_end_s: int
    # Fuel (computed by cascade)
    fuel_at_start_kg: float
    fuel_at_end_kg: float
    refueled_before: bool
    # Ballast (computed by cascade)
    ballast_kg: float
    ballast_base_kg: float
    ballast_fuel_offset_kg: float
    # Constraints
    violations: list[str]
    warnings: list[str]
    # Actual (filled during live)
    actual_start_s: int | None = None
    actual_end_s: int | None = None
    actual_duration_s: int | None = None
    status: str = "planned"
    notes: str = ""
```

## Fuel Model

### FuelModel Dataclass

```python
@dataclass
class FuelModel:
    full_tank_kg: float        # fuel mass only (full_tank_kg - empty_kart_kg)
    fuel_autonomy_s: int       # how long a full tank lasts
    burn_rate_kgs: float       # full_tank_kg / fuel_autonomy_s
    quali_fuel_used_kg: float  # fuel burned during qualifying (0 if refueled)
```

### Calculations

**Burn rate:** `burn_rate = fuel_capacity_kg / fuel_autonomy_s` (linear, constant)

**Qualifying bridge:**
- `refuel_after_quali = False` → `quali_fuel_used = burn_rate x qualifying_duration_s`
- stint 1 starts with `fuel_capacity - quali_fuel_used`

**Per-stint fuel state (cascade order):**
- Stint 1: `fuel_at_start = fuel_capacity - quali_fuel_used`
- Stint N (refueled): `fuel_at_start = fuel_capacity`
- Stint N (not refueled): `fuel_at_start = stint[N-1].fuel_at_end`
- All stints: `fuel_at_end = fuel_at_start - (burn_rate x planned_duration_s)`
- If `fuel_at_end < 0` → violation with exact time fuel runs out

**Real-time fuel (live dashboard):**
- `current_fuel = active_stint.fuel_at_start - (burn_rate x time_in_stint)`

### Assumptions

- Linear burn rate (constant consumption)
- Refuel = full tank always (no partial refueling)

## Ballast Model

### Decomposition

```
ballast_total = ballast_base + ballast_fuel_offset

ballast_base       = max(0, min_total_kart_kg - empty_kart_kg - fuel_capacity_kg - driver_weight_kg)
ballast_fuel_offset = max(0, fuel_capacity_kg - fuel_at_start_kg)
```

Both components are visible in the stint plan table and driver cards so the crew understands why ballast changes between stops.

### Cascade trigger map

| Mutation | Cascade Effect |
|----------|---------------|
| Toggle fuel OFF on stint N pit | Stint N+1 fuel_at_start = stint N fuel_at_end → recalc all from N+1 |
| Toggle fuel ON on stint N pit | Stint N+1 fuel_at_start = full_tank → recalc all from N+1 |
| Change driver on stint N | Stint N ballast recalc (different weight) → no fuel cascade |
| Edit stint N duration | Stint N fuel_at_end changes → cascade if N+1 not refueled |
| Set pit type to quick on stint N | Duration changes + refueled=0 → fuel cascade from N+1 |
| Reoptimize remaining | Full recalc from current point |

### weigh_on_pit_exit

- When enabled: ballast target uses NEXT stint's driver weight; pit crew card shows "Set ballast to Xkg for [next driver]"
- When disabled: informational only

### Real-time ballast (live dashboard)

```python
def current_ballast(self, elapsed_s: float) -> dict:
    current_fuel = self.current_fuel_kg(elapsed_s)
    active_stint = self._find_active_stint(elapsed_s)
    driver = self._get_driver(active_stint.driver_id)
    fuel_offset = max(0.0, self.fuel_model.full_tank_kg - current_fuel)
    base = active_stint.ballast_base_kg
    return {
        "base_kg": base,
        "fuel_offset_kg": round(fuel_offset, 2),
        "total_kg": round(base + fuel_offset, 2),
        "driver_name": driver["driver_name"],
    }
```

## Constraint Enforcement

### Validation per stint (in cascade)

| Constraint | Source | Severity | Logic |
|-----------|--------|----------|-------|
| Fuel exhaustion | computed | violation | `fuel_at_end < 0` with exact runout time |
| Min rest time | `race_drivers.min_rest_s` | violation | gap between consecutive stints for same driver < min_rest_s |
| Mandatory driver change | `race_configs.mandatory_driver_change` | violation | consecutive stints with same driver |
| Cumulative > max | `race_drivers.max_cumulative_s` | violation | sum of driver's stint durations exceeds max |
| Cumulative > 90% of max | `race_drivers.max_cumulative_s` | warning | approaching limit |
| Cumulative < min | `race_drivers.min_cumulative_s` | violation | only checked on final plan |
| Pit window | `pit_open_s`, `pit_close_s` | warning | soft target, kept as warning |

### Config field wiring

| Column | UI | Logic |
|--------|-----|-------|
| `pit_speed_kmh` | Number input in config form, info badge on live dashboard | Informational only |
| `mandatory_driver_change` | Checkbox in config form | Enforced as violation in `_validate_constraints()` |
| `refueling_allowed` | Checkbox in config form | When OFF: all `refueled` flags forced False, `toggle_fuel()` is no-op |
| `com_channel` | Text input per driver in config form | Shown in current/next driver cards on live dashboard as "COM: Ch X" |

### QuickChange pit stop type

New column `race_configs.quick_pit_stop_s` (INTEGER, nullable). New column `race_pit_stops.pit_type` (TEXT, default 'full').

- Config form: optional "Quick stop duration" field
- Stint plan: toggle icon per pit stop row (full/quick)
- Quick stops use `quick_pit_stop_s` for duration, auto-set `refueled = 0`
- Timeline adjusts accordingly (quick stops save time but carry less fuel)

## Stint Plan Import/Export

### Export format

```json
{
    "format": "stint-plan-v1",
    "exported_at": "2026-02-25T14:30:00",
    "race_name": "Endurance 4H Le Mans",
    "stints": [
        {
            "stint_order": 1,
            "driver_name": "Alex",
            "planned_duration_s": 2400,
            "refueled_before": true,
            "ballast_kg": 4.2,
            "ballast_base_kg": 2.0,
            "ballast_fuel_offset_kg": 2.2
        }
    ],
    "pit_stops": [
        {
            "after_stint": 1,
            "duration_s": 60,
            "driver_change": true,
            "refueled": true,
            "pit_type": "full"
        }
    ]
}
```

### Import behavior

- Match drivers by name (case-insensitive) to existing race drivers
- Unmatched driver names → warning, stint kept but driver unassigned
- Durations applied, engine cascade runs to recompute fuel/ballast
- Does NOT overwrite race config

### Routes

- `GET /<race_id>/export-plan` → stint plan JSON download
- `POST /<race_id>/import-plan` → upload, apply, redirect to detail

## Schema Changes

Version bump: 21 → 22. All additive, applied via `ensure_schema()`.

### race_configs (1 new column)

```sql
ALTER TABLE race_configs ADD COLUMN quick_pit_stop_s INTEGER;
```

### race_pit_stops (1 new column)

```sql
ALTER TABLE race_pit_stops ADD COLUMN pit_type TEXT NOT NULL DEFAULT 'full';
```

### race_stints (3 new columns)

```sql
ALTER TABLE race_stints ADD COLUMN ballast_base_kg REAL;
ALTER TABLE race_stints ADD COLUMN ballast_fuel_offset_kg REAL;
ALTER TABLE race_stints ADD COLUMN fuel_burn_rate_kgs REAL;
```

## Files Touched

| File | Action | Description |
|------|--------|-------------|
| `telemetry_tool/race_state_engine.py` | NEW | RaceStateEngine, FuelModel, StintState, cascade |
| `telemetry_tool/race_strategy_v2.py` | MODIFY | Optimizer returns raw plan, engine wraps for fuel/ballast |
| `telemetry_tool/web/routes/race_strategy_v2.py` | MODIFY | API uses engine; new export-plan/import-plan routes |
| `telemetry_tool/db/schema.py` | MODIFY | New columns, v22 |
| `telemetry_tool/db/migrate.py` | MODIFY | v22 migration |
| `telemetry_tool/web/templates/race_strategy/config.html` | MODIFY | Wire pit_speed, quick_pit, com_channel |
| `telemetry_tool/web/templates/race_strategy/detail.html` | MODIFY | Fuel toggles, ballast decomposition, refuel count |
| `telemetry_tool/web/templates/race_strategy/live.html` | MODIFY | Real-time ballast, fuel offset, COM channel |
| `telemetry_tool/web/static/js/race_strategy.js` | MODIFY | Fuel toggle interactions, cascade UI |
| `telemetry_tool/web/static/js/race_strategy_live.js` | MODIFY | Real-time ballast rendering, fuel gauge |
| `telemetry_tool/web/static/css/race_strategy.css` | MODIFY | Ballast decomposition, toggle styles |
| `telemetry_tool/tests/test_race_strategy_v2.py` | MODIFY | Engine tests, fuel cascade, ballast decomposition |

## Integration with Existing System

- `optimize_stints()` remains the entry point for initial plan generation
- `RaceStateEngine` wraps optimizer output and enriches it with fuel/ballast cascade
- All existing API routes (`/api/state`, `/api/stint/end`, `/api/reoptimize`) are updated to use engine
- Live dashboard polling continues at 2s intervals; engine provides `current_ballast()` and `current_fuel_kg()`
- Existing import/export (full race JSON) unchanged; stint-plan export is additive
