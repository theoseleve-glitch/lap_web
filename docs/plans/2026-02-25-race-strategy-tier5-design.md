# Race Strategy Tier 5 Design: Pit Windows & Live Dashboard

## Overview

Tier 5 adds typed race windows (pitlane, refuel, tech stop) with engine-level validation, a three-card live status bar with countdowns, a compact "Pit Wall" layout mode, persistent driver colors, fullscreen toggle, and wall clock display. The central new concept is `race_windows` — a child table of `race_configs` holding typed time ranges that the `RaceStateEngine` validates against during cascade.

## Tier Scope

Tier 4 — Core Race Mechanics (COMPLETE)
**Tier 5 — Pit Windows & Live Dashboard (this document)**
Tier 6 — Live Race Intelligence + Connectivity (future)

## Feature List

### Build New

1. **Multiple refueling windows** — definable time ranges when refueling is permitted
2. **Technical pit stop windows** — mandatory stop windows with own rules (refuel? driver change?)
3. **Three-card window status bar** — live dashboard top row: Pitlane / Refuel / Tech Stop status
4. **Compact "Pit Wall" layout** — 4-column grid (Chrono | Fuel | Current Driver | Next Driver)
5. **Fullscreen toggle** — browser Fullscreen API for pit wall monitors
6. **Wall clock display** — HH:MM:SS in toolbar next to race timer
7. **Persistent driver colors** — DB-stored color per driver, used consistently everywhere

### Enhance Existing

8. **Pit window engine validation** — wire `pit_open_s`/`pit_close_s` and new windows into constraint checks
9. **Window status computation** — `RaceStateEngine.window_status()` returns countdown data for all windows
10. **Legacy pit window migration** — auto-create `pitlane` window from existing `pit_open_s`/`pit_close_s` columns
11. **Config form: window editor** — add/remove typed windows with time pickers and rule toggles
12. **Config form: driver color picker** — per-driver color selector with palette defaults

## Architecture: Window Table + Engine Integration

### Approach

A new `race_windows` child table stores typed time ranges. The `RaceStateEngine` loads windows alongside config/drivers/stints. During cascade, `_validate_constraints()` checks pit times against active windows. A new `window_status()` query method computes live countdown data for the dashboard.

### Window Types

| Type | Purpose | Validation Severity |
|------|---------|-------------------|
| `pitlane` | When pit lane is open at all | **warning** (pit stop outside = warned) |
| `refuel` | When refueling is permitted | **violation** (refuel outside = blocked) |
| `tech_stop` | Mandatory technical stop window | **violation** (no stop in window = blocked) |

### Validation Rules

- **Pitlane**: If pitlane windows exist and a pit stop falls outside all of them → warning
- **Refuel**: If refuel windows exist and a refueled pit stop falls outside all of them → violation
- **Tech stop**: If a tech_stop window exists and no pit stop falls within it → violation
- **No windows of a type**: No restriction (permissive by default)

## Schema Changes

Version bump: 22 → 23. All additive, applied via `ensure_schema()`.

### New table: `race_windows`

```sql
CREATE TABLE IF NOT EXISTS race_windows (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id               INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    window_type           TEXT NOT NULL,          -- 'pitlane' | 'refuel' | 'tech_stop'
    label                 TEXT,                   -- user-facing name, e.g. "Refuel Window 1"
    start_s               INTEGER NOT NULL,       -- absolute seconds from race start
    end_s                 INTEGER NOT NULL,       -- absolute seconds from race start
    refuel_allowed        INTEGER NOT NULL DEFAULT 1,
    driver_change_allowed INTEGER NOT NULL DEFAULT 1,
    window_order          INTEGER NOT NULL DEFAULT 1
);
```

### `race_drivers` (1 new column)

```sql
ALTER TABLE race_drivers ADD COLUMN color_hex TEXT;
```

Default NULL — JS falls back to existing positional palette.

## RaceStateEngine Changes

### New fields

```python
class RaceStateEngine:
    # Existing: config, drivers, stints, fuel_model, _refuel_map, _pit_type_map
    # NEW:
    windows: list[dict]  # race_windows rows for this race
```

### Window validation (added to `_validate_constraints`)

```python
def _validate_constraints(self, stint: StintState) -> None:
    # ... existing checks (fuel, rest, driver change, cumulative) ...

    # 5. Pit window check (warning): pit stop time outside pitlane windows
    if stint.stint_order > 1:
        pit_time_s = stint.planned_start_s
        if not self._is_in_any_window('pitlane', pit_time_s):
            stint.warnings.append(
                f"Pit stop at {self._fmt_time(pit_time_s)} outside pit lane window"
            )

    # 6. Refuel window check (violation): refuel outside refuel windows
    if stint.refueled_before and stint.stint_order > 1:
        pit_time_s = stint.planned_start_s
        if not self._is_in_any_window('refuel', pit_time_s):
            stint.violations.append(
                f"Refuel at {self._fmt_time(pit_time_s)} outside refuel window"
            )
```

### Tech stop global validation (after full cascade)

```python
def _validate_tech_stops(self) -> None:
    """Check each tech_stop window has at least one pit stop inside it."""
    tech_windows = [w for w in self.windows if w['window_type'] == 'tech_stop']
    for w in tech_windows:
        has_stop = any(
            w['start_s'] <= s.planned_start_s <= w['end_s']
            for s in self.stints if s.stint_order > 1
        )
        if not has_stop:
            # Attach to the stint whose planned_end_s is closest to window start
            target = min(self.stints, key=lambda s: abs(s.planned_end_s - w['start_s']))
            target.violations.append(
                f"No pit stop in tech window '{w.get('label', 'Tech Stop')}' "
                f"({self._fmt_time(w['start_s'])} – {self._fmt_time(w['end_s'])})"
            )
```

### Helper

```python
def _is_in_any_window(self, window_type: str, time_s: int) -> bool:
    """True if time_s falls within any window of the given type.
    Returns True if no windows of that type exist (no restriction)."""
    typed = [w for w in self.windows if w['window_type'] == window_type]
    if not typed:
        return True
    return any(w['start_s'] <= time_s <= w['end_s'] for w in typed)
```

### Window status query (no mutation, no cascade)

```python
def window_status(self, elapsed_s: float) -> list[dict]:
    """Compute live status for each window type.

    Returns list of dicts, one per configured window type:
    {type, label, status: 'before'|'open'|'closing'|'closed', countdown_s, ...}
    """
```

### Legacy pit window migration

In `RaceStateEngine.load()`: if `config['pit_open_s']` or `config['pit_close_s']` are set but no `pitlane` windows exist in `race_windows`, synthesize a virtual pitlane window from those columns. This keeps backward compatibility with pre-Tier-5 races.

### Persistence changes

- `save()`: also write `race_windows` rows
- `load()`: also read `race_windows` rows
- `snapshot()`: include `windows` and `window_status`

## Live Dashboard: Three-Card Status Bar

New row inserted at the top of `rs-live-grid`:

```
┌─────────────────┬─────────────────┬─────────────────┐
│ 🟢 PIT LANE     │ 🔴 REFUEL       │ ⚪ TECH STOP    │
│ OPEN            │ Opens in 12:34  │ No window set   │
│ Closes in 45:00 │                 │                 │
└─────────────────┴─────────────────┴─────────────────┘
```

### Card states

| State | Color | Label |
|-------|-------|-------|
| `before` | Yellow | "Opens in MM:SS" |
| `open` | Green | "OPEN — Closes in MM:SS" |
| `closing` | Orange pulse | "CLOSING IN MM:SS" (< 5 min) |
| `closed` | Red | "CLOSED" |
| `none` | Gray | "Not configured" |

### Data source

Window status comes from the `/api/state` response (engine provides `window_status`). JS renders the three cards by type, picking the next relevant window of each type.

## Live Dashboard: Compact Pit Wall Mode

CSS class `.rs-compact` on `#rs-live-root`:

```
┌──────────┬──────────┬──────────────┬──────────────┐
│ CHRONO   │ FUEL     │ CURRENT      │ NEXT DRIVER  │
│ 1:23:45  │ ████ 6.2 │ Alice        │ Bob          │
│ Rem 2:36 │ 85%      │ Stint 24:00  │ Ballast 4.2  │
└──────────┴──────────┴──────────────┴──────────────┘
┌────────────────────────────────────────────────────┐
│ 🟢 PIT OPEN  │ 🔴 REFUEL 12:34  │ ⚪ TECH N/A   │
└────────────────────────────────────────────────────┘
```

- Activated via "Pit Wall" button in layout toggle (alongside Grid/Vertical)
- Hides: stint log, race summary, team talk, weather, radar
- Shows: timer, fuel, drivers, window status bar
- Persisted in localStorage

## Fullscreen Toggle

Uses browser Fullscreen API: `document.documentElement.requestFullscreen()`.

- Button in toolbar: "Fullscreen" / "Exit Fullscreen"
- Toggle listener on `fullscreenchange` event
- Combined with compact mode for pit wall monitors

## Wall Clock Display

Small `HH:MM:SS` element in the top toolbar header, updated every second via the existing 1s `setInterval`. Styled with `font-variant-numeric: tabular-nums` for non-jittery display.

## Driver Color System

### Flow

1. Config form: `<input type="color">` per driver row (defaults from palette if NULL)
2. Saved to `race_drivers.color_hex` via `_save_drivers()`
3. `/api/state` returns `color_hex` per driver in the drivers array
4. JS uses `color_hex` for: timeline blocks, driver bar chart, stint log driver name
5. Fallback: if `color_hex` is NULL, use existing positional `DRIVER_COLORS` palette

### Palette defaults

```python
DEFAULT_DRIVER_COLORS = ['#58a6ff', '#f78166', '#7ee787', '#d2a8ff', '#ffa657', '#79c0ff']
```

Matches the existing JS `DRIVER_COLORS` array. Assigned on driver creation when no color specified.

## Config Form Changes

### New "Pit Windows" section

Placed after the existing "Pit Strategy" section:

```
Pit Windows
────────────────────────────────────────
[+ Add Window]

| Type ▼    | Label      | Start (H:MM) | End (H:MM) | Refuel? | Driver Change? | [×] |
| pitlane   | Pit Window | 0:30         | 3:30       |   —     |      —         | [×] |
| refuel    | Refuel 1   | 0:30         | 1:30       |   —     |      —         | [×] |
| tech_stop | Tech Stop  | 1:30         | 2:00       |  ☑      |      ☑         | [×] |
```

- "Add Window" button adds a row with JS
- Type dropdown: pitlane, refuel, tech_stop
- Refuel/Driver Change checkboxes only visible for tech_stop type
- Delete button per row
- Existing `pit_open`/`pit_close` fields remain for backward compat

### Driver color picker

Added to each driver card in the config form: a small color input `<input type="color">`.

## API Changes

### Modified: `/api/state`

Add `window_status` to response:

```json
{
  "race": {...},
  "drivers": [{..., "color_hex": "#58a6ff"}, ...],
  "window_status": [
    {"type": "pitlane", "label": "Pit Window", "status": "open", "countdown_s": 2700, ...},
    {"type": "refuel", "label": "Refuel 1", "status": "before", "countdown_s": 300, ...},
    {"type": "tech_stop", "label": "Tech Stop", "status": "before", "countdown_s": 3600, ...}
  ],
  ...
}
```

### New: Window CRUD via form POST

Windows are saved alongside the config form (same POST to new_race / update_race). No separate API endpoint needed — they're part of the race config lifecycle.

## Files Touched

| File | Action | Description |
|------|--------|-------------|
| `telemetry_tool/db/schema.py` | MODIFY | v23, `race_windows` table, `color_hex` column |
| `telemetry_tool/db/migrate.py` | MODIFY | v23 migration |
| `telemetry_tool/race_state_engine.py` | MODIFY | Window loading, validation, `window_status()`, tech stop check |
| `telemetry_tool/web/routes/race_strategy_v2.py` | MODIFY | Window save/load in form handlers, color_hex in `_save_drivers`, window status in api_state |
| `telemetry_tool/web/templates/race_strategy/config.html` | MODIFY | Window editor section, driver color pickers |
| `telemetry_tool/web/templates/race_strategy/live.html` | MODIFY | Three-card status bar, compact mode toggle, fullscreen btn, wall clock |
| `telemetry_tool/web/static/js/race_strategy.js` | MODIFY | Window form interactions, color picker wiring |
| `telemetry_tool/web/static/js/race_strategy_live.js` | MODIFY | Window status rendering, compact mode, fullscreen, wall clock, driver colors from DB |
| `telemetry_tool/web/static/css/race_strategy.css` | MODIFY | Compact grid, window cards, color system, fullscreen |
| `telemetry_tool/tests/test_race_state_engine.py` | MODIFY | Window validation tests |
| `telemetry_tool/tests/test_race_strategy_v2.py` | MODIFY | Schema v23, window CRUD tests |

## Integration with Existing System

- `RaceStateEngine.load()` gains a `race_windows` query — backward compatible (empty list for pre-v23 races)
- Existing `updatePitWindow()` JS function replaced by the new three-card renderer
- Legacy `pit_open_s`/`pit_close_s` columns kept and auto-migrated to virtual windows
- Driver colors degrade gracefully — NULL → positional palette
- Compact mode and fullscreen are purely CSS/JS — no server changes
