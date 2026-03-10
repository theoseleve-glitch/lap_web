# Driver Sleep Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add sleep window planning and live sleep tracking for endurance races (12h+), with optimizer soft-constraint integration and live dashboard wake/sleep management.

**Architecture:** New `race_sleep_windows` table stores per-driver sleep blocks. Backend service layer gains sleep CRUD + live status computation. Optimizer penalizes (but allows) stints that overlap sleep. Frontend form gets a conditional "Sleep Windows" section; live dashboard gets driver sleep indicators and wake actions.

**Tech Stack:** Python/Flask (backend), SQLite/PostgreSQL (DB), Next.js/React/TypeScript (frontend), TanStack Query (polling)

---

### Task 1: Database — Add `race_sleep_windows` Table

**Files:**
- Modify: `telemetry_tool/db/schema.py` (add table definition + Phase 22, register in ALL_TABLES)

**Step 1: Add the table definition**

In `telemetry_tool/db/schema.py`, after the Phase 21 tables block (around line 1044), add:

```python
# ------------------------------------------------------------------
# Phase 22 tables — Driver sleep windows (endurance 12h+)
# ------------------------------------------------------------------

_RACE_SLEEP_WINDOWS_TABLE = """
CREATE TABLE IF NOT EXISTS race_sleep_windows (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id         INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    driver_id       INTEGER NOT NULL REFERENCES race_drivers(id) ON DELETE CASCADE,
    start_s         INTEGER NOT NULL,
    end_s           INTEGER NOT NULL,
    label           TEXT,
    actual_wake_s   INTEGER,
    status          TEXT    NOT NULL DEFAULT 'planned',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

PHASE_22_TABLES: list[tuple[str, str]] = [
    ("race_sleep_windows", _RACE_SLEEP_WINDOWS_TABLE),
]
```

**Step 2: Register in ALL_TABLES**

Find the `ALL_TABLES = PHASE_1_TABLES + ...` line and append `+ PHASE_22_TABLES`.

**Step 3: Bump schema version**

Change `SCHEMA_VERSION = 34` to `SCHEMA_VERSION = 35`.

**Step 4: Run tests to verify schema loads**

Run: `pytest telemetry_tool/tests/ -k "schema or migrate" -v --no-header -q`
Expected: PASS (idempotent CREATE IF NOT EXISTS)

**Step 5: Commit**

```bash
git add telemetry_tool/db/schema.py
git commit -m "feat(sleep): add race_sleep_windows table (Phase 22)"
```

---

### Task 2: Alembic Migration for PostgreSQL

**Files:**
- Create: `telemetry_tool/alembic/versions/017_sleep_windows.py`

**Step 1: Write the migration**

```python
"""Add race_sleep_windows table for driver sleep management in 12h+ races."""

revision = "017"
down_revision = "016"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "race_sleep_windows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer(), sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"), nullable=False),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("race_drivers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_s", sa.Integer(), nullable=False),
        sa.Column("end_s", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("actual_wake_s", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="planned"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("race_sleep_windows")
```

**Step 2: Commit**

```bash
git add telemetry_tool/alembic/versions/017_sleep_windows.py
git commit -m "feat(sleep): alembic migration 017 for race_sleep_windows"
```

---

### Task 3: Backend Service — Sleep CRUD Helpers

**Files:**
- Modify: `telemetry_tool/services/race_strategy.py` (add `_save_sleep_windows`, `_get_sleep_windows`, update `create_race`, `update_race`, `get_race_detail`, `export_race`, `import_race`, `duplicate_race`)

**Step 1: Add `_save_sleep_windows` helper**

After `_save_windows()` (around line 131), add:

```python
def _save_sleep_windows(conn, race_id: int, driver_id_map: dict[int, int],
                        sleep_windows: list[dict]) -> None:
    """Persist sleep windows for a race. Deletes existing first."""
    conn.execute("DELETE FROM race_sleep_windows WHERE race_id = ?", (race_id,))
    for sw in sleep_windows:
        start = sw.get("start_s")
        end = sw.get("end_s")
        if start is None or end is None or end <= start:
            continue
        # Remap driver_id if needed (import/duplicate flows)
        raw_did = sw.get("driver_id")
        driver_id = driver_id_map.get(raw_did, raw_did) if driver_id_map else raw_did
        if driver_id is None:
            continue
        conn.execute(
            "INSERT INTO race_sleep_windows "
            "(race_id, driver_id, start_s, end_s, label, status) "
            "VALUES (?,?,?,?,?,?)",
            (race_id, driver_id, start, end,
             sw.get("label"), sw.get("status", "planned")),
        )


def _get_sleep_windows(conn, race_id: int) -> list[dict]:
    """Fetch all sleep windows for a race, ordered by start time."""
    return _rows_to_list(conn.execute(
        "SELECT sw.*, d.driver_name FROM race_sleep_windows sw "
        "JOIN race_drivers d ON sw.driver_id = d.id "
        "WHERE sw.race_id = ? ORDER BY sw.start_s",
        (race_id,),
    ).fetchall())
```

**Step 2: Update `create_race` to save sleep windows**

In `create_race()` (around line 249-291), after `windows = data.get("windows", [])`, add:
```python
    sleep_windows = data.get("sleep_windows", [])
```

After `if windows: _save_windows(...)` (line 289), add:
```python
    if sleep_windows:
        # Need driver_id mapping: use freshly inserted driver IDs
        # Sleep windows reference driver_id from the payload
        _save_sleep_windows(conn, race_id, {}, sleep_windows)
```

**Step 3: Update `update_race` to save sleep windows**

In `update_race()` (around line 334-388), after `windows = data.get("windows", [])`, add:
```python
    sleep_windows = data.get("sleep_windows", [])
```

After `if windows: _save_windows(...)` (line 378), add:
```python
    conn.execute("DELETE FROM race_sleep_windows WHERE race_id = ?", (race_id,))
    if sleep_windows:
        _save_sleep_windows(conn, race_id, {}, sleep_windows)
```

**Step 4: Update `get_race_detail` to include sleep windows**

In `get_race_detail()` (around line 206-217), before the `return` dict, add:
```python
    sleep_windows = _get_sleep_windows(conn, race_id)
```

And add `"sleep_windows": sleep_windows` to the return dict.

**Step 5: Update `export_race` to include sleep windows**

In `export_race()` (around line 806-820), add a query for sleep windows and include in return dict:
```python
    sleep_windows = _rows_to_list(conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ? ORDER BY start_s",
        (race_id,),
    ).fetchall())
```
Add `"sleep_windows": sleep_windows` to the return dict.

**Step 6: Update `import_race` to import sleep windows**

In `import_race()` (around line 965-983), after the windows import block, add:
```python
    # Import sleep windows
    for sw in data.get("sleep_windows", []):
        old_driver_id = sw.get("driver_id")
        new_driver_id = id_map.get(old_driver_id, old_driver_id)
        conn.execute(
            "INSERT INTO race_sleep_windows "
            "(race_id, driver_id, start_s, end_s, label, status) "
            "VALUES (?,?,?,?,?,?)",
            (new_race_id, new_driver_id,
             sw.get("start_s", 0), sw.get("end_s", 0),
             sw.get("label"), sw.get("status", "planned")),
        )
```

**Step 7: Update `duplicate_race` to copy sleep windows**

In `duplicate_race()` (around line 1059-1082), after the windows copy block, add:
```python
    # Copy sleep windows (need driver id remapping)
    old_sleep = conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ?", (race_id,)
    ).fetchall()
    # Build old->new driver id map
    new_drivers = conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
        (new_id,),
    ).fetchall()
    sleep_id_map = {}
    for old_d, new_d in zip(old_drivers, new_drivers):
        sleep_id_map[_row_to_dict(old_d)["id"]] = _row_to_dict(new_d)["id"]
    for sw in old_sleep:
        swd = _row_to_dict(sw)
        new_did = sleep_id_map.get(swd["driver_id"], swd["driver_id"])
        conn.execute(
            "INSERT INTO race_sleep_windows "
            "(race_id, driver_id, start_s, end_s, label, status) "
            "VALUES (?,?,?,?,?,?)",
            (new_id, new_did, swd["start_s"], swd["end_s"],
             swd.get("label"), "planned"),
        )
```

**Step 8: Commit**

```bash
git add telemetry_tool/services/race_strategy.py
git commit -m "feat(sleep): add sleep window CRUD to race strategy service"
```

---

### Task 4: Backend Service — Live Sleep State + Wake Driver

**Files:**
- Modify: `telemetry_tool/services/race_strategy.py` (update `get_live_state`, add `wake_driver`, add `_compute_driver_sleep_status`)

**Step 1: Add `_compute_driver_sleep_status` helper**

After `_get_sleep_windows()`, add:

```python
def _compute_driver_sleep_status(
    sleep_windows: list[dict], elapsed_s: int
) -> dict[int, dict]:
    """Compute current sleep status for each driver.

    Returns a dict keyed by driver_id with:
      - sleeping: bool
      - until_s: race-second when current window ends (if sleeping)
      - remaining_s: seconds until wake (if sleeping)
      - window_id: active window id (if sleeping)
      - next_sleep_s: race-second of next upcoming sleep (if awake)
    """
    status: dict[int, dict] = {}
    for sw in sleep_windows:
        did = sw["driver_id"]
        effective_end = sw.get("actual_wake_s") or sw["end_s"]
        # Is this window currently active?
        if sw["start_s"] <= elapsed_s < effective_end and sw.get("actual_wake_s") is None:
            status[did] = {
                "sleeping": True,
                "until_s": sw["end_s"],
                "remaining_s": max(0, sw["end_s"] - elapsed_s),
                "window_id": sw["id"],
                "label": sw.get("label"),
            }
        elif did not in status:
            # Check for upcoming sleep
            if sw["start_s"] > elapsed_s and sw.get("actual_wake_s") is None:
                status[did] = {
                    "sleeping": False,
                    "next_sleep_s": sw["start_s"],
                }
            else:
                status[did] = {"sleeping": False}
    return status
```

**Step 2: Update `get_live_state` to include sleep data**

In `get_live_state()` (around line 602-614), before the return dict, add:

```python
    # Sleep windows + live status
    sleep_windows = _get_sleep_windows(conn, race_id)
    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    driver_sleep_status = _compute_driver_sleep_status(sleep_windows, elapsed)

    # Auto-update sleep window statuses
    for sw in sleep_windows:
        effective_end = sw.get("actual_wake_s") or sw["end_s"]
        if sw["status"] == "planned" and sw["start_s"] <= elapsed:
            conn.execute(
                "UPDATE race_sleep_windows SET status = 'active' WHERE id = ?",
                (sw["id"],),
            )
            sw["status"] = "active"
        elif sw["status"] == "active" and elapsed >= effective_end:
            conn.execute(
                "UPDATE race_sleep_windows SET status = 'completed' WHERE id = ?",
                (sw["id"],),
            )
            sw["status"] = "completed"
    conn.commit()
```

Add to the return dict:
```python
        "sleep_windows": sleep_windows,
        "driver_sleep_status": driver_sleep_status,
```

**Step 3: Add `wake_driver` function**

After `set_pit_type()` (around line 711), add:

```python
def wake_driver(conn, race_id: int, driver_id: int) -> dict | None:
    """Wake a driver early by setting actual_wake_s on their active sleep window.

    Returns {"ok": True, "elapsed_s": <int>} on success, or None if no
    active sleep window found for this driver.
    """
    race = get_race(conn, race_id)
    if not race:
        return None

    elapsed = _compute_elapsed_s(race.get("race_start_ts"))

    active_window = conn.execute(
        "SELECT id FROM race_sleep_windows "
        "WHERE race_id = ? AND driver_id = ? AND status = 'active' "
        "AND actual_wake_s IS NULL LIMIT 1",
        (race_id, driver_id),
    ).fetchone()
    if not active_window:
        return None

    conn.execute(
        "UPDATE race_sleep_windows SET actual_wake_s = ?, status = 'completed' "
        "WHERE id = ?",
        (elapsed, active_window["id"]),
    )
    conn.commit()
    return {"ok": True, "elapsed_s": elapsed}
```

**Step 4: Commit**

```bash
git add telemetry_tool/services/race_strategy.py
git commit -m "feat(sleep): live sleep status computation + wake_driver action"
```

---

### Task 5: Backend Routes — Wake Driver Endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py` (add wake-driver route, update config form save to handle sleep windows)

**Step 1: Add API wake-driver endpoint**

Find the `/end-stint` route (search for `end-stint`). After it, add:

```python
@bp.route("/<int:race_id>/wake-driver", methods=["POST"])
def wake_driver_route(race_id: int):
    """Wake a sleeping driver early."""
    import sys as _sys
    from pathlib import Path as _Path
    _root = str(_Path(__file__).resolve().parents[2])
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    from services.race_strategy import wake_driver

    data = request.get_json(silent=True) or {}
    driver_id = data.get("driver_id")
    if not driver_id:
        return jsonify({"ok": False, "error": "driver_id required"}), 400

    conn = get_db_connection()
    result = wake_driver(conn, race_id, int(driver_id))
    if result is None:
        return jsonify({"ok": False, "error": "No active sleep window for this driver"}), 404
    return jsonify(result)
```

**Step 2: Update `_save_drivers` and form POST to handle sleep windows**

In the `new_race()` POST handler (around line 447-452) and `update_race()` POST handler (around line 500-510), after `_save_windows(conn, race_id, request.form)`, add:

```python
    _save_sleep_windows_from_form(conn, race_id, request.form)
```

Add this helper function near the top of the file (after `_rows_to_list`):

```python
def _save_sleep_windows_from_form(conn, race_id: int, form) -> None:
    """Parse sleep windows from form data and save to DB."""
    conn.execute("DELETE FROM race_sleep_windows WHERE race_id = ?", (race_id,))
    i = 0
    while True:
        driver_id = form.get(f"sleep_driver_id_{i}")
        start_h = form.get(f"sleep_start_h_{i}")
        start_m = form.get(f"sleep_start_m_{i}")
        end_h = form.get(f"sleep_end_h_{i}")
        end_m = form.get(f"sleep_end_m_{i}")
        if driver_id is None and start_h is None:
            break
        if driver_id and start_h is not None and end_h is not None:
            start_s = (int(start_h) * 3600) + (int(start_m or 0) * 60)
            end_s = (int(end_h) * 3600) + (int(end_m or 0) * 60)
            if end_s > start_s:
                conn.execute(
                    "INSERT INTO race_sleep_windows "
                    "(race_id, driver_id, start_s, end_s, label) "
                    "VALUES (?,?,?,?,?)",
                    (race_id, int(driver_id), start_s, end_s,
                     form.get(f"sleep_label_{i}") or None),
                )
        i += 1
```

**Step 3: Update the `edit_race()` GET handler to load sleep windows**

In `edit_race()` (around line 513-529), after loading `race_windows`, add:

```python
    sleep_windows = _rows_to_list(conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ? ORDER BY start_s",
        (race_id,),
    ).fetchall())
```

Pass `sleep_windows=sleep_windows` to the `render_template()` call.

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py
git commit -m "feat(sleep): wake-driver endpoint + sleep window form persistence"
```

---

### Task 6: Optimizer — Soft Constraint for Sleep Windows

**Files:**
- Modify: `telemetry_tool/race_strategy_v2.py` (accept `sleep_windows` param, add overlap penalty + warnings)
- Modify: `telemetry_tool/services/race_strategy.py` (pass sleep_windows to optimizer)

**Step 1: Update `optimize_stints` signature**

In `telemetry_tool/race_strategy_v2.py`, update `optimize_stints()` (line 37-56):

```python
def optimize_stints(
    config: dict[str, Any],
    drivers: list[dict[str, Any]],
    sleep_windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
```

**Step 2: Add sleep overlap check after stint assignment**

After the stint assignment loop builds the `stints` list and rebuilds the timeline (around line 215), before the feasibility checks (around line 243), add:

```python
    # Check sleep window overlaps (soft constraint — warn, don't block)
    if sleep_windows:
        for s in stints:
            did = s["driver_id"]
            s_start = s["planned_start_s"]
            s_end = s["planned_end_s"]
            driver_name = s.get("driver_name", f"Driver {did}")
            for sw in sleep_windows:
                if sw.get("driver_id") != did:
                    continue
                sw_start = sw.get("start_s", 0)
                sw_end = sw.get("end_s", 0)
                # Check overlap
                overlap_start = max(s_start, sw_start)
                overlap_end = min(s_end, sw_end)
                if overlap_start < overlap_end:
                    overlap_min = (overlap_end - overlap_start) // 60
                    sw_label = sw.get("label") or f"{sw_start // 3600}h{(sw_start % 3600) // 60:02d}–{sw_end // 3600}h{(sw_end % 3600) // 60:02d}"
                    warnings.append(
                        f"{driver_name} stint {s['stint_order']} overlaps sleep window "
                        f"'{sw_label}' by {overlap_min}min"
                    )
```

**Step 3: Update `run_optimization` in service to pass sleep windows**

In `telemetry_tool/services/race_strategy.py`, in `run_optimization()` (around line 419), change:
```python
    result = optimize_stints(race, drivers)
```
to:
```python
    sleep_windows = _rows_to_list(conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ? ORDER BY start_s",
        (race_id,),
    ).fetchall())
    result = optimize_stints(race, drivers, sleep_windows=sleep_windows)
```

**Step 4: Also pass to `reoptimize_remaining`**

In `reoptimize()` (around line 739), similarly add sleep window loading and pass to `reoptimize_remaining`:
```python
    sleep_windows = _rows_to_list(conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ? ORDER BY start_s",
        (race_id,),
    ).fetchall())
    result = reoptimize_remaining(race, drivers, completed, elapsed, sleep_windows=sleep_windows)
```

Update `reoptimize_remaining` in `race_strategy_v2.py` to accept and pass through `sleep_windows`:
```python
def reoptimize_remaining(
    config, drivers, completed_stints, elapsed_s,
    sleep_windows=None,
):
```
And pass `sleep_windows` to the internal `optimize_stints()` call if present.

**Step 5: Commit**

```bash
git add telemetry_tool/race_strategy_v2.py telemetry_tool/services/race_strategy.py
git commit -m "feat(sleep): optimizer soft constraint — warn on sleep window overlaps"
```

---

### Task 7: Frontend — Sleep Windows in RaceConfigForm

**Files:**
- Modify: `lap-website/src/components/app/race-strategy/RaceConfigForm.tsx` (add SleepWindowForm type, sleep windows section, submit logic)

**Step 1: Add SleepWindowForm type**

After the `WindowForm` interface (line 32), add:

```typescript
export interface SleepWindowForm {
  driver_id: string;
  start_hh: string;
  start_mm: string;
  end_hh: string;
  end_mm: string;
  label: string;
}
```

**Step 2: Update RaceFormData to include sleep_windows**

After the `windows` array in `RaceFormData` (line 76), add:

```typescript
  sleep_windows: Array<{
    driver_id: number;
    start_s: number;
    end_s: number;
    label: string | null;
  }>;
```

**Step 3: Add state and section in the form component**

In the form component, add state for sleep windows:
```typescript
const [sleepWindows, setSleepWindows] = useState<SleepWindowForm[]>([]);
```

Add the "Sleep Windows" section — only render when `race_duration_s >= 43200` (12h). This section should appear after the "Pit Windows" section. It includes:

- A check: `const isEndurance = raceDurationS >= 43200;` where `raceDurationS` is computed from the form's duration fields
- If `!isEndurance`, don't render the section
- For each sleep window: a row with driver dropdown (from `drivers` state), start time (hh:mm), end time (hh:mm), label text, remove button
- "Add Sleep Window" button
- Visual timeline bar showing driver-colored blocks

```tsx
{isEndurance && (
  <section>
    <h3 className="text-lg font-semibold text-chalk mb-3">Sleep Windows</h3>
    <p className="text-sm text-steel mb-4">
      Plan rest periods for your drivers. The optimizer will try to avoid scheduling
      stints during sleep windows.
    </p>
    {sleepWindows.map((sw, i) => (
      <div key={i} className="grid grid-cols-[1fr_auto_auto_1fr_auto] gap-2 mb-2 items-end">
        <select
          value={sw.driver_id}
          onChange={e => {
            const next = [...sleepWindows];
            next[i] = { ...next[i], driver_id: e.target.value };
            setSleepWindows(next);
          }}
          className="bg-graphite border border-steel/30 rounded px-2 py-1.5 text-chalk text-sm"
        >
          <option value="">Driver...</option>
          {drivers.map((d, di) => (
            <option key={di} value={di.toString()}>{d.driver_name}</option>
          ))}
        </select>
        <div className="flex gap-1 items-center">
          <input type="number" min="0" max="47" placeholder="hh"
            value={sw.start_hh}
            onChange={e => { const n = [...sleepWindows]; n[i] = {...n[i], start_hh: e.target.value}; setSleepWindows(n); }}
            className="w-12 bg-graphite border border-steel/30 rounded px-1 py-1.5 text-chalk text-sm text-center"
          />
          <span className="text-steel">:</span>
          <input type="number" min="0" max="59" placeholder="mm"
            value={sw.start_mm}
            onChange={e => { const n = [...sleepWindows]; n[i] = {...n[i], start_mm: e.target.value}; setSleepWindows(n); }}
            className="w-12 bg-graphite border border-steel/30 rounded px-1 py-1.5 text-chalk text-sm text-center"
          />
        </div>
        <span className="text-steel self-center">to</span>
        <div className="flex gap-1 items-center">
          <input type="number" min="0" max="47" placeholder="hh"
            value={sw.end_hh}
            onChange={e => { const n = [...sleepWindows]; n[i] = {...n[i], end_hh: e.target.value}; setSleepWindows(n); }}
            className="w-12 bg-graphite border border-steel/30 rounded px-1 py-1.5 text-chalk text-sm text-center"
          />
          <span className="text-steel">:</span>
          <input type="number" min="0" max="59" placeholder="mm"
            value={sw.end_mm}
            onChange={e => { const n = [...sleepWindows]; n[i] = {...n[i], end_mm: e.target.value}; setSleepWindows(n); }}
            className="w-12 bg-graphite border border-steel/30 rounded px-1 py-1.5 text-chalk text-sm text-center"
          />
        </div>
        <button type="button" onClick={() => setSleepWindows(sleepWindows.filter((_, j) => j !== i))}
          className="text-safety-red hover:text-red-400 text-sm px-2">Remove</button>
      </div>
    ))}
    <button type="button"
      onClick={() => setSleepWindows([...sleepWindows, { driver_id: '', start_hh: '', start_mm: '00', end_hh: '', end_mm: '00', label: '' }])}
      className="text-acid-green hover:text-green-400 text-sm mt-1">
      + Add Sleep Window
    </button>
  </section>
)}
```

**Step 4: Update `onSubmit` to include sleep_windows in payload**

In the form submit handler, convert sleep window form state to the API shape:

```typescript
sleep_windows: sleepWindows
  .filter(sw => sw.driver_id && sw.start_hh && sw.end_hh)
  .map((sw, i) => ({
    driver_id: parseInt(sw.driver_id),
    start_s: parseInt(sw.start_hh) * 3600 + parseInt(sw.start_mm || '0') * 60,
    end_s: parseInt(sw.end_hh) * 3600 + parseInt(sw.end_mm || '0') * 60,
    label: sw.label || null,
  })),
```

**Step 5: Populate sleep windows when editing**

When `initialData` is provided (edit mode), populate the `sleepWindows` state from `initialData.sleep_windows`.

**Step 6: Commit**

```bash
git add lap-website/src/components/app/race-strategy/RaceConfigForm.tsx
git commit -m "feat(sleep): sleep windows section in RaceConfigForm (12h+ only)"
```

---

### Task 8: Frontend — Live Dashboard Sleep Indicators

**Files:**
- Modify: `lap-website/src/app/app/race-strategy/[id]/live/page.tsx` (add sleep types to LiveState, driver card sleep badges, wake button, end-stint soft block)

**Step 1: Update LiveState interface**

Add to the `LiveState` interface (around line 60-82):

```typescript
  sleep_windows?: Array<{
    id: number;
    driver_id: number;
    driver_name: string;
    start_s: number;
    end_s: number;
    label: string | null;
    actual_wake_s: number | null;
    status: 'planned' | 'active' | 'completed' | 'cancelled';
  }>;
  driver_sleep_status?: Record<number, {
    sleeping: boolean;
    until_s?: number;
    remaining_s?: number;
    window_id?: number;
    label?: string;
    next_sleep_s?: number;
  }>;
```

**Step 2: Add wake-driver mutation**

After the existing mutations (around line 158), add:

```typescript
  const wakeDriverMut = useMutation({
    mutationFn: (driverId: number) =>
      api.post<unknown>(`/race-strategy/${raceId}/wake-driver`, { driver_id: driverId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });
```

**Step 3: Add end-stint confirmation state**

Add state for the soft-block confirmation dialog:

```typescript
  const [showSleepWarning, setShowSleepWarning] = useState(false);
```

**Step 4: Update driver cards to show sleep status**

Find the section that renders driver cards (search for `Current Driver` or `Next Driver`). For each driver card, check `state.driver_sleep_status?.[driver.id]`:

- If `sleeping === true`: dim the card (opacity-50), show a moon icon and "Sleeping until {formatTime(until_s)}" with countdown. Add a "Wake" button.
- If `next_sleep_s` exists: show small text "Sleeps at {formatTime(next_sleep_s)}"

```tsx
{sleepStatus?.sleeping && (
  <div className="flex items-center gap-2 mt-2">
    <span className="text-lg">🌙</span>
    <span className="text-sm text-steel">
      Sleeping until {formatTime(sleepStatus.until_s)}
      {sleepStatus.remaining_s != null && (
        <span className="text-chalk ml-1">({formatTime(sleepStatus.remaining_s)} left)</span>
      )}
    </span>
    <button
      onClick={() => wakeDriverMut.mutate(driver.id)}
      className="ml-auto text-xs bg-acid-green/20 text-acid-green border border-acid-green/30 rounded px-2 py-1 hover:bg-acid-green/30"
    >
      Wake
    </button>
  </div>
)}
```

**Step 5: Add soft-block to end-stint**

Update the "End Stint" button handler. When clicked, check if `next_stint` exists and the next driver is sleeping:

```typescript
const handleEndStint = () => {
  if (state?.next_stint && state?.driver_sleep_status) {
    const nextDriverId = state.next_stint.driver_id;
    const sleepStatus = state.driver_sleep_status[nextDriverId];
    if (sleepStatus?.sleeping) {
      setShowSleepWarning(true);
      return;
    }
  }
  endStintMut.mutate();
};
```

Add a confirmation dialog:

```tsx
{showSleepWarning && state?.next_stint && (
  <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
    <div className="bg-graphite border border-steel/30 rounded-xl p-6 max-w-md">
      <h3 className="text-chalk text-lg font-semibold mb-2">Driver is sleeping</h3>
      <p className="text-steel text-sm mb-4">
        {state.next_stint.driver_name} is currently in a sleep window
        (until {formatTime(state.driver_sleep_status?.[state.next_stint.driver_id]?.until_s)}).
        Are you sure you want to assign them?
      </p>
      <div className="flex gap-3 justify-end">
        <button onClick={() => setShowSleepWarning(false)}
          className="px-4 py-2 text-sm text-steel border border-steel/30 rounded hover:bg-steel/10">
          Cancel
        </button>
        <button onClick={() => { setShowSleepWarning(false); endStintMut.mutate(); }}
          className="px-4 py-2 text-sm bg-safety-red/20 text-safety-red border border-safety-red/30 rounded hover:bg-safety-red/30">
          Assign Anyway
        </button>
      </div>
    </div>
  </div>
)}
```

**Step 6: Commit**

```bash
git add lap-website/src/app/app/race-strategy/[id]/live/page.tsx
git commit -m "feat(sleep): live dashboard sleep indicators, wake action, end-stint soft block"
```

---

### Task 9: Backend Tests — Sleep Window Service

**Files:**
- Create: `telemetry_tool/tests/test_sleep_windows.py`

**Step 1: Write tests**

```python
"""Tests for driver sleep window management in race strategy."""
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest
from db.schema import ALL_TABLES


@pytest.fixture
def conn():
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    for _, ddl in ALL_TABLES:
        c.execute(ddl)
    c.commit()
    return c


@pytest.fixture
def race_12h(conn):
    """Create a 12h race with 3 drivers."""
    from services.race_strategy import create_race
    data = {
        "race": {"race_name": "12H Test", "race_duration_s": 43200, "desired_stints": 6},
        "drivers": [
            {"driver_name": "Alice", "driver_order": 1, "weight_kg": 70},
            {"driver_name": "Bob", "driver_order": 2, "weight_kg": 75},
            {"driver_name": "Charlie", "driver_order": 3, "weight_kg": 80},
        ],
        "sleep_windows": [
            {"driver_id": 1, "start_s": 21600, "end_s": 32400, "label": "Night A"},
            {"driver_id": 2, "start_s": 28800, "end_s": 39600, "label": "Night B"},
        ],
    }
    race_id = create_race(conn, data)
    return race_id


def test_sleep_windows_saved(conn, race_12h):
    rows = conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ? ORDER BY start_s",
        (race_12h,),
    ).fetchall()
    assert len(rows) == 2
    assert dict(rows[0])["label"] == "Night A"
    assert dict(rows[1])["start_s"] == 28800


def test_get_race_detail_includes_sleep_windows(conn, race_12h):
    from services.race_strategy import get_race_detail
    detail = get_race_detail(conn, race_12h)
    assert "sleep_windows" in detail
    assert len(detail["sleep_windows"]) == 2


def test_sleep_windows_cleared_on_update(conn, race_12h):
    from services.race_strategy import update_race
    update_race(conn, race_12h, {
        "race": {"race_name": "12H Updated", "race_duration_s": 43200, "desired_stints": 6},
        "drivers": [
            {"driver_name": "Alice", "driver_order": 1, "weight_kg": 70},
            {"driver_name": "Bob", "driver_order": 2, "weight_kg": 75},
        ],
        "sleep_windows": [],
    })
    rows = conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ?", (race_12h,)
    ).fetchall()
    assert len(rows) == 0


def test_export_includes_sleep_windows(conn, race_12h):
    from services.race_strategy import export_race
    data = export_race(conn, race_12h)
    assert "sleep_windows" in data
    assert len(data["sleep_windows"]) == 2


def test_duplicate_copies_sleep_windows(conn, race_12h):
    from services.race_strategy import duplicate_race
    new_id = duplicate_race(conn, race_12h)
    rows = conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ?", (new_id,)
    ).fetchall()
    assert len(rows) == 2
    # Verify driver IDs were remapped (different from original)
    orig_dids = {dict(r)["driver_id"] for r in conn.execute(
        "SELECT driver_id FROM race_sleep_windows WHERE race_id = ?", (race_12h,)
    ).fetchall()}
    new_dids = {dict(r)["driver_id"] for r in rows}
    assert orig_dids != new_dids  # IDs should be different


def test_compute_driver_sleep_status():
    from services.race_strategy import _compute_driver_sleep_status
    windows = [
        {"id": 1, "driver_id": 10, "start_s": 1000, "end_s": 2000,
         "actual_wake_s": None, "label": "Rest"},
        {"id": 2, "driver_id": 20, "start_s": 5000, "end_s": 8000,
         "actual_wake_s": None, "label": None},
    ]
    # During driver 10's sleep
    status = _compute_driver_sleep_status(windows, 1500)
    assert status[10]["sleeping"] is True
    assert status[10]["remaining_s"] == 500
    assert status[20]["sleeping"] is False
    assert status[20]["next_sleep_s"] == 5000

    # After driver 10's sleep
    status2 = _compute_driver_sleep_status(windows, 3000)
    assert status2[10]["sleeping"] is False


def test_wake_driver(conn, race_12h):
    from services.race_strategy import wake_driver, go_live, run_optimization
    # Need to optimize + go live first
    run_optimization(conn, race_12h)
    go_live(conn, race_12h)

    # Manually set a sleep window to active
    conn.execute(
        "UPDATE race_sleep_windows SET status = 'active' WHERE race_id = ? LIMIT 1",
        (race_12h,),
    )
    conn.commit()
    sw = conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ? AND status = 'active'",
        (race_12h,),
    ).fetchone()
    if sw:
        result = wake_driver(conn, race_12h, dict(sw)["driver_id"])
        assert result is not None
        assert result["ok"] is True


def test_invalid_sleep_window_skipped(conn):
    """Sleep windows with end <= start should be skipped."""
    from services.race_strategy import create_race
    data = {
        "race": {"race_name": "Bad Sleep", "race_duration_s": 43200, "desired_stints": 4},
        "drivers": [{"driver_name": "Test", "driver_order": 1, "weight_kg": 70}],
        "sleep_windows": [
            {"driver_id": 1, "start_s": 5000, "end_s": 3000},  # invalid
            {"driver_id": 1, "start_s": 5000, "end_s": 5000},  # invalid (equal)
        ],
    }
    race_id = create_race(conn, data)
    rows = conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ?", (race_id,)
    ).fetchall()
    assert len(rows) == 0
```

**Step 2: Run tests**

Run: `pytest telemetry_tool/tests/test_sleep_windows.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_sleep_windows.py
git commit -m "test(sleep): backend tests for sleep window CRUD + live status"
```

---

### Task 10: Deploy to Production

**Step 1: Run full test suite locally**

Run: `pytest telemetry_tool/tests/ -v --no-header -q`
Expected: All pass

**Step 2: Create the table on production PG**

```bash
ssh root@46.225.227.24 "docker exec lap-api-postgres-1 psql -U telemetry -d telemetry -c \"
CREATE TABLE IF NOT EXISTS race_sleep_windows (
    id              SERIAL PRIMARY KEY,
    race_id         INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    driver_id       INTEGER NOT NULL REFERENCES race_drivers(id) ON DELETE CASCADE,
    start_s         INTEGER NOT NULL,
    end_s           INTEGER NOT NULL,
    label           TEXT,
    actual_wake_s   INTEGER,
    status          TEXT NOT NULL DEFAULT 'planned',
    created_at      TIMESTAMP DEFAULT NOW()
);
\""
```

**Step 3: Sync code to VPS + rebuild Docker**

```bash
# From local: tar up and sync
tar czf /tmp/telemetry_sync.tar.gz --exclude='__pycache__' --exclude='.pytest_cache' --exclude='dist' --exclude='build' --exclude='results' --exclude='data' --exclude='.claude' --exclude='*.pyc' --exclude='tests' --exclude='*.db' --exclude='*.parquet' telemetry_tool/
scp /tmp/telemetry_sync.tar.gz root@46.225.227.24:/tmp/
ssh root@46.225.227.24 "cd /opt/lap-api && tar xzf /tmp/telemetry_sync.tar.gz --overwrite && rm /tmp/telemetry_sync.tar.gz"
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api celery-pipeline celery-default celery-beat && docker compose -f docker-compose.prod.yml up -d api celery-pipeline celery-default celery-beat"
```

**Step 4: Build and deploy frontend**

```bash
cd lap-website && npm run build && npm run cf:deploy
```

**Step 5: Verify health**

```bash
ssh root@46.225.227.24 "curl -s https://api.lap-coach.racing/healthz"
```

**Step 6: Commit all remaining changes**

```bash
git add -A
git commit -m "feat(sleep): driver sleep mode for 12h+ endurance races"
```
