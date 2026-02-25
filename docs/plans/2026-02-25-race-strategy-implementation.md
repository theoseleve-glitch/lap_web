# Race Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an endurance race management tool with pre-race config, stint optimizer, live dashboard (6 components), and post-race summary.

**Architecture:** Approach C — multi-page config flow + single-page live dashboard. Flask blueprint + SQLite persistence + vanilla JS polling. See `docs/plans/2026-02-25-race-strategy-design.md` for full design.

**Tech Stack:** Python/Flask, SQLite, vanilla JS, Canvas 2D, existing CSS design system.

---

### Task 1: Database Schema — Phase 15 Tables

**Files:**
- Modify: `telemetry_tool/db/schema.py:752-755`
- Modify: `telemetry_tool/db/migrate.py:365-370`
- Test: `telemetry_tool/tests/test_race_strategy_v2.py` (create)

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
"""Tests for the endurance race strategy feature."""

import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def strategy_db():
    """In-memory DB with full schema including race strategy tables."""
    from db.migrate import ensure_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


class TestRaceStrategySchema:
    """Phase 15 tables exist and accept inserts."""

    def test_race_configs_table_exists(self, strategy_db):
        row = strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('Test 3h', 10800) RETURNING race_id"
        ).fetchone()
        assert row["race_id"] >= 1

    def test_race_drivers_table_exists(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'Alice', 1)"
        )
        row = strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = 1").fetchone()
        assert row["driver_name"] == "Alice"

    def test_race_stints_table_exists(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
        strategy_db.execute(
            "INSERT INTO race_stints (race_id, stint_order, driver_id, status) VALUES (1, 1, 1, 'planned')"
        )
        row = strategy_db.execute("SELECT * FROM race_stints WHERE race_id = 1").fetchone()
        assert row["stint_order"] == 1

    def test_race_pit_stops_table_exists(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
        strategy_db.execute("INSERT INTO race_stints (race_id, stint_order, driver_id, status) VALUES (1, 1, 1, 'planned')")
        strategy_db.execute(
            "INSERT INTO race_pit_stops (race_id, stint_id, driver_change, refueled) VALUES (1, 1, 1, 0)"
        )
        row = strategy_db.execute("SELECT * FROM race_pit_stops WHERE race_id = 1").fetchone()
        assert row["driver_change"] == 1

    def test_race_configs_default_values(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        row = strategy_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone()
        assert row["status"] == "draft"
        assert row["desired_stints"] == 4
        assert row["min_pit_stop_s"] == 60
        assert row["weigh_on_pit_exit"] == 0

    def test_schema_version_is_20(self, strategy_db):
        row = strategy_db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        assert row["v"] == 20
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py -v`
Expected: FAIL — tables don't exist yet

**Step 3: Write the schema tables**

In `telemetry_tool/db/schema.py`, after line 752 (after `PHASE_14_TABLES`), add:

```python
# ── Phase 15: Race Strategy (endurance race management) ──────────────

_RACE_CONFIGS_TABLE = """
CREATE TABLE IF NOT EXISTS race_configs (
    race_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    race_name           TEXT    NOT NULL,
    track_name          TEXT,
    team_name           TEXT,
    race_duration_s     INTEGER NOT NULL,
    reference_weight_kg REAL,
    desired_stints      INTEGER NOT NULL DEFAULT 4,
    fuel_autonomy_s     INTEGER,
    min_pit_stop_s      INTEGER NOT NULL DEFAULT 60,
    pit_speed_kmh       REAL,
    pit_open_s          INTEGER,
    pit_close_s         INTEGER,
    empty_kart_kg       REAL,
    full_tank_kg        REAL,
    min_total_kart_kg   REAL,
    weigh_on_pit_exit   INTEGER NOT NULL DEFAULT 0,
    qualifying_duration_s INTEGER,
    refuel_after_quali  INTEGER NOT NULL DEFAULT 0,
    mandatory_driver_change INTEGER NOT NULL DEFAULT 1,
    refueling_allowed   INTEGER NOT NULL DEFAULT 1,
    race_start_ts       TEXT,
    status              TEXT    NOT NULL DEFAULT 'draft',
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_RACE_DRIVERS_TABLE = """
CREATE TABLE IF NOT EXISTS race_drivers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id             INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    driver_name         TEXT    NOT NULL,
    driver_order        INTEGER NOT NULL,
    min_stint_s         INTEGER,
    max_stint_s         INTEGER,
    min_cumulative_s    INTEGER,
    max_cumulative_s    INTEGER,
    min_rest_s          INTEGER NOT NULL DEFAULT 0,
    weight_kg           REAL
);
"""

_RACE_STINTS_TABLE = """
CREATE TABLE IF NOT EXISTS race_stints (
    stint_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id             INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    stint_order         INTEGER NOT NULL,
    driver_id           INTEGER NOT NULL REFERENCES race_drivers(id),
    planned_start_s     INTEGER,
    planned_end_s       INTEGER,
    planned_duration_s  INTEGER,
    actual_start_s      INTEGER,
    actual_end_s        INTEGER,
    actual_duration_s   INTEGER,
    fuel_at_start       REAL,
    fuel_at_end         REAL,
    ballast_kg          REAL,
    notes               TEXT,
    status              TEXT NOT NULL DEFAULT 'planned'
);
"""

_RACE_PIT_STOPS_TABLE = """
CREATE TABLE IF NOT EXISTS race_pit_stops (
    pit_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id             INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    stint_id            INTEGER REFERENCES race_stints(stint_id),
    planned_at_s        INTEGER,
    actual_at_s         INTEGER,
    duration_s          INTEGER,
    driver_change       INTEGER NOT NULL DEFAULT 1,
    refueled            INTEGER NOT NULL DEFAULT 0,
    fuel_added_kg       REAL,
    ballast_changed     INTEGER NOT NULL DEFAULT 0,
    notes               TEXT
);
"""

PHASE_15_TABLES: list[tuple[str, str]] = [
    ("race_configs", _RACE_CONFIGS_TABLE),
    ("race_drivers", _RACE_DRIVERS_TABLE),
    ("race_stints", _RACE_STINTS_TABLE),
    ("race_pit_stops", _RACE_PIT_STOPS_TABLE),
]
```

Update `ALL_TABLES` on line 755 to append `+ PHASE_15_TABLES`.

Update `SCHEMA_VERSION` on line 9 from `19` to `20`.

In `telemetry_tool/db/migrate.py`, before `conn.commit()` (line 367), add:

```python
    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (20, "Phase 15 schema — race strategy (race_configs, race_drivers, race_stints, race_pit_stops)"),
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py -v`
Expected: 6 PASSED

**Step 5: Run full test suite for regressions**

Run: `pytest telemetry_tool/tests/ -x -q`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/migrate.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(race-strategy): add Phase 15 schema — 4 tables for endurance race management"
```

---

### Task 2: Optimizer Engine

**Files:**
- Create: `telemetry_tool/race_strategy_v2.py`
- Test: `telemetry_tool/tests/test_race_strategy_v2.py` (append)

**Step 1: Write failing tests**

Append to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestOptimizer:
    """Stint allocation optimizer."""

    def test_basic_equal_split(self):
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 10800,  # 3h
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
        }
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 80,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
        assert len(result["stints"]) == 3
        total_drive = sum(s["planned_duration_s"] for s in result["stints"])
        total_pit = (3 - 1) * 60
        assert total_drive + total_pit == 10800

    def test_fuel_autonomy_caps_stint(self):
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 2,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": 2400,  # 40 min max
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
        for s in result["stints"]:
            assert s["planned_duration_s"] <= 2400

    def test_driver_max_stint_respected(self):
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": 1800,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            {"id": 2, "driver_name": "B", "driver_order": 2, "weight_kg": 80,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
        for s in result["stints"]:
            if s["driver_id"] == 1:
                assert s["planned_duration_s"] <= 1800

    def test_infeasible_returns_false(self):
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 2,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
        }
        # Both drivers max 1000s each = 2000s, race needs 7140s drive time
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": 1000,
             "min_cumulative_s": None, "max_cumulative_s": 1000, "min_rest_s": 0},
            {"id": 2, "driver_name": "B", "driver_order": 2, "weight_kg": 80,
             "min_stint_s": None, "max_stint_s": 1000,
             "min_cumulative_s": None, "max_cumulative_s": 1000, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is False
        assert len(result["violations"]) > 0

    def test_round_robin_driver_assignment(self):
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 4,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            {"id": 2, "driver_name": "B", "driver_order": 2, "weight_kg": 80,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        driver_ids = [s["driver_id"] for s in result["stints"]]
        assert driver_ids == [1, 2, 1, 2]


class TestBallastCalculator:
    """Ballast calculation per stint."""

    def test_basic_ballast(self):
        from race_strategy_v2 import compute_ballast
        result = compute_ballast(
            min_total_kart_kg=165.0,
            empty_kart_kg=80.0,
            fuel_kg=12.0,
            driver_weight_kg=70.0,
        )
        assert result == pytest.approx(3.0)

    def test_no_ballast_needed(self):
        from race_strategy_v2 import compute_ballast
        result = compute_ballast(
            min_total_kart_kg=150.0,
            empty_kart_kg=80.0,
            fuel_kg=12.0,
            driver_weight_kg=70.0,
        )
        assert result == pytest.approx(0.0)  # 162 > 150, no ballast needed (but 0 minimum)

    def test_ballast_clamps_to_zero(self):
        from race_strategy_v2 import compute_ballast
        result = compute_ballast(
            min_total_kart_kg=100.0,
            empty_kart_kg=80.0,
            fuel_kg=12.0,
            driver_weight_kg=70.0,
        )
        assert result == 0.0  # Already over minimum
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestOptimizer -v`
Expected: FAIL — module not found

**Step 3: Implement the optimizer**

Create `telemetry_tool/race_strategy_v2.py`:

```python
"""
race_strategy_v2.py
-------------------
Endurance race strategy optimizer: constraint-bounded stint allocation
with ballast and fuel calculations.

Public API
~~~~~~~~~~
``optimize_stints(config, drivers)``
    Generate optimal stint plan satisfying all constraints.
``compute_ballast(min_total_kart_kg, empty_kart_kg, fuel_kg, driver_weight_kg)``
    Calculate required ballast weight.
``reoptimize_remaining(config, drivers, completed_stints, elapsed_s)``
    Mid-race re-optimization with completed stints fixed.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_ballast(
    min_total_kart_kg: float,
    empty_kart_kg: float,
    fuel_kg: float,
    driver_weight_kg: float,
) -> float:
    """Calculate required ballast to meet minimum kart weight."""
    current = empty_kart_kg + fuel_kg + driver_weight_kg
    needed = min_total_kart_kg - current
    return max(0.0, round(needed, 2))


def optimize_stints(
    config: dict[str, Any],
    drivers: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Generate optimal stint plan using constraint-bounded equal distribution.

    Parameters
    ----------
    config : dict
        race_duration_s, desired_stints, min_pit_stop_s, fuel_autonomy_s,
        empty_kart_kg, full_tank_kg, min_total_kart_kg (all optional except duration/stints)
    drivers : list[dict]
        Each with: id, driver_name, driver_order, weight_kg,
        min_stint_s, max_stint_s, min_cumulative_s, max_cumulative_s, min_rest_s

    Returns
    -------
    dict with feasible, stints, pit_stops, driver_summary, violations, warnings
    """
    race_duration = config["race_duration_s"]
    n_stints = max(1, config.get("desired_stints") or 1)
    pit_time = config.get("min_pit_stop_s") or 60
    fuel_autonomy = config.get("fuel_autonomy_s")

    if not drivers:
        return {"feasible": False, "stints": [], "pit_stops": [],
                "driver_summary": {}, "violations": ["No drivers configured"],
                "warnings": [], "total_pit_time_s": 0, "total_drive_time_s": 0}

    # Sort drivers by order
    drivers = sorted(drivers, key=lambda d: d.get("driver_order", 0))

    # Effective drive time (subtract pit stops)
    n_pits = n_stints - 1
    total_pit_time = n_pits * pit_time
    drive_time = race_duration - total_pit_time

    if drive_time <= 0:
        return {"feasible": False, "stints": [], "pit_stops": [],
                "driver_summary": {}, "violations": ["Pit stops exceed race duration"],
                "warnings": [], "total_pit_time_s": total_pit_time, "total_drive_time_s": 0}

    # Ideal equal stint length
    ideal_stint = drive_time / n_stints

    # Cap by fuel autonomy
    max_any_stint = fuel_autonomy if fuel_autonomy else ideal_stint * 3

    # Assign drivers round-robin
    stints = []
    cumulative = {}  # driver_id -> total seconds assigned
    last_end = {}    # driver_id -> end time of their last stint

    violations = []
    warnings = []
    clock = 0  # seconds from race start

    for i in range(n_stints):
        driver = drivers[i % len(drivers)]
        did = driver["id"]

        # Calculate stint duration
        duration = ideal_stint

        # Apply driver max stint
        d_max = driver.get("max_stint_s")
        if d_max and duration > d_max:
            duration = d_max

        # Apply driver min stint
        d_min = driver.get("min_stint_s")
        if d_min and duration < d_min:
            duration = d_min

        # Apply fuel autonomy
        if fuel_autonomy and duration > fuel_autonomy:
            duration = fuel_autonomy

        # Check driver cumulative max
        d_cum_max = driver.get("max_cumulative_s")
        so_far = cumulative.get(did, 0)
        if d_cum_max and so_far + duration > d_cum_max:
            duration = max(0, d_cum_max - so_far)

        # Check rest time
        d_rest = driver.get("min_rest_s") or 0
        if did in last_end and d_rest > 0:
            rest_available = clock - last_end[did]
            if rest_available < d_rest:
                warnings.append(
                    f"{driver['driver_name']} has only {rest_available}s rest "
                    f"(needs {d_rest}s) before stint {i + 1}"
                )

        duration = round(duration)

        stints.append({
            "stint_order": i + 1,
            "driver_id": did,
            "driver_name": driver["driver_name"],
            "planned_start_s": round(clock),
            "planned_end_s": round(clock + duration),
            "planned_duration_s": duration,
            "ballast_kg": _compute_stint_ballast(config, driver, i == 0),
        })

        cumulative[did] = cumulative.get(did, 0) + duration
        last_end[did] = clock + duration
        clock += duration

        # Add pit stop time (except after last stint)
        if i < n_stints - 1:
            clock += pit_time

    # Redistribute slack if total drive time doesn't match
    total_assigned = sum(s["planned_duration_s"] for s in stints)
    slack = drive_time - total_assigned

    if slack > 0 and stints:
        # Distribute slack to stints that can accept more time
        per_stint_extra = slack / len(stints)
        clock = 0
        for i, s in enumerate(stints):
            extra = per_stint_extra
            did = s["driver_id"]
            driver = next(d for d in drivers if d["id"] == did)

            d_max = driver.get("max_stint_s")
            if d_max and s["planned_duration_s"] + extra > d_max:
                extra = max(0, d_max - s["planned_duration_s"])

            if fuel_autonomy and s["planned_duration_s"] + extra > fuel_autonomy:
                extra = max(0, fuel_autonomy - s["planned_duration_s"])

            s["planned_duration_s"] = round(s["planned_duration_s"] + extra)
            s["planned_start_s"] = round(clock)
            s["planned_end_s"] = round(clock + s["planned_duration_s"])
            clock += s["planned_duration_s"]
            if i < n_stints - 1:
                clock += pit_time

        # Update cumulative after redistribution
        cumulative = {}
        for s in stints:
            cumulative[s["driver_id"]] = cumulative.get(s["driver_id"], 0) + s["planned_duration_s"]

    # Check feasibility: total assigned drive time
    total_assigned = sum(s["planned_duration_s"] for s in stints)
    if total_assigned + total_pit_time < race_duration * 0.95:
        violations.append(
            f"Cannot fill race: {total_assigned}s drive + {total_pit_time}s pit = "
            f"{total_assigned + total_pit_time}s vs {race_duration}s race"
        )

    # Check cumulative minimums
    for driver in drivers:
        did = driver["id"]
        d_cum_min = driver.get("min_cumulative_s")
        actual = cumulative.get(did, 0)
        if d_cum_min and actual < d_cum_min:
            violations.append(
                f"{driver['driver_name']} cumulative {actual}s < minimum {d_cum_min}s"
            )

    # Build pit stops
    pit_stops = []
    for i in range(len(stints) - 1):
        pit_stops.append({
            "after_stint": i + 1,
            "at_s": stints[i]["planned_end_s"],
            "duration_s": pit_time,
            "driver_change": stints[i]["driver_id"] != stints[i + 1]["driver_id"],
            "refuel": True,
        })

    # Build driver summary
    driver_summary = {}
    for driver in drivers:
        did = driver["id"]
        d_stints = [s for s in stints if s["driver_id"] == did]
        driver_summary[driver["driver_name"]] = {
            "total_drive_s": cumulative.get(did, 0),
            "stints": len(d_stints),
        }

    return {
        "feasible": len(violations) == 0,
        "stints": stints,
        "pit_stops": pit_stops,
        "driver_summary": driver_summary,
        "violations": violations,
        "warnings": warnings,
        "total_pit_time_s": total_pit_time,
        "total_drive_time_s": total_assigned,
    }


def reoptimize_remaining(
    config: dict[str, Any],
    drivers: list[dict[str, Any]],
    completed_stints: list[dict[str, Any]],
    elapsed_s: int,
) -> dict[str, Any]:
    """Re-optimize remaining stints given completed work."""
    remaining_time = config["race_duration_s"] - elapsed_s

    # Compute remaining cumulative budgets
    cumulative_used = {}
    for s in completed_stints:
        did = s["driver_id"]
        cumulative_used[did] = cumulative_used.get(did, 0) + s.get("actual_duration_s", 0)

    adjusted_drivers = []
    for d in drivers:
        adj = dict(d)
        used = cumulative_used.get(d["id"], 0)
        if adj.get("max_cumulative_s"):
            adj["max_cumulative_s"] = max(0, adj["max_cumulative_s"] - used)
        if adj.get("min_cumulative_s"):
            adj["min_cumulative_s"] = max(0, adj["min_cumulative_s"] - used)
        adjusted_drivers.append(adj)

    remaining_stints = max(1, config.get("desired_stints", 4) - len(completed_stints))

    remaining_config = {
        **config,
        "race_duration_s": remaining_time,
        "desired_stints": remaining_stints,
    }

    result = optimize_stints(remaining_config, adjusted_drivers)

    # Offset times by elapsed
    for s in result["stints"]:
        s["planned_start_s"] += elapsed_s
        s["planned_end_s"] += elapsed_s
        s["stint_order"] += len(completed_stints)
    for p in result["pit_stops"]:
        p["at_s"] += elapsed_s
        p["after_stint"] += len(completed_stints)

    return result


def _compute_stint_ballast(
    config: dict[str, Any],
    driver: dict[str, Any],
    is_first: bool,
) -> float:
    """Compute ballast for a stint based on config and driver weight."""
    min_kart = config.get("min_total_kart_kg")
    empty = config.get("empty_kart_kg")
    full_tank = config.get("full_tank_kg")
    driver_weight = driver.get("weight_kg")

    if not all([min_kart, empty, driver_weight]):
        return 0.0

    fuel_kg = (full_tank or 0) - (empty or 0) if full_tank else 0
    fuel_kg = max(0, fuel_kg)

    return compute_ballast(min_kart, empty, fuel_kg, driver_weight)
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py -v`
Expected: ALL PASSED (schema + optimizer + ballast)

**Step 5: Commit**

```bash
git add telemetry_tool/race_strategy_v2.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(race-strategy): add constraint-bounded stint optimizer and ballast calculator"
```

---

### Task 3: Blueprint + Navigation + Index Page

**Files:**
- Create: `telemetry_tool/web/routes/race_strategy_v2.py`
- Create: `telemetry_tool/web/templates/race_strategy/index.html`
- Modify: `telemetry_tool/web/app.py:116` (add blueprint)
- Modify: `telemetry_tool/web/templates/base.html:135-136` (add nav link)

**Step 1: Create the blueprint with index route**

Create `telemetry_tool/web/routes/race_strategy_v2.py`:

```python
"""Endurance race strategy blueprint — config, live dashboard, summary."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from web.db import get_db_connection

logger = logging.getLogger(__name__)

bp = Blueprint(
    "race_strategy_v2",
    __name__,
    url_prefix="/race-strategy",
)


def _row_to_dict(row) -> dict:
    """Convert sqlite3.Row to dict."""
    if row is None:
        return {}
    return dict(row)


def _rows_to_list(rows) -> list[dict]:
    """Convert list of sqlite3.Row to list of dict."""
    return [dict(r) for r in rows]


@bp.route("/")
def index():
    """List all saved races, with any live race promoted to hero card."""
    conn = get_db_connection()
    races = _rows_to_list(conn.execute(
        "SELECT * FROM race_configs ORDER BY "
        "CASE status WHEN 'live' THEN 0 ELSE 1 END, created_at DESC"
    ).fetchall())

    live_race = None
    for r in races:
        if r["status"] == "live":
            live_race = r
            break

    return render_template(
        "race_strategy/index.html",
        races=races,
        live_race=live_race,
    )
```

**Step 2: Create the index template**

Create `telemetry_tool/web/templates/race_strategy/index.html`:

```html
{% extends "base.html" %}

{% block title %}Race Strategy — Telemetry{% endblock %}

{% block head_extra %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/race_strategy.css') }}">
{% endblock %}

{% block content %}
<div class="page-header">
    <div>
        <h1>Race Strategy</h1>
        <p>Plan and manage endurance races with stint optimization, live timing, and driver management.</p>
    </div>
    <a href="{{ url_for('race_strategy_v2.new_race') }}" class="btn btn-primary">+ New Race</a>
</div>

{% if live_race %}
<section class="rs-live-hero section">
    <div class="rs-live-badge">LIVE</div>
    <div class="rs-live-info">
        <h2>{{ live_race.race_name }}</h2>
        <div class="rs-live-meta">
            {% if live_race.team_name %}{{ live_race.team_name }} · {% endif %}
            {{ (live_race.race_duration_s // 3600) }}h{{ '%02d' | format((live_race.race_duration_s % 3600) // 60) }} race
        </div>
    </div>
    <a href="{{ url_for('race_strategy_v2.live', race_id=live_race.race_id) }}" class="btn btn-primary">Open Live</a>
</section>
{% endif %}

<section class="section">
    <h2>Saved Races</h2>
    {% if races %}
    <div class="table-wrap">
        <table class="data-table striped">
            <thead>
                <tr>
                    <th>Race</th>
                    <th>Track</th>
                    <th>Team</th>
                    <th>Duration</th>
                    <th>Stints</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
                {% for r in races %}
                <tr class="clickable-row" data-href="{{ url_for('race_strategy_v2.detail', race_id=r.race_id) }}">
                    <td><strong>{{ r.race_name }}</strong></td>
                    <td>{{ r.track_name or '—' }}</td>
                    <td>{{ r.team_name or '—' }}</td>
                    <td>{{ '%d:%02d' | format(r.race_duration_s // 3600, (r.race_duration_s % 3600) // 60) }}</td>
                    <td>{{ r.desired_stints }}</td>
                    <td>
                        <span class="rs-status rs-status-{{ r.status }}">{{ r.status }}</span>
                    </td>
                    <td>{{ r.created_at[:10] if r.created_at else '—' }}</td>
                    <td>
                        <form method="POST" action="{{ url_for('race_strategy_v2.duplicate', race_id=r.race_id) }}"
                              style="display:inline;" onsubmit="event.stopPropagation();">
                            <button type="submit" class="btn btn-ghost" title="Duplicate">&#x2398;</button>
                        </form>
                        <form method="POST" action="{{ url_for('race_strategy_v2.delete', race_id=r.race_id) }}"
                              style="display:inline;" onsubmit="event.stopPropagation(); return confirm('Delete this race?');">
                            <button type="submit" class="btn btn-danger-text" title="Delete">&times;</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% else %}
    <div class="no-data">
        <div class="no-data-text">No races yet. Create your first race to get started.</div>
    </div>
    {% endif %}
</section>
{% endblock %}
```

**Step 3: Create minimal CSS file**

Create `telemetry_tool/web/static/css/race_strategy.css`:

```css
/* Race Strategy — Endurance race management styles */

/* Status badges */
.rs-status {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.rs-status-draft { background: rgba(150,150,150,0.15); color: var(--text-secondary); }
.rs-status-ready { background: rgba(88,166,255,0.15); color: var(--blue); }
.rs-status-live  { background: rgba(63,185,80,0.15); color: var(--green); animation: rs-pulse 2s infinite; }
.rs-status-finished { background: rgba(150,150,150,0.1); color: var(--text-secondary); }

@keyframes rs-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
}

/* Live hero card on index */
.rs-live-hero {
    display: flex;
    align-items: center;
    gap: 1rem;
    border: 1px solid var(--green);
    border-radius: 8px;
    padding: 1rem 1.5rem;
    margin-bottom: 1.5rem;
}
.rs-live-badge {
    background: var(--green);
    color: #000;
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    font-weight: 700;
    font-size: 0.8rem;
    animation: rs-pulse 2s infinite;
}
.rs-live-info { flex: 1; }
.rs-live-info h2 { margin: 0; font-size: 1.1rem; }
.rs-live-meta { font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.2rem; }
```

**Step 4: Register blueprint in app.py**

In `telemetry_tool/web/app.py`, add to `_blueprint_imports` list (after line 116):

```python
        ('.routes.race_strategy_v2', 'bp', 'race_strategy_v2_bp'),
```

**Step 5: Add nav link in base.html**

In `telemetry_tool/web/templates/base.html`, after the Coaching link (line 135), before the "+ Analyze" CTA (line 137), insert:

```html
            <a href="/race-strategy/"
               class="{% if request.endpoint and request.endpoint.startswith('race_strategy_v2.') %}active{% endif %}"
               {% if request.endpoint and request.endpoint.startswith('race_strategy_v2.') %}aria-current="page"{% endif %}>
                Race Strategy
            </a>
```

**Step 6: Verify the app starts**

Run: `python telemetry_tool/main.py --serve`
Expected: App starts, `/race-strategy/` loads (may be empty table). Kill with Ctrl+C.

**Step 7: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/web/templates/race_strategy/index.html telemetry_tool/web/static/css/race_strategy.css telemetry_tool/web/app.py telemetry_tool/web/templates/base.html
git commit -m "feat(race-strategy): add blueprint, index page, nav link"
```

---

### Task 4: Config Form (New/Edit Race)

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (add new_race, update routes)
- Create: `telemetry_tool/web/templates/race_strategy/config.html`
- Create: `telemetry_tool/web/static/js/race_strategy.js`

**Step 1: Add routes to blueprint**

Append to `telemetry_tool/web/routes/race_strategy_v2.py`:

```python
@bp.route("/new", methods=["GET", "POST"])
def new_race():
    """Create a new race configuration."""
    if request.method == "GET":
        conn = get_db_connection()
        tracks = _rows_to_list(conn.execute("SELECT track_id, track_name FROM tracks ORDER BY track_name").fetchall())
        drivers = _rows_to_list(conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall())
        return render_template("race_strategy/config.html", race=None, tracks=tracks, drivers=drivers)

    # POST: save new race
    conn = get_db_connection()
    cur = conn.execute(
        """INSERT INTO race_configs (
            race_name, track_name, team_name, race_duration_s,
            reference_weight_kg, desired_stints, fuel_autonomy_s,
            min_pit_stop_s, pit_speed_kmh, pit_open_s, pit_close_s,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            request.form.get("race_name", "Untitled Race"),
            request.form.get("track_name") or None,
            request.form.get("team_name") or None,
            _parse_duration(request.form.get("race_duration", "3:00")),
            _parse_float(request.form.get("reference_weight_kg")),
            _parse_int(request.form.get("desired_stints"), 4),
            _parse_duration(request.form.get("fuel_autonomy")) if request.form.get("fuel_autonomy") else None,
            _parse_int(request.form.get("min_pit_stop_s"), 60),
            _parse_float(request.form.get("pit_speed_kmh")),
            _parse_duration(request.form.get("pit_open")) if request.form.get("pit_open") else None,
            _parse_duration(request.form.get("pit_close")) if request.form.get("pit_close") else None,
            _parse_float(request.form.get("empty_kart_kg")),
            _parse_float(request.form.get("full_tank_kg")),
            _parse_float(request.form.get("min_total_kart_kg")),
            1 if request.form.get("weigh_on_pit_exit") else 0,
            _parse_duration(request.form.get("qualifying_duration")) if request.form.get("qualifying_duration") else None,
            1 if request.form.get("refuel_after_quali") else 0,
            1 if request.form.get("mandatory_driver_change") else 0,
            1 if request.form.get("refueling_allowed") else 0,
        ),
    )
    race_id = cur.lastrowid

    # Save drivers
    _save_drivers(conn, race_id, request.form)

    conn.commit()
    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))


@bp.route("/<int:race_id>/update", methods=["POST"])
def update_race(race_id: int):
    """Update existing race configuration."""
    conn = get_db_connection()
    race = conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
    if not race:
        abort(404)
    if race["status"] not in ("draft", "ready"):
        abort(400)

    conn.execute(
        """UPDATE race_configs SET
            race_name=?, track_name=?, team_name=?, race_duration_s=?,
            reference_weight_kg=?, desired_stints=?, fuel_autonomy_s=?,
            min_pit_stop_s=?, pit_speed_kmh=?, pit_open_s=?, pit_close_s=?,
            empty_kart_kg=?, full_tank_kg=?, min_total_kart_kg=?,
            weigh_on_pit_exit=?, qualifying_duration_s=?, refuel_after_quali=?,
            mandatory_driver_change=?, refueling_allowed=?,
            updated_at=datetime('now'), status='draft'
        WHERE race_id=?""",
        (
            request.form.get("race_name", "Untitled Race"),
            request.form.get("track_name") or None,
            request.form.get("team_name") or None,
            _parse_duration(request.form.get("race_duration", "3:00")),
            _parse_float(request.form.get("reference_weight_kg")),
            _parse_int(request.form.get("desired_stints"), 4),
            _parse_duration(request.form.get("fuel_autonomy")) if request.form.get("fuel_autonomy") else None,
            _parse_int(request.form.get("min_pit_stop_s"), 60),
            _parse_float(request.form.get("pit_speed_kmh")),
            _parse_duration(request.form.get("pit_open")) if request.form.get("pit_open") else None,
            _parse_duration(request.form.get("pit_close")) if request.form.get("pit_close") else None,
            _parse_float(request.form.get("empty_kart_kg")),
            _parse_float(request.form.get("full_tank_kg")),
            _parse_float(request.form.get("min_total_kart_kg")),
            1 if request.form.get("weigh_on_pit_exit") else 0,
            _parse_duration(request.form.get("qualifying_duration")) if request.form.get("qualifying_duration") else None,
            1 if request.form.get("refuel_after_quali") else 0,
            1 if request.form.get("mandatory_driver_change") else 0,
            1 if request.form.get("refueling_allowed") else 0,
            race_id,
        ),
    )

    # Clear and re-save drivers
    conn.execute("DELETE FROM race_drivers WHERE race_id = ?", (race_id,))
    _save_drivers(conn, race_id, request.form)

    # Clear planned stints (will need re-optimize)
    conn.execute("DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'", (race_id,))
    conn.execute("DELETE FROM race_pit_stops WHERE race_id = ?", (race_id,))

    conn.commit()
    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))


@bp.route("/<int:race_id>/edit")
def edit_race(race_id: int):
    """Edit an existing race configuration."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)
    race_drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    tracks = _rows_to_list(conn.execute("SELECT track_id, track_name FROM tracks ORDER BY track_name").fetchall())
    drivers = _rows_to_list(conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall())
    return render_template("race_strategy/config.html", race=race, race_drivers=race_drivers,
                           tracks=tracks, drivers=drivers)


@bp.route("/<int:race_id>/duplicate", methods=["POST"])
def duplicate(race_id: int):
    """Duplicate a race configuration."""
    conn = get_db_connection()
    race = conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
    if not race:
        abort(404)
    r = dict(race)
    cur = conn.execute(
        """INSERT INTO race_configs (
            race_name, track_name, team_name, race_duration_s,
            reference_weight_kg, desired_stints, fuel_autonomy_s,
            min_pit_stop_s, pit_speed_kmh, pit_open_s, pit_close_s,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft')""",
        (r["race_name"] + " (copy)", r["track_name"], r["team_name"],
         r["race_duration_s"], r["reference_weight_kg"], r["desired_stints"],
         r["fuel_autonomy_s"], r["min_pit_stop_s"], r["pit_speed_kmh"],
         r["pit_open_s"], r["pit_close_s"], r["empty_kart_kg"],
         r["full_tank_kg"], r["min_total_kart_kg"], r["weigh_on_pit_exit"],
         r["qualifying_duration_s"], r["refuel_after_quali"],
         r["mandatory_driver_change"], r["refueling_allowed"]),
    )
    new_id = cur.lastrowid
    # Copy drivers
    old_drivers = conn.execute("SELECT * FROM race_drivers WHERE race_id = ?", (race_id,)).fetchall()
    for d in old_drivers:
        dd = dict(d)
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, min_stint_s, max_stint_s, "
            "min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg) VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id, dd["driver_name"], dd["driver_order"], dd["min_stint_s"],
             dd["max_stint_s"], dd["min_cumulative_s"], dd["max_cumulative_s"],
             dd["min_rest_s"], dd["weight_kg"]),
        )
    conn.commit()
    return redirect(url_for("race_strategy_v2.detail", race_id=new_id))


@bp.route("/<int:race_id>/delete", methods=["POST"])
def delete(race_id: int):
    """Delete a race configuration."""
    conn = get_db_connection()
    conn.execute("DELETE FROM race_configs WHERE race_id = ?", (race_id,))
    conn.commit()
    return redirect(url_for("race_strategy_v2.index"))


# ── Helpers ──────────────────────────────────────

def _parse_duration(val: str | None) -> int:
    """Parse 'H:MM' or 'MM:SS' or 'MM' duration string to seconds."""
    if not val:
        return 0
    val = val.strip()
    parts = val.split(":")
    try:
        if len(parts) == 2:
            a, b = int(parts[0]), int(parts[1])
            # If first part >= 60, treat as H:MM; otherwise MM:SS
            if a >= 60:
                return a * 3600 + b * 60  # not likely but handle
            # Heuristic: if user typed into a race-duration field, it's H:MM
            # We'll let the template specify the format
            return a * 3600 + b * 60  # Default: H:MM for race duration
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            return int(float(val) * 60)  # Plain number = minutes
    except (ValueError, TypeError):
        return 0


def _parse_duration_mmss(val: str | None) -> int | None:
    """Parse 'MM:SS' to seconds."""
    if not val or not val.strip():
        return None
    parts = val.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(val)
    except (ValueError, TypeError):
        return None


def _parse_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_int(val: str | None, default: int = 0) -> int:
    if not val:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _save_drivers(conn, race_id: int, form):
    """Save drivers from form data. Expects driver_name_N, driver_order_N, etc."""
    i = 0
    while True:
        name = form.get(f"driver_name_{i}")
        if name is None:
            break
        if not name.strip():
            i += 1
            continue
        conn.execute(
            """INSERT INTO race_drivers (
                race_id, driver_name, driver_order, min_stint_s, max_stint_s,
                min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                race_id,
                name.strip(),
                _parse_int(form.get(f"driver_order_{i}"), i + 1),
                _parse_duration_mmss(form.get(f"driver_min_stint_{i}")),
                _parse_duration_mmss(form.get(f"driver_max_stint_{i}")),
                _parse_duration_mmss(form.get(f"driver_min_cumulative_{i}")),
                _parse_duration_mmss(form.get(f"driver_max_cumulative_{i}")),
                _parse_duration_mmss(form.get(f"driver_min_rest_{i}")) or 0,
                _parse_float(form.get(f"driver_weight_{i}")),
            ),
        )
        i += 1
```

**Step 2: Create config template**

Create `telemetry_tool/web/templates/race_strategy/config.html` — this is a long template with collapsible sections for Race, Drivers, Pits, Fuel/Ballast, and Qualifying. The template uses the existing form classes (`.form-group`, `.form-section`, `.btn`, etc.) and includes dynamic driver rows managed by `race_strategy.js`.

**Step 3: Create the JS for dynamic driver rows**

Create `telemetry_tool/web/static/js/race_strategy.js` — handles adding/removing driver rows dynamically on the config form page.

**Step 4: Verify app starts and form renders**

Run: `python telemetry_tool/main.py --serve`, visit `/race-strategy/new`
Expected: Config form renders with all sections

**Step 5: Test form submission**

Create a race via the form, verify redirect to detail page (will 404 until Task 5)

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/web/templates/race_strategy/config.html telemetry_tool/web/static/js/race_strategy.js
git commit -m "feat(race-strategy): add config form with dynamic driver rows, CRUD routes"
```

---

### Task 5: Detail Page + Optimizer Integration

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (add detail, optimize routes)
- Create: `telemetry_tool/web/templates/race_strategy/detail.html`
- Create: `telemetry_tool/web/static/js/race_strategy_optimizer.js`

**Step 1: Add detail and optimize routes**

Append to blueprint:

```python
@bp.route("/<int:race_id>")
def detail(race_id: int):
    """Race detail: review config, optimize, and go-live."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)
    race_drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name FROM race_stints s "
        "JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = ? ORDER BY s.stint_order", (race_id,)
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY planned_at_s", (race_id,)
    ).fetchall())

    return render_template("race_strategy/detail.html",
                           race=race, drivers=race_drivers,
                           stints=stints, pit_stops=pit_stops)


@bp.route("/<int:race_id>/optimize", methods=["POST"])
def optimize(race_id: int):
    """Run optimizer and save planned stints."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_strategy_v2 import optimize_stints

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())

    result = optimize_stints(race, drivers)

    # Clear existing planned stints
    conn.execute("DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'", (race_id,))
    conn.execute("DELETE FROM race_pit_stops WHERE race_id = ?", (race_id,))

    # Save new stints
    for s in result["stints"]:
        conn.execute(
            """INSERT INTO race_stints (race_id, stint_order, driver_id,
                planned_start_s, planned_end_s, planned_duration_s, ballast_kg, status)
            VALUES (?,?,?,?,?,?,?,'planned')""",
            (race_id, s["stint_order"], s["driver_id"],
             s["planned_start_s"], s["planned_end_s"],
             s["planned_duration_s"], s.get("ballast_kg", 0)),
        )

    # Save pit stops
    for p in result["pit_stops"]:
        conn.execute(
            """INSERT INTO race_pit_stops (race_id, planned_at_s, duration_s,
                driver_change, refueled)
            VALUES (?,?,?,?,?)""",
            (race_id, p["at_s"], p["duration_s"],
             1 if p["driver_change"] else 0, 1 if p["refuel"] else 0),
        )

    # Update status to ready if feasible
    new_status = "ready" if result["feasible"] else "draft"
    conn.execute("UPDATE race_configs SET status = ?, updated_at = datetime('now') WHERE race_id = ?",
                 (new_status, race_id))
    conn.commit()

    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))
```

**Step 2: Create detail template**

Create `telemetry_tool/web/templates/race_strategy/detail.html` — shows config summary card, stint timeline (horizontal bars per driver), driver summary table, constraint validation, and action buttons (Edit Config, Optimize, Go Live).

**Step 3: Create optimizer visualization JS**

Create `telemetry_tool/web/static/js/race_strategy_optimizer.js` — renders the horizontal stint timeline on a canvas, color-coded per driver.

**Step 4: Test the full flow**

Visit `/race-strategy/new`, create a race with 2 drivers, save, click Optimize, verify stints appear.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/web/templates/race_strategy/detail.html telemetry_tool/web/static/js/race_strategy_optimizer.js
git commit -m "feat(race-strategy): add detail page with optimizer integration and stint timeline"
```

---

### Task 6: Go-Live + Live Dashboard

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (add go-live, live, finish, API routes)
- Create: `telemetry_tool/web/templates/race_strategy/live.html`
- Create: `telemetry_tool/web/static/js/race_strategy_live.js`

**Step 1: Add live management routes**

Append to blueprint:

```python
@bp.route("/<int:race_id>/go-live", methods=["POST"])
def go_live(race_id: int):
    """Start the race — set status to live and record start timestamp."""
    conn = get_db_connection()
    race = conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
    if not race or race["status"] not in ("ready", "draft"):
        abort(400)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "UPDATE race_configs SET status = 'live', race_start_ts = ?, updated_at = datetime('now') WHERE race_id = ?",
        (now, race_id),
    )

    # Set first stint to active
    first_stint = conn.execute(
        "SELECT stint_id FROM race_stints WHERE race_id = ? AND status = 'planned' ORDER BY stint_order LIMIT 1",
        (race_id,),
    ).fetchone()
    if first_stint:
        conn.execute("UPDATE race_stints SET status = 'active', actual_start_s = 0 WHERE stint_id = ?",
                      (first_stint["stint_id"],))

    conn.commit()
    return redirect(url_for("race_strategy_v2.live", race_id=race_id))


@bp.route("/<int:race_id>/live")
def live(race_id: int):
    """Live dashboard page."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)
    return render_template("race_strategy/live.html", race=race)


@bp.route("/<int:race_id>/finish", methods=["POST"])
def finish(race_id: int):
    """End the race."""
    conn = get_db_connection()
    # Mark any active stint as completed
    conn.execute(
        "UPDATE race_stints SET status = 'completed' WHERE race_id = ? AND status = 'active'",
        (race_id,),
    )
    conn.execute(
        "UPDATE race_configs SET status = 'finished', updated_at = datetime('now') WHERE race_id = ?",
        (race_id,),
    )
    conn.commit()
    return redirect(url_for("race_strategy_v2.summary", race_id=race_id))


# ── API Routes (JSON, for live dashboard polling) ──

@bp.route("/<int:race_id>/api/state")
def api_state(race_id: int):
    """Full race state for live dashboard polling."""
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

    active_stint = next((s for s in stints if s["status"] == "active"), None)
    next_stint = next((s for s in stints if s["status"] == "planned"), None)

    # Driver cumulative times
    driver_cumulative = {}
    for s in stints:
        if s["status"] == "completed":
            did = s["driver_id"]
            dur = s.get("actual_duration_s") or s.get("planned_duration_s") or 0
            driver_cumulative[did] = driver_cumulative.get(did, 0) + dur

    return jsonify({
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "active_stint": active_stint,
        "next_stint": next_stint,
        "driver_cumulative": driver_cumulative,
    })


@bp.route("/<int:race_id>/api/stint/end", methods=["POST"])
def api_stint_end(race_id: int):
    """End the current active stint."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())

    active = conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? AND status = 'active'", (race_id,)
    ).fetchone()
    if not active:
        return jsonify({"error": "no active stint"}), 400

    # Compute elapsed since race start
    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    actual_duration = elapsed - (active["actual_start_s"] or 0)

    conn.execute(
        "UPDATE race_stints SET status = 'completed', actual_end_s = ?, actual_duration_s = ? WHERE stint_id = ?",
        (elapsed, actual_duration, active["stint_id"]),
    )

    # Log pit stop
    data = request.get_json(silent=True) or {}
    conn.execute(
        """INSERT INTO race_pit_stops (race_id, stint_id, actual_at_s, driver_change, refueled, notes)
        VALUES (?,?,?,?,?,?)""",
        (race_id, active["stint_id"], elapsed,
         1 if data.get("driver_change", True) else 0,
         1 if data.get("refueled", False) else 0,
         data.get("notes")),
    )

    # Start next stint
    next_stint = conn.execute(
        "SELECT stint_id FROM race_stints WHERE race_id = ? AND status = 'planned' ORDER BY stint_order LIMIT 1",
        (race_id,),
    ).fetchone()
    if next_stint:
        conn.execute(
            "UPDATE race_stints SET status = 'active', actual_start_s = ? WHERE stint_id = ?",
            (elapsed, next_stint["stint_id"]),
        )

    conn.commit()
    return jsonify({"ok": True, "elapsed_s": elapsed})


@bp.route("/<int:race_id>/api/stint/note", methods=["POST"])
def api_stint_note(race_id: int):
    """Update notes on a stint."""
    data = request.get_json(silent=True) or {}
    stint_id = data.get("stint_id")
    notes = data.get("notes", "")
    conn = get_db_connection()
    conn.execute("UPDATE race_stints SET notes = ? WHERE stint_id = ? AND race_id = ?",
                 (notes, stint_id, race_id))
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/<int:race_id>/api/reoptimize", methods=["POST"])
def api_reoptimize(race_id: int):
    """Re-optimize remaining stints mid-race."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_strategy_v2 import reoptimize_remaining

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

    # Replace planned stints
    conn.execute("DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'", (race_id,))
    for s in result["stints"]:
        conn.execute(
            """INSERT INTO race_stints (race_id, stint_order, driver_id,
                planned_start_s, planned_end_s, planned_duration_s, ballast_kg, status)
            VALUES (?,?,?,?,?,?,?,'planned')""",
            (race_id, s["stint_order"], s["driver_id"],
             s["planned_start_s"], s["planned_end_s"],
             s["planned_duration_s"], s.get("ballast_kg", 0)),
        )
    conn.commit()

    return jsonify({"ok": True, "result": result})


def _compute_elapsed_s(race_start_ts: str | None) -> int:
    """Compute seconds elapsed since race start."""
    if not race_start_ts:
        return 0
    from datetime import datetime, timezone
    try:
        start = datetime.fromisoformat(race_start_ts)
        now = datetime.now(timezone.utc)
        return max(0, int((now - start).total_seconds()))
    except (ValueError, TypeError):
        return 0
```

**Step 2: Create live dashboard template**

Create `telemetry_tool/web/templates/race_strategy/live.html` — single-page layout with the 6-component grid. Loads `race_strategy_live.js`.

**Step 3: Create live dashboard JS**

Create `telemetry_tool/web/static/js/race_strategy_live.js` — client-side timer, 2-second polling loop, renders all 6 components, "End Stint" and "Reoptimize" button handlers.

**Step 4: Test live flow end-to-end**

Create race → add drivers → optimize → go live → verify timer ticks → end stint → verify stint log updates → finish race.

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/web/templates/race_strategy/live.html telemetry_tool/web/static/js/race_strategy_live.js
git commit -m "feat(race-strategy): add live dashboard with 6 components, polling, stint management API"
```

---

### Task 7: Post-Race Summary

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (add summary route)
- Create: `telemetry_tool/web/templates/race_strategy/summary.html`

**Step 1: Add summary route**

```python
@bp.route("/<int:race_id>/summary")
def summary(race_id: int):
    """Post-race summary — read-only view of completed race."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)
    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name FROM race_stints s "
        "JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = ? ORDER BY s.stint_order", (race_id,)
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY actual_at_s", (race_id,)
    ).fetchall())

    # Compute per-driver stats
    driver_stats = {}
    for d in drivers:
        d_stints = [s for s in stints if s["driver_id"] == d["id"]]
        total_time = sum(s.get("actual_duration_s") or s.get("planned_duration_s") or 0 for s in d_stints)
        durations = [s.get("actual_duration_s") or s.get("planned_duration_s") or 0 for s in d_stints]
        driver_stats[d["id"]] = {
            "name": d["driver_name"],
            "total_drive_s": total_time,
            "n_stints": len(d_stints),
            "longest_stint_s": max(durations) if durations else 0,
            "shortest_stint_s": min(durations) if durations else 0,
        }

    total_actual_drive = sum(s.get("actual_duration_s") or s.get("planned_duration_s") or 0 for s in stints)
    total_pit = sum(p.get("duration_s") or 0 for p in pit_stops)

    return render_template("race_strategy/summary.html",
                           race=race, drivers=drivers, stints=stints,
                           pit_stops=pit_stops, driver_stats=driver_stats,
                           total_drive_s=total_actual_drive, total_pit_s=total_pit)
```

**Step 2: Create summary template**

Create `telemetry_tool/web/templates/race_strategy/summary.html` — read-only view with race stats, driver stats table, stint log with planned vs actual deltas, and a horizontal stint timeline.

**Step 3: Add remaining CSS for live + summary pages**

Append to `telemetry_tool/web/static/css/race_strategy.css` — styles for live dashboard grid, timer, fuel bar, stint timeline, driver cards, and summary cards.

**Step 4: Test complete lifecycle**

Create → Config → Optimize → Go Live → End stints → Finish → View Summary

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/web/templates/race_strategy/summary.html telemetry_tool/web/static/css/race_strategy.css
git commit -m "feat(race-strategy): add post-race summary page, complete lifecycle"
```

---

### Task 8: Integration Tests

**Files:**
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py` (add integration tests)

**Step 1: Add route integration tests**

```python
class TestRaceStrategyRoutes:
    """Integration tests for the race strategy blueprint."""

    def test_create_and_list(self, strategy_db):
        """Create a race and verify it appears in the index."""
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('Test 3h', 10800)"
        )
        strategy_db.commit()
        rows = strategy_db.execute("SELECT * FROM race_configs").fetchall()
        assert len(rows) == 1
        assert rows[0]["race_name"] == "Test 3h"

    def test_optimize_and_go_live_flow(self, strategy_db):
        """Full flow: create race, add drivers, optimize, go live."""
        from race_strategy_v2 import optimize_stints

        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, desired_stints, min_pit_stop_s) "
            "VALUES ('Race', 7200, 4, 60)"
        )
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'A', 1, 70)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'B', 2, 80)")
        strategy_db.commit()

        race = dict(strategy_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        drivers = [dict(r) for r in strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order").fetchall()]

        result = optimize_stints(race, drivers)
        assert result["feasible"] is True
        assert len(result["stints"]) == 4

        # Save stints
        for s in result["stints"]:
            strategy_db.execute(
                "INSERT INTO race_stints (race_id, stint_order, driver_id, planned_start_s, planned_end_s, planned_duration_s, status) "
                "VALUES (?,?,?,?,?,?,'planned')",
                (1, s["stint_order"], s["driver_id"], s["planned_start_s"], s["planned_end_s"], s["planned_duration_s"]),
            )
        strategy_db.commit()

        stints = strategy_db.execute("SELECT * FROM race_stints WHERE race_id = 1").fetchall()
        assert len(stints) == 4

    def test_duplicate_race(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('Original', 7200)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
        strategy_db.commit()

        # Simulate duplicate
        race = dict(strategy_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        cur = strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES (?, ?)",
            (race["race_name"] + " (copy)", race["race_duration_s"]),
        )
        new_id = cur.lastrowid
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (?, 'A', 1)", (new_id,)
        )
        strategy_db.commit()

        races = strategy_db.execute("SELECT * FROM race_configs").fetchall()
        assert len(races) == 2
        assert races[1]["race_name"] == "Original (copy)"

    def test_cascade_delete(self, strategy_db):
        """Deleting a race cascades to drivers, stints, pit stops."""
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order) VALUES (1, 'A', 1)")
        strategy_db.execute("INSERT INTO race_stints (race_id, stint_order, driver_id, status) VALUES (1, 1, 1, 'planned')")
        strategy_db.execute("INSERT INTO race_pit_stops (race_id, driver_change, refueled) VALUES (1, 1, 0)")
        strategy_db.commit()

        # Enable FK enforcement for cascade test
        strategy_db.execute("PRAGMA foreign_keys = ON")
        strategy_db.execute("DELETE FROM race_configs WHERE race_id = 1")
        strategy_db.commit()

        assert strategy_db.execute("SELECT COUNT(*) FROM race_drivers").fetchone()[0] == 0
        assert strategy_db.execute("SELECT COUNT(*) FROM race_stints").fetchone()[0] == 0
        assert strategy_db.execute("SELECT COUNT(*) FROM race_pit_stops").fetchone()[0] == 0
```

**Step 2: Run all tests**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py -v`
Expected: ALL PASSED

Run: `pytest telemetry_tool/tests/ -x -q`
Expected: Full suite passes, no regressions

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "test(race-strategy): add integration tests for full race lifecycle"
```
