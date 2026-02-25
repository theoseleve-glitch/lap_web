# Race Strategy Tier 6: Live Race Intelligence — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add safety car neutralization with fuel-burn pause, race intelligence (finish predictor, fuel alerts, pace analysis, swap suggestions), rival tracker with strategy gap analysis, and browser notifications with audio alerts.

**Architecture:** `RaceStateEngine` gains neutralization periods (the only new mutation). A new stateless `race_intelligence.py` decorates engine snapshots with predictions/alerts. Rival tracker uses two new tables + CRUD API. Notifications are 100% client-side JS via the existing 2s polling.

**Tech Stack:** Python 3, Flask, SQLite, vanilla JS, CSS (existing stack — no new dependencies)

---

## Task 1: Schema Migration (v24)

**Files:**
- Modify: `telemetry_tool/db/schema.py:9` (bump SCHEMA_VERSION to 24)
- Modify: `telemetry_tool/db/schema.py:882-885` (add Phase 17 tables, update ALL_TABLES)
- Modify: `telemetry_tool/db/migrate.py:439-444` (add v24 migration block)
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py` (schema version + new table tests)

**Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_race_strategy_v2.py` — new class after `TestWeatherIntegration`:

```python
class TestTier6Schema:
    """Tier 6 schema — neutralizations, rivals, rival events."""

    def test_schema_version_is_24(self, strategy_db):
        row = strategy_db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        assert row["v"] == 24

    def test_race_neutralizations_table_exists(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_neutralizations (race_id, start_s, reason) "
            "VALUES (1, 600, 'safety_car')"
        )
        row = strategy_db.execute("SELECT * FROM race_neutralizations WHERE race_id = 1").fetchone()
        assert row["start_s"] == 600
        assert row["end_s"] is None
        assert row["reason"] == "safety_car"

    def test_race_rivals_table_exists(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_rivals (race_id, team_name, car_number) "
            "VALUES (1, 'Team Alpha', '42')"
        )
        row = strategy_db.execute("SELECT * FROM race_rivals WHERE race_id = 1").fetchone()
        assert row["team_name"] == "Team Alpha"
        assert row["car_number"] == "42"

    def test_race_rival_events_table_exists(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_rivals (race_id, team_name, car_number) VALUES (1, 'X', '1')"
        )
        strategy_db.execute(
            "INSERT INTO race_rival_events (race_id, rival_id, event_type, at_s, detail) "
            "VALUES (1, 1, 'pit_in', 1200, 'quick stop')"
        )
        row = strategy_db.execute("SELECT * FROM race_rival_events WHERE race_id = 1").fetchone()
        assert row["event_type"] == "pit_in"
        assert row["at_s"] == 1200
        assert row["detail"] == "quick stop"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_strategy_v2.py::TestTier6Schema -v`
Expected: FAIL — tables don't exist, version is 23

**Step 3: Add table definitions to schema.py**

In `telemetry_tool/db/schema.py`, after the `PHASE_16_TABLES` block (line 882), add:

```python
# ------------------------------------------------------------------
# Phase 17 tables  (Tier 6: Race Intelligence — neutralizations, rivals)
# ------------------------------------------------------------------

_RACE_NEUTRALIZATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS race_neutralizations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id   INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    start_s   INTEGER NOT NULL,
    end_s     INTEGER,
    reason    TEXT DEFAULT 'safety_car'
);
"""

_RACE_RIVALS_TABLE = """
CREATE TABLE IF NOT EXISTS race_rivals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id    INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    team_name  TEXT NOT NULL,
    car_number TEXT,
    notes      TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_RACE_RIVAL_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS race_rival_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id    INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    rival_id   INTEGER NOT NULL REFERENCES race_rivals(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    at_s       INTEGER NOT NULL,
    detail     TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

PHASE_17_TABLES: list[tuple[str, str]] = [
    ("race_neutralizations", _RACE_NEUTRALIZATIONS_TABLE),
    ("race_rivals", _RACE_RIVALS_TABLE),
    ("race_rival_events", _RACE_RIVAL_EVENTS_TABLE),
]
```

Update `SCHEMA_VERSION` on line 9 from `23` to `24`.

Update `ALL_TABLES` on line 885 to append `+ PHASE_17_TABLES`.

**Step 4: Add v24 migration to migrate.py**

In `telemetry_tool/db/migrate.py`, after the v23 migration block (line 439), before `conn.commit()`:

```python
    # Phase 24 migration: Tier 6 — race intelligence tables.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_neutralizations (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id   INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
            start_s   INTEGER NOT NULL,
            end_s     INTEGER,
            reason    TEXT DEFAULT 'safety_car'
        );
    """)
    logger.debug("Ensured race_neutralizations table exists.")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_rivals (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id    INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
            team_name  TEXT NOT NULL,
            car_number TEXT,
            notes      TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    logger.debug("Ensured race_rivals table exists.")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_rival_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id    INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
            rival_id   INTEGER NOT NULL REFERENCES race_rivals(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            at_s       INTEGER NOT NULL,
            detail     TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    logger.debug("Ensured race_rival_events table exists.")

    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (24, "Phase 24 schema — Tier 6 race intelligence (neutralizations, rivals)"),
    )
```

**Step 5: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_strategy_v2.py::TestTier6Schema -v`
Expected: PASS — all 4 tests green

**Step 6: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/migrate.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(schema): v24 — race_neutralizations, race_rivals, race_rival_events tables"
```

---

## Task 2: Neutralization Engine — Overlap Calculation + Fuel Cascade

**Files:**
- Modify: `telemetry_tool/race_state_engine.py:119-199` (add neutralizations field to __init__)
- Modify: `telemetry_tool/race_state_engine.py:275-299` (update _calc_fuel_state to subtract SC overlap)
- Modify: `telemetry_tool/tests/test_race_state_engine.py` (new TestNeutralization class)

**Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_race_state_engine.py` after `TestWindowPersistence`:

```python
class TestNeutralization:
    """Safety car / neutralization — fuel burn pause during cascade."""

    def test_neutralized_overlap_no_periods(self):
        engine = _make_engine()
        engine.neutralizations = []
        assert engine._neutralized_overlap(0, 2360) == 0.0

    def test_neutralized_overlap_full_overlap(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 500, "end_s": 1000}]
        assert engine._neutralized_overlap(0, 2360) == 500.0

    def test_neutralized_overlap_partial_overlap(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 2000, "end_s": 3000}]
        # stint is 0-2360, overlap is 2000-2360 = 360s
        assert engine._neutralized_overlap(0, 2360) == 360.0

    def test_neutralized_overlap_no_overlap(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 3000, "end_s": 4000}]
        assert engine._neutralized_overlap(0, 2360) == 0.0

    def test_neutralized_overlap_open_period(self):
        """Open SC period (end_s=None) extends to stint end."""
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 1000}]
        # No end_s -> extends to stint_end (2360). Overlap = 2360 - 1000 = 1360
        assert engine._neutralized_overlap(0, 2360) == 1360.0

    def test_neutralized_overlap_multiple_periods(self):
        engine = _make_engine()
        engine.neutralizations = [
            {"start_s": 100, "end_s": 200},
            {"start_s": 500, "end_s": 700},
        ]
        # Both fully within stint 0-2360: 100 + 200 = 300
        assert engine._neutralized_overlap(0, 2360) == 300.0

    def test_fuel_cascade_with_neutralization(self):
        """SC during stint 1 should reduce fuel consumption."""
        engine = _make_engine()
        fuel_no_sc = engine.stints[0].fuel_at_end_kg

        # Add 600s of SC during stint 1 -> saves 600s of fuel
        engine.neutralizations = [{"start_s": 500, "end_s": 1100}]
        engine._cascade_from(1)
        fuel_with_sc = engine.stints[0].fuel_at_end_kg

        # With SC, less fuel consumed -> more fuel at end
        saved = engine.fuel_model.burn_rate_kgs * 600
        assert abs(fuel_with_sc - (fuel_no_sc + saved)) < 0.001

    def test_start_neutralization(self):
        engine = _make_engine()
        engine.neutralizations = []
        engine.start_neutralization(1000.0, "safety_car")
        assert len(engine.neutralizations) == 1
        assert engine.neutralizations[0]["start_s"] == 1000
        assert engine.neutralizations[0].get("end_s") is None
        assert engine.neutralizations[0]["reason"] == "safety_car"

    def test_end_neutralization(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 1000, "reason": "safety_car"}]
        engine.end_neutralization(1500.0)
        assert engine.neutralizations[0]["end_s"] == 1500

    def test_end_neutralization_noop_when_none_open(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 1000, "end_s": 1500, "reason": "safety_car"}]
        engine.end_neutralization(2000.0)
        # Should not modify the already-closed period
        assert engine.neutralizations[0]["end_s"] == 1500

    def test_is_neutralized_true_when_open(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 1000, "reason": "safety_car"}]
        assert engine.is_neutralized is True

    def test_is_neutralized_false_when_all_closed(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 1000, "end_s": 1500, "reason": "safety_car"}]
        assert engine.is_neutralized is False

    def test_snapshot_includes_neutralizations(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 500, "end_s": 800, "reason": "safety_car"}]
        snap = engine.snapshot()
        assert "neutralizations" in snap
        assert "is_neutralized" in snap
        assert snap["is_neutralized"] is False
        assert len(snap["neutralizations"]) == 1
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestNeutralization -v`
Expected: FAIL — `neutralizations` attribute doesn't exist, methods not defined

**Step 3: Implement neutralization in race_state_engine.py**

3a. Add `neutralizations` field to `__init__` (after `self.windows` on line 181):

```python
        # Neutralization periods (populated by load() or externally)
        self.neutralizations: list[dict] = []
```

3b. Add `_neutralized_overlap` helper (after `_is_in_any_window`, around line 258):

```python
    def _neutralized_overlap(self, stint_start_s: int, stint_end_s: int) -> float:
        """Total neutralized seconds within a stint's time range."""
        total = 0.0
        for n in self.neutralizations:
            ns = n["start_s"]
            ne = n.get("end_s") or stint_end_s  # open period extends to stint end
            overlap_start = max(stint_start_s, ns)
            overlap_end = min(stint_end_s, ne)
            if overlap_end > overlap_start:
                total += overlap_end - overlap_start
        return total
```

3c. Modify `_calc_fuel_state` (line 298) to subtract neutralized overlap:

Replace `consumed = fm.burn_rate_kgs * stint.planned_duration_s` with:

```python
        # Subtract neutralized time from burn calculation
        sc_overlap = self._neutralized_overlap(stint.planned_start_s, stint.planned_end_s)
        effective_burn_s = max(0.0, stint.planned_duration_s - sc_overlap)
        consumed = fm.burn_rate_kgs * effective_burn_s
```

3d. Add mutation methods (after `toggle_fuel`, around line 475):

```python
    # -- neutralization API ------------------------------------------------

    def start_neutralization(self, elapsed_s: float, reason: str = "safety_car") -> None:
        """Begin a neutralization period at the given elapsed time."""
        self.neutralizations.append({
            "start_s": int(elapsed_s),
            "reason": reason,
        })
        self._cascade_from(1)

    def end_neutralization(self, elapsed_s: float) -> None:
        """Close the currently open neutralization period."""
        for n in self.neutralizations:
            if n.get("end_s") is None:
                n["end_s"] = int(elapsed_s)
                self._cascade_from(1)
                return

    @property
    def is_neutralized(self) -> bool:
        """True if there is an open (no end_s) neutralization period."""
        return any(n.get("end_s") is None for n in self.neutralizations)
```

3e. Update `snapshot()` (around line 845) to include neutralization data. Add after `"windows": self.windows,`:

```python
            "neutralizations": self.neutralizations,
            "is_neutralized": self.is_neutralized,
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestNeutralization -v`
Expected: PASS — all 13 tests green

**Step 5: Run full engine test suite for regressions**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py -v`
Expected: All existing tests still pass (no regressions in fuel cascade)

**Step 6: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(engine): neutralization periods — fuel burn pause during safety car"
```

---

## Task 3: Neutralization Persistence (Save/Load)

**Files:**
- Modify: `telemetry_tool/race_state_engine.py:600-812` (save/load methods)
- Modify: `telemetry_tool/tests/test_race_state_engine.py` (persistence round-trip tests)

**Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_race_state_engine.py`:

```python
class TestNeutralizationPersistence:

    @pytest.fixture
    def engine_db(self):
        from db.schema import ALL_TABLES
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        for _, ddl in ALL_TABLES:
            conn.executescript(ddl)
        yield conn
        conn.close()

    def _seed_race(self, conn):
        conn.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, fuel_autonomy_s, "
            "empty_kart_kg, full_tank_kg, min_total_kart_kg, min_pit_stop_s) "
            "VALUES ('Test 2h', 7200, 2400, 85, 93, 160, 60)"
        )
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) "
            "VALUES (1, 'Alice', 1, 65)"
        )
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) "
            "VALUES (1, 'Bob', 2, 75)"
        )
        conn.commit()
        return 1

    def test_save_stores_neutralizations(self, engine_db):
        race_id = self._seed_race(engine_db)
        config = dict(engine_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        drivers = [dict(r) for r in engine_db.execute(
            "SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order"
        ).fetchall()]
        raw_stints = [
            {"stint_order": 1, "driver_id": drivers[0]["id"], "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints)
        engine.neutralizations = [
            {"start_s": 500, "end_s": 800, "reason": "safety_car"},
            {"start_s": 2000, "end_s": 2300, "reason": "red_flag"},
        ]
        engine.save(engine_db, race_id)
        rows = engine_db.execute(
            "SELECT * FROM race_neutralizations WHERE race_id = ? ORDER BY start_s", (race_id,)
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["start_s"] == 500
        assert rows[0]["end_s"] == 800
        assert rows[0]["reason"] == "safety_car"
        assert rows[1]["reason"] == "red_flag"

    def test_load_restores_neutralizations(self, engine_db):
        race_id = self._seed_race(engine_db)
        config = dict(engine_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        drivers = [dict(r) for r in engine_db.execute(
            "SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order"
        ).fetchall()]
        raw_stints = [
            {"stint_order": 1, "driver_id": drivers[0]["id"], "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints)
        engine.neutralizations = [
            {"start_s": 500, "end_s": 800, "reason": "safety_car"},
        ]
        engine.save(engine_db, race_id)

        loaded = RaceStateEngine.load(engine_db, race_id)
        assert len(loaded.neutralizations) == 1
        assert loaded.neutralizations[0]["start_s"] == 500
        assert loaded.neutralizations[0]["end_s"] == 800

    def test_load_applies_neutralization_to_fuel(self, engine_db):
        race_id = self._seed_race(engine_db)
        config = dict(engine_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        drivers = [dict(r) for r in engine_db.execute(
            "SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order"
        ).fetchall()]
        raw_stints = [
            {"stint_order": 1, "driver_id": drivers[0]["id"], "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints)
        engine.save(engine_db, race_id)
        loaded_no_sc = RaceStateEngine.load(engine_db, race_id)
        fuel_no_sc = loaded_no_sc.stints[0].fuel_at_end_kg

        # Add SC period to DB directly
        engine_db.execute(
            "INSERT INTO race_neutralizations (race_id, start_s, end_s, reason) "
            "VALUES (?, 500, 1100, 'safety_car')", (race_id,)
        )
        engine_db.commit()

        loaded_sc = RaceStateEngine.load(engine_db, race_id)
        fuel_sc = loaded_sc.stints[0].fuel_at_end_kg
        # 600s of SC -> fuel saved
        assert fuel_sc > fuel_no_sc
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestNeutralizationPersistence -v`
Expected: FAIL — save doesn't write neutralizations, load doesn't read them

**Step 3: Update save() and load() methods**

3a. In the `save()` method, after the existing pit_stops insert loop, add neutralization save (with try/except for backward compat):

```python
        try:
            conn.execute("DELETE FROM race_neutralizations WHERE race_id = ?", (race_id,))
            for n in self.neutralizations:
                conn.execute(
                    "INSERT INTO race_neutralizations (race_id, start_s, end_s, reason) "
                    "VALUES (?, ?, ?, ?)",
                    (race_id, n["start_s"], n.get("end_s"), n.get("reason", "safety_car")),
                )
        except Exception:
            pass  # Pre-v24 databases without race_neutralizations table
```

3b. In the `load()` classmethod, after loading windows (around line 806), before `engine._cascade_from(1)`, add:

```python
        # Load neutralization periods
        try:
            neut_rows = conn.execute(
                "SELECT * FROM race_neutralizations WHERE race_id = ? ORDER BY start_s",
                (race_id,),
            ).fetchall()
            engine.neutralizations = [dict(r) for r in neut_rows]
        except Exception:
            engine.neutralizations = []  # Pre-v24 databases
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestNeutralizationPersistence -v`
Expected: PASS — all 3 tests green

**Step 5: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(engine): neutralization persistence — save/load round-trip"
```

---

## Task 4: Race Intelligence Module — Finish Predictor + Fuel Alerts

**Files:**
- Create: `telemetry_tool/race_intelligence.py`
- Create: `telemetry_tool/tests/test_race_intelligence.py`

**Step 1: Write the failing tests**

Create `telemetry_tool/tests/test_race_intelligence.py`:

```python
"""Tests for the race intelligence module — stateless race analytics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from race_intelligence import predict_finish, fuel_alerts


class TestPredictFinish:

    def test_remaining_time(self):
        result = predict_finish(
            race_duration_s=7200, elapsed_s=3600.0,
            stints=[], race_start_ts=None, neutralizations=[],
        )
        assert result["remaining_s"] == 3600

    def test_completion_pct(self):
        result = predict_finish(
            race_duration_s=7200, elapsed_s=1800.0,
            stints=[], race_start_ts=None, neutralizations=[],
        )
        assert result["completion_pct"] == pytest.approx(25.0, abs=0.1)

    def test_pace_status_on_plan(self):
        stints = [
            {"status": "completed", "actual_duration_s": 2360, "planned_duration_s": 2360},
        ]
        result = predict_finish(
            race_duration_s=7200, elapsed_s=2420.0,
            stints=stints, race_start_ts=None, neutralizations=[],
        )
        assert result["pace_status"] == "ON PLAN"
        assert result["pace_delta_s"] == 0

    def test_pace_status_behind(self):
        stints = [
            {"status": "completed", "actual_duration_s": 2420, "planned_duration_s": 2360},
        ]
        result = predict_finish(
            race_duration_s=7200, elapsed_s=2480.0,
            stints=stints, race_start_ts=None, neutralizations=[],
        )
        assert result["pace_status"] == "BEHIND"
        assert result["pace_delta_s"] == 60

    def test_pace_status_ahead(self):
        stints = [
            {"status": "completed", "actual_duration_s": 2300, "planned_duration_s": 2360},
        ]
        result = predict_finish(
            race_duration_s=7200, elapsed_s=2360.0,
            stints=stints, race_start_ts=None, neutralizations=[],
        )
        assert result["pace_status"] == "AHEAD"
        assert result["pace_delta_s"] == -60

    def test_no_completed_stints_is_on_plan(self):
        result = predict_finish(
            race_duration_s=7200, elapsed_s=100.0,
            stints=[], race_start_ts=None, neutralizations=[],
        )
        assert result["pace_status"] == "ON PLAN"

    def test_neutralized_time_subtracted(self):
        result = predict_finish(
            race_duration_s=7200, elapsed_s=3600.0,
            stints=[], race_start_ts=None,
            neutralizations=[{"start_s": 1000, "end_s": 1600}],
        )
        assert result["neutralized_total_s"] == 600


class TestFuelAlerts:

    def test_fuel_ok(self):
        result = fuel_alerts(
            current_fuel_kg=6.0, burn_rate_kgs=0.003333,
            active_stint_end_s=2360, elapsed_s=500.0,
            next_planned_pit_s=2360,
        )
        assert result["fuel_status"] == "ok"
        assert result["fuel_remaining_s"] > 300

    def test_fuel_warning(self):
        # 0.8 kg at 0.003333 kg/s = ~240s < 300s (5 min)
        result = fuel_alerts(
            current_fuel_kg=0.8, burn_rate_kgs=0.003333,
            active_stint_end_s=2360, elapsed_s=2000.0,
            next_planned_pit_s=2360,
        )
        assert result["fuel_status"] == "warning"

    def test_fuel_critical(self):
        # 0.3 kg at 0.003333 kg/s = ~90s < 120s (2 min)
        result = fuel_alerts(
            current_fuel_kg=0.3, burn_rate_kgs=0.003333,
            active_stint_end_s=2360, elapsed_s=2200.0,
            next_planned_pit_s=2360,
        )
        assert result["fuel_status"] == "critical"

    def test_can_reach_pit_true(self):
        result = fuel_alerts(
            current_fuel_kg=6.0, burn_rate_kgs=0.003333,
            active_stint_end_s=2360, elapsed_s=500.0,
            next_planned_pit_s=2360,
        )
        assert result["can_reach_pit"] is True
        assert result["shortfall_s"] == 0

    def test_can_reach_pit_false(self):
        # Only 0.3kg left, need to last until 2360, currently at 2000 -> 360s needed
        # 0.3 / 0.003333 = ~90s. Shortfall = 360 - 90 = 270s
        result = fuel_alerts(
            current_fuel_kg=0.3, burn_rate_kgs=0.003333,
            active_stint_end_s=2360, elapsed_s=2000.0,
            next_planned_pit_s=2360,
        )
        assert result["can_reach_pit"] is False
        assert result["shortfall_s"] > 0

    def test_zero_burn_rate_safe(self):
        result = fuel_alerts(
            current_fuel_kg=5.0, burn_rate_kgs=0.0,
            active_stint_end_s=2360, elapsed_s=500.0,
            next_planned_pit_s=2360,
        )
        assert result["fuel_status"] == "ok"
        assert result["can_reach_pit"] is True
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_intelligence.py::TestPredictFinish telemetry_tool/tests/test_race_intelligence.py::TestFuelAlerts -v`
Expected: FAIL — module doesn't exist

**Step 3: Implement predict_finish and fuel_alerts**

Create `telemetry_tool/race_intelligence.py`:

```python
"""
race_intelligence.py
--------------------
Stateless race intelligence -- pure functions that take engine state
and return predictions, alerts, and analysis.

All functions are read-only: they never mutate engine state.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Thresholds
_PACE_TOLERANCE_S = 30   # +/-30s = ON PLAN
_FUEL_WARNING_S = 300    # 5 minutes
_FUEL_CRITICAL_S = 120   # 2 minutes


def predict_finish(
    race_duration_s: int,
    elapsed_s: float,
    stints: list[dict],
    race_start_ts: str | None,
    neutralizations: list[dict],
) -> dict[str, Any]:
    """Predict race finish time, pace delta, and completion percentage."""
    remaining = max(0.0, race_duration_s - elapsed_s)
    completion = (elapsed_s / race_duration_s * 100) if race_duration_s > 0 else 0.0

    # Pace delta: sum of (actual - planned) across completed stints
    pace_delta = 0
    for s in stints:
        if s.get("status") == "completed":
            actual = s.get("actual_duration_s") or s.get("planned_duration_s") or 0
            planned = s.get("planned_duration_s") or 0
            pace_delta += actual - planned

    if pace_delta > _PACE_TOLERANCE_S:
        pace_status = "BEHIND"
    elif pace_delta < -_PACE_TOLERANCE_S:
        pace_status = "AHEAD"
    else:
        pace_status = "ON PLAN"

    # Total neutralized time
    neutralized_total = 0.0
    for n in neutralizations:
        ns = n["start_s"]
        ne = n.get("end_s") or elapsed_s
        if ne > ns:
            neutralized_total += ne - ns

    return {
        "remaining_s": int(remaining),
        "completion_pct": round(completion, 1),
        "pace_delta_s": pace_delta,
        "pace_status": pace_status,
        "race_start_ts": race_start_ts,
        "neutralized_total_s": int(neutralized_total),
    }


def fuel_alerts(
    current_fuel_kg: float,
    burn_rate_kgs: float,
    active_stint_end_s: int,
    elapsed_s: float,
    next_planned_pit_s: int | None,
) -> dict[str, Any]:
    """Fuel red zone alerts: countdown to empty, can-reach-pit check."""
    if burn_rate_kgs <= 0:
        return {
            "fuel_remaining_s": 999999,
            "fuel_status": "ok",
            "can_reach_pit": True,
            "shortfall_s": 0,
        }

    fuel_remaining_s = current_fuel_kg / burn_rate_kgs

    if fuel_remaining_s < _FUEL_CRITICAL_S:
        status = "critical"
    elif fuel_remaining_s < _FUEL_WARNING_S:
        status = "warning"
    else:
        status = "ok"

    # Can we reach the next pit stop?
    pit_target = next_planned_pit_s or active_stint_end_s
    time_to_pit = max(0.0, pit_target - elapsed_s)
    fuel_needed_s = time_to_pit
    can_reach = fuel_remaining_s >= fuel_needed_s
    shortfall = max(0, int(fuel_needed_s - fuel_remaining_s)) if not can_reach else 0

    return {
        "fuel_remaining_s": int(fuel_remaining_s),
        "fuel_status": status,
        "can_reach_pit": can_reach,
        "shortfall_s": shortfall,
    }
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_intelligence.py::TestPredictFinish telemetry_tool/tests/test_race_intelligence.py::TestFuelAlerts -v`
Expected: PASS — all tests green

**Step 5: Commit**

```bash
git add telemetry_tool/race_intelligence.py telemetry_tool/tests/test_race_intelligence.py
git commit -m "feat(intelligence): predict_finish + fuel_alerts — stateless race analytics"
```

---

## Task 5: Race Intelligence — Pace Analysis + Swap Suggestion + Rival Analysis

**Files:**
- Modify: `telemetry_tool/race_intelligence.py` (add pace_analysis, swap_suggestion, rival_analysis, analyze_race)
- Modify: `telemetry_tool/tests/test_race_intelligence.py` (new test classes)

**Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_race_intelligence.py`:

```python
from race_intelligence import pace_analysis, swap_suggestion, rival_analysis, analyze_race


class TestPaceAnalysis:

    def test_no_completed_stints_returns_none_deltas(self):
        result = pace_analysis(stints=[], active_stint=None, elapsed_s=100.0)
        assert result["pace_vs_own_avg_s"] is None
        assert result["pace_vs_field_avg_s"] is None
        assert result["pace_trend"] == "stable"

    def test_own_average_comparison(self):
        stints = [
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2400, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2380, "planned_duration_s": 2360},
        ]
        active = {"driver_id": 1, "planned_start_s": 4900, "planned_duration_s": 2360, "status": "active"}
        result = pace_analysis(stints=stints, active_stint=active, elapsed_s=5500.0)
        assert result["pace_vs_own_avg_s"] is not None

    def test_pace_trend_degrading(self):
        stints = [
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2360, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2400, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2450, "planned_duration_s": 2360},
        ]
        result = pace_analysis(stints=stints, active_stint=None, elapsed_s=7500.0)
        assert result["pace_trend"] == "degrading"

    def test_pace_trend_improving(self):
        stints = [
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2450, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2400, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2360, "planned_duration_s": 2360},
        ]
        result = pace_analysis(stints=stints, active_stint=None, elapsed_s=7500.0)
        assert result["pace_trend"] == "improving"


class TestSwapSuggestion:

    def test_no_suggestion_when_pace_ok(self):
        stints = [
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2360, "planned_duration_s": 2360},
        ]
        active = {"driver_id": 1, "planned_start_s": 2420, "planned_duration_s": 2360, "status": "active"}
        drivers = [
            {"id": 1, "driver_name": "Alice", "max_cumulative_s": 7200},
            {"id": 2, "driver_name": "Bob", "max_cumulative_s": 7200},
        ]
        result = swap_suggestion(
            stints=stints, drivers=drivers, active_stint=active,
            elapsed_s=3000.0, burn_rate_kgs=0.003333,
            current_fuel_kg=5.0,
        )
        assert result is None

    def test_suggestion_when_pace_degraded(self):
        stints = [
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2360, "planned_duration_s": 2360},
            {"status": "completed", "driver_id": 1, "actual_duration_s": 2700, "planned_duration_s": 2360},
        ]
        active = {
            "driver_id": 1, "planned_start_s": 5200, "planned_duration_s": 2360,
            "status": "active",
        }
        drivers = [
            {"id": 1, "driver_name": "Alice", "max_cumulative_s": 7200},
            {"id": 2, "driver_name": "Bob", "max_cumulative_s": 7200},
        ]
        result = swap_suggestion(
            stints=stints, drivers=drivers, active_stint=active,
            elapsed_s=6000.0, burn_rate_kgs=0.003333,
            current_fuel_kg=3.0,
        )
        assert result is not None
        assert result["suggest_swap"] is True
        assert "Bob" in result["next_driver"]


class TestRivalAnalysis:

    def test_empty_rivals(self):
        result = rival_analysis(rivals=[], rival_events=[], elapsed_s=3600.0)
        assert result == []

    def test_single_rival_with_pits(self):
        rivals = [{"id": 1, "team_name": "Alpha", "car_number": "42"}]
        events = [
            {"rival_id": 1, "event_type": "pit_in", "at_s": 1200},
            {"rival_id": 1, "event_type": "pit_in", "at_s": 2400},
            {"rival_id": 1, "event_type": "pit_in", "at_s": 3600},
        ]
        result = rival_analysis(rivals=rivals, rival_events=events, elapsed_s=4000.0)
        assert len(result) == 1
        assert result[0]["team_name"] == "Alpha"
        assert result[0]["estimated_pits"] == 3
        assert result[0]["avg_stint_s"] == 1200

    def test_last_activity_seconds(self):
        rivals = [{"id": 1, "team_name": "Beta", "car_number": "7"}]
        events = [{"rival_id": 1, "event_type": "pit_in", "at_s": 3000}]
        result = rival_analysis(rivals=rivals, rival_events=events, elapsed_s=3600.0)
        assert result[0]["last_activity_s"] == 600


class TestAnalyzeRace:

    def test_analyze_race_returns_all_keys(self):
        result = analyze_race(
            race_duration_s=7200, elapsed_s=3600.0, race_start_ts=None,
            stints=[], active_stint=None,
            drivers=[], neutralizations=[],
            current_fuel_kg=5.0, burn_rate_kgs=0.003333,
            active_stint_end_s=7200, next_planned_pit_s=None,
            rivals=[], rival_events=[],
        )
        assert "finish" in result
        assert "fuel" in result
        assert "pace" in result
        assert "swap" in result
        assert "rivals" in result
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_intelligence.py -v`
Expected: FAIL — pace_analysis, swap_suggestion, rival_analysis, analyze_race not defined

**Step 3: Implement remaining intelligence functions**

Add to `telemetry_tool/race_intelligence.py`:

```python
_SWAP_PACE_THRESHOLD = 0.10  # 10% slower triggers suggestion
_TREND_THRESHOLD_S = 20      # 20s difference per stint = trending


def pace_analysis(
    stints: list[dict],
    active_stint: dict | None,
    elapsed_s: float,
) -> dict[str, Any]:
    """Compare current driver pace vs own history and field average."""
    completed = [s for s in stints if s.get("status") == "completed"]

    if not completed:
        return {
            "pace_vs_own_avg_s": None,
            "pace_vs_field_avg_s": None,
            "pace_trend": "stable",
            "recommendation": None,
        }

    # Field average
    field_durations = [s.get("actual_duration_s") or s.get("planned_duration_s") for s in completed]
    field_avg = sum(field_durations) / len(field_durations) if field_durations else 0

    # Own average (same driver as active stint)
    pace_vs_own = None
    if active_stint:
        driver_id = active_stint.get("driver_id")
        own_stints = [s for s in completed if s.get("driver_id") == driver_id]
        if own_stints:
            own_durations = [s.get("actual_duration_s") or s.get("planned_duration_s") for s in own_stints]
            own_avg = sum(own_durations) / len(own_durations)
            time_in_stint = elapsed_s - active_stint.get("planned_start_s", 0)
            planned = active_stint.get("planned_duration_s", 1)
            if time_in_stint > 0 and planned > 0:
                rate = time_in_stint / planned
                projected = planned * rate if rate > 0.1 else planned
                pace_vs_own = int(projected - own_avg)

    pace_vs_field = None
    if active_stint and field_avg > 0:
        time_in_stint = elapsed_s - active_stint.get("planned_start_s", 0)
        planned = active_stint.get("planned_duration_s", 1)
        if time_in_stint > 0 and planned > 0:
            rate = time_in_stint / planned
            projected = planned * rate if rate > 0.1 else planned
            pace_vs_field = int(projected - field_avg)

    # Trend: last 3 completed stints for the active driver (or all)
    if active_stint:
        driver_id = active_stint.get("driver_id")
        own_completed = [s for s in completed if s.get("driver_id") == driver_id]
    else:
        own_completed = completed

    trend = "stable"
    if len(own_completed) >= 3:
        last3 = own_completed[-3:]
        durations = [s.get("actual_duration_s") or s.get("planned_duration_s") for s in last3]
        diffs = [durations[i+1] - durations[i] for i in range(len(durations)-1)]
        if all(d > _TREND_THRESHOLD_S for d in diffs):
            trend = "degrading"
        elif all(d < -_TREND_THRESHOLD_S for d in diffs):
            trend = "improving"

    recommendation = None
    if trend == "degrading":
        recommendation = "Consider early driver swap"

    return {
        "pace_vs_own_avg_s": pace_vs_own,
        "pace_vs_field_avg_s": pace_vs_field,
        "pace_trend": trend,
        "recommendation": recommendation,
    }


def swap_suggestion(
    stints: list[dict],
    drivers: list[dict],
    active_stint: dict | None,
    elapsed_s: float,
    burn_rate_kgs: float,
    current_fuel_kg: float,
) -> dict[str, Any] | None:
    """Suggest driver swap when performance degrades significantly."""
    if not active_stint or not drivers:
        return None

    driver_id = active_stint.get("driver_id")
    completed = [s for s in stints if s.get("status") == "completed" and s.get("driver_id") == driver_id]

    if len(completed) < 1:
        return None

    own_durations = [s.get("actual_duration_s") or s.get("planned_duration_s") for s in completed]
    own_avg = sum(own_durations) / len(own_durations)

    time_in_stint = elapsed_s - active_stint.get("planned_start_s", 0)
    planned = active_stint.get("planned_duration_s", 1)
    if time_in_stint <= 0 or planned <= 0:
        return None

    rate = time_in_stint / planned
    if rate < 0.3:  # Too early in stint to judge
        return None

    projected = planned * rate
    degradation = (projected - own_avg) / own_avg if own_avg > 0 else 0

    if degradation < _SWAP_PACE_THRESHOLD:
        return None

    # Check fuel allows pitting now
    min_fuel_s = 60
    fuel_remaining_s = current_fuel_kg / burn_rate_kgs if burn_rate_kgs > 0 else 999999
    if fuel_remaining_s < min_fuel_s:
        return None

    # Find current and next driver names
    active_driver_name = None
    for d in drivers:
        if d.get("id") == driver_id:
            active_driver_name = d.get("driver_name", "Unknown")
            break

    next_driver = None
    for d in drivers:
        if d.get("id") != driver_id:
            next_driver = d.get("driver_name", "Unknown")
            break

    if not next_driver:
        return None

    return {
        "suggest_swap": True,
        "reason": f"{active_driver_name} is {degradation:.0%} slower than their average",
        "next_driver": next_driver,
        "degradation_pct": round(degradation * 100, 1),
    }


def rival_analysis(
    rivals: list[dict],
    rival_events: list[dict],
    elapsed_s: float,
) -> list[dict[str, Any]]:
    """Analyze rival teams based on observed events."""
    if not rivals:
        return []

    results = []
    for rival in rivals:
        rid = rival.get("id")
        events = [e for e in rival_events if e.get("rival_id") == rid]
        pit_events = sorted(
            [e for e in events if e.get("event_type") == "pit_in"],
            key=lambda e: e["at_s"],
        )

        estimated_pits = len(pit_events)

        avg_stint = 0
        if len(pit_events) >= 2:
            gaps = [pit_events[i+1]["at_s"] - pit_events[i]["at_s"] for i in range(len(pit_events)-1)]
            avg_stint = int(sum(gaps) / len(gaps))

        all_sorted = sorted(events, key=lambda e: e["at_s"])
        last_activity_s = int(elapsed_s - all_sorted[-1]["at_s"]) if all_sorted else None

        results.append({
            "rival_id": rid,
            "team_name": rival.get("team_name", "Unknown"),
            "car_number": rival.get("car_number", ""),
            "estimated_pits": estimated_pits,
            "avg_stint_s": avg_stint,
            "last_activity_s": last_activity_s,
        })

    return results


def analyze_race(
    race_duration_s: int,
    elapsed_s: float,
    race_start_ts: str | None,
    stints: list[dict],
    active_stint: dict | None,
    drivers: list[dict],
    neutralizations: list[dict],
    current_fuel_kg: float,
    burn_rate_kgs: float,
    active_stint_end_s: int,
    next_planned_pit_s: int | None,
    rivals: list[dict],
    rival_events: list[dict],
) -> dict[str, Any]:
    """Top-level intelligence aggregator -- called by api_state()."""
    return {
        "finish": predict_finish(
            race_duration_s, elapsed_s, stints, race_start_ts, neutralizations,
        ),
        "fuel": fuel_alerts(
            current_fuel_kg, burn_rate_kgs, active_stint_end_s, elapsed_s, next_planned_pit_s,
        ),
        "pace": pace_analysis(stints, active_stint, elapsed_s),
        "swap": swap_suggestion(
            stints, drivers, active_stint, elapsed_s, burn_rate_kgs, current_fuel_kg,
        ),
        "rivals": rival_analysis(rivals, rival_events, elapsed_s),
    }
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_intelligence.py -v`
Expected: PASS — all tests green

**Step 5: Commit**

```bash
git add telemetry_tool/race_intelligence.py telemetry_tool/tests/test_race_intelligence.py
git commit -m "feat(intelligence): pace analysis, swap suggestion, rival analysis, analyze_race"
```

---

## Task 6: Rival CRUD API + Neutralization API Endpoints

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py:614-674` (update api_state with intelligence)
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (add rival + neutralization endpoints at end)
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py` (API tests)

**Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestRivalAPI:
    """Tier 6 rival CRUD endpoints."""

    def _seed_live_race(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, status, race_start_ts) "
            "VALUES ('Test Race', 7200, 'live', datetime('now'))"
        )
        strategy_db.commit()
        return 1

    def test_add_rival(self, client, strategy_db):
        race_id = self._seed_live_race(strategy_db)
        resp = client.post(f"/race-strategy/{race_id}/api/rivals",
                           json={"team_name": "Team Alpha", "car_number": "42"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["team_name"] == "Team Alpha"
        assert "id" in data

    def test_list_rivals(self, client, strategy_db):
        race_id = self._seed_live_race(strategy_db)
        strategy_db.execute(
            "INSERT INTO race_rivals (race_id, team_name, car_number) VALUES (?, 'X', '1')", (race_id,)
        )
        strategy_db.commit()
        resp = client.get(f"/race-strategy/{race_id}/api/rivals")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["rivals"]) == 1

    def test_add_rival_event(self, client, strategy_db):
        race_id = self._seed_live_race(strategy_db)
        strategy_db.execute(
            "INSERT INTO race_rivals (race_id, team_name, car_number) VALUES (?, 'X', '1')", (race_id,)
        )
        strategy_db.commit()
        resp = client.post(f"/race-strategy/{race_id}/api/rivals/1/event",
                           json={"event_type": "pit_in", "detail": "quick stop"})
        assert resp.status_code == 200

    def test_delete_rival(self, client, strategy_db):
        race_id = self._seed_live_race(strategy_db)
        strategy_db.execute(
            "INSERT INTO race_rivals (race_id, team_name, car_number) VALUES (?, 'X', '1')", (race_id,)
        )
        strategy_db.commit()
        resp = client.delete(f"/race-strategy/{race_id}/api/rivals/1")
        assert resp.status_code == 200
        row = strategy_db.execute("SELECT * FROM race_rivals WHERE id = 1").fetchone()
        assert row is None


class TestNeutralizationAPI:
    """Tier 6 neutralization toggle endpoints."""

    def _seed_live_race(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, status, race_start_ts, "
            "fuel_autonomy_s, empty_kart_kg, full_tank_kg, min_total_kart_kg, min_pit_stop_s) "
            "VALUES ('Test', 7200, 'live', datetime('now'), 2400, 85, 93, 160, 60)"
        )
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'A', 1, 65)"
        )
        strategy_db.execute(
            "INSERT INTO race_stints (race_id, stint_order, driver_id, planned_start_s, planned_end_s, "
            "planned_duration_s, status) VALUES (1, 1, 1, 0, 3600, 3600, 'active')"
        )
        strategy_db.commit()
        return 1

    def test_start_neutralization(self, client, strategy_db):
        race_id = self._seed_live_race(strategy_db)
        resp = client.post(f"/race-strategy/{race_id}/api/neutralization/start",
                           json={"reason": "safety_car"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_neutralized"] is True

    def test_end_neutralization(self, client, strategy_db):
        race_id = self._seed_live_race(strategy_db)
        strategy_db.execute(
            "INSERT INTO race_neutralizations (race_id, start_s, reason) VALUES (?, 500, 'safety_car')",
            (race_id,)
        )
        strategy_db.commit()
        resp = client.post(f"/race-strategy/{race_id}/api/neutralization/end")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_neutralized"] is False
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_strategy_v2.py::TestRivalAPI telemetry_tool/tests/test_race_strategy_v2.py::TestNeutralizationAPI -v`
Expected: FAIL — endpoints don't exist

**Step 3: Add rival CRUD endpoints**

Add at end of `telemetry_tool/web/routes/race_strategy_v2.py` (before the private helper functions):

Rival endpoints: `api_list_rivals`, `api_add_rival`, `api_add_rival_event`, `api_delete_rival`.
Neutralization endpoints: `api_neutralization_start`, `api_neutralization_end`.

See the design doc `docs/plans/2026-02-25-race-strategy-tier6-design.md` Section 3 (Rival Tracker API) and Section 1 (Safety Car API) for exact endpoint signatures.

Key implementation notes:
- Rival add validates `team_name` is non-empty
- Rival event auto-computes `at_s` from elapsed time if not provided
- Rival delete cascades to `race_rival_events`
- Neutralization start inserts with `end_s = NULL`
- Neutralization end updates the open row (`end_s IS NULL`)

**Step 4: Wire intelligence into api_state**

In the `api_state()` function (around line 660), after the engine_data block, add intelligence analysis. Import `analyze_race` from `race_intelligence`, call it with engine snapshot data + rivals/events from DB, and add result as `"intelligence"` key in the jsonify response.

**Step 5: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_strategy_v2.py::TestRivalAPI telemetry_tool/tests/test_race_strategy_v2.py::TestNeutralizationAPI -v`
Expected: PASS

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(routes): rival CRUD, neutralization toggle, intelligence in api_state"
```

---

## Task 7: Live Dashboard — Neutralization UI + Intelligence Display

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html` (SC button, alert strip, rival panel, intelligence row)
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js` (render intelligence, SC toggle, rival panel)
- Modify: `telemetry_tool/web/static/css/race_strategy.css` (neutralization bar, intelligence cards, rival panel)

**Step 1: Add HTML elements to live.html**

Add to the toolbar: SC toggle button, notification bell with badge.
Add after window status bar: neutralization banner (hidden by default), alert toast strip.
Add after main grid: intelligence row (3-column: finish prediction, fuel alert, pace analysis).
Add collapsible rival tracker panel with quick-add form and rival card list.
Add alert history panel.

See design doc Section 1 (SC UI), Section 2 (intelligence display), Section 3 (rival UI).

**Step 2: Add JS rendering functions to race_strategy_live.js**

Add functions: `toggleNeutralization()`, `updateNeutralizationUI(state)`, `updateIntelligence(intel)`, `updateRivals(rivalsData)`, `addRival()`, `logRivalEvent(rivalId, eventType)`, `deleteRival(rivalId)`, `toggleRivalsPanel()`.

Wire into existing polling loop: call `updateIntelligence(state.intelligence)` and `updateNeutralizationUI(state)` inside the state update callback.

Fetch rivals separately via `/api/rivals` and merge with `state.intelligence.rivals` analysis.

**Important:** Use `textContent` for plain text values. For structured HTML rendering within the dashboard cards, construct DOM elements programmatically using `createElement`/`appendChild` or use the existing template pattern from the codebase. Only use safe DOM construction methods.

**Step 3: Add CSS styles**

Add styles for: `.rs-sc-banner` (pulsing yellow), `.rs-btn-sc` / `.rs-btn-sc.active`, `.rs-intel-row` (3-column grid), `.rs-intel-metric`, `.rs-ahead` / `.rs-behind` / `.rs-on-plan`, `.rs-fuel-critical` / `.rs-fuel-warning`, `.rs-alert-strip` / `.rs-alert-toast`, `.rs-btn-bell` / `.rs-badge`, `.rs-rival-card` / `.rs-rivals-panel`.

Hide intelligence row and rivals panel in compact mode: `.rs-compact .rs-rivals-panel, .rs-compact .rs-intel-row { display: none; }`

**Step 4: Commit**

```bash
git add telemetry_tool/web/templates/race_strategy/live.html telemetry_tool/web/static/js/race_strategy_live.js telemetry_tool/web/static/css/race_strategy.css
git commit -m "feat(live): neutralization UI, intelligence display, rival tracker panel"
```

---

## Task 8: Browser Notifications & Sound Alerts (AlertManager)

**Files:**
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js` (add AlertManager class)
- Modify: `telemetry_tool/web/static/css/race_strategy.css` (alert history, muted bell)
- Modify: `telemetry_tool/web/templates/race_strategy/live.html` (alert history container)

**Step 1: Implement AlertManager class in JS**

Add `AlertManager` class with:
- `constructor()`: init previousState, muted (from localStorage), cooldowns, audioCtx (lazy), history array
- `playTone(freq, durationMs, type)`: Web Audio oscillator, gain ramp, guards for muted/unavailable
- `_canFire(type)`: 30s cooldown check per alert type
- `notify(type, title, body, priority)`: show toast, browser Notification (if granted), add to history, update badge
- `check(state)`: edge detection — compare state vs previousState for transitions:
  - Fuel status transitions (ok->warning->critical)
  - Window status transitions (before->open, open->closing)
  - Neutralization start/end
  - Swap suggestion appearance
  - Stint time limit (90% of max_stint_s)
- `toggleMute()`: flip muted, persist to localStorage

Create global `alertManager` instance. Add `toggleAlertMute()` function.
Add `showAlertToast(type, message, priority)` using safe DOM construction.
Add `Notification.requestPermission()` on first click event.

Wire `alertManager.check(state)` into the existing polling loop callback.

**Step 2: Add CSS for alert history and muted state**

```css
.rs-alert-history { max-height: 200px; overflow-y: auto; }
.rs-btn-bell.muted { opacity: 0.4; }
```

**Step 3: Add alert history container to live.html**

```html
<div class="rs-card" id="rs-alert-history-panel">
    <h4>Alert Log</h4>
    <div id="rs-alert-history" class="rs-alert-history"></div>
</div>
```

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/js/race_strategy_live.js telemetry_tool/web/static/css/race_strategy.css telemetry_tool/web/templates/race_strategy/live.html
git commit -m "feat(live): AlertManager — browser notifications, audio alerts, edge detection"
```

---

## Task 9: Full Integration Test + Regression Suite

**Files:**
- All test files

**Step 1: Run all engine tests**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py -v`
Expected: All tests pass including Neutralization + NeutralizationPersistence

**Step 2: Run all intelligence tests**

Run: `python -m pytest telemetry_tool/tests/test_race_intelligence.py -v`
Expected: All tests pass

**Step 3: Run all route/schema tests**

Run: `python -m pytest telemetry_tool/tests/test_race_strategy_v2.py -v`
Expected: All tests pass including TestTier6Schema, TestRivalAPI, TestNeutralizationAPI

**Step 4: Run the complete telemetry_tool test suite**

Run: `python -m pytest telemetry_tool/tests/ -v`
Expected: Zero regressions across the entire test suite

**Step 5: Commit (fix and commit if any regressions found)**

```bash
git add -A
git commit -m "test: full Tier 6 regression pass — all tests green"
```
