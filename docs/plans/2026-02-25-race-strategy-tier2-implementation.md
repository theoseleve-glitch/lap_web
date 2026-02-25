# Race Strategy Tier 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add import/export (JSON), vertical/grid layout toggle, qualifying-aware fuel optimization, and pit window enforcement to the race strategy tool.

**Architecture:** All features extend existing files — no new modules. Optimizer gets pit-window and qualifying logic. Blueprint gets export/import routes. Live JS gets layout toggle and pit window banner. No schema changes.

**Tech Stack:** Python/Flask, SQLite, vanilla JS, existing CSS design system.

---

### Task 1: Import/Export — Tests + Export Route

**Files:**
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py` (append)
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (add export route)

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestImportExport:
    """JSON import/export for race configs."""

    def test_export_structure(self, strategy_db):
        """Export produces valid JSON with all sections."""
        from web.routes.race_strategy_v2 import _build_export_dict

        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, desired_stints) VALUES ('Export Test', 7200, 4)"
        )
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'A', 1, 70)")
        strategy_db.execute("INSERT INTO race_stints (race_id, stint_order, driver_id, planned_duration_s, status) VALUES (1, 1, 1, 1800, 'planned')")
        strategy_db.execute("INSERT INTO race_pit_stops (race_id, driver_change, refueled) VALUES (1, 1, 0)")
        strategy_db.commit()

        result = _build_export_dict(strategy_db, 1)
        assert result["version"] == 1
        assert result["race"]["race_name"] == "Export Test"
        assert len(result["drivers"]) == 1
        assert len(result["stints"]) == 1
        assert len(result["pit_stops"]) == 1

    def test_import_creates_race(self, strategy_db):
        """Import JSON creates a new race in draft status."""
        from web.routes.race_strategy_v2 import _import_race_from_dict

        data = {
            "version": 1,
            "race": {
                "race_name": "Imported Race",
                "race_duration_s": 10800,
                "desired_stints": 3,
                "min_pit_stop_s": 60,
                "status": "finished",
            },
            "drivers": [
                {"driver_name": "Alice", "driver_order": 1, "weight_kg": 70,
                 "min_stint_s": None, "max_stint_s": None,
                 "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
                {"driver_name": "Bob", "driver_order": 2, "weight_kg": 80,
                 "min_stint_s": None, "max_stint_s": None,
                 "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            ],
            "stints": [],
            "pit_stops": [],
        }

        race_id = _import_race_from_dict(strategy_db, data)
        assert race_id >= 1

        race = strategy_db.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
        assert race["race_name"] == "Imported Race"
        assert race["status"] == "draft"  # Always draft on import

        drivers = strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)).fetchall()
        assert len(drivers) == 2
        assert drivers[0]["driver_name"] == "Alice"

    def test_import_remaps_driver_ids_in_stints(self, strategy_db):
        """Import remaps old driver IDs to new auto-increment IDs."""
        from web.routes.race_strategy_v2 import _import_race_from_dict

        data = {
            "version": 1,
            "race": {"race_name": "Remap Test", "race_duration_s": 3600, "min_pit_stop_s": 60},
            "drivers": [
                {"id": 99, "driver_name": "Old", "driver_order": 1, "weight_kg": 70,
                 "min_stint_s": None, "max_stint_s": None,
                 "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
            ],
            "stints": [
                {"stint_order": 1, "driver_id": 99, "planned_duration_s": 1800,
                 "planned_start_s": 0, "planned_end_s": 1800, "status": "planned",
                 "ballast_kg": 0, "actual_start_s": None, "actual_end_s": None,
                 "actual_duration_s": None, "notes": None},
            ],
            "pit_stops": [],
        }

        race_id = _import_race_from_dict(strategy_db, data)
        stints = strategy_db.execute("SELECT * FROM race_stints WHERE race_id = ?", (race_id,)).fetchall()
        assert len(stints) == 1
        # The driver_id should be the NEW auto-increment id, not 99
        new_driver = strategy_db.execute("SELECT id FROM race_drivers WHERE race_id = ?", (race_id,)).fetchone()
        assert stints[0]["driver_id"] == new_driver["id"]

    def test_import_rejects_missing_name(self, strategy_db):
        """Import rejects JSON without race_name."""
        from web.routes.race_strategy_v2 import _import_race_from_dict

        data = {"version": 1, "race": {"race_duration_s": 3600}, "drivers": [], "stints": [], "pit_stops": []}
        with pytest.raises(ValueError, match="race_name"):
            _import_race_from_dict(strategy_db, data)

    def test_roundtrip_export_import(self, strategy_db):
        """Export then import produces equivalent race."""
        from web.routes.race_strategy_v2 import _build_export_dict, _import_race_from_dict

        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, desired_stints, team_name) "
            "VALUES ('Roundtrip', 7200, 4, 'Team X')"
        )
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'A', 1, 70)")
        strategy_db.execute("INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) VALUES (1, 'B', 2, 80)")
        strategy_db.commit()

        exported = _build_export_dict(strategy_db, 1)
        new_id = _import_race_from_dict(strategy_db, exported)

        new_race = dict(strategy_db.execute("SELECT * FROM race_configs WHERE race_id = ?", (new_id,)).fetchone())
        assert new_race["race_name"] == "Roundtrip"
        assert new_race["team_name"] == "Team X"
        assert new_race["race_duration_s"] == 7200

        new_drivers = strategy_db.execute("SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (new_id,)).fetchall()
        assert len(new_drivers) == 2
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestImportExport -v`
Expected: FAIL — `_build_export_dict` not found

**Step 3: Implement export route and helpers**

In `telemetry_tool/web/routes/race_strategy_v2.py`, add before the helpers section (`# ── Helpers`):

```python
# ── Import / Export ──────────────────────────────

@bp.route("/<int:race_id>/export")
def export(race_id: int):
    """Export race as JSON file download."""
    conn = get_db_connection()
    race = conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
    if not race:
        abort(404)

    data = _build_export_dict(conn, race_id)
    payload = json.dumps(data, indent=2, default=str)

    # Slugify name for filename
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', race["race_name"].lower()).strip('-')
    date = (race["created_at"] or "")[:10]
    filename = f"race-{slug}-{date}.json"

    from flask import Response
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_export_dict(conn, race_id: int) -> dict:
    """Build the full export dictionary for a race."""
    from datetime import datetime, timezone

    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? ORDER BY stint_order", (race_id,)
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY pit_id", (race_id,)
    ).fetchall())

    return {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
    }
```

**Step 4: Implement import route and helper**

Add after the export route:

```python
@bp.route("/import", methods=["POST"])
def import_race():
    """Import race from JSON file upload."""
    from flask import flash

    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("race_strategy_v2.index"))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        flash("Invalid JSON file.", "error")
        return redirect(url_for("race_strategy_v2.index"))

    conn = get_db_connection()
    try:
        race_id = _import_race_from_dict(conn, data)
        conn.commit()
    except ValueError as e:
        flash(f"Import failed: {e}", "error")
        return redirect(url_for("race_strategy_v2.index"))

    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))


def _import_race_from_dict(conn, data: dict) -> int:
    """Import a race from an export dict. Returns new race_id."""
    race = data.get("race", {})
    if not race.get("race_name"):
        raise ValueError("Missing required field: race_name")
    if not race.get("race_duration_s"):
        raise ValueError("Missing required field: race_duration_s")

    # Insert race config (always as draft)
    cur = conn.execute(
        """INSERT INTO race_configs (
            race_name, track_name, team_name, race_duration_s,
            reference_weight_kg, desired_stints, fuel_autonomy_s,
            min_pit_stop_s, pit_speed_kmh, pit_open_s, pit_close_s,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft')""",
        (
            race.get("race_name"), race.get("track_name"), race.get("team_name"),
            race["race_duration_s"], race.get("reference_weight_kg"),
            race.get("desired_stints", 4), race.get("fuel_autonomy_s"),
            race.get("min_pit_stop_s", 60), race.get("pit_speed_kmh"),
            race.get("pit_open_s"), race.get("pit_close_s"),
            race.get("empty_kart_kg"), race.get("full_tank_kg"),
            race.get("min_total_kart_kg"), race.get("weigh_on_pit_exit", 0),
            race.get("qualifying_duration_s"), race.get("refuel_after_quali", 0),
            race.get("mandatory_driver_change", 1), race.get("refueling_allowed", 1),
        ),
    )
    new_race_id = cur.lastrowid

    # Insert drivers, building old_id -> new_id map
    id_map = {}  # old driver id -> new driver id
    for d in data.get("drivers", []):
        old_id = d.get("id")
        cur = conn.execute(
            """INSERT INTO race_drivers (
                race_id, driver_name, driver_order, min_stint_s, max_stint_s,
                min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                new_race_id, d["driver_name"], d.get("driver_order", 1),
                d.get("min_stint_s"), d.get("max_stint_s"),
                d.get("min_cumulative_s"), d.get("max_cumulative_s"),
                d.get("min_rest_s", 0), d.get("weight_kg"),
            ),
        )
        if old_id is not None:
            id_map[old_id] = cur.lastrowid

    # Insert stints with remapped driver IDs
    for s in data.get("stints", []):
        old_driver_id = s.get("driver_id")
        new_driver_id = id_map.get(old_driver_id, old_driver_id)
        conn.execute(
            """INSERT INTO race_stints (
                race_id, stint_order, driver_id, planned_start_s, planned_end_s,
                planned_duration_s, actual_start_s, actual_end_s, actual_duration_s,
                ballast_kg, notes, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_race_id, s.get("stint_order", 1), new_driver_id,
                s.get("planned_start_s"), s.get("planned_end_s"),
                s.get("planned_duration_s"), s.get("actual_start_s"),
                s.get("actual_end_s"), s.get("actual_duration_s"),
                s.get("ballast_kg", 0), s.get("notes"), s.get("status", "planned"),
            ),
        )

    # Insert pit stops
    for p in data.get("pit_stops", []):
        conn.execute(
            """INSERT INTO race_pit_stops (
                race_id, planned_at_s, actual_at_s, duration_s,
                driver_change, refueled, fuel_added_kg, ballast_changed, notes
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                new_race_id, p.get("planned_at_s"), p.get("actual_at_s"),
                p.get("duration_s"), p.get("driver_change", 1),
                p.get("refueled", 0), p.get("fuel_added_kg"),
                p.get("ballast_changed", 0), p.get("notes"),
            ),
        )

    return new_race_id
```

**Step 5: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestImportExport -v`
Expected: 5 PASSED

**Step 6: Add UI buttons to templates**

In `telemetry_tool/web/templates/race_strategy/index.html`, after the `+ New Race` button in the page-header, add:

```html
    <div style="display:flex;gap:0.5rem;">
        <form method="POST" action="{{ url_for('race_strategy_v2.import_race') }}" enctype="multipart/form-data"
              style="display:flex;gap:0.5rem;align-items:center;">
            <input type="file" name="file" accept=".json" required style="max-width:200px;">
            <button type="submit" class="btn btn-ghost">Import</button>
        </form>
        <a href="{{ url_for('race_strategy_v2.new_race') }}" class="btn btn-primary">+ New Race</a>
    </div>
```

(Replace the existing standalone `+ New Race` link.)

In `telemetry_tool/web/templates/race_strategy/detail.html`, add an export button next to the existing action buttons:

```html
    <a href="{{ url_for('race_strategy_v2.export', race_id=race.race_id) }}" class="btn btn-ghost">Export JSON</a>
```

In `telemetry_tool/web/templates/race_strategy/summary.html`, add an export button in the actions section:

```html
    <a href="{{ url_for('race_strategy_v2.export', race_id=race.race_id) }}" class="btn btn-ghost">Export JSON</a>
```

**Step 7: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/tests/test_race_strategy_v2.py telemetry_tool/web/templates/race_strategy/index.html telemetry_tool/web/templates/race_strategy/detail.html telemetry_tool/web/templates/race_strategy/summary.html
git commit -m "feat(race-strategy): add JSON import/export with driver ID remapping"
```

---

### Task 2: Vertical/Grid Layout Toggle

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html`
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js`
- Modify: `telemetry_tool/web/static/css/race_strategy.css`

**Step 1: Add toggle HTML to live.html**

In `telemetry_tool/web/templates/race_strategy/live.html`, replace the header `<div style="display:flex;gap:0.5rem;">` section with:

```html
    <div style="display:flex;gap:0.5rem;align-items:center;">
        <div class="rs-layout-toggle" id="rs-layout-toggle">
            <button type="button" class="rs-toggle-btn rs-toggle-active" data-layout="grid" title="Grid view">Grid</button>
            <button type="button" class="rs-toggle-btn" data-layout="vertical" title="Vertical view">Vertical</button>
        </div>
        <a href="{{ url_for('race_strategy_v2.detail', race_id=race.race_id) }}" class="btn btn-ghost">Detail</a>
    </div>
```

**Step 2: Add CSS for toggle and vertical layout**

Append to `telemetry_tool/web/static/css/race_strategy.css`:

```css
/* Layout toggle */
.rs-layout-toggle {
    display: flex;
    border: 1px solid var(--border);
    border-radius: 4px;
    overflow: hidden;
}
.rs-toggle-btn {
    background: transparent;
    border: none;
    padding: 0.25rem 0.6rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
    cursor: pointer;
}
.rs-toggle-btn.rs-toggle-active {
    background: var(--blue);
    color: #fff;
}

/* Vertical layout */
.rs-live-grid.rs-vertical {
    grid-template-columns: 1fr;
}
```

**Step 3: Add JS toggle logic**

In `telemetry_tool/web/static/js/race_strategy_live.js`, add after the `// ── Init` section, before `fetchState()`:

```javascript
    // ── Layout Toggle ────────────────────────────

    var toggleContainer = document.getElementById('rs-layout-toggle');
    var grid = document.getElementById('rs-live-root');

    function applyLayout(layout) {
        if (!grid) return;
        if (layout === 'vertical') {
            grid.classList.add('rs-vertical');
        } else {
            grid.classList.remove('rs-vertical');
        }
        // Update toggle button states
        if (toggleContainer) {
            var btns = toggleContainer.querySelectorAll('.rs-toggle-btn');
            btns.forEach(function(btn) {
                if (btn.getAttribute('data-layout') === layout) {
                    btn.classList.add('rs-toggle-active');
                } else {
                    btn.classList.remove('rs-toggle-active');
                }
            });
        }
        try { localStorage.setItem('rs-live-layout', layout); } catch(e) {}
    }

    // Restore saved preference
    try {
        var saved = localStorage.getItem('rs-live-layout');
        if (saved === 'vertical') applyLayout('vertical');
    } catch(e) {}

    if (toggleContainer) {
        toggleContainer.addEventListener('click', function(e) {
            var btn = e.target.closest('.rs-toggle-btn');
            if (btn) applyLayout(btn.getAttribute('data-layout'));
        });
    }
```

**Step 4: Verify manually**

Visit `/race-strategy/<id>/live`, click Grid/Vertical toggle, reload page, verify preference persists.

**Step 5: Commit**

```bash
git add telemetry_tool/web/templates/race_strategy/live.html telemetry_tool/web/static/js/race_strategy_live.js telemetry_tool/web/static/css/race_strategy.css
git commit -m "feat(race-strategy): add vertical/grid layout toggle on live dashboard"
```

---

### Task 3: Qualifying-Aware Optimizer

**Files:**
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py` (append)
- Modify: `telemetry_tool/race_strategy_v2.py`
- Modify: `telemetry_tool/web/templates/race_strategy/detail.html`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestQualifyingFuel:
    """Qualifying fuel deduction in optimizer."""

    def test_qualifying_no_refuel_reduces_first_stint(self):
        """Without refuel-after-quali, first stint fuel is reduced."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 2,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": 2400,
            "qualifying_duration_s": 600,  # 10 min quali
            "refuel_after_quali": 0,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
        # First stint should be capped at fuel_autonomy - qualifying_duration
        assert result["stints"][0]["planned_duration_s"] <= 2400 - 600

    def test_qualifying_with_refuel_no_change(self):
        """With refuel-after-quali, first stint uses full autonomy."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 2,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": 2400,
            "qualifying_duration_s": 600,
            "refuel_after_quali": 1,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
        # First stint can use full autonomy
        assert result["stints"][0]["planned_duration_s"] <= 2400

    def test_qualifying_no_fuel_autonomy_no_effect(self):
        """Without fuel_autonomy_s, qualifying has no optimizer effect."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 2,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
            "qualifying_duration_s": 600,
            "refuel_after_quali": 0,
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        assert result["feasible"] is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestQualifyingFuel -v`
Expected: FAIL — first stint not capped correctly

**Step 3: Implement qualifying fuel logic in optimizer**

In `telemetry_tool/race_strategy_v2.py`, in `optimize_stints()`, after the fuel_autonomy variable is set (line 60), add:

```python
    # Qualifying fuel deduction: first stint has less fuel if not refueled after quali
    quali_duration = config.get("qualifying_duration_s") or 0
    refuel_after_quali = config.get("refuel_after_quali", 0)
    first_stint_autonomy = fuel_autonomy
    if fuel_autonomy and quali_duration and not refuel_after_quali:
        first_stint_autonomy = max(0, fuel_autonomy - quali_duration)
```

Then in the stint assignment loop, where fuel autonomy is applied (the `if fuel_autonomy and duration > fuel_autonomy` block), change to:

```python
        # Apply fuel autonomy (reduced for first stint if qualifying without refuel)
        effective_autonomy = first_stint_autonomy if (i == 0 and first_stint_autonomy is not None) else fuel_autonomy
        if effective_autonomy and duration > effective_autonomy:
            duration = effective_autonomy
```

And in the slack redistribution, the fuel_autonomy cap check also needs the per-stint autonomy:

```python
            effective_autonomy = first_stint_autonomy if (idx == 0 and first_stint_autonomy is not None) else fuel_autonomy
            if effective_autonomy and s["planned_duration_s"] + extra > effective_autonomy:
                extra = max(0, effective_autonomy - s["planned_duration_s"])
```

Also update `_stint_cap()` — it doesn't know about stint index, so the per-stint cap must be applied inline in the loop (already handled above).

**Step 4: Add qualifying card to detail page**

In `telemetry_tool/web/templates/race_strategy/detail.html`, after the weight card in the detail grid, add:

```html
    {% if race.qualifying_duration_s %}
    <div class="rs-detail-card">
        <h3>Qualifying</h3>
        <div class="rs-kv"><span class="rs-kv-label">Duration</span><span>{{ '%d:%02d' | format(race.qualifying_duration_s // 60, race.qualifying_duration_s % 60) }}</span></div>
        <div class="rs-kv"><span class="rs-kv-label">Refuel After</span><span>{{ 'Yes' if race.refuel_after_quali else 'No' }}</span></div>
        {% if race.fuel_autonomy_s and not race.refuel_after_quali %}
        <div class="rs-kv"><span class="rs-kv-label">First Stint Fuel</span><span>{{ '%d:%02d' | format((race.fuel_autonomy_s - race.qualifying_duration_s) // 60, (race.fuel_autonomy_s - race.qualifying_duration_s) % 60) }}</span></div>
        {% endif %}
    </div>
    {% endif %}
```

**Step 5: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestQualifyingFuel -v`
Expected: 3 PASSED

**Step 6: Commit**

```bash
git add telemetry_tool/race_strategy_v2.py telemetry_tool/tests/test_race_strategy_v2.py telemetry_tool/web/templates/race_strategy/detail.html
git commit -m "feat(race-strategy): add qualifying fuel deduction to optimizer"
```

---

### Task 4: Pit Window Enforcement — Optimizer

**Files:**
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py` (append)
- Modify: `telemetry_tool/race_strategy_v2.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestPitWindows:
    """Pit window enforcement in optimizer."""

    def test_pit_open_delays_first_pit(self):
        """First pit stop should not happen before pit_open_s."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
            "pit_open_s": 1800,  # pit opens at 30 min
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
        assert result["feasible"] is True
        # First pit stop (end of stint 1) should be >= pit_open_s
        assert result["stints"][0]["planned_end_s"] >= 1800

    def test_pit_close_ensures_last_pit_before_close(self):
        """Last pit stop should happen before pit_close_s from end."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 7200,
            "desired_stints": 3,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
            "pit_close_s": 1800,  # pit closes 30 min before end = at 5400s
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
        assert result["feasible"] is True
        # Last pit stop should be before close time (7200 - 1800 = 5400)
        if result["pit_stops"]:
            last_pit = result["pit_stops"][-1]
            assert last_pit["at_s"] <= 5400

    def test_pit_window_warning_when_violated(self):
        """When constraints force a pit outside window, add warning."""
        from race_strategy_v2 import optimize_stints
        config = {
            "race_duration_s": 3600,
            "desired_stints": 4,
            "min_pit_stop_s": 60,
            "fuel_autonomy_s": None,
            "pit_open_s": 2400,  # pit opens very late
        }
        drivers = [
            {"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 70,
             "min_stint_s": None, "max_stint_s": None,
             "min_cumulative_s": None, "max_cumulative_s": None, "min_rest_s": 0},
        ]
        result = optimize_stints(config, drivers)
        # Should have warnings about pit window violations
        pit_warnings = [w for w in result["warnings"] if "pit window" in w.lower()]
        assert len(pit_warnings) > 0 or result["stints"][0]["planned_end_s"] >= 2400
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestPitWindows -v`
Expected: FAIL — optimizer doesn't respect pit windows yet

**Step 3: Implement pit window logic in optimizer**

In `telemetry_tool/race_strategy_v2.py`, in `optimize_stints()`, after the qualifying fuel variables, add:

```python
    pit_open = config.get("pit_open_s")
    pit_close_before_end = config.get("pit_close_s")
    pit_close = (race_duration - pit_close_before_end) if pit_close_before_end else None
```

After the stint assignment loop and before slack redistribution, add pit window adjustment:

```python
    # Pit window enforcement: adjust stint boundaries
    if pit_open and len(stints) > 1:
        first_stint = stints[0]
        if first_stint["planned_end_s"] < pit_open:
            # Extend first stint to reach pit window opening
            deficit = pit_open - first_stint["planned_end_s"]
            first_stint["planned_duration_s"] += deficit
            first_stint["planned_end_s"] = pit_open
            # Rebuild clock from first stint
            clock = first_stint["planned_end_s"] + pit_time
            for j in range(1, len(stints)):
                stints[j]["planned_start_s"] = round(clock)
                stints[j]["planned_end_s"] = round(clock + stints[j]["planned_duration_s"])
                clock += stints[j]["planned_duration_s"]
                if j < len(stints) - 1:
                    clock += pit_time

    if pit_close and len(stints) > 1:
        # Ensure last pit stop is before close time
        last_pit_idx = len(stints) - 2  # pit after second-to-last stint
        last_pit_at = stints[last_pit_idx]["planned_end_s"]
        if last_pit_at > pit_close:
            # Shorten second-to-last stint to fit, extend last stint
            overshoot = last_pit_at - pit_close
            stints[last_pit_idx]["planned_duration_s"] -= overshoot
            stints[last_pit_idx]["planned_end_s"] -= overshoot
            stints[-1]["planned_start_s"] -= overshoot
            stints[-1]["planned_duration_s"] += overshoot
```

After pit stop generation, add window violation warnings:

```python
    # Check pit window violations
    if pit_open:
        for p in pit_stops:
            if p["at_s"] < pit_open:
                warnings.append(f"Pit stop at {p['at_s']}s is before pit window opens at {pit_open}s")
    if pit_close:
        for p in pit_stops:
            if p["at_s"] > pit_close:
                warnings.append(f"Pit stop at {p['at_s']}s is after pit window closes at {pit_close}s")
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestPitWindows -v`
Expected: 3 PASSED

**Step 5: Run full test suite**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py -v`
Expected: ALL PASSED (no regressions to earlier optimizer tests)

**Step 6: Commit**

```bash
git add telemetry_tool/race_strategy_v2.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(race-strategy): add pit window enforcement to optimizer"
```

---

### Task 5: Pit Window Banner on Live Dashboard

**Files:**
- Modify: `telemetry_tool/web/templates/race_strategy/live.html`
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js`
- Modify: `telemetry_tool/web/static/css/race_strategy.css`

**Step 1: Add pit window data attributes and banner HTML**

In `telemetry_tool/web/templates/race_strategy/live.html`, on the `rs-live-root` div, add data attributes:

```
     data-pit-open="{{ race.pit_open_s or 0 }}"
     data-pit-close="{{ race.pit_close_s or 0 }}"
```

Inside the Race Timer card, after the stint count line, add:

```html
        <div id="rs-pit-window-banner" class="rs-pit-banner" style="display:none;"></div>
```

**Step 2: Add CSS for pit window banner**

Append to `telemetry_tool/web/static/css/race_strategy.css`:

```css
/* Pit window banner */
.rs-pit-banner {
    text-align: center;
    padding: 0.3rem 0.5rem;
    border-radius: 4px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-top: 0.5rem;
}
.rs-pit-banner-before { background: rgba(150,150,150,0.15); color: var(--text-secondary); }
.rs-pit-banner-open { background: rgba(63,185,80,0.2); color: var(--green); }
.rs-pit-banner-closing { background: rgba(210,153,34,0.2); color: var(--yellow, #d29922); }
.rs-pit-banner-closed { background: rgba(248,81,73,0.15); color: var(--red, #f85149); }

/* End stint warning */
.rs-btn-pit-warning { position: relative; }
.rs-btn-pit-warning::after {
    content: '!';
    position: absolute;
    top: -6px;
    right: -6px;
    background: var(--yellow, #d29922);
    color: #000;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    font-size: 0.7rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
}
```

**Step 3: Add JS pit window logic**

In `telemetry_tool/web/static/js/race_strategy_live.js`, add variables after the existing config reads:

```javascript
    var PIT_OPEN  = parseInt(root.getAttribute('data-pit-open'), 10) || 0;
    var PIT_CLOSE_BEFORE_END = parseInt(root.getAttribute('data-pit-close'), 10) || 0;
    var PIT_CLOSE = PIT_CLOSE_BEFORE_END ? RACE_DURATION - PIT_CLOSE_BEFORE_END : 0;
```

Add a new update function:

```javascript
    // ── Pit Window Banner ────────────────────────

    function updatePitWindow() {
        var banner = document.getElementById('rs-pit-window-banner');
        var endBtn = document.getElementById('rs-btn-end-stint');
        if (!banner) return;
        if (!PIT_OPEN && !PIT_CLOSE) { banner.style.display = 'none'; return; }

        var elapsed = getElapsed();
        banner.style.display = 'block';

        var outsideWindow = false;

        if (PIT_OPEN && elapsed < PIT_OPEN) {
            var until = PIT_OPEN - elapsed;
            banner.textContent = 'Pit window opens in ' + fmtShort(until);
            banner.className = 'rs-pit-banner rs-pit-banner-before';
            outsideWindow = true;
        } else if (PIT_CLOSE && elapsed > PIT_CLOSE) {
            banner.textContent = 'PIT WINDOW CLOSED';
            banner.className = 'rs-pit-banner rs-pit-banner-closed';
            outsideWindow = true;
        } else if (PIT_CLOSE && PIT_CLOSE - elapsed < 300) {
            var left = PIT_CLOSE - elapsed;
            banner.textContent = 'Pit window closes in ' + fmtShort(left);
            banner.className = 'rs-pit-banner rs-pit-banner-closing';
        } else if (PIT_OPEN && elapsed >= PIT_OPEN) {
            banner.textContent = 'PIT WINDOW OPEN';
            banner.className = 'rs-pit-banner rs-pit-banner-open';
        } else {
            banner.style.display = 'none';
        }

        // Warning on End Stint button
        if (endBtn) {
            if (outsideWindow) {
                endBtn.classList.add('rs-btn-pit-warning');
            } else {
                endBtn.classList.remove('rs-btn-pit-warning');
            }
        }
    }
```

Add `updatePitWindow()` to the 1-second interval alongside the other update calls.

**Step 4: Verify manually**

Create a race with `pit_open_s` set, go live, verify banner transitions.

**Step 5: Commit**

```bash
git add telemetry_tool/web/templates/race_strategy/live.html telemetry_tool/web/static/js/race_strategy_live.js telemetry_tool/web/static/css/race_strategy.css
git commit -m "feat(race-strategy): add pit window banner and End Stint warning on live dashboard"
```

---

### Task 6: Final Verification

**Step 1: Run full test suite**

Run: `pytest telemetry_tool/tests/ -x -q`
Expected: ALL PASSED, no regressions

**Step 2: Run race strategy tests specifically**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py -v`
Expected: ALL tests pass (schema + optimizer + ballast + integration + import/export + qualifying + pit windows)

**Step 3: Commit any remaining changes**

If any cleanup needed, commit with appropriate message.
