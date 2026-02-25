# Race Strategy Tier 5: Pit Windows & Live Dashboard — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add typed race windows (pitlane, refuel, tech stop) with engine validation, three-card live status bar, compact pit wall mode, persistent driver colors, fullscreen toggle, and wall clock.

**Architecture:** A new `race_windows` table holds typed time ranges. `RaceStateEngine` loads windows alongside existing data and validates pit stops against them during cascade. The live dashboard gains a three-card status bar rendered from engine's `window_status()`, plus a compact "Pit Wall" CSS layout mode, fullscreen API integration, and wall clock display.

**Tech Stack:** Python 3, Flask, SQLite, vanilla JS, CSS (existing stack — no new dependencies)

---

## Task 1: Schema Migration (v23)

**Files:**
- Modify: `telemetry_tool/db/schema.py:754-865` (add race_windows table, color_hex column)
- Modify: `telemetry_tool/db/migrate.py:406-414` (add v23 migration block)
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py` (update schema version test)

**Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_race_strategy_v2.py` inside class `TestRaceStrategySchema`:

```python
def test_schema_version_is_23(self, strategy_db):
    row = strategy_db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    assert row["v"] == 23

def test_race_windows_table_exists(self, strategy_db):
    strategy_db.execute(
        "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
    )
    strategy_db.execute(
        "INSERT INTO race_windows (race_id, window_type, start_s, end_s, window_order) "
        "VALUES (1, 'pitlane', 300, 3300, 1)"
    )
    row = strategy_db.execute("SELECT * FROM race_windows WHERE race_id = 1").fetchone()
    assert row["window_type"] == "pitlane"
    assert row["start_s"] == 300
    assert row["end_s"] == 3300

def test_race_windows_has_rule_columns(self, strategy_db):
    strategy_db.execute(
        "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
    )
    strategy_db.execute(
        "INSERT INTO race_windows (race_id, window_type, label, start_s, end_s, "
        "refuel_allowed, driver_change_allowed, window_order) "
        "VALUES (1, 'tech_stop', 'Tech 1', 1800, 2400, 0, 1, 1)"
    )
    row = strategy_db.execute("SELECT * FROM race_windows WHERE race_id = 1").fetchone()
    assert row["label"] == "Tech 1"
    assert row["refuel_allowed"] == 0
    assert row["driver_change_allowed"] == 1

def test_race_drivers_has_color_hex_column(self, strategy_db):
    strategy_db.execute(
        "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
    )
    strategy_db.execute(
        "INSERT INTO race_drivers (race_id, driver_name, driver_order, color_hex) "
        "VALUES (1, 'Alice', 1, '#58a6ff')"
    )
    row = strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = 1").fetchone()
    assert row["color_hex"] == "#58a6ff"
```

Also update the existing `test_schema_version_is_22` → rename to `test_schema_version_is_23` (or replace it).

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_strategy_v2.py::TestRaceStrategySchema -v`
Expected: FAIL — race_windows table doesn't exist, color_hex column missing, version is 22

**Step 3: Add race_windows table to schema.py**

In `telemetry_tool/db/schema.py`, after `PHASE_15_TABLES` (line 847), add a new table definition and include it in a new phase or add to Phase 15:

```python
_RACE_WINDOWS_TABLE = """
CREATE TABLE IF NOT EXISTS race_windows (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id               INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    window_type           TEXT NOT NULL,
    label                 TEXT,
    start_s               INTEGER NOT NULL,
    end_s                 INTEGER NOT NULL,
    refuel_allowed        INTEGER NOT NULL DEFAULT 1,
    driver_change_allowed INTEGER NOT NULL DEFAULT 1,
    window_order          INTEGER NOT NULL DEFAULT 1
);
"""
```

Add `color_hex TEXT` to `_RACE_DRIVERS_TABLE` after `com_channel TEXT`.

Add `race_windows` to `PHASE_15_TABLES` list.

Update `SCHEMA_VERSION = 23`.

**Step 4: Add v23 migration block to migrate.py**

In `telemetry_tool/db/migrate.py`, after the Phase 22 block (line 410), add:

```python
# Phase 23 migration: Tier 5 — race windows, driver colors.
cur.execute(_RACE_WINDOWS_TABLE)  # CREATE TABLE IF NOT EXISTS is idempotent

try:
    cur.execute("ALTER TABLE race_drivers ADD COLUMN color_hex TEXT;")
    logger.debug("Added column race_drivers.color_hex.")
except sqlite3.OperationalError:
    pass  # Column already exists.

cur.execute(
    "INSERT OR IGNORE INTO schema_version (version, description) "
    "VALUES (?, ?);",
    (23, "Phase 23 schema — Tier 5 race windows, driver colors"),
)
```

Note: The `CREATE TABLE IF NOT EXISTS` for `race_windows` needs to be accessible in the migration function. Import or inline the SQL string. The simplest approach: use `conn.executescript()` with the raw SQL, or import from schema.py.

**Step 5: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_strategy_v2.py::TestRaceStrategySchema -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/migrate.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(schema): v23 — race_windows table + driver color_hex column"
```

---

## Task 2: Engine — Window Loading & `_is_in_any_window` Helper

**Files:**
- Modify: `telemetry_tool/race_state_engine.py:127-170` (__init__ and load)
- Create tests in: `telemetry_tool/tests/test_race_state_engine.py`

**Step 1: Write failing tests**

Add a new test class `TestWindowValidation` to `telemetry_tool/tests/test_race_state_engine.py`:

```python
class TestWindowValidation:
    """Tests for race window validation in RaceStateEngine."""

    def _make_engine_with_windows(self, windows=None):
        """Create a 3-stint engine with optional race windows."""
        config = {
            "race_duration_s": 3600,
            "empty_kart_kg": 85,
            "full_tank_kg": 93,
            "min_total_kart_kg": 160,
            "fuel_autonomy_s": 2400,
            "min_pit_stop_s": 60,
            "mandatory_driver_change": 0,
            "refueling_allowed": 1,
            "pit_open_s": None,
            "pit_close_s": None,
        }
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75},
        ]
        raw_stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 1200, "planned_duration_s": 1200},
            {"stint_order": 2, "driver_id": 2, "driver_name": "Bob",
             "planned_start_s": 1260, "planned_end_s": 2460, "planned_duration_s": 1200},
            {"stint_order": 3, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 2520, "planned_end_s": 3600, "planned_duration_s": 1080},
        ]
        pit_stops = [
            {"after_stint": 1, "refuel": True, "driver_change": True, "pit_type": "full"},
            {"after_stint": 2, "refuel": True, "driver_change": True, "pit_type": "full"},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints, pit_stops)
        if windows:
            engine.windows = windows
            engine._cascade_from(1)
        return engine

    def test_no_windows_means_no_restriction(self):
        engine = self._make_engine_with_windows(windows=[])
        # No windows = no violations related to windows
        for s in engine.stints:
            assert not any("window" in v.lower() for v in s.violations)
            assert not any("window" in w.lower() for w in s.warnings)

    def test_is_in_any_window_true_when_inside(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "pitlane", "start_s": 1000, "end_s": 3000},
        ])
        assert engine._is_in_any_window("pitlane", 1500) is True

    def test_is_in_any_window_false_when_outside(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "pitlane", "start_s": 1000, "end_s": 3000},
        ])
        assert engine._is_in_any_window("pitlane", 500) is False

    def test_is_in_any_window_true_when_no_windows_of_type(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "refuel", "start_s": 1000, "end_s": 3000},
        ])
        # No pitlane windows → no restriction
        assert engine._is_in_any_window("pitlane", 500) is True

    def test_is_in_any_window_multiple_windows(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "refuel", "start_s": 500, "end_s": 1000},
            {"window_type": "refuel", "start_s": 2000, "end_s": 3000},
        ])
        assert engine._is_in_any_window("refuel", 800) is True
        assert engine._is_in_any_window("refuel", 2500) is True
        assert engine._is_in_any_window("refuel", 1500) is False
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestWindowValidation -v`
Expected: FAIL — `windows` attribute and `_is_in_any_window` don't exist

**Step 3: Add windows to engine __init__ and load**

In `telemetry_tool/race_state_engine.py`:

1. Add `self.windows: list[dict] = []` to `__init__` (after `self._pit_type_map`).
2. Add `_is_in_any_window` method:

```python
def _is_in_any_window(self, window_type: str, time_s: int) -> bool:
    """Return True if time_s is inside any window of the given type.
    Returns True if no windows of that type exist (permissive default)."""
    typed = [w for w in self.windows if w['window_type'] == window_type]
    if not typed:
        return True
    return any(w['start_s'] <= time_s <= w['end_s'] for w in typed)
```

3. In `load()` (line ~605), add a query for windows after loading pit stops:

```python
window_rows = conn.execute(
    "SELECT * FROM race_windows WHERE race_id = ? ORDER BY window_order",
    (race_id,),
).fetchall()
windows = [dict(r) for r in window_rows]
```

Then set `engine.windows = windows` before returning.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestWindowValidation -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(engine): add windows list + _is_in_any_window helper"
```

---

## Task 3: Engine — Pit Window & Refuel Window Constraint Validation

**Files:**
- Modify: `telemetry_tool/race_state_engine.py:288-352` (_validate_constraints)
- Modify: `telemetry_tool/tests/test_race_state_engine.py`

**Step 1: Write failing tests**

Add to `TestWindowValidation`:

```python
def test_pitlane_window_warning_when_pit_outside(self):
    """Pit stop outside pitlane window → warning on the stint."""
    engine = self._make_engine_with_windows(windows=[
        {"window_type": "pitlane", "start_s": 2000, "end_s": 3500},
    ])
    # Stint 2 starts at 1260 (pit stop at 1260, outside 2000-3500)
    stint2 = engine.stints[1]
    assert any("pit" in w.lower() and "window" in w.lower() for w in stint2.warnings)

def test_pitlane_window_no_warning_when_inside(self):
    """Pit stop inside pitlane window → no warning."""
    engine = self._make_engine_with_windows(windows=[
        {"window_type": "pitlane", "start_s": 1000, "end_s": 3500},
    ])
    stint2 = engine.stints[1]
    assert not any("pit" in w.lower() and "window" in w.lower() for w in stint2.warnings)

def test_refuel_window_violation_when_refuel_outside(self):
    """Refueling outside refuel window → violation."""
    engine = self._make_engine_with_windows(windows=[
        {"window_type": "refuel", "start_s": 2000, "end_s": 3500},
    ])
    # Stint 2 starts at 1260 and is refueled (outside 2000-3500)
    stint2 = engine.stints[1]
    assert any("refuel" in v.lower() and "window" in v.lower() for v in stint2.violations)

def test_refuel_window_no_violation_when_not_refueled(self):
    """Non-refueled stint outside refuel window → no violation."""
    engine = self._make_engine_with_windows(windows=[
        {"window_type": "refuel", "start_s": 2000, "end_s": 3500},
    ])
    engine.toggle_fuel(2)  # Turn off refueling for stint 2
    stint2 = engine.stints[1]
    assert not any("refuel" in v.lower() and "window" in v.lower() for v in stint2.violations)

def test_refuel_window_no_violation_when_inside(self):
    """Refueling inside refuel window → no violation."""
    engine = self._make_engine_with_windows(windows=[
        {"window_type": "refuel", "start_s": 1000, "end_s": 3500},
    ])
    stint2 = engine.stints[1]
    assert not any("refuel" in v.lower() and "window" in v.lower() for v in stint2.violations)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestWindowValidation -v -k "pitlane or refuel_window"``
Expected: FAIL — no window checks in _validate_constraints

**Step 3: Add window checks to _validate_constraints**

In `_validate_constraints()` (after the cumulative time check, ~line 352), add:

```python
# 5. Pit window check (warning): pit stop outside pitlane windows
if stint.stint_order > 1:
    pit_time_s = stint.planned_start_s
    if not self._is_in_any_window('pitlane', pit_time_s):
        stint.warnings.append(
            f"Pit stop at {int(pit_time_s)}s outside pit lane window"
        )

# 6. Refuel window check (violation): refuel outside refuel windows
if stint.refueled_before and stint.stint_order > 1:
    pit_time_s = stint.planned_start_s
    if not self._is_in_any_window('refuel', pit_time_s):
        stint.violations.append(
            f"Refuel at {int(pit_time_s)}s outside refuel window"
        )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestWindowValidation -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(engine): pit window warnings + refuel window violations"
```

---

## Task 4: Engine — Tech Stop Validation & Legacy Window Migration

**Files:**
- Modify: `telemetry_tool/race_state_engine.py` (add _validate_tech_stops, legacy migration in load)
- Modify: `telemetry_tool/tests/test_race_state_engine.py`

**Step 1: Write failing tests**

Add to `TestWindowValidation`:

```python
def test_tech_stop_violation_when_no_stop_in_window(self):
    """Tech stop window with no pit stop inside → violation."""
    engine = self._make_engine_with_windows(windows=[
        {"window_type": "tech_stop", "label": "Tech 1",
         "start_s": 100, "end_s": 200},  # No pit stops happen in 100-200
    ])
    all_violations = []
    for s in engine.stints:
        all_violations.extend(s.violations)
    assert any("tech" in v.lower() for v in all_violations)

def test_tech_stop_no_violation_when_stop_in_window(self):
    """Tech stop window with a pit stop inside → no violation."""
    engine = self._make_engine_with_windows(windows=[
        {"window_type": "tech_stop", "label": "Tech 1",
         "start_s": 1200, "end_s": 1400},  # Stint 2 starts at 1260 (pit there)
    ])
    all_violations = []
    for s in engine.stints:
        all_violations.extend(s.violations)
    assert not any("tech" in v.lower() for v in all_violations)

def test_legacy_pit_open_close_creates_virtual_window(self):
    """Legacy pit_open_s/pit_close_s config creates a virtual pitlane window."""
    config = {
        "race_duration_s": 3600,
        "empty_kart_kg": 85, "full_tank_kg": 93,
        "min_total_kart_kg": 160, "fuel_autonomy_s": 2400,
        "min_pit_stop_s": 60, "mandatory_driver_change": 0,
        "refueling_allowed": 1,
        "pit_open_s": 600,
        "pit_close_s": 300,  # 300s before end = 3300 absolute
    }
    drivers = [
        {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65},
    ]
    raw_stints = [
        {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
         "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
    ]
    engine = RaceStateEngine(config, drivers, raw_stints, [])
    # Legacy migration should create a virtual pitlane window
    assert len(engine.windows) == 1
    assert engine.windows[0]["window_type"] == "pitlane"
    assert engine.windows[0]["start_s"] == 600
    assert engine.windows[0]["end_s"] == 3300
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestWindowValidation -v -k "tech_stop or legacy"``
Expected: FAIL

**Step 3: Implement tech stop validation and legacy migration**

Add `_validate_tech_stops()` method and call it at the end of `_cascade_from()`:

```python
def _validate_tech_stops(self) -> None:
    """Check that each tech_stop window has at least one pit stop inside it."""
    tech_windows = [w for w in self.windows if w['window_type'] == 'tech_stop']
    for w in tech_windows:
        has_stop = any(
            w['start_s'] <= s.planned_start_s <= w['end_s']
            for s in self.stints if s.stint_order > 1
        )
        if not has_stop:
            label = w.get('label') or 'Tech Stop'
            target = min(
                self.stints,
                key=lambda s: abs(s.planned_end_s - w['start_s'])
            )
            target.violations.append(
                f"No pit stop in tech window '{label}' "
                f"({int(w['start_s'])}s – {int(w['end_s'])}s)"
            )
```

Add legacy migration in `__init__()` (after `self.windows = []`):

```python
# Legacy pit window migration: create virtual pitlane window from config
pit_open = config.get("pit_open_s")
pit_close = config.get("pit_close_s")
race_dur = config.get("race_duration_s") or 0
if (pit_open or pit_close) and not self.windows:
    start = pit_open or 0
    end = (race_dur - pit_close) if pit_close else race_dur
    self.windows.append({
        "window_type": "pitlane",
        "label": "Pit Window (legacy)",
        "start_s": start,
        "end_s": end,
        "refuel_allowed": 1,
        "driver_change_allowed": 1,
        "window_order": 1,
    })
```

Call `_validate_tech_stops()` at the end of `_cascade_from()`.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestWindowValidation -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(engine): tech stop validation + legacy pit window migration"
```

---

## Task 5: Engine — `window_status()` Query Method

**Files:**
- Modify: `telemetry_tool/race_state_engine.py` (add window_status method)
- Modify: `telemetry_tool/tests/test_race_state_engine.py`

**Step 1: Write failing tests**

Add a new test class `TestWindowStatus`:

```python
class TestWindowStatus:
    """Tests for window_status() query method."""

    def _make_engine_with_windows(self, windows):
        config = {
            "race_duration_s": 3600, "empty_kart_kg": 85, "full_tank_kg": 93,
            "min_total_kart_kg": 160, "fuel_autonomy_s": 2400,
            "min_pit_stop_s": 60, "mandatory_driver_change": 0,
            "refueling_allowed": 1, "pit_open_s": None, "pit_close_s": None,
        }
        drivers = [{"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 65}]
        stints = [{"stint_order": 1, "driver_id": 1, "driver_name": "A",
                   "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600}]
        engine = RaceStateEngine(config, drivers, stints, [])
        engine.windows = windows
        return engine

    def test_empty_windows_returns_all_none_status(self):
        engine = self._make_engine_with_windows([])
        status = engine.window_status(1000)
        # Should return entries for all three types, each with status 'none'
        types = {s['type'] for s in status}
        assert 'pitlane' in types
        assert 'refuel' in types
        assert 'tech_stop' in types
        for s in status:
            assert s['status'] == 'none'

    def test_window_before_open(self):
        engine = self._make_engine_with_windows([
            {"window_type": "pitlane", "start_s": 600, "end_s": 3000, "label": "Pit"},
        ])
        status = engine.window_status(300)
        pit = next(s for s in status if s['type'] == 'pitlane')
        assert pit['status'] == 'before'
        assert pit['countdown_s'] == 300  # 600 - 300

    def test_window_open(self):
        engine = self._make_engine_with_windows([
            {"window_type": "pitlane", "start_s": 600, "end_s": 3000, "label": "Pit"},
        ])
        status = engine.window_status(1000)
        pit = next(s for s in status if s['type'] == 'pitlane')
        assert pit['status'] == 'open'
        assert pit['countdown_s'] == 2000  # 3000 - 1000

    def test_window_closing_within_5_min(self):
        engine = self._make_engine_with_windows([
            {"window_type": "refuel", "start_s": 600, "end_s": 3000, "label": "R1"},
        ])
        status = engine.window_status(2800)  # 200s until close < 300s threshold
        refuel = next(s for s in status if s['type'] == 'refuel')
        assert refuel['status'] == 'closing'
        assert refuel['countdown_s'] == 200

    def test_window_closed(self):
        engine = self._make_engine_with_windows([
            {"window_type": "refuel", "start_s": 600, "end_s": 3000, "label": "R1"},
        ])
        status = engine.window_status(3100)
        refuel = next(s for s in status if s['type'] == 'refuel')
        assert refuel['status'] == 'closed'

    def test_multiple_windows_same_type_picks_active_or_next(self):
        engine = self._make_engine_with_windows([
            {"window_type": "refuel", "start_s": 300, "end_s": 900, "label": "R1"},
            {"window_type": "refuel", "start_s": 1800, "end_s": 2700, "label": "R2"},
        ])
        # At 1200, R1 is closed, R2 is next
        status = engine.window_status(1200)
        refuel = next(s for s in status if s['type'] == 'refuel')
        assert refuel['status'] == 'before'
        assert refuel['label'] == 'R2'
        assert refuel['countdown_s'] == 600  # 1800 - 1200
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestWindowStatus -v`
Expected: FAIL — window_status doesn't exist

**Step 3: Implement window_status()**

```python
def window_status(self, elapsed_s: float) -> list[dict]:
    """Compute live status for each window type.

    Returns a list with one entry per window type (pitlane, refuel, tech_stop).
    Each entry has: type, label, status ('none'|'before'|'open'|'closing'|'closed'), countdown_s.
    """
    CLOSING_THRESHOLD = 300  # 5 minutes

    result = []
    for wtype in ('pitlane', 'refuel', 'tech_stop'):
        typed = sorted(
            [w for w in self.windows if w['window_type'] == wtype],
            key=lambda w: w['start_s'],
        )
        if not typed:
            result.append({"type": wtype, "label": "", "status": "none", "countdown_s": 0})
            continue

        # Find the active or next window
        active = None
        upcoming = None
        for w in typed:
            if w['start_s'] <= elapsed_s <= w['end_s']:
                active = w
                break
            elif w['start_s'] > elapsed_s and upcoming is None:
                upcoming = w

        if active:
            remaining = active['end_s'] - elapsed_s
            status = 'closing' if remaining <= CLOSING_THRESHOLD else 'open'
            result.append({
                "type": wtype,
                "label": active.get('label', ''),
                "status": status,
                "countdown_s": int(remaining),
            })
        elif upcoming:
            result.append({
                "type": wtype,
                "label": upcoming.get('label', ''),
                "status": "before",
                "countdown_s": int(upcoming['start_s'] - elapsed_s),
            })
        else:
            # All windows of this type have ended
            result.append({
                "type": wtype,
                "label": typed[-1].get('label', ''),
                "status": "closed",
                "countdown_s": 0,
            })

    return result
```

Also add `window_status` to `snapshot()`:

```python
def snapshot(self) -> dict[str, Any]:
    # ... existing code ...
    return {
        "fuel_model": {...},
        "stints": stint_dicts,
        "refuel_map": dict(self._refuel_map),
        "pit_type_map": dict(self._pit_type_map),
        "windows": self.windows,  # ADD THIS
    }
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestWindowStatus -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(engine): window_status() query + snapshot includes windows"
```

---

## Task 6: Engine — Window Persistence (save/load)

**Files:**
- Modify: `telemetry_tool/race_state_engine.py:501-657` (save and load)
- Modify: `telemetry_tool/tests/test_race_state_engine.py`

**Step 1: Write failing test**

Add to `TestEnginePersistence`:

```python
def test_save_and_load_preserves_windows(self, strategy_db):
    """Windows survive a save/load round-trip."""
    engine = self._make_engine()  # existing helper
    engine.windows = [
        {"race_id": 1, "window_type": "pitlane", "label": "Pit 1",
         "start_s": 600, "end_s": 3000, "refuel_allowed": 1,
         "driver_change_allowed": 1, "window_order": 1},
        {"race_id": 1, "window_type": "refuel", "label": "Refuel 1",
         "start_s": 600, "end_s": 1800, "refuel_allowed": 1,
         "driver_change_allowed": 1, "window_order": 1},
    ]
    engine.save(strategy_db, 1)

    loaded = RaceStateEngine.load(strategy_db, 1)
    assert len(loaded.windows) == 2
    assert loaded.windows[0]["window_type"] == "pitlane"
    assert loaded.windows[1]["window_type"] == "refuel"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestEnginePersistence::test_save_and_load_preserves_windows -v`
Expected: FAIL

**Step 3: Add window save/load to engine**

In `save()`, after pit stop insertion and before `conn.commit()`:

```python
# Save windows
cur.execute("DELETE FROM race_windows WHERE race_id = ?", (race_id,))
for w in self.windows:
    cur.execute(
        "INSERT INTO race_windows "
        "(race_id, window_type, label, start_s, end_s, "
        " refuel_allowed, driver_change_allowed, window_order) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            race_id,
            w.get("window_type", "pitlane"),
            w.get("label"),
            w["start_s"],
            w["end_s"],
            w.get("refuel_allowed", 1),
            w.get("driver_change_allowed", 1),
            w.get("window_order", 1),
        ),
    )
```

In `load()`, add window loading (after pit stop loading, before `return cls(...)`):

```python
# Load windows
try:
    window_rows = conn.execute(
        "SELECT * FROM race_windows WHERE race_id = ? ORDER BY window_order",
        (race_id,),
    ).fetchall()
    windows = [dict(r) for r in window_rows]
except Exception:
    windows = []  # Pre-v23 databases without race_windows table
```

Set `engine.windows = windows` on the constructed engine before returning.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py::TestEnginePersistence -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/race_state_engine.py telemetry_tool/tests/test_race_state_engine.py
git commit -m "feat(engine): save/load race windows in persistence layer"
```

---

## Task 7: Routes — Window CRUD + Color + API State Enhancement

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (form handlers, _save_drivers, api_state)
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py`

**Step 1: Write failing tests**

Add to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestWindowRoutes:
    def test_windows_saved_with_race_create(self, client, strategy_db):
        """Windows posted in config form are saved to race_windows."""
        resp = client.post("/race-strategy/new", data={
            "race_name": "Test Race",
            "race_duration": "3:00",
            "driver_name_0": "Alice",
            "driver_order_0": "1",
            "window_type_0": "pitlane",
            "window_label_0": "Pit Window",
            "window_start_0": "0:30",
            "window_end_0": "2:30",
            "window_type_1": "refuel",
            "window_label_1": "Refuel 1",
            "window_start_1": "0:30",
            "window_end_1": "1:30",
        }, follow_redirects=True)
        assert resp.status_code == 200
        rows = strategy_db.execute(
            "SELECT * FROM race_windows WHERE race_id = 1 ORDER BY window_order"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["window_type"] == "pitlane"
        assert rows[1]["window_type"] == "refuel"

    def test_driver_color_saved(self, client, strategy_db):
        """Driver color_hex is saved from config form."""
        client.post("/race-strategy/new", data={
            "race_name": "Test",
            "race_duration": "3:00",
            "driver_name_0": "Alice",
            "driver_order_0": "1",
            "driver_color_0": "#ff0000",
        }, follow_redirects=True)
        row = strategy_db.execute(
            "SELECT color_hex FROM race_drivers WHERE race_id = 1"
        ).fetchone()
        assert row["color_hex"] == "#ff0000"

    def test_api_state_includes_window_status(self, client, strategy_db):
        """The /api/state response includes window_status."""
        # Create a race with windows
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, status, race_start_ts) "
            "VALUES ('R', 3600, 'live', datetime('now'))"
        )
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, color_hex) "
            "VALUES (1, 'A', 1, '#58a6ff')"
        )
        strategy_db.execute(
            "INSERT INTO race_windows (race_id, window_type, start_s, end_s, window_order) "
            "VALUES (1, 'pitlane', 600, 3000, 1)"
        )
        strategy_db.commit()

        resp = client.get("/race-strategy/1/api/state")
        data = resp.get_json()
        assert "window_status" in data
        assert isinstance(data["window_status"], list)
        assert data["drivers"][0]["color_hex"] == "#58a6ff"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_race_strategy_v2.py::TestWindowRoutes -v`
Expected: FAIL

**Step 3: Wire window saving into form handlers**

1. **Add `_save_windows()` helper** (near `_save_drivers`):

```python
def _save_windows(conn, race_id: int, form):
    """Save windows from form data. Expects window_type_N, etc."""
    conn.execute("DELETE FROM race_windows WHERE race_id = ?", (race_id,))
    i = 0
    while True:
        wtype = form.get(f"window_type_{i}")
        if wtype is None:
            break
        start = _parse_duration(form.get(f"window_start_{i}"))
        end = _parse_duration(form.get(f"window_end_{i}"))
        if not start and not end:
            i += 1
            continue
        conn.execute(
            "INSERT INTO race_windows (race_id, window_type, label, start_s, end_s, "
            "refuel_allowed, driver_change_allowed, window_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                race_id, wtype,
                form.get(f"window_label_{i}") or None,
                start or 0, end or 0,
                1 if form.get(f"window_refuel_{i}") else 0,
                1 if form.get(f"window_driver_change_{i}") else 0,
                i + 1,
            ),
        )
        i += 1
```

2. **Call `_save_windows()`** in `new_race()` (after `_save_drivers()`) and `update_race()` (after `_save_drivers()`).

3. **Add `color_hex` to `_save_drivers()`**: add `form.get(f"driver_color_{i}") or None` as the new column value in the INSERT.

4. **Enhance `api_state()`**: after engine loading, add:

```python
engine_data["window_status"] = engine.window_status(elapsed)
```

And ensure the drivers query result already includes `color_hex` (it does — `SELECT *` from `race_drivers`).

**Step 4: Run tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_race_strategy_v2.py::TestWindowRoutes -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(routes): window CRUD, driver color_hex, window_status in API"
```

---

## Task 8: Config Template — Window Editor + Color Picker

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/config.html:178-180` (after Pit Strategy section)
- Modify: `telemetry_tool/web/static/js/race_strategy.js` (window row JS interactions)

**Step 1: Add Pit Windows section to config.html**

After the existing "Pit Strategy" section closing `</section>` tag (~line 180), add:

```html
<!-- ── Pit Windows ────────────────────────── -->
<section class="section rs-form-section">
    <h2>Pit Windows</h2>
    <p style="font-size:0.85rem;color:var(--text-secondary);">
        Define time ranges for pit lane, refueling, and mandatory technical stops.
    </p>
    <div id="rs-windows-list">
        {% if race_windows %}
        {% for w in race_windows %}
        <div class="rs-window-row form-row" data-window-idx="{{ loop.index0 }}">
            <div class="form-group">
                <label>Type</label>
                <select name="window_type_{{ loop.index0 }}">
                    <option value="pitlane" {{ 'selected' if w.window_type == 'pitlane' }}>Pit Lane</option>
                    <option value="refuel" {{ 'selected' if w.window_type == 'refuel' }}>Refuel</option>
                    <option value="tech_stop" {{ 'selected' if w.window_type == 'tech_stop' }}>Tech Stop</option>
                </select>
            </div>
            <div class="form-group">
                <label>Label</label>
                <input type="text" name="window_label_{{ loop.index0 }}" value="{{ w.label or '' }}" placeholder="Window 1">
            </div>
            <div class="form-group">
                <label>Start (H:MM)</label>
                <input type="text" name="window_start_{{ loop.index0 }}"
                       value="{{ '%d:%02d' | format(w.start_s // 3600, (w.start_s % 3600) // 60) if w.start_s else '' }}"
                       placeholder="0:30">
            </div>
            <div class="form-group">
                <label>End (H:MM)</label>
                <input type="text" name="window_end_{{ loop.index0 }}"
                       value="{{ '%d:%02d' | format(w.end_s // 3600, (w.end_s % 3600) // 60) if w.end_s else '' }}"
                       placeholder="3:00">
            </div>
            <div class="form-group rs-window-rules" style="{{ 'display:none' if w.window_type != 'tech_stop' else '' }}">
                <label><input type="checkbox" name="window_refuel_{{ loop.index0 }}" {{ 'checked' if w.refuel_allowed }}> Refuel</label>
                <label><input type="checkbox" name="window_driver_change_{{ loop.index0 }}" {{ 'checked' if w.driver_change_allowed }}> Driver Change</label>
            </div>
            <button type="button" class="btn btn-ghost rs-remove-window" title="Remove">×</button>
        </div>
        {% endfor %}
        {% endif %}
    </div>
    <button type="button" id="rs-add-window" class="btn btn-ghost" style="margin-top:0.5rem;">+ Add Window</button>
</section>
```

**Step 2: Add driver color picker to driver rows**

In the existing driver row template (around line 75-85 in the driver card), add after the COM channel field:

```html
<div class="form-group" style="width:60px;">
    <label>Color</label>
    <input type="color" name="driver_color_{{ loop.index0 }}"
           value="{{ d.color_hex or '#58a6ff' }}"
           style="width:40px;height:30px;padding:0;border:none;cursor:pointer;">
</div>
```

**Step 3: Add JS for window row add/remove**

In `race_strategy.js`, add window management code:

```javascript
// ── Pit Window Rows ──────────────────────
var windowList = document.getElementById('rs-windows-list');
var addWindowBtn = document.getElementById('rs-add-window');

if (addWindowBtn && windowList) {
    var windowIdx = windowList.querySelectorAll('.rs-window-row').length;

    addWindowBtn.addEventListener('click', function() {
        // Build a new window row with incrementing index
        // ... (HTML template with windowIdx++)
    });

    windowList.addEventListener('click', function(e) {
        if (e.target.classList.contains('rs-remove-window')) {
            e.target.closest('.rs-window-row').remove();
        }
    });

    // Show/hide tech_stop rule checkboxes based on type selection
    windowList.addEventListener('change', function(e) {
        if (e.target.tagName === 'SELECT') {
            var rules = e.target.closest('.rs-window-row').querySelector('.rs-window-rules');
            if (rules) {
                rules.style.display = e.target.value === 'tech_stop' ? '' : 'none';
            }
        }
    });
}
```

**Step 4: Wire route to pass windows to template**

In `edit_race()` and `new_race()` (GET handler), query and pass `race_windows`:

```python
race_windows = _rows_to_list(conn.execute(
    "SELECT * FROM race_windows WHERE race_id = ? ORDER BY window_order", (race_id,)
).fetchall()) if race else []
```

Pass `race_windows=race_windows` to `render_template()`.

**Step 5: Test manually in browser**

- Create new race with 2 windows → verify saved to DB
- Edit race → verify windows pre-filled
- Add/remove window rows with JS → verify form works

**Step 6: Commit**

```bash
git add telemetry_tool/web/templates/race_strategy/config.html telemetry_tool/web/static/js/race_strategy.js telemetry_tool/web/routes/race_strategy_v2.py
git commit -m "feat(config): pit windows editor + driver color picker in config form"
```

---

## Task 9: Live Dashboard — Three-Card Window Status Bar

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html:40-53` (insert status bar)
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js:737-775` (replace updatePitWindow)
- Modify: `telemetry_tool/web/static/css/race_strategy.css` (add card styles)

**Step 1: Add HTML for three-card status bar**

In `live.html`, insert after `<div class="rs-live-grid" ...>` (line 40) and before `<!-- 1. Race Timer -->`:

```html
<!-- 0. Window Status Bar -->
<div class="rs-window-status-bar rs-full" id="rs-window-bar">
    <div class="rs-window-card rs-window-none" id="rs-window-pitlane">
        <div class="rs-window-card-type">PIT LANE</div>
        <div class="rs-window-card-status">Not configured</div>
        <div class="rs-window-card-countdown"></div>
    </div>
    <div class="rs-window-card rs-window-none" id="rs-window-refuel">
        <div class="rs-window-card-type">REFUEL</div>
        <div class="rs-window-card-status">Not configured</div>
        <div class="rs-window-card-countdown"></div>
    </div>
    <div class="rs-window-card rs-window-none" id="rs-window-tech_stop">
        <div class="rs-window-card-type">TECH STOP</div>
        <div class="rs-window-card-status">Not configured</div>
        <div class="rs-window-card-countdown"></div>
    </div>
</div>
```

**Step 2: Add CSS for window cards**

In `race_strategy.css`, add:

```css
.rs-window-status-bar {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.5rem;
    grid-column: 1 / -1;
}
.rs-window-card {
    padding: 0.75rem;
    border-radius: 6px;
    text-align: center;
    border: 2px solid transparent;
    transition: all 0.3s;
}
.rs-window-card-type {
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-bottom: 0.25rem;
}
.rs-window-card-status { font-weight: 600; font-size: 0.95rem; }
.rs-window-card-countdown { font-size: 0.85rem; font-variant-numeric: tabular-nums; }

.rs-window-none { background: var(--bg-secondary); color: var(--text-secondary); border-color: var(--border); }
.rs-window-before { background: rgba(255, 200, 50, 0.1); color: #ffc832; border-color: #ffc832; }
.rs-window-open { background: rgba(126, 231, 135, 0.1); color: #7ee787; border-color: #7ee787; }
.rs-window-closing { background: rgba(255, 166, 87, 0.15); color: #ffa657; border-color: #ffa657; animation: rs-pulse 1s infinite; }
.rs-window-closed { background: rgba(248, 81, 73, 0.1); color: #f85149; border-color: #f85149; }

@keyframes rs-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
}
```

**Step 3: Replace updatePitWindow() in JS**

In `race_strategy_live.js`, replace the existing `updatePitWindow()` function (lines 737-775) with:

```javascript
function updateWindowStatus() {
    if (!state || !state.window_status) {
        // Fallback: use legacy pit window logic if no window_status
        updatePitWindowLegacy();
        return;
    }
    var bar = document.getElementById('rs-window-bar');
    if (!bar) return;

    state.window_status.forEach(function(ws) {
        var card = document.getElementById('rs-window-' + ws.type);
        if (!card) return;

        var statusEl = card.querySelector('.rs-window-card-status');
        var countdownEl = card.querySelector('.rs-window-card-countdown');

        card.className = 'rs-window-card rs-window-' + ws.status;

        if (ws.status === 'none') {
            statusEl.textContent = 'Not configured';
            countdownEl.textContent = '';
        } else if (ws.status === 'before') {
            statusEl.textContent = 'Opens in';
            countdownEl.textContent = fmtShort(ws.countdown_s);
        } else if (ws.status === 'open') {
            statusEl.textContent = 'OPEN';
            countdownEl.textContent = 'Closes in ' + fmtShort(ws.countdown_s);
        } else if (ws.status === 'closing') {
            statusEl.textContent = 'CLOSING';
            countdownEl.textContent = fmtShort(ws.countdown_s);
        } else if (ws.status === 'closed') {
            statusEl.textContent = 'CLOSED';
            countdownEl.textContent = '';
        }
    });

    // Update end-stint button warning based on pitlane status
    var pitStatus = state.window_status.find(function(w) { return w.type === 'pitlane'; });
    var endBtn = document.getElementById('rs-btn-end-stint');
    if (endBtn && pitStatus) {
        if (pitStatus.status === 'before' || pitStatus.status === 'closed') {
            endBtn.classList.add('rs-btn-pit-warning');
        } else {
            endBtn.classList.remove('rs-btn-pit-warning');
        }
    }
}
```

Keep the old `updatePitWindow()` renamed to `updatePitWindowLegacy()` as fallback.

Update the 1s tick to call `updateWindowStatus()` instead of `updatePitWindow()`.

**Step 4: Test in browser**

- Create a race with pitlane + refuel windows → go live → verify three cards show
- Watch countdowns tick down
- Verify pulsing animation when closing

**Step 5: Commit**

```bash
git add telemetry_tool/web/templates/race_strategy/live.html telemetry_tool/web/static/js/race_strategy_live.js telemetry_tool/web/static/css/race_strategy.css
git commit -m "feat(live): three-card window status bar with live countdowns"
```

---

## Task 10: Live Dashboard — Compact Pit Wall Mode + Fullscreen + Wall Clock

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html:22-29` (toolbar buttons)
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js:700-733` (layout logic)
- Modify: `telemetry_tool/web/static/css/race_strategy.css` (compact mode CSS)

**Step 1: Add toolbar buttons**

In `live.html` toolbar area (line 22-28), add Pit Wall + Fullscreen + Wall Clock:

```html
<div style="display:flex;gap:0.5rem;align-items:center;">
    <span class="rs-wall-clock" id="rs-wall-clock" style="font-variant-numeric:tabular-nums;font-size:0.85rem;color:var(--text-secondary);"></span>
    <div class="rs-layout-toggle" id="rs-layout-toggle">
        <button type="button" class="rs-toggle-btn rs-toggle-active" data-layout="grid" title="Grid view">Grid</button>
        <button type="button" class="rs-toggle-btn" data-layout="vertical" title="Vertical view">Vertical</button>
        <button type="button" class="rs-toggle-btn" data-layout="compact" title="Pit Wall mode">Pit Wall</button>
    </div>
    <button type="button" class="btn btn-ghost" id="rs-btn-fullscreen" title="Toggle fullscreen">Fullscreen</button>
    <a href="{{ url_for('race_strategy_v2.detail', race_id=race.race_id) }}" class="btn btn-ghost">Detail</a>
</div>
```

**Step 2: Add compact mode CSS**

```css
/* Compact Pit Wall Mode */
.rs-live-grid.rs-compact {
    grid-template-columns: repeat(4, 1fr);
    gap: 0.5rem;
}
.rs-live-grid.rs-compact .rs-live-card.rs-full {
    display: none;  /* Hide stint log, summary, team talk */
}
.rs-live-grid.rs-compact .rs-window-status-bar {
    grid-column: 1 / -1;
}
.rs-live-grid.rs-compact .rs-live-card {
    grid-column: span 1;  /* Each card takes one column */
}

/* Fullscreen adjustments */
:fullscreen .rs-page-live {
    padding: 1rem;
    background: var(--bg-primary);
}
:fullscreen .page-header h1 { font-size: 1.2rem; }
```

**Step 3: Add JS for compact mode, fullscreen, and wall clock**

In `race_strategy_live.js`, enhance the layout logic:

```javascript
// ── Layout Toggle (enhanced with compact) ────
function applyLayout(layout) {
    var grid = document.getElementById('rs-live-root');
    if (!grid) return;
    grid.classList.remove('rs-vertical', 'rs-compact');
    if (layout === 'vertical') grid.classList.add('rs-vertical');
    if (layout === 'compact') grid.classList.add('rs-compact');

    // Update toggle button active state
    var btns = document.querySelectorAll('.rs-toggle-btn');
    btns.forEach(function(b) {
        b.classList.toggle('rs-toggle-active', b.getAttribute('data-layout') === layout);
    });
    try { localStorage.setItem('rs-live-layout', layout); } catch(e) {}
}

// ── Fullscreen ───────────────────────────────
var fsBtn = document.getElementById('rs-btn-fullscreen');
if (fsBtn) {
    fsBtn.addEventListener('click', function() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(function() {});
        } else {
            document.exitFullscreen();
        }
    });
    document.addEventListener('fullscreenchange', function() {
        fsBtn.textContent = document.fullscreenElement ? 'Exit Fullscreen' : 'Fullscreen';
    });
}

// ── Wall Clock ───────────────────────────────
function updateWallClock() {
    var el = document.getElementById('rs-wall-clock');
    if (!el) return;
    var now = new Date();
    el.textContent = pad2(now.getHours()) + ':' + pad2(now.getMinutes()) + ':' + pad2(now.getSeconds());
}
```

Add `updateWallClock()` to the 1s setInterval.

**Step 4: Test in browser**

- Click "Pit Wall" → verify only 4 cards + window bar visible
- Click "Fullscreen" → verify browser enters fullscreen
- Verify wall clock ticks every second
- Verify layout persists in localStorage

**Step 5: Commit**

```bash
git add telemetry_tool/web/templates/race_strategy/live.html telemetry_tool/web/static/js/race_strategy_live.js telemetry_tool/web/static/css/race_strategy.css
git commit -m "feat(live): compact pit wall mode, fullscreen toggle, wall clock"
```

---

## Task 11: Live Dashboard — Driver Colors from DB

**Files:**
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js:52-54` (driverColor function)
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js` (timeline, bar chart, stint log rendering)

**Step 1: Enhance driverColor function**

Replace the existing `driverColor(driverOrder)` function:

```javascript
function driverColor(driverIdOrOrder, isOrder) {
    // Try to get DB color from state.drivers
    if (state && state.drivers) {
        var driver;
        if (isOrder) {
            driver = state.drivers.find(function(d) { return d.driver_order === driverIdOrOrder; });
        } else {
            driver = state.drivers.find(function(d) { return d.id === driverIdOrOrder; });
        }
        if (driver && driver.color_hex) return driver.color_hex;
        if (driver) return DRIVER_COLORS[(driver.driver_order - 1) % DRIVER_COLORS.length];
    }
    // Fallback to positional palette
    var idx = (typeof driverIdOrOrder === 'number' ? driverIdOrOrder - 1 : 0);
    return DRIVER_COLORS[idx % DRIVER_COLORS.length];
}
```

**Step 2: Update all usages of driverColor**

Find all places where `driverColor()` is called and ensure they pass the correct parameter. The key places are:

1. Timeline blocks — use `driverColor(stint.driver_id, false)`
2. Driver bar chart — use `driverColor(driver.driver_order, true)`
3. Stint log driver name — use color from stint's driver

**Step 3: Test in browser**

- Set driver colors in config → go live → verify timeline uses custom colors
- Verify fallback to palette when no color set

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/js/race_strategy_live.js
git commit -m "feat(live): driver colors from DB with palette fallback"
```

---

## Task 12: Full Verification

**Step 1: Run all engine tests**

Run: `python -m pytest telemetry_tool/tests/test_race_state_engine.py -v`
Expected: ALL PASS (31 existing + ~15 new window tests)

**Step 2: Run all route tests**

Run: `python -m pytest telemetry_tool/tests/test_race_strategy_v2.py -v`
Expected: ALL PASS (50 existing + ~6 new window/color tests)

**Step 3: Run full test suite**

Run: `python -m pytest telemetry_tool/tests/ -v`
Expected: ALL PASS

**Step 4: Manual browser verification**

1. Create new race with pit windows → verify saved
2. Edit race → verify windows pre-filled
3. Optimize → go live → verify three-card status bar
4. Test compact pit wall mode
5. Test fullscreen
6. Test wall clock
7. Test driver colors in timeline
8. Test window countdowns tick down

**Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(tier5): address any issues found in verification"
```
