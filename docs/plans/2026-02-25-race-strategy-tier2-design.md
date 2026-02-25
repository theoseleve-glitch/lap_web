# Race Strategy — Tier 2 Features

**Date:** 2026-02-25
**Status:** Approved
**Depends on:** Tier 1 (complete)

## Overview

Four features that complete the race strategy tool: Import/Export for archiving, layout toggle for live dashboard, qualifying-aware optimizer, and pit window enforcement.

No schema changes required — all needed columns already exist from Tier 1.

---

## Feature 1: Import/Export (JSON)

### Export

- Route: `GET /race-strategy/<id>/export`
- Returns a JSON file download with Content-Disposition header
- Filename: `race-<name-slug>-<date>.json`
- Payload structure:

```json
{
  "version": 1,
  "exported_at": "2026-02-25T14:30:00Z",
  "race": { ...race_configs row... },
  "drivers": [ ...race_drivers rows... ],
  "stints": [ ...race_stints rows with actuals... ],
  "pit_stops": [ ...race_pit_stops rows... ]
}
```

- All DB columns preserved. Internal IDs (`race_id`, `id`, `stint_id`, `pit_id`) included for reference but ignored on import.
- Available on detail page (any status) and summary page.

### Import

- Route: `POST /race-strategy/import` (accepts multipart file upload)
- Creates a new `race_configs` row in `draft` status (regardless of original status)
- Recreates drivers with new auto-increment IDs, maps old driver IDs to new ones in stints
- If the exported race had stints/pit stops, imports them as `planned` status (for draft/ready originals) or preserves `completed` status (for finished originals, enabling archive viewing)
- Validation: requires `race_name` and `race_duration_s`, rejects malformed JSON with flash message
- UI: file input + "Import Race" button on the index page

---

## Feature 2: Vertical/Grid View Toggle

- Toggle button in the live dashboard header: Grid (2-col) | Vertical (1-col)
- Preference stored in `localStorage` key `rs-live-layout`
- Implementation: CSS class toggle on `.rs-live-grid`
  - Default (grid): `grid-template-columns: 1fr 1fr` (existing)
  - Vertical: `grid-template-columns: 1fr`
- Full-width cards (stint log, race summary) stay full-width in both modes
- Toggle rendered as two small buttons or a segmented control in the page header

---

## Feature 3: Qualifying Config with Refuel-After

### What already exists
- DB columns: `qualifying_duration_s`, `refuel_after_quali`
- Form fields in config.html (collapsible "Qualifying" section)

### What's new

**Optimizer awareness:**
- When `qualifying_duration_s` is set and `refuel_after_quali` is false:
  - First stint fuel estimate = `fuel_autonomy_s - qualifying_duration_s`
  - If this makes the first stint shorter than min_stint, add a warning
- When `refuel_after_quali` is true: no change (full tank at race start)
- Ballast calculation for first stint accounts for reduced fuel if not refueled

**Detail page:**
- When qualifying is configured, show a "Qualifying" info card in the detail grid:
  - Duration, refuel-after status
  - If not refueling: estimated fuel remaining at race start

---

## Feature 4: Pit Windows

### Optimizer enforcement

- If `pit_open_s` is set: no pit stop should be scheduled before this time
  - Stints covering the pre-window period are extended (or the first stint is lengthened) so the first pit happens after `pit_open_s`
- If `pit_close_s` is set (seconds before race end): no pit stop after `race_duration_s - pit_close_s`
  - The last pit stop must occur before the close time; the final stint runs to the end
- Violations reported as warnings (not hard infeasible) since regulations vary

### Live dashboard

- **Pit window banner** in the timer card:
  - Before open: "Pit window opens in MM:SS"
  - While open: "PIT WINDOW OPEN" (green banner)
  - Approaching close (last 5 min): "Pit window closes in MM:SS" (yellow)
  - After close: "PIT WINDOW CLOSED" (red)
- **End Stint button**: shows a warning icon if pitting would be outside the window
- All computed client-side from `pit_open_s`, `pit_close_s`, and elapsed time

---

## File Changes

```
telemetry_tool/
  race_strategy_v2.py                  # Optimizer: pit windows + qualifying fuel
  web/
    routes/
      race_strategy_v2.py              # + export, import routes
    templates/
      race_strategy/
        index.html                     # + import button/form
        detail.html                    # + export button, qualifying card
        live.html                      # + layout toggle, pit window banner
        summary.html                   # + export button
    static/
      js/
        race_strategy_live.js          # + layout toggle, pit window rendering
      css/
        race_strategy.css              # + vertical layout, pit window banner styles
  tests/
    test_race_strategy_v2.py           # + tests for all 4 features
```

## Testing

- Export returns valid JSON matching schema
- Import creates race with correct driver ID remapping
- Import rejects malformed JSON
- Layout toggle persists in localStorage
- Optimizer respects pit_open_s / pit_close_s boundaries
- Optimizer adjusts first stint fuel when qualifying without refuel
- Pit window banner shows correct states at different elapsed times
