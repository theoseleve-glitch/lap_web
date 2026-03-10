# Driver Sleep Mode — Design

> **Gate:** Only available for races with `race_duration_s >= 43200` (12h+).

## Goal

Add sleep window planning and live sleep tracking to the race strategy feature, so endurance teams can schedule driver rest periods and manage availability during 12h+ races.

## Data Model

New table `race_sleep_windows`:

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `race_id` | TEXT FK | → race_configs.race_id, CASCADE delete |
| `driver_id` | INTEGER FK | → race_drivers.id, CASCADE delete |
| `start_s` | INTEGER NOT NULL | Race-seconds (e.g., 21600 = 6h00) |
| `end_s` | INTEGER NOT NULL | Race-seconds (e.g., 32400 = 9h00) |
| `label` | TEXT | Optional (e.g., "Night rest") |
| `actual_wake_s` | INTEGER | Nullable — set when driver wakes early |
| `status` | TEXT DEFAULT 'planned' | `planned` / `active` / `completed` / `cancelled` |
| `created_at` | TIMESTAMP | Default NOW() |

Constraints: `end_s > start_s`, no overlapping windows for same driver.

No changes to existing tables. The existing `min_rest_s` on `race_drivers` is inter-stint minimum, unrelated.

## Setup Page (RaceConfigForm)

- New "Sleep Windows" section, visible only when `race_duration_s >= 43200`
- Per-driver: add one or more sleep blocks as race-time ranges (h:mm → h:mm)
- Visual timeline bar showing all drivers' sleep blocks as colored bands (using driver color)
- Validation: no overlapping windows for same driver; warn if total sleep < 2h per driver in 12h+ race

## Optimizer Integration (Soft Constraint)

- Sleep windows are a penalty, not a hard block
- Scheduling a driver during their sleep window is allowed but penalized
- If any stint overlaps a sleep window, optimization returns warnings:
  "Driver A stint 5 overlaps sleep window by 23min (06:00–09:00)"
- Warnings shown on detail page after optimization, before going live

## Live Dashboard

### Driver Cards
- Sleeping drivers: moon icon + "Sleeping until 9h00" countdown, card dimmed (lower opacity)
- Awake drivers with upcoming sleep: subtle indicator "Sleeps at 18h00"

### Sleep Timeline
- Horizontal bar below stint timeline showing sleep blocks with current-time marker

### End Stint — Soft Block
- When ending a stint, if next planned driver is currently sleeping, confirmation dialog:
  "Driver A is in sleep window until 9h00 (1h 23min remaining). Assign anyway?"
- User can confirm override or pick a different driver

### Wake Early Action
- Tap sleeping driver card → "Wake" button
- Sets `actual_wake_s`, makes driver immediately available
- Irreversible for that window

### Status Transitions
- `planned` → `active`: race time enters window range
- `active` → `completed`: race time exits range (or early wake)
- Any → `cancelled`: driver removed or race finished

## API Changes

### Existing Endpoints (Modified)
- `POST /race-strategy/` and `PATCH /race-strategy/<id>` — accept `sleep_windows` array nested in payload (same pattern as `drivers` and `windows`)
- `POST /race-strategy/<id>/state` — returns additional `sleep_windows` and `driver_sleep_status` in response

### New Endpoint
- `POST /race-strategy/<id>/wake-driver` — body: `{driver_id}`, sets `actual_wake_s` on active sleep window

### get_live_state() Response Additions
```json
{
  "sleep_windows": [
    {"id": 1, "driver_id": 3, "start_s": 21600, "end_s": 32400, "status": "active", "label": "Night rest"}
  ],
  "driver_sleep_status": {
    "3": {"sleeping": true, "until_s": 32400, "window_id": 1, "remaining_s": 4980},
    "5": {"sleeping": false, "next_sleep_s": 64800}
  }
}
```

## Edge Cases
- Race shortened mid-race: future sleep windows stay but become irrelevant
- Driver removed mid-race: their sleep windows ignored
- All drivers sleeping: end-stint lists all sleeping drivers, forces user to pick and confirm
- Sleep window in the past at go-live: auto-marked `completed`
