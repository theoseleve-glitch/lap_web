# Race Strategy Tier 4: Core Race Mechanics — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add fuel-aware ballast cascade engine, per-stint fuel toggles, constraint enforcement, and config wiring to the endurance race strategy system.

**Architecture:** Event-driven `RaceStateEngine` wraps the existing `optimize_stints()` output and enriches it with fuel state, ballast decomposition, and constraint validation. Every mutation (toggle fuel, change driver, edit duration) triggers `_cascade_from(stint_order)` which recalculates all downstream stints. The engine is used by both the pre-race optimizer route and the live dashboard API.

**Tech Stack:** Python 3, Flask, SQLite, vanilla JS, Chart.js (existing stack — no new dependencies)

---

## Task 1: Schema Migration (v22)

**Files:**
- Modify: `telemetry_tool/db/schema.py:756-842` (add columns to CREATE TABLE statements)
- Modify: `telemetry_tool/db/migrate.py:373-389` (add v22 ALTER TABLE migrations)
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py:25-72` (update schema version test)

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_race_strategy_v2.py` inside class `TestRaceStrategySchema`:

```python
def test_schema_version_is_22(self, strategy_db):
    row = strategy_db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    assert row["v"] == 22

def test_race_stints_has_ballast_decomposition_columns(self, strategy_db):
    strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
    strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
    strategy_db.execute(
        "INSERT INTO race_stints (race_id, stint_order, driver_id, ballast_base_kg, "
        "ballast_fuel_offset_kg, fuel_burn_rate_kgs, status) VALUES (1, 1, 1, 2.0, 1.5, 0.003, 'planned')"
    )
    row = strategy_db.execute("SELECT * FROM race_stints WHERE race_id = 1").fetchone()
    assert row["ballast_base_kg"] == 2.0
    assert row["ballast_fuel_offset_kg"] == 1.5
    assert row["fuel_burn_rate_kgs"] == 0.003

def test_race_configs_has_quick_pit_stop_column(self, strategy_db):
    strategy_db.execute(
        "INSERT INTO race_configs (race_name, race_duration_s, quick_pit_stop_s) VALUES ('R', 3600, 30)"
    )
    row = strategy_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone()
    assert row["quick_pit_stop_s"] == 30

def test_race_pit_stops_has_pit_type_column(self, strategy_db):
    strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
    strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
    strategy_db.execute("INSERT INTO race_stints (race_id, stint_order, driver_id, status) VALUES (1, 1, 1, 'planned')")
    strategy_db.execute(
        "INSERT INTO race_pit_stops (race_id, stint_id, driver_change, refueled, pit_type) VALUES (1, 1, 1, 0, 'quick')"
    )
    row = strategy_db.execute("SELECT * FROM race_pit_stops WHERE race_id = 1").fetchone()
    assert row["pit_type"] == "quick"
```

Also update the existing `test_schema_version_is_21` → rename to `test_schema_version_is_22` (or delete the old one and use the new).

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestRaceStrategySchema -v`
Expected: FAIL — columns don't exist yet, schema version is 21

**Step 3: Add columns to schema.py CREATE TABLE statements**

In `telemetry_tool/db/schema.py`:

Update `_RACE_CONFIGS_TABLE` (line 757) — add after `refueling_allowed` line:
```sql
    quick_pit_stop_s    INTEGER,
```

Update `_RACE_STINTS_TABLE` (line 802) — add after `ballast_kg` line:
```sql
    ballast_base_kg         REAL,
    ballast_fuel_offset_kg  REAL,
    fuel_burn_rate_kgs      REAL,
```

Update `_RACE_PIT_STOPS_TABLE` (line 822) — add after `notes` line:
```sql
    pit_type            TEXT NOT NULL DEFAULT 'full'
```

Bump `SCHEMA_VERSION = 22` (line 9).

**Step 4: Add ALTER TABLE migrations to migrate.py**

In `telemetry_tool/db/migrate.py`, after the Phase 21 block (line 383), add:

```python
# Phase 22 migration: Tier 4 — fuel-aware ballast, quick pit stops.
try:
    cur.execute("ALTER TABLE race_configs ADD COLUMN quick_pit_stop_s INTEGER;")
    logger.debug("Added column race_configs.quick_pit_stop_s.")
except sqlite3.OperationalError:
    pass  # Column already exists.

for col in ("ballast_base_kg REAL", "ballast_fuel_offset_kg REAL", "fuel_burn_rate_kgs REAL"):
    try:
        cur.execute(f"ALTER TABLE race_stints ADD COLUMN {col};")
        logger.debug("Added column race_stints.%s.", col.split()[0])
    except sqlite3.OperationalError:
        pass  # Column already exists.

try:
    cur.execute("ALTER TABLE race_pit_stops ADD COLUMN pit_type TEXT NOT NULL DEFAULT 'full';")
    logger.debug("Added column race_pit_stops.pit_type.")
except sqlite3.OperationalError:
    pass  # Column already exists.

cur.execute(
    "INSERT OR IGNORE INTO schema_version (version, description) "
    "VALUES (?, ?);",
    (22, "Phase 22 schema — Tier 4 fuel-aware ballast, quick pit stops"),
)
```

**Step 5: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestRaceStrategySchema -v`
Expected: PASS

**Step 6: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/migrate.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(race-strategy): add schema v22 — ballast decomposition, quick pit stops"
```

---

## Task 2: FuelModel and StintState Dataclasses

**Files:**
- Create: `telemetry_tool/race_state_engine.py`
- Create: `telemetry_tool/tests/test_race_state_engine.py`

**Step 1: Write the failing tests**

Create `telemetry_tool/tests/test_race_state_engine.py`:

```python
"""Tests for RaceStateEngine — fuel model, ballast cascade, constraints."""

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestFuelModel:
    """FuelModel calculations."""

    def test_burn_rate_calculation(self):
        from race_state_engine import FuelModel
        # 8kg fuel, 2400s autonomy → 0.003333 kg/s
        fm = FuelModel(full_tank_kg=8.0, fuel_autonomy_s=2400, quali_fuel_used_kg=0.0)
        assert abs(fm.burn_rate_kgs - 8.0 / 2400) < 1e-6

    def test_quali_fuel_bridge(self):
        from race_state_engine import FuelModel
        # 8kg tank, 2400s autonomy, 600s quali → burn_rate * 600 = 2kg burned
        fm = FuelModel(full_tank_kg=8.0, fuel_autonomy_s=2400, quali_fuel_used_kg=2.0)
        assert fm.quali_fuel_used_kg == 2.0
        assert fm.fuel_after_quali_kg == 6.0

    def test_zero_autonomy_safe(self):
        from race_state_engine import FuelModel
        fm = FuelModel(full_tank_kg=0.0, fuel_autonomy_s=0, quali_fuel_used_kg=0.0)
        assert fm.burn_rate_kgs == 0.0


class TestStintState:
    """StintState dataclass."""

    def test_stint_state_creation(self):
        from race_state_engine import StintState
        s = StintState(
            stint_order=1, driver_id=1, driver_name="Alice",
            planned_duration_s=1200, planned_start_s=0, planned_end_s=1200,
        )
        assert s.fuel_at_start_kg == 0.0
        assert s.ballast_kg == 0.0
        assert s.violations == []
        assert s.warnings == []
        assert s.refueled_before is True
        assert s.status == "planned"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_race_state_engine.py::TestFuelModel -v`
Expected: FAIL — `race_state_engine` module doesn't exist

**Step 3: Write the dataclasses**

Create `telemetry_tool/race_state_engine.py`:

```python
"""
race_state_engine.py
--------------------
Event-driven race state engine with fuel-aware ballast cascade.

Every mutation triggers downstream recalculation of fuel state, ballast
decomposition, and constraint validation for all subsequent stints.

Public API
~~~~~~~~~~
``RaceStateEngine(config, drivers, stints, pit_stops)``
    Create engine from DB rows or optimizer output.
``RaceStateEngine.load(conn, race_id)``
    Reconstruct engine from database.
``engine.snapshot()``
    Full state dict for API responses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FuelModel:
    """Linear fuel consumption model."""

    full_tank_kg: float
    fuel_autonomy_s: int
    quali_fuel_used_kg: float = 0.0

    @property
    def burn_rate_kgs(self) -> float:
        """Fuel burn rate in kg/s (constant, linear)."""
        if self.fuel_autonomy_s <= 0:
            return 0.0
        return self.full_tank_kg / self.fuel_autonomy_s

    @property
    def fuel_after_quali_kg(self) -> float:
        """Fuel remaining after qualifying."""
        return max(0.0, self.full_tank_kg - self.quali_fuel_used_kg)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> FuelModel:
        """Build FuelModel from a race_configs dict."""
        empty = config.get("empty_kart_kg") or 0.0
        full_tank = config.get("full_tank_kg") or 0.0
        fuel_capacity = max(0.0, full_tank - empty)
        autonomy = config.get("fuel_autonomy_s") or 0

        # Qualifying fuel bridge
        quali_used = 0.0
        if autonomy > 0 and not config.get("refuel_after_quali", 0):
            quali_dur = config.get("qualifying_duration_s") or 0
            burn_rate = fuel_capacity / autonomy if autonomy else 0
            quali_used = burn_rate * quali_dur

        return cls(
            full_tank_kg=fuel_capacity,
            fuel_autonomy_s=autonomy,
            quali_fuel_used_kg=quali_used,
        )


@dataclass
class StintState:
    """Enriched stint with fuel, ballast, and constraint state."""

    stint_order: int
    driver_id: int
    driver_name: str
    planned_duration_s: int
    planned_start_s: int
    planned_end_s: int

    # Fuel (computed by cascade)
    fuel_at_start_kg: float = 0.0
    fuel_at_end_kg: float = 0.0
    refueled_before: bool = True

    # Ballast (computed by cascade)
    ballast_kg: float = 0.0
    ballast_base_kg: float = 0.0
    ballast_fuel_offset_kg: float = 0.0

    # Constraints
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Actual (filled during live)
    actual_start_s: int | None = None
    actual_end_s: int | None = None
    actual_duration_s: int | None = None
    status: str = "planned"
    notes: str = ""
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_state_engine.py -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(race-strategy): add FuelModel and StintState dataclasses"
```

---

## Task 3: Fuel Cascade Logic

**Files:**
- Modify: `telemetry_tool/race_state_engine.py` (add `_calc_fuel_state` and `_cascade_from`)
- Modify: `telemetry_tool/tests/test_race_state_engine.py` (add fuel cascade tests)

**Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_race_state_engine.py`:

```python
class TestFuelCascade:
    """Fuel state cascade calculations."""

    def _make_engine(self, **overrides):
        from race_state_engine import RaceStateEngine
        config = {
            "race_duration_s": 7200,
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": 2400,
            "empty_kart_kg": 85.0,
            "full_tank_kg": 93.0,  # 8kg fuel
            "min_total_kart_kg": 160.0,
            "qualifying_duration_s": 0,
            "refuel_after_quali": 0,
            "refueling_allowed": 1,
            **overrides,
        }
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65.0,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75.0,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        raw_stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 2360, "planned_duration_s": 2360},
            {"stint_order": 2, "driver_id": 2, "driver_name": "Bob",
             "planned_start_s": 2420, "planned_end_s": 4780, "planned_duration_s": 2360},
            {"stint_order": 3, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 4840, "planned_end_s": 7200, "planned_duration_s": 2360},
        ]
        pit_stops = [
            {"after_stint": 1, "at_s": 2360, "duration_s": 60, "refuel": True, "driver_change": True, "pit_type": "full"},
            {"after_stint": 2, "at_s": 4780, "duration_s": 60, "refuel": True, "driver_change": True, "pit_type": "full"},
        ]
        return RaceStateEngine(config, drivers, raw_stints, pit_stops)

    def test_all_refueled_stints_start_full(self):
        engine = self._make_engine()
        # Stint 1 starts full (no quali), stints 2 and 3 refueled → start full
        assert engine.stints[0].fuel_at_start_kg == 8.0
        assert engine.stints[1].fuel_at_start_kg == 8.0
        assert engine.stints[2].fuel_at_start_kg == 8.0

    def test_fuel_depletes_during_stint(self):
        engine = self._make_engine()
        burn = 8.0 / 2400  # kg/s
        expected_end = 8.0 - (burn * 2360)
        assert abs(engine.stints[0].fuel_at_end_kg - expected_end) < 0.01

    def test_qualifying_bridge_reduces_first_stint_fuel(self):
        engine = self._make_engine(qualifying_duration_s=600, refuel_after_quali=0)
        burn = 8.0 / 2400
        quali_used = burn * 600
        assert abs(engine.stints[0].fuel_at_start_kg - (8.0 - quali_used)) < 0.01

    def test_toggle_fuel_off_carries_fuel_from_previous(self):
        engine = self._make_engine()
        engine.toggle_fuel(2)  # Turn off refuel before stint 2
        # Stint 2 should now start with stint 1's fuel_at_end, not full tank
        assert engine.stints[1].fuel_at_start_kg == engine.stints[0].fuel_at_end_kg

    def test_toggle_fuel_cascades_downstream(self):
        engine = self._make_engine()
        engine.toggle_fuel(2)
        # Stint 3 is still refueled, so it starts full
        assert engine.stints[2].fuel_at_start_kg == 8.0

    def test_refueling_allowed_false_forces_no_refuel(self):
        engine = self._make_engine(refueling_allowed=0)
        # All stints carry fuel from previous
        assert engine.stints[1].fuel_at_start_kg == engine.stints[0].fuel_at_end_kg
        assert engine.stints[2].fuel_at_start_kg == engine.stints[1].fuel_at_end_kg
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_race_state_engine.py::TestFuelCascade -v`
Expected: FAIL — `RaceStateEngine` class doesn't exist yet

**Step 3: Implement RaceStateEngine with fuel cascade**

Add to `telemetry_tool/race_state_engine.py` (after the `StintState` dataclass):

```python
class RaceStateEngine:
    """Event-driven race state with fuel-aware ballast cascade."""

    def __init__(
        self,
        config: dict[str, Any],
        drivers: list[dict[str, Any]],
        raw_stints: list[dict[str, Any]],
        pit_stops: list[dict[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self.drivers = {d["id"]: d for d in drivers}
        self.driver_list = sorted(drivers, key=lambda d: d.get("driver_order", 0))
        self.fuel_model = FuelModel.from_config(config)

        # Build StintState objects from raw optimizer output
        self.stints: list[StintState] = []
        for s in raw_stints:
            self.stints.append(StintState(
                stint_order=s["stint_order"],
                driver_id=s["driver_id"],
                driver_name=s.get("driver_name", ""),
                planned_duration_s=s["planned_duration_s"],
                planned_start_s=s["planned_start_s"],
                planned_end_s=s["planned_end_s"],
                actual_start_s=s.get("actual_start_s"),
                actual_end_s=s.get("actual_end_s"),
                actual_duration_s=s.get("actual_duration_s"),
                status=s.get("status", "planned"),
                notes=s.get("notes", "") or "",
            ))

        # Build pit stop refuel map: pit_stops[i] is the stop AFTER stint i+1
        self._pit_stops = pit_stops or []
        self._refuel_map: dict[int, bool] = {}  # stint_order -> refueled_before
        self._pit_type_map: dict[int, str] = {}  # stint_order -> pit_type for preceding stop
        self._init_refuel_map()

        # Run initial cascade from stint 1
        self._cascade_from(1)

    def _init_refuel_map(self) -> None:
        """Build refuel map from pit stops."""
        refueling_allowed = bool(self.config.get("refueling_allowed", 1))

        # Stint 1 is never preceded by a pit stop — gets full tank (minus quali)
        self._refuel_map[1] = True

        for ps in self._pit_stops:
            after = ps.get("after_stint", 0)
            next_stint_order = after + 1
            if refueling_allowed:
                self._refuel_map[next_stint_order] = bool(ps.get("refuel", True))
            else:
                self._refuel_map[next_stint_order] = False
            self._pit_type_map[next_stint_order] = ps.get("pit_type", "full")

    def _get_stint(self, stint_order: int) -> StintState | None:
        """Get stint by order number."""
        for s in self.stints:
            if s.stint_order == stint_order:
                return s
        return None

    def _get_driver(self, driver_id: int) -> dict[str, Any]:
        """Get driver dict by ID."""
        return self.drivers.get(driver_id, {})

    # ── Cascade ────────────────────────────────────────────────

    def _cascade_from(self, from_order: int) -> None:
        """Recalculate fuel, ballast, and constraints from stint_order onward."""
        for stint in self.stints:
            if stint.stint_order < from_order:
                continue
            stint.refueled_before = self._refuel_map.get(stint.stint_order, True)
            self._calc_fuel_state(stint)
            self._calc_ballast(stint)
            self._validate_constraints(stint)

    def _calc_fuel_state(self, stint: StintState) -> None:
        """Compute fuel_at_start and fuel_at_end for a stint."""
        fm = self.fuel_model

        if stint.stint_order == 1:
            stint.fuel_at_start_kg = fm.fuel_after_quali_kg
        elif stint.refueled_before:
            stint.fuel_at_start_kg = fm.full_tank_kg
        else:
            prev = self._get_stint(stint.stint_order - 1)
            stint.fuel_at_start_kg = prev.fuel_at_end_kg if prev else fm.full_tank_kg

        stint.fuel_at_end_kg = stint.fuel_at_start_kg - (fm.burn_rate_kgs * stint.planned_duration_s)

    def _calc_ballast(self, stint: StintState) -> None:
        """Compute ballast decomposition: base + fuel offset."""
        cfg = self.config
        driver = self._get_driver(stint.driver_id)

        min_kart = cfg.get("min_total_kart_kg")
        empty = cfg.get("empty_kart_kg")
        driver_weight = driver.get("weight_kg")

        if not all([min_kart, empty, driver_weight]):
            stint.ballast_base_kg = 0.0
            stint.ballast_fuel_offset_kg = 0.0
            stint.ballast_kg = 0.0
            return

        fuel_capacity = self.fuel_model.full_tank_kg
        stint.ballast_base_kg = max(0.0, min_kart - empty - fuel_capacity - driver_weight)
        stint.ballast_fuel_offset_kg = max(0.0, fuel_capacity - stint.fuel_at_start_kg)
        stint.ballast_kg = round(stint.ballast_base_kg + stint.ballast_fuel_offset_kg, 2)

    def _validate_constraints(self, stint: StintState) -> None:
        """Check constraints for a single stint. Populates violations/warnings."""
        stint.violations = []
        stint.warnings = []
        # Constraint checks implemented in Task 4

    # ── Mutations ──────────────────────────────────────────────

    def toggle_fuel(self, stint_order: int) -> None:
        """Toggle refuel on the pit stop BEFORE this stint."""
        if stint_order <= 1:
            return  # Can't toggle fuel before first stint
        if not self.config.get("refueling_allowed", 1):
            return  # Refueling globally disabled
        current = self._refuel_map.get(stint_order, True)
        self._refuel_map[stint_order] = not current
        self._cascade_from(stint_order)

    # ── Queries ────────────────────────────────────────────────

    def current_fuel_kg(self, elapsed_s: float) -> float:
        """Interpolate current fuel level based on elapsed race time."""
        active = self._find_active_stint(elapsed_s)
        if not active:
            return 0.0
        time_in_stint = elapsed_s - active.planned_start_s
        return max(0.0, active.fuel_at_start_kg - (self.fuel_model.burn_rate_kgs * time_in_stint))

    def current_ballast(self, elapsed_s: float) -> dict[str, Any]:
        """Real-time ballast based on interpolated fuel level."""
        active = self._find_active_stint(elapsed_s)
        if not active:
            return {"base_kg": 0, "fuel_offset_kg": 0, "total_kg": 0, "driver_name": ""}
        current_fuel = self.current_fuel_kg(elapsed_s)
        fuel_offset = max(0.0, self.fuel_model.full_tank_kg - current_fuel)
        base = active.ballast_base_kg
        return {
            "base_kg": round(base, 2),
            "fuel_offset_kg": round(fuel_offset, 2),
            "total_kg": round(base + fuel_offset, 2),
            "driver_name": active.driver_name,
        }

    def _find_active_stint(self, elapsed_s: float) -> StintState | None:
        """Find the stint that covers the given elapsed time."""
        # First try status-based (live race)
        for s in self.stints:
            if s.status == "active":
                return s
        # Fallback to time-based (pre-race / planning)
        for s in self.stints:
            if s.planned_start_s <= elapsed_s <= s.planned_end_s:
                return s
        return self.stints[-1] if self.stints else None
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_state_engine.py -v`
Expected: PASS (all tests including TestFuelCascade)

**Step 5: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(race-strategy): add RaceStateEngine with fuel cascade"
```

---

## Task 4: Ballast Cascade and Constraint Validation

**Files:**
- Modify: `telemetry_tool/race_state_engine.py` (implement `_validate_constraints`, add mutations)
- Modify: `telemetry_tool/tests/test_race_state_engine.py` (add ballast and constraint tests)

**Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_race_state_engine.py`:

```python
class TestBallastCascade:
    """Ballast decomposition and cascade."""

    def _make_engine(self, **overrides):
        """Same helper as TestFuelCascade."""
        from race_state_engine import RaceStateEngine
        config = {
            "race_duration_s": 7200,
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": 2400,
            "empty_kart_kg": 85.0,
            "full_tank_kg": 93.0,  # 8kg fuel
            "min_total_kart_kg": 160.0,
            "qualifying_duration_s": 0,
            "refuel_after_quali": 0,
            "refueling_allowed": 1,
            **overrides,
        }
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65.0,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75.0,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        raw_stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 2360, "planned_duration_s": 2360},
            {"stint_order": 2, "driver_id": 2, "driver_name": "Bob",
             "planned_start_s": 2420, "planned_end_s": 4780, "planned_duration_s": 2360},
            {"stint_order": 3, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 4840, "planned_end_s": 7200, "planned_duration_s": 2360},
        ]
        pit_stops = [
            {"after_stint": 1, "at_s": 2360, "duration_s": 60, "refuel": True, "driver_change": True, "pit_type": "full"},
            {"after_stint": 2, "at_s": 4780, "duration_s": 60, "refuel": True, "driver_change": True, "pit_type": "full"},
        ]
        return RaceStateEngine(config, drivers, raw_stints, pit_stops)

    def test_full_tank_ballast_base_only(self):
        engine = self._make_engine()
        # Alice: 160 - 85 - 8 - 65 = 2kg base, 0 fuel offset (full tank)
        assert engine.stints[0].ballast_base_kg == 2.0
        assert engine.stints[0].ballast_fuel_offset_kg == 0.0
        assert engine.stints[0].ballast_kg == 2.0

    def test_heavier_driver_less_ballast(self):
        engine = self._make_engine()
        # Bob: 160 - 85 - 8 - 75 = -8 → clamped to 0
        assert engine.stints[1].ballast_base_kg == 0.0

    def test_no_refuel_adds_fuel_offset(self):
        engine = self._make_engine()
        engine.toggle_fuel(2)  # No refuel before stint 2
        # Stint 2 starts with depleted fuel → fuel_offset > 0
        assert engine.stints[1].ballast_fuel_offset_kg > 0
        assert engine.stints[1].ballast_kg > engine.stints[1].ballast_base_kg

    def test_ballast_cascade_on_driver_change(self):
        engine = self._make_engine()
        original = engine.stints[1].ballast_kg
        engine.set_driver(2, 1)  # Change stint 2 to Alice (lighter)
        assert engine.stints[1].ballast_kg != original

    def test_real_time_ballast_during_stint(self):
        engine = self._make_engine()
        result = engine.current_ballast(1200)  # Midway through stint 1
        # Fuel has depleted, so fuel_offset > 0 → total > base
        assert result["fuel_offset_kg"] > 0
        assert result["total_kg"] > result["base_kg"]
        assert result["driver_name"] == "Alice"


class TestConstraintValidation:
    """Constraint enforcement in cascade."""

    def _make_engine(self, drivers=None, config_overrides=None, stints=None, pit_stops=None):
        from race_state_engine import RaceStateEngine
        config = {
            "race_duration_s": 7200,
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": 2400,
            "empty_kart_kg": 85.0,
            "full_tank_kg": 93.0,
            "min_total_kart_kg": 160.0,
            "qualifying_duration_s": 0,
            "refuel_after_quali": 0,
            "refueling_allowed": 1,
            "mandatory_driver_change": 0,
            **(config_overrides or {}),
        }
        if drivers is None:
            drivers = [
                {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65.0,
                 "min_stint_s": None, "max_stint_s": None,
                 "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
                {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75.0,
                 "min_stint_s": None, "max_stint_s": None,
                 "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            ]
        if stints is None:
            stints = [
                {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
                 "planned_start_s": 0, "planned_end_s": 2360, "planned_duration_s": 2360},
                {"stint_order": 2, "driver_id": 2, "driver_name": "Bob",
                 "planned_start_s": 2420, "planned_end_s": 4780, "planned_duration_s": 2360},
                {"stint_order": 3, "driver_id": 1, "driver_name": "Alice",
                 "planned_start_s": 4840, "planned_end_s": 7200, "planned_duration_s": 2360},
            ]
        if pit_stops is None:
            pit_stops = [
                {"after_stint": 1, "at_s": 2360, "duration_s": 60, "refuel": True, "driver_change": True, "pit_type": "full"},
                {"after_stint": 2, "at_s": 4780, "duration_s": 60, "refuel": True, "driver_change": True, "pit_type": "full"},
            ]
        return RaceStateEngine(config, drivers, stints, pit_stops)

    def test_fuel_exhaustion_violation(self):
        # Very long stint with small tank → fuel runs out
        engine = self._make_engine(config_overrides={"fuel_autonomy_s": 1000})
        # Stint 1 is 2360s but autonomy is 1000s → fuel_at_end < 0
        assert any("Fuel runs out" in v for v in engine.stints[0].violations)

    def test_mandatory_driver_change_violation(self):
        # Same driver for stints 1 and 2 with mandatory_driver_change=1
        stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 2360, "planned_duration_s": 2360},
            {"stint_order": 2, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 2420, "planned_end_s": 4780, "planned_duration_s": 2360},
            {"stint_order": 3, "driver_id": 2, "driver_name": "Bob",
             "planned_start_s": 4840, "planned_end_s": 7200, "planned_duration_s": 2360},
        ]
        engine = self._make_engine(
            config_overrides={"mandatory_driver_change": 1},
            stints=stints,
        )
        assert any("Mandatory driver change" in v for v in engine.stints[1].violations)

    def test_min_rest_time_violation(self):
        # Alice in stints 1 and 3 with only 60s gap (pit stop) but needs 300s rest
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65.0,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 300},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75.0,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        # Stints: Alice(0-1000), Bob(1060-2060), Alice(2120-3120) → Alice rest = 2120-1000 = 1120s OK
        # Make it tighter: Alice(0-3000), Bob(3060-4060), Alice(4120-5120) → rest = 4120-3000 = 1120s OK
        # Use 3 stints with very short middle stint
        stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 3000, "planned_duration_s": 3000},
            {"stint_order": 2, "driver_id": 2, "driver_name": "Bob",
             "planned_start_s": 3060, "planned_end_s": 3180, "planned_duration_s": 120},
            {"stint_order": 3, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 3240, "planned_end_s": 7200, "planned_duration_s": 3960},
        ]
        engine = self._make_engine(drivers=drivers, stints=stints)
        # Alice's rest: 3240 - 3000 = 240s < 300s → violation
        assert any("rest" in v.lower() for v in engine.stints[2].violations)

    def test_cumulative_max_exceeded_violation(self):
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65.0,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": 3000, "min_rest_s": 0},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75.0,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        # Alice drives stints 1 (2360s) and 3 (2360s) = 4720s > 3000s max
        engine = self._make_engine(drivers=drivers)
        assert any("exceeds max" in v.lower() for v in engine.stints[2].violations)

    def test_cumulative_90_percent_warning(self):
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65.0,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": 5000, "min_rest_s": 0},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75.0,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        # Alice drives 2360 + 2360 = 4720s, 90% of 5000 = 4500 → warning
        engine = self._make_engine(drivers=drivers)
        assert any("90%" in w for w in engine.stints[2].warnings)

    def test_no_violations_on_valid_plan(self):
        engine = self._make_engine()
        for s in engine.stints:
            assert s.violations == [], f"Stint {s.stint_order} has unexpected violations: {s.violations}"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_race_state_engine.py::TestBallastCascade -v`
Run: `pytest telemetry_tool/tests/test_race_state_engine.py::TestConstraintValidation -v`
Expected: FAIL — `set_driver` method doesn't exist, `_validate_constraints` is empty

**Step 3: Implement constraint validation and set_driver mutation**

In `telemetry_tool/race_state_engine.py`, replace the placeholder `_validate_constraints` and add `set_driver`:

```python
def _validate_constraints(self, stint: StintState) -> None:
    """Check constraints for a single stint. Populates violations/warnings."""
    stint.violations = []
    stint.warnings = []
    driver = self._get_driver(stint.driver_id)

    # Fuel exhaustion
    if stint.fuel_at_end_kg < 0:
        if self.fuel_model.burn_rate_kgs > 0:
            runout_s = stint.planned_start_s + (stint.fuel_at_start_kg / self.fuel_model.burn_rate_kgs)
            stint.violations.append(f"Fuel runs out at {int(runout_s)}s into race")
        else:
            stint.violations.append("Fuel exhausted but no burn rate configured")

    # Min rest time
    if driver.get("min_rest_s") and stint.stint_order > 1:
        for prev in self.stints:
            if prev.stint_order >= stint.stint_order:
                break
            if prev.driver_id == stint.driver_id:
                gap = stint.planned_start_s - prev.planned_end_s
                if gap < driver["min_rest_s"]:
                    stint.violations.append(
                        f"{driver['driver_name']}: {gap}s rest, needs {driver['min_rest_s']}s"
                    )

    # Mandatory driver change
    if self.config.get("mandatory_driver_change") and stint.stint_order > 1:
        prev = self._get_stint(stint.stint_order - 1)
        if prev and prev.driver_id == stint.driver_id:
            stint.violations.append("Mandatory driver change required at every pit stop")

    # Cumulative time
    max_cum = driver.get("max_cumulative_s")
    if max_cum:
        cumulative = sum(
            s.planned_duration_s for s in self.stints
            if s.driver_id == stint.driver_id and s.stint_order <= stint.stint_order
        )
        if cumulative > max_cum:
            stint.violations.append(
                f"{driver['driver_name']}: {cumulative}s exceeds max {max_cum}s"
            )
        elif cumulative > max_cum * 0.9:
            stint.warnings.append(
                f"{driver['driver_name']}: {cumulative}s is 90%+ of max {max_cum}s"
            )


def set_driver(self, stint_order: int, driver_id: int) -> None:
    """Change the driver on a stint. Recascades ballast."""
    stint = self._get_stint(stint_order)
    if not stint:
        return
    driver = self._get_driver(driver_id)
    if not driver:
        return
    stint.driver_id = driver_id
    stint.driver_name = driver.get("driver_name", "")
    self._cascade_from(stint_order)


def set_duration(self, stint_order: int, duration_s: int) -> None:
    """Change a stint's planned duration. Rebuilds timeline and recascades."""
    stint = self._get_stint(stint_order)
    if not stint:
        return
    stint.planned_duration_s = duration_s
    stint.planned_end_s = stint.planned_start_s + duration_s
    # Rebuild timeline for subsequent stints
    pit_time = self.config.get("min_pit_stop_s") or 60
    for s in self.stints:
        if s.stint_order <= stint_order:
            continue
        prev = self._get_stint(s.stint_order - 1)
        if prev:
            quick = self._pit_type_map.get(s.stint_order) == "quick"
            stop_dur = (self.config.get("quick_pit_stop_s") or pit_time) if quick else pit_time
            s.planned_start_s = prev.planned_end_s + stop_dur
            s.planned_end_s = s.planned_start_s + s.planned_duration_s
    self._cascade_from(stint_order)


def set_pit_type(self, stint_order: int, pit_type: str) -> None:
    """Toggle pit stop type (full/quick) before a stint. Recascades."""
    if stint_order <= 1:
        return
    self._pit_type_map[stint_order] = pit_type
    if pit_type == "quick":
        # Quick stops don't refuel
        self._refuel_map[stint_order] = False
    self._cascade_from(stint_order)
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_state_engine.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(race-strategy): add ballast cascade and constraint validation"
```

---

## Task 5: Engine Persistence (save/load) and Snapshot

**Files:**
- Modify: `telemetry_tool/race_state_engine.py` (add `save`, `load`, `snapshot`, `stint_plan_export`)
- Modify: `telemetry_tool/tests/test_race_state_engine.py` (add persistence tests)

**Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_race_state_engine.py`:

```python
import sqlite3

@pytest.fixture
def engine_db():
    """In-memory DB with v22 schema."""
    from db.migrate import ensure_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


class TestEnginePersistence:
    """Save/load round-trip."""

    def _seed_race(self, conn):
        """Insert a race config + drivers, return race_id."""
        conn.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, fuel_autonomy_s, "
            "empty_kart_kg, full_tank_kg, min_total_kart_kg, min_pit_stop_s) "
            "VALUES ('Test 2h', 7200, 2400, 85, 93, 160, 60)"
        )
        conn.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'Alice', 1, 65)")
        conn.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'Bob', 2, 75)")
        conn.commit()
        return 1

    def test_save_and_load_round_trip(self, engine_db):
        from race_state_engine import RaceStateEngine
        race_id = self._seed_race(engine_db)

        config = dict(engine_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        drivers = [dict(r) for r in engine_db.execute("SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order").fetchall()]

        raw_stints = [
            {"stint_order": 1, "driver_id": drivers[0]["id"], "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 2360, "planned_duration_s": 2360},
            {"stint_order": 2, "driver_id": drivers[1]["id"], "driver_name": "Bob",
             "planned_start_s": 2420, "planned_end_s": 4780, "planned_duration_s": 2360},
        ]
        pit_stops = [
            {"after_stint": 1, "at_s": 2360, "duration_s": 60, "refuel": True, "driver_change": True, "pit_type": "full"},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints, pit_stops)
        engine.save(engine_db, race_id)

        # Reload
        loaded = RaceStateEngine.load(engine_db, race_id)
        assert len(loaded.stints) == 2
        assert loaded.stints[0].fuel_at_start_kg == engine.stints[0].fuel_at_start_kg
        assert loaded.stints[0].ballast_kg == engine.stints[0].ballast_kg
        assert loaded.stints[1].ballast_base_kg == engine.stints[1].ballast_base_kg

    def test_snapshot_returns_full_state(self, engine_db):
        from race_state_engine import RaceStateEngine
        config = {
            "race_duration_s": 3600, "fuel_autonomy_s": 2400,
            "empty_kart_kg": 85, "full_tank_kg": 93, "min_total_kart_kg": 160,
            "min_pit_stop_s": 60, "refuel_after_quali": 0, "qualifying_duration_s": 0,
            "refueling_allowed": 1,
        }
        drivers = [{"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 65}]
        stints = [{"stint_order": 1, "driver_id": 1, "driver_name": "A",
                    "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600}]
        engine = RaceStateEngine(config, drivers, stints, [])
        snap = engine.snapshot()
        assert "stints" in snap
        assert "fuel_model" in snap
        assert snap["stints"][0]["ballast_base_kg"] is not None
        assert snap["stints"][0]["fuel_at_start_kg"] is not None

    def test_stint_plan_export_format(self, engine_db):
        from race_state_engine import RaceStateEngine
        config = {
            "race_duration_s": 3600, "fuel_autonomy_s": 2400,
            "empty_kart_kg": 85, "full_tank_kg": 93, "min_total_kart_kg": 160,
            "min_pit_stop_s": 60, "refuel_after_quali": 0, "qualifying_duration_s": 0,
            "refueling_allowed": 1,
        }
        drivers = [{"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 65}]
        stints = [{"stint_order": 1, "driver_id": 1, "driver_name": "A",
                    "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600}]
        engine = RaceStateEngine(config, drivers, stints, [])
        export = engine.stint_plan_export("Test Race")
        assert export["format"] == "stint-plan-v1"
        assert export["race_name"] == "Test Race"
        assert len(export["stints"]) == 1
        assert "ballast_kg" in export["stints"][0]
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_race_state_engine.py::TestEnginePersistence -v`
Expected: FAIL — `save`, `load`, `snapshot`, `stint_plan_export` don't exist

**Step 3: Implement save/load/snapshot/export**

Add to `RaceStateEngine` class in `telemetry_tool/race_state_engine.py`:

```python
def save(self, conn, race_id: int) -> None:
    """Write all stints and pit stops to database."""
    conn.execute("DELETE FROM race_stints WHERE race_id = ?", (race_id,))
    conn.execute("DELETE FROM race_pit_stops WHERE race_id = ?", (race_id,))

    for s in self.stints:
        conn.execute(
            """INSERT INTO race_stints (race_id, stint_order, driver_id,
                planned_start_s, planned_end_s, planned_duration_s,
                actual_start_s, actual_end_s, actual_duration_s,
                fuel_at_start, fuel_at_end, ballast_kg,
                ballast_base_kg, ballast_fuel_offset_kg, fuel_burn_rate_kgs,
                notes, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (race_id, s.stint_order, s.driver_id,
             s.planned_start_s, s.planned_end_s, s.planned_duration_s,
             s.actual_start_s, s.actual_end_s, s.actual_duration_s,
             round(s.fuel_at_start_kg, 4), round(s.fuel_at_end_kg, 4),
             s.ballast_kg, s.ballast_base_kg, s.ballast_fuel_offset_kg,
             self.fuel_model.burn_rate_kgs,
             s.notes, s.status),
        )

    for ps in self._pit_stops:
        after = ps.get("after_stint", 0)
        next_order = after + 1
        conn.execute(
            """INSERT INTO race_pit_stops (race_id, planned_at_s, duration_s,
                driver_change, refueled, pit_type, notes)
            VALUES (?,?,?,?,?,?,?)""",
            (race_id, ps.get("at_s"), ps.get("duration_s"),
             1 if ps.get("driver_change") else 0,
             1 if self._refuel_map.get(next_order, True) else 0,
             self._pit_type_map.get(next_order, "full"),
             ps.get("notes")),
        )

    conn.commit()

@classmethod
def load(cls, conn, race_id: int) -> RaceStateEngine:
    """Reconstruct engine from database."""
    race = dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    drivers = [dict(r) for r in conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall()]

    stint_rows = conn.execute(
        "SELECT s.*, d.driver_name FROM race_stints s "
        "JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = ? ORDER BY s.stint_order", (race_id,)
    ).fetchall()

    raw_stints = []
    for r in stint_rows:
        raw_stints.append(dict(r))

    pit_rows = conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY planned_at_s", (race_id,)
    ).fetchall()

    pit_stops = []
    for i, r in enumerate(pit_rows):
        pit_stops.append({
            "after_stint": i + 1,
            "at_s": r["planned_at_s"],
            "duration_s": r["duration_s"],
            "driver_change": bool(r["driver_change"]),
            "refuel": bool(r["refueled"]),
            "pit_type": r["pit_type"] if "pit_type" in r.keys() else "full",
        })

    return cls(race, drivers, raw_stints, pit_stops)

def snapshot(self) -> dict[str, Any]:
    """Full state dict for API responses."""
    return {
        "fuel_model": {
            "full_tank_kg": self.fuel_model.full_tank_kg,
            "fuel_autonomy_s": self.fuel_model.fuel_autonomy_s,
            "burn_rate_kgs": round(self.fuel_model.burn_rate_kgs, 6),
            "quali_fuel_used_kg": round(self.fuel_model.quali_fuel_used_kg, 4),
        },
        "stints": [
            {
                "stint_order": s.stint_order,
                "driver_id": s.driver_id,
                "driver_name": s.driver_name,
                "planned_start_s": s.planned_start_s,
                "planned_end_s": s.planned_end_s,
                "planned_duration_s": s.planned_duration_s,
                "fuel_at_start_kg": round(s.fuel_at_start_kg, 4),
                "fuel_at_end_kg": round(s.fuel_at_end_kg, 4),
                "refueled_before": s.refueled_before,
                "ballast_kg": s.ballast_kg,
                "ballast_base_kg": round(s.ballast_base_kg, 2),
                "ballast_fuel_offset_kg": round(s.ballast_fuel_offset_kg, 2),
                "actual_start_s": s.actual_start_s,
                "actual_end_s": s.actual_end_s,
                "actual_duration_s": s.actual_duration_s,
                "status": s.status,
                "notes": s.notes,
                "violations": s.violations,
                "warnings": s.warnings,
            }
            for s in self.stints
        ],
        "refuel_map": {str(k): v for k, v in self._refuel_map.items()},
        "pit_type_map": {str(k): v for k, v in self._pit_type_map.items()},
    }

def stint_plan_export(self, race_name: str) -> dict[str, Any]:
    """Export stint plan as lightweight JSON (no config, no DB IDs)."""
    from datetime import datetime, timezone
    return {
        "format": "stint-plan-v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "race_name": race_name,
        "stints": [
            {
                "stint_order": s.stint_order,
                "driver_name": s.driver_name,
                "planned_duration_s": s.planned_duration_s,
                "refueled_before": s.refueled_before,
                "ballast_kg": s.ballast_kg,
                "ballast_base_kg": round(s.ballast_base_kg, 2),
                "ballast_fuel_offset_kg": round(s.ballast_fuel_offset_kg, 2),
            }
            for s in self.stints
        ],
        "pit_stops": [
            {
                "after_stint": ps.get("after_stint"),
                "duration_s": ps.get("duration_s"),
                "driver_change": ps.get("driver_change"),
                "refueled": self._refuel_map.get(ps.get("after_stint", 0) + 1, True),
                "pit_type": self._pit_type_map.get(ps.get("after_stint", 0) + 1, "full"),
            }
            for ps in self._pit_stops
        ],
    }
```

**Step 4: Run all tests**

Run: `pytest telemetry_tool/tests/test_race_state_engine.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(race-strategy): add engine save/load/snapshot/export"
```

---

## Task 6: Wire Engine into Optimizer Route

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py:437-486` (optimize route)
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py:604-647` (api_state route)
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py:710-743` (api_reoptimize route)
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py` (update integration tests)

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_race_strategy_v2.py` inside `TestRaceStrategyIntegration`:

```python
def test_optimize_saves_fuel_and_ballast_columns(self, strategy_db):
    """After optimize, stints have fuel_at_start, ballast_base_kg filled."""
    from race_strategy_v2 import optimize_stints
    from race_state_engine import RaceStateEngine

    strategy_db.execute(
        "INSERT INTO race_configs (race_name, race_duration_s, fuel_autonomy_s, "
        "empty_kart_kg, full_tank_kg, min_total_kart_kg, min_pit_stop_s, desired_stints) "
        "VALUES ('Test', 7200, 2400, 85, 93, 160, 60, 3)"
    )
    strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'Alice', 1, 65)")
    strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'Bob', 2, 75)")
    strategy_db.commit()

    config = dict(strategy_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
    drivers = [dict(r) for r in strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order").fetchall()]

    result = optimize_stints(config, drivers)
    engine = RaceStateEngine(config, drivers, result["stints"], result["pit_stops"])
    engine.save(strategy_db, 1)

    rows = strategy_db.execute("SELECT * FROM race_stints WHERE race_id = 1 ORDER BY stint_order").fetchall()
    assert rows[0]["fuel_at_start"] is not None
    assert rows[0]["ballast_base_kg"] is not None
    assert rows[0]["fuel_at_start"] > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestRaceStrategyIntegration::test_optimize_saves_fuel_and_ballast_columns -v`
Expected: FAIL (columns are NULL because current optimizer doesn't set them)

**Step 3: Update the optimize route**

In `telemetry_tool/web/routes/race_strategy_v2.py`, update the `optimize` function (line 437) to use `RaceStateEngine`:

Replace the stint-saving block (lines 453-484) with:

```python
@bp.route("/<int:race_id>/optimize", methods=["POST"])
def optimize(race_id: int):
    """Run optimizer and save planned stints with fuel-aware ballast."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_strategy_v2 import optimize_stints
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())

    result = optimize_stints(race, drivers)

    # Wrap in engine for fuel/ballast cascade
    engine = RaceStateEngine(race, drivers, result["stints"], result["pit_stops"])
    engine.save(conn, race_id)

    # Update status to ready if feasible
    new_status = "ready" if result["feasible"] else "draft"
    conn.execute("UPDATE race_configs SET status = ?, updated_at = datetime('now') WHERE race_id = ?",
                 (new_status, race_id))
    conn.commit()

    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))
```

**Step 4: Update the api_state route to include engine data**

Replace `api_state` (line 604) to add fuel/ballast to response:

```python
@bp.route("/<int:race_id>/api/state")
def api_state(race_id: int):
    """Full race state for live dashboard polling."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        return jsonify({"error": "not found"}), 404

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name, d.weight_kg as driver_weight_kg FROM race_stints s "
        "JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = ? ORDER BY s.stint_order", (race_id,)
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY planned_at_s", (race_id,)
    ).fetchall())
    messages = _rows_to_list(conn.execute(
        "SELECT * FROM race_messages WHERE race_id = ? ORDER BY msg_id", (race_id,)
    ).fetchall())

    active_stint = next((s for s in stints if s["status"] == "active"), None)
    next_stint = next((s for s in stints if s["status"] == "planned"), None)

    # Driver cumulative times
    driver_cumulative = {}
    for s in stints:
        if s["status"] == "completed":
            did = s["driver_id"]
            dur = s.get("actual_duration_s") or s.get("planned_duration_s") or 0
            driver_cumulative[did] = driver_cumulative.get(did, 0) + dur

    # Engine-computed real-time data
    engine_data = {}
    try:
        from race_state_engine import RaceStateEngine
        engine = RaceStateEngine.load(conn, race_id)
        elapsed = _compute_elapsed_s(race.get("race_start_ts"))
        engine_data = {
            "current_fuel_kg": round(engine.current_fuel_kg(elapsed), 4),
            "current_ballast": engine.current_ballast(elapsed),
            "fuel_model": engine.snapshot()["fuel_model"],
        }
    except Exception:
        logger.debug("Engine load failed for race %d, returning basic state", race_id)

    return jsonify({
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "messages": messages,
        "active_stint": active_stint,
        "next_stint": next_stint,
        "driver_cumulative": driver_cumulative,
        **engine_data,
    })
```

**Step 5: Update the api_reoptimize route**

Replace `api_reoptimize` (line 710) to use engine:

```python
@bp.route("/<int:race_id>/api/reoptimize", methods=["POST"])
def api_reoptimize(race_id: int):
    """Re-optimize remaining stints mid-race."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_strategy_v2 import reoptimize_remaining
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    completed = _rows_to_list(conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? AND status = 'completed' ORDER BY stint_order",
        (race_id,),
    ).fetchall())

    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    result = reoptimize_remaining(race, drivers, completed, elapsed)

    # Clear planned stints, keep completed and active
    conn.execute("DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'", (race_id,))

    # Rebuild full stint list for engine (completed + new planned)
    all_stints = completed + result["stints"]
    engine = RaceStateEngine(race, drivers, all_stints, result["pit_stops"])
    # Only save the new planned stints (keep completed as-is in DB)
    for s in engine.stints:
        if s.stint_order > len(completed):
            conn.execute(
                """INSERT INTO race_stints (race_id, stint_order, driver_id,
                    planned_start_s, planned_end_s, planned_duration_s,
                    fuel_at_start, fuel_at_end, ballast_kg,
                    ballast_base_kg, ballast_fuel_offset_kg, fuel_burn_rate_kgs,
                    status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'planned')""",
                (race_id, s.stint_order, s.driver_id,
                 s.planned_start_s, s.planned_end_s, s.planned_duration_s,
                 round(s.fuel_at_start_kg, 4), round(s.fuel_at_end_kg, 4),
                 s.ballast_kg, s.ballast_base_kg, s.ballast_fuel_offset_kg,
                 engine.fuel_model.burn_rate_kgs),
            )
    conn.commit()

    return jsonify({"ok": True, "result": engine.snapshot()})
```

**Step 4: Run all tests**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py -v`
Run: `pytest telemetry_tool/tests/test_race_state_engine.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(race-strategy): wire RaceStateEngine into optimize and live API routes"
```

---

## Task 7: Stint Plan Import/Export Routes and Fuel Toggle API

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (add new API routes)
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py` (add route tests)

**Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestStintPlanExportImport:
    """Stint-plan-only import/export."""

    def test_export_plan_format(self, strategy_db):
        from race_state_engine import RaceStateEngine

        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, fuel_autonomy_s, "
            "empty_kart_kg, full_tank_kg, min_total_kart_kg, min_pit_stop_s) "
            "VALUES ('Test', 3600, 2400, 85, 93, 160, 60)"
        )
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'A', 1, 65)")
        strategy_db.commit()

        config = dict(strategy_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        drivers = [dict(r) for r in strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = 1").fetchall()]
        stints = [{"stint_order": 1, "driver_id": drivers[0]["id"], "driver_name": "A",
                    "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600}]
        engine = RaceStateEngine(config, drivers, stints, [])
        export = engine.stint_plan_export("Test")
        assert export["format"] == "stint-plan-v1"
        assert len(export["stints"]) == 1
        assert "ballast_base_kg" in export["stints"][0]
        assert "ballast_fuel_offset_kg" in export["stints"][0]
```

**Step 2: Run test to verify it passes** (should pass — `stint_plan_export` was added in Task 5)

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestStintPlanExportImport -v`
Expected: PASS

**Step 3: Add routes for stint plan export/import and fuel toggle API**

Add to `telemetry_tool/web/routes/race_strategy_v2.py` (after the existing export route, around line 83):

```python
@bp.route("/<int:race_id>/export-plan")
def export_plan(race_id: int):
    """Export stint plan only (lightweight, no config) as JSON download."""
    import re
    import sys

    from flask import Response

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)

    try:
        engine = RaceStateEngine.load(conn, race_id)
    except Exception:
        abort(400)

    data = engine.stint_plan_export(race.get("race_name", ""))
    payload = json.dumps(data, indent=2, default=str)

    slug = re.sub(r'[^a-z0-9]+', '-', race["race_name"].lower()).strip('-')
    filename = f"stint-plan-{slug}.json"

    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/<int:race_id>/import-plan", methods=["POST"])
def import_plan(race_id: int):
    """Import stint plan into existing race. Matches drivers by name."""
    import sys

    from flask import flash

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)

    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("race_strategy_v2.detail", race_id=race_id))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        flash("Invalid JSON file.", "error")
        return redirect(url_for("race_strategy_v2.detail", race_id=race_id))

    if data.get("format") != "stint-plan-v1":
        flash("Unsupported plan format.", "error")
        return redirect(url_for("race_strategy_v2.detail", race_id=race_id))

    # Match drivers by name
    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    name_to_id = {d["driver_name"].lower(): d["id"] for d in drivers}

    raw_stints = []
    warnings = []
    for s in data.get("stints", []):
        driver_name = s.get("driver_name", "")
        driver_id = name_to_id.get(driver_name.lower())
        if not driver_id:
            warnings.append(f"Driver '{driver_name}' not found in race")
            driver_id = drivers[0]["id"] if drivers else None
        if driver_id:
            raw_stints.append({
                "stint_order": s["stint_order"],
                "driver_id": driver_id,
                "driver_name": driver_name,
                "planned_duration_s": s["planned_duration_s"],
                "planned_start_s": 0,  # Will be rebuilt
                "planned_end_s": 0,
            })

    # Rebuild timeline
    pit_time = race.get("min_pit_stop_s") or 60
    pit_stops = []
    clock = 0
    for i, s in enumerate(raw_stints):
        s["planned_start_s"] = clock
        s["planned_end_s"] = clock + s["planned_duration_s"]
        clock += s["planned_duration_s"]
        if i < len(raw_stints) - 1:
            ps = data.get("pit_stops", [{}] * len(raw_stints))
            p = ps[i] if i < len(ps) else {}
            pit_stops.append({
                "after_stint": i + 1,
                "at_s": clock,
                "duration_s": p.get("duration_s", pit_time),
                "driver_change": p.get("driver_change", True),
                "refuel": p.get("refueled", True),
                "pit_type": p.get("pit_type", "full"),
            })
            clock += p.get("duration_s", pit_time)

    engine = RaceStateEngine(race, drivers, raw_stints, pit_stops)
    engine.save(conn, race_id)

    if warnings:
        from flask import flash as flash_msg
        for w in warnings:
            flash_msg(w, "warning")

    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))
```

Add fuel toggle and pit type API routes (after existing API routes):

```python
@bp.route("/<int:race_id>/api/toggle-fuel", methods=["POST"])
def api_toggle_fuel(race_id: int):
    """Toggle refuel on a pit stop. Triggers cascade recalculation."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    if not stint_order:
        return jsonify({"error": "stint_order required"}), 400

    engine = RaceStateEngine.load(conn, race_id)
    engine.toggle_fuel(stint_order)
    engine.save(conn, race_id)
    return jsonify({"ok": True, "snapshot": engine.snapshot()})


@bp.route("/<int:race_id>/api/set-pit-type", methods=["POST"])
def api_set_pit_type(race_id: int):
    """Set pit stop type (full/quick). Triggers cascade."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    pit_type = data.get("pit_type", "full")
    if not stint_order or pit_type not in ("full", "quick"):
        return jsonify({"error": "stint_order and valid pit_type required"}), 400

    engine = RaceStateEngine.load(conn, race_id)
    engine.set_pit_type(stint_order, pit_type)
    engine.save(conn, race_id)
    return jsonify({"ok": True, "snapshot": engine.snapshot()})


@bp.route("/<int:race_id>/api/set-driver", methods=["POST"])
def api_set_driver(race_id: int):
    """Change driver on a stint. Triggers cascade."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    driver_id = data.get("driver_id")
    if not stint_order or not driver_id:
        return jsonify({"error": "stint_order and driver_id required"}), 400

    engine = RaceStateEngine.load(conn, race_id)
    engine.set_driver(stint_order, driver_id)
    engine.save(conn, race_id)
    return jsonify({"ok": True, "snapshot": engine.snapshot()})


@bp.route("/<int:race_id>/api/set-duration", methods=["POST"])
def api_set_duration(race_id: int):
    """Edit stint duration. Triggers cascade."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    duration_s = data.get("duration_s")
    if not stint_order or duration_s is None:
        return jsonify({"error": "stint_order and duration_s required"}), 400

    engine = RaceStateEngine.load(conn, race_id)
    engine.set_duration(stint_order, int(duration_s))
    engine.save(conn, race_id)
    return jsonify({"ok": True, "snapshot": engine.snapshot()})
```

**Step 4: Run all tests**

Run: `pytest telemetry_tool/tests/ -v -k "race_strategy or race_state"`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(race-strategy): add stint plan export/import, fuel toggle, and cascade API routes"
```

---

## Task 8: Config Form — Wire Up Existing DB Fields

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/config.html` (add UI for pit_speed, quick_pit, com_channel, mandatory_driver_change, refueling_allowed)
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (ensure new/update routes read new fields)

This task requires reading the config.html template first to understand the current form layout, then adding the missing fields. No test for this step — it's pure template wiring of existing DB columns.

**Step 1: Read current config.html**

Read: `telemetry_tool/web/templates/race_strategy/config.html`

**Step 2: Add form fields**

Add to the config form in appropriate sections:

- **Pit lane speed limit** (`pit_speed_kmh`): number input in the Pit section
- **Quick pit stop duration** (`quick_pit_stop_s`): number input in the Pit section
- **Mandatory driver change** (`mandatory_driver_change`): checkbox in the Rules section
- **Refueling allowed** (`refueling_allowed`): checkbox in the Fuel section
- **COM channel per driver** (`com_channel`): text input in each driver row

**Step 3: Ensure the route reads and saves these fields**

Check `new_race()` (line 238) and `update()` (line 289) routes — they should already INSERT/UPDATE these columns since they exist in the schema. If not, add them to the INSERT/UPDATE statements.

**Step 4: Verify visually** by launching `python telemetry_tool/main.py --serve` and visiting the config page.

**Step 5: Commit**

```bash
git add telemetry_tool/web/templates/race_strategy/config.html telemetry_tool/web/routes/race_strategy_v2.py
git commit -m "feat(race-strategy): wire pit_speed, quick_pit, com_channel, refueling_allowed into config form"
```

---

## Task 9: Detail Page — Fuel Toggles, Ballast Decomposition, Refuel Count

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/detail.html` (stint plan table enhancements)
- Modify: `telemetry_tool/web/static/js/race_strategy.js` (fuel toggle interaction, cascade UI update)

**Step 1: Read current detail.html and race_strategy.js**

Read both files to understand current stint table layout.

**Step 2: Enhance stint plan table**

In `detail.html`, update the stint plan table to show:
- Per-stint ballast decomposition: "Base + Fuel Offset = Total" in the ballast column
- Fuel toggle icon per pit stop row (calls `POST /api/toggle-fuel`)
- Color-coded cumulative time (red when exceeding fuel autonomy)
- Running refuel count in table header: "Refuels: X/Y stops"
- Pit type toggle per pit stop (full/quick)

**Step 3: Add JS interaction handlers**

In `race_strategy.js`, add click handlers for:
- Fuel toggle button → `fetch('/{race_id}/api/toggle-fuel', {method: 'POST', body: JSON.stringify({stint_order})})` → update table with response snapshot
- Pit type toggle → same pattern with `/api/set-pit-type`
- Duration inline edit → same pattern with `/api/set-duration`

**Step 4: Test manually** — run `--serve`, create a race, optimize, verify toggles cascade correctly.

**Step 5: Commit**

```bash
git add telemetry_tool/web/templates/race_strategy/detail.html telemetry_tool/web/static/js/race_strategy.js
git commit -m "feat(race-strategy): add fuel toggles and ballast decomposition to stint plan table"
```

---

## Task 10: Live Dashboard — Real-Time Ballast, Fuel Gauge, COM Channel

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html` (add ballast display, COM channel)
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js` (render real-time ballast, fuel offset)
- Modify: `telemetry_tool/web/static/css/race_strategy.css` (ballast decomposition styles)

**Step 1: Read current live.html and race_strategy_live.js**

Read both files to understand the 6-component layout and polling loop.

**Step 2: Enhance Fuel & Ballast component**

The existing "Fuel & Ballast" component (component 2 in the live dashboard) currently shows a fuel percentage and ballast number. Update to:
- Show fuel as a depleting progress bar (width = `current_fuel_kg / full_tank_kg * 100%`)
- Show ballast decomposition: "Base: Xkg + Fuel: Ykg = Total: Zkg" in large text
- Show pit lane speed limit badge: "Pit limit: 40 km/h"

**Step 3: Enhance driver cards**

The current/next driver cards show driver name and stint time. Add:
- COM channel: "COM: Ch 4" badge
- Ballast decomposition: "Ballast: 2.0 + 1.5 = 3.5 kg"

**Step 4: Update polling response handler**

In `race_strategy_live.js`, the polling handler processes `/api/state` response. Update to use new fields:
- `data.current_fuel_kg` → fuel bar width
- `data.current_ballast.base_kg`, `.fuel_offset_kg`, `.total_kg` → ballast display
- `data.fuel_model.full_tank_kg` → fuel bar scale
- `data.drivers[i].com_channel` → driver card badges

**Step 5: Add CSS for ballast decomposition**

In `race_strategy.css`, add:
```css
.ballast-decomposition { display: flex; gap: 0.5rem; align-items: baseline; }
.ballast-base { color: var(--text-secondary); }
.ballast-fuel-offset { color: var(--accent-warning); }
.ballast-total { font-size: 1.5rem; font-weight: 700; }
```

**Step 6: Test manually** — create race, go live, verify ballast ticks in real-time.

**Step 7: Commit**

```bash
git add telemetry_tool/web/templates/race_strategy/live.html telemetry_tool/web/static/js/race_strategy_live.js telemetry_tool/web/static/css/race_strategy.css
git commit -m "feat(race-strategy): add real-time ballast and fuel gauge to live dashboard"
```

---

## Task 11: Full Test Suite Verification

**Files:**
- Run: all tests to ensure nothing is broken

**Step 1: Run full test suite**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py telemetry_tool/tests/test_race_state_engine.py -v`
Expected: ALL PASS

**Step 2: Run broader test suite for regressions**

Run: `pytest telemetry_tool/tests/ -v --tb=short`
Expected: ALL PASS (no regressions)

**Step 3: Fix any failures, commit fixes**

If any test fails, fix the issue and commit:
```bash
git commit -m "fix(race-strategy): [describe fix]"
```

---

## Summary

| Task | Description | Files | Est. Steps |
|------|-------------|-------|------------|
| 1 | Schema v22 migration | schema.py, migrate.py, tests | 6 |
| 2 | FuelModel + StintState dataclasses | race_state_engine.py, tests | 5 |
| 3 | Fuel cascade logic | race_state_engine.py, tests | 5 |
| 4 | Ballast cascade + constraints | race_state_engine.py, tests | 5 |
| 5 | Engine save/load/snapshot | race_state_engine.py, tests | 5 |
| 6 | Wire engine into routes | routes/race_strategy_v2.py, tests | 5 |
| 7 | Stint plan import/export + toggle APIs | routes/race_strategy_v2.py, tests | 5 |
| 8 | Config form field wiring | config.html, routes | 5 |
| 9 | Detail page enhancements | detail.html, race_strategy.js | 5 |
| 10 | Live dashboard enhancements | live.html, race_strategy_live.js, CSS | 7 |
| 11 | Full test verification | all test files | 3 |

**Total: 11 tasks, ~56 steps**

Build order: Tasks 1-7 are backend (test-driven, sequential). Tasks 8-10 are frontend (can run in parallel after Task 7). Task 11 is final verification.
