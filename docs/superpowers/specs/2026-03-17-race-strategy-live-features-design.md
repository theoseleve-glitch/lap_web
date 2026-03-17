# Race Strategy Live Features — Design Spec

**Date**: 2026-03-17
**Status**: Approved
**Scope**: 4 new features for the race strategy live dashboard

---

## Feature 3: Blackout Windows

### Problem
Race regulations prohibit pit stops during the first X minutes and last Y minutes of the race (e.g., first 5 min, last 15 min for 24h). Violating this incurs a 20-lap penalty. The tool has no way to warn teams or prevent the optimizer from scheduling stints that end in these zones.

### Data Model
Add to `race_configs`:
- `blackout_start_min INTEGER` — no pit in the first N minutes (nullable)
- `blackout_end_min INTEGER` — no pit in the last N minutes (nullable)

### Optimizer
- Stint 1 duration must be >= `blackout_start_min * 60` seconds
- Last stint must extend through the final `blackout_end_min * 60` seconds (no pit stop scheduled after `race_duration_s - blackout_end_min * 60`)
- Applied after fuel autonomy and driver constraint checks

### Live Dashboard
- During a blackout period, Pit In button shows a red warning banner: "Blackout period — 20-lap penalty if you pit now"
- Button stays active (emergencies happen)
- Countdown shows time until blackout lifts (start) or how long until blackout begins (end)

### Form
Two number fields in Pit Strategy section:
- "No pit first (min)"
- "No pit last (min)"

---

## Feature 4: Tech Stop

### Problem
24h races have a mandatory mid-race technical inspection stop (between hours 10-12). No driver change, no refueling. Minimum 6 minutes. Missing it or changing driver/refueling during it incurs severe penalties.

### Data Model
Add to `race_configs`:
- `tech_stop_enabled BOOLEAN DEFAULT false`
- `tech_stop_duration_s INTEGER DEFAULT 360`
- `tech_stop_window_start_s INTEGER` — earliest the tech stop can happen
- `tech_stop_window_end_s INTEGER` — latest the tech stop must be completed

Actual tech stop stored in `race_pit_stops` with `pit_type = 'tech'`.

### Service Functions
`tech_stop_in(conn, race_id)`:
- Records `pit_in_at_s` on race config (same mechanism as normal pit)
- Does NOT end the active stint — same driver stays assigned
- Does NOT allow driver change or refueling

`tech_stop_out(conn, race_id)`:
- Validates minimum duration elapsed (`tech_stop_duration_s`)
- Records pit stop with `pit_type = 'tech'`
- Clears `pit_in_at_s`
- Active stint continues (no new stint started)

### Live Dashboard
- "Tech Stop" button (yellow/amber) in action bar, distinct from Pit In
- When clicked: dashboard shows "TECH STOP" panel with:
  - Countdown timer (minimum 6 min)
  - "Resume" button appears when minimum time reached
  - Reminder: "No driver change. No refueling."
- Tech stop time is NOT added to any driver's drive time (same driver, time is paused for their stint)

### Optimizer
When tech stop is enabled, the optimizer inserts a gap in the timeline at the configured window. It shifts all planned stints after the gap by `tech_stop_duration_s`. It does not create a new stint — just a time offset.

### Form
Checkbox "Mandatory tech stop" with:
- Duration (default 6 min)
- Window start (e.g., "10:00:00" from race start)
- Window end (e.g., "12:00:00" from race start)
Complex+ tier only.

---

## Feature 5: Quick Change Mode

### Problem
In Sport category, after refueling the driver takes their number plate, ballast, and chrono to a random new kart with a full tank. Fuel carry-over is irrelevant. Teams need to track which kart chassis they received to assess kart quality.

### Data Model
Add to `race_configs`:
- `quick_change_enabled BOOLEAN DEFAULT false`

Add to `race_stints`:
- `kart_number TEXT` — chassis number (nullable, manually entered)

### Fuel Logic
When `quick_change_enabled = true`:
- Every stint starts with `fuel_at_start_kg = fuel_capacity` (full tank)
- Fuel carry-over from previous stint is ignored
- Refuel toggle is hidden in the UI (always effectively "refueled")
- `_calc_fuel_state` in `RaceStateEngine` checks `quick_change_enabled` and forces full tank

### Optimizer
When quick change is enabled:
- All pit stops have `refuel = false` (refueling is handled externally by the organizer)
- Every stint starts with full fuel regardless
- Stint duration still capped by fuel autonomy

### Live Dashboard — Pit Out Flow
When quick change is ON, Pit Out shows an inline form:
- "Kart number:" text input (chassis number)
- "Confirm Pit Out" button
- Kart number stored on the new stint's `kart_number` field

### Live Dashboard — Kart History
Collapsible section "Kart History" showing:
- Table: stint #, driver, kart number, avg lap time for that stint
- Helps spot fast/slow karts across the race

### Stint Log
New "Kart" column showing the chassis number (only when quick change is enabled).

### Form
Checkbox "Quick change (Sport category)" in Pit Strategy section.
When checked, fuel/refuel UI controls are hidden.

---

## Feature 6: Penalty Tracker

### Problem
Penalties are common in kart endurance (pit lane speed, overweight, track limits, overtime). Some are automatic lap deductions (applied post-race), others require immediate action (forced 2min30s pit passage). Teams need to track penalties and adjust strategy for forced stops.

### Data Model
New table `race_penalties`:
```sql
CREATE TABLE race_penalties (
    id              SERIAL PRIMARY KEY,
    race_id         INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    stint_order     INTEGER,
    elapsed_s       INTEGER NOT NULL,
    penalty_type    TEXT NOT NULL,  -- 'auto_laps', 'passage', 'exclusion'
    laps_deducted   INTEGER NOT NULL DEFAULT 0,
    passage_duration_s INTEGER,     -- for passage penalties (e.g., 150)
    reason          TEXT,
    cleared         BOOLEAN NOT NULL DEFAULT false,
    cleared_at_s    INTEGER,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id)
);
```
With RLS policy on `workspace_id`.

### Penalty Types
| Type | Effect | Example |
|------|--------|---------|
| `auto_laps` | N laps deducted from final count | Pit lane speed: 1 lap |
| `passage` | Forced pit passage of N seconds, no refuel/driver change allowed | Overweight: 2min30s passage |
| `exclusion` | Driver or team excluded | Alcohol in stands |

### Service Functions
`add_penalty(conn, race_id, penalty_type, laps, reason, passage_duration_s=None)`:
- Creates penalty record with current elapsed time
- Returns penalty dict

`clear_penalty(conn, race_id, penalty_id)`:
- Marks penalty as cleared with current elapsed time
- Only for `passage` type (auto_laps don't need clearing)

### Live Dashboard
**Penalty button** (red) in action bar. Click opens inline form:
- Type dropdown: Lap deduction / Pit passage / Driver exclusion
- Reason text field
- Laps deducted (auto-suggested based on type, editable)
- For passage: duration field (default 150s)

**Active penalty banner** at the top when unserved passage penalties exist:
- "PENALTY: 2min30s passage required" with serve instructions
- When in pit with active passage penalty: pit timer minimum extended by passage duration
- Pit Out disabled until passage time elapsed
- When served: penalty auto-cleared

**Penalty log** (collapsible table):
- Columns: time, type, reason, laps, status (pending/served)
- Running total of deducted laps

### Driver Summary
"Net Laps" or penalty indicator showing total penalty laps for the team.

### Optimizer Impact
When an uncleared passage penalty exists, re-optimizer adds the passage duration to the next planned pit stop duration. This ensures the plan accounts for the forced extra time.

---

## Implementation Order

These features are independent and can be built in parallel, but a logical order is:

1. **Blackout Windows** — smallest scope, touches optimizer + form + live dashboard warning
2. **Tech Stop** — new button + timer flow, similar to existing pit in/out
3. **Quick Change** — fuel logic change + kart number input + history section
4. **Penalty Tracker** — new table + button + form + passage enforcement

Each feature follows the pattern: DB column/table → service function → API endpoint → frontend UI.

---

## What's NOT Included (YAGNI)
- No auto-detection from live timing feeds
- No multi-team rivalry tracking
- No kart quality scoring algorithm — just raw data (lap times + kart number)
- No category presets — too variable across organizers
- No integration with Apex Timing or SWS systems
