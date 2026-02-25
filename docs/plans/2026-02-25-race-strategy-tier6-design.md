# Race Strategy Tier 6 Design: Live Race Intelligence + Connectivity

## Overview

Tier 6 adds live race intelligence (finish prediction, fuel red zone alerts, pace comparison, auto-swap suggestions), safety car / neutralization mode with fuel-burn pause, a manual rival team tracker, and browser-based notifications with audio alerts. Architecture follows a hybrid pattern: engine owns state mutations (neutralization), a new stateless `race_intelligence.py` module decorates snapshots with predictions/alerts, and all notifications are client-side via the existing 2s polling.

## Tier Scope

Tier 5 — Pit Windows & Live Dashboard (COMPLETE)
**Tier 6 — Live Race Intelligence + Connectivity (this document)**
Tier 7 — Multi-Device Sync, Live Timing API, Shared Workspaces (future)

## Feature List

### Build New

1. **Safety car / neutralization mode** — pause fuel burn, recalculate strategy, pulsing SC bar
2. **Predicted finish time calculator** — remaining time, completion %, pace delta (ahead/behind/on plan)
3. **Fuel red zone alerts** — countdown to empty, can-reach-pit check, critical/warning status
4. **Live stint pace comparison** — current vs own previous stints vs field average, trend detection
5. **Auto stint swap suggestion** — detect underperformance, suggest early driver change
6. **Rival team tracker** — manual competitor logging with strategy gap analysis
7. **Browser notifications & sound alerts** — edge-detected alerts with Web Audio tones, toasts, mute toggle

### Enhance Existing

8. **Intelligence in api_state** — new `intelligence` block merged into polling response
9. **Neutralization cascade** — fuel calculation skips neutralized time during cascade
10. **Alert toast strip** — new UI row below window status bar for dismissible alerts
11. **Rival panel** — collapsible dashboard panel with quick-add and one-tap event logging

## Architecture: Hybrid — Engine Owns State, Intelligence Decorates

### Approach

`RaceStateEngine` gains neutralization period management (the only mutation). A new `race_intelligence.py` module contains stateless pure functions that take engine snapshot + race state and return predictions/alerts/analysis. The route layer calls `engine.snapshot()` then `intelligence.analyze(snapshot, race, elapsed)` and merges both into the API response. Browser notifications are 100% client-side JS using existing polling data.

### Data flow

```
Engine (mutations)                Intelligence (read-only)
─────────────────                 ───────────────────────
neutralization start/end   ──→   predict_finish()
fuel cascade w/ SC pause   ──→   fuel_alerts()
snapshot()                 ──→   pace_analysis()
                                 swap_suggestion()
                                 rival_analysis()
                                        │
                                        ▼
                              api_state response
                              { ...engine_data, intelligence: {...} }
                                        │
                                        ▼
                              JS AlertManager (client-side)
                              → edge detection → toasts + audio + Notification API
```

## Section 1: Safety Car / Neutralization Mode

### How it works

New field on `RaceStateEngine`: `neutralizations: list[dict]` — each with `{start_s, end_s, reason}`. When the user presses "Safety Car" on the live dashboard, a POST records `start_s = elapsed`. When they press "Green Flag", it records `end_s = elapsed`.

During cascade, fuel calculation subtracts neutralized overlap from burn time:

```
effective_burn_time = planned_duration_s - overlap_with_neutralizations(stint_start, stint_end)
fuel_at_end = fuel_at_start - (burn_rate × effective_burn_time)
```

### Engine changes

- `RaceStateEngine.start_neutralization(elapsed_s, reason)` → appends period, re-cascades
- `RaceStateEngine.end_neutralization(elapsed_s)` → closes open period, re-cascades
- `_calc_fuel_state()` calls `_neutralized_overlap(start_s, end_s)` to subtract paused time
- `snapshot()` includes `neutralizations` list and `is_neutralized` bool
- `load()` reads `race_neutralizations` table
- `save()` writes neutralization periods

### Helper

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

### UI

- Yellow "SC" button in toolbar → toggles neutralization on/off
- Active neutralization: pulsing yellow bar across the top of the dashboard
- Fuel gauge pauses depletion visually during SC
- Neutralization log shows start/end times and duration

## Section 2: Race Intelligence Module (`race_intelligence.py`)

Stateless module — pure functions. Called by `api_state()` after engine snapshot.

### 2a. Predicted Finish Time

```python
def predict_finish(race, stints, fuel_model, elapsed_s, neutralizations) -> dict:
```

Returns:
- `remaining_s`: race_duration_s - elapsed_s
- `completion_pct`: elapsed / duration × 100
- `predicted_finish_ts`: race_start_ts + race_duration_s (absolute)
- `pace_delta_s`: sum of (actual - planned) across completed stints
- `pace_status`: "AHEAD" / "BEHIND" / "ON PLAN" (±30s threshold)

### 2b. Fuel Red Zone Alerts

```python
def fuel_alerts(current_fuel_kg, burn_rate_kgs, elapsed_s, active_stint, next_pit_s) -> dict:
```

Returns:
- `fuel_remaining_s`: seconds until fuel runs out at current burn rate
- `fuel_status`: "ok" / "warning" (< 5 min) / "critical" (< 2 min)
- `can_reach_pit`: bool — enough fuel to reach next planned pit stop?
- `shortfall_s`: if can't reach pit, how many seconds short

### 2c. Live Stint Pace Comparison

```python
def pace_analysis(stints, active_stint, elapsed_s) -> dict:
```

Returns:
- `pace_vs_own_avg_s`: delta per-stint-second vs same driver's completed stints
- `pace_vs_field_avg_s`: delta vs all completed stints
- `pace_trend`: "improving" / "stable" / "degrading" (last 3 data points)
- `recommendation`: if degrading significantly → "Consider early driver swap"

### 2d. Auto Stint Swap Suggestion

```python
def swap_suggestion(stints, drivers, active_stint, elapsed_s, fuel_model) -> dict | None:
```

Returns suggestion only when:
- Current driver pace > 10% slower than their own average
- Next driver has available cumulative time
- Remaining fuel sufficient to pit now

Returns `None` or `{"suggest_swap": True, "reason": "...", "next_driver": "..."}`.

### 2e. Rival Analysis

```python
def rival_analysis(rivals, rival_events, elapsed_s) -> list[dict]:
```

Per rival:
- `estimated_pits`: count of pit_in events
- `avg_stint_s`: average time between consecutive pit events
- `last_activity_s`: seconds since last event
- `strategy_gap`: "1 stop ahead" / "1 stop behind" / "same pace"

### Integration point

```python
# In api_state():
from race_intelligence import analyze_race
engine_data["intelligence"] = analyze_race(engine_snapshot, race, stints, elapsed, rivals, rival_events)
```

## Section 3: Rival Tracker

Manual entry — crew logs observed competitor activity. No external API integration.

### Schema

```sql
CREATE TABLE IF NOT EXISTS race_rivals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id    INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    team_name  TEXT NOT NULL,
    car_number TEXT,
    notes      TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS race_rival_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id    INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    rival_id   INTEGER NOT NULL REFERENCES race_rivals(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,       -- 'pit_in','pit_out','driver_change','penalty','note'
    at_s       INTEGER NOT NULL,
    detail     TEXT,
    created_at TEXT
);
```

### API

- `GET /api/<race_id>/rivals` → list rivals with events
- `POST /api/<race_id>/rivals` → add rival `{team_name, car_number}`
- `POST /api/<race_id>/rivals/<rival_id>/event` → log event `{event_type, detail}`
- `DELETE /api/<race_id>/rivals/<rival_id>` → remove rival and events

### UI

Collapsible panel on live dashboard (hidden in Pit Wall compact mode). Quick-add form for team name + car number. One-tap event buttons: Pit In / Pit Out / Driver Change / Penalty / Note.

Compact rival card:
```
┌─────────────────────────────────┐
│ #42 Team Alpha   │ 3 pits      │
│ Last pit: 12:34 ago │ ~28min stints │
│ 1 stop ahead                    │
└─────────────────────────────────┘
```

## Section 4: Browser Notifications & Sound Alerts

100% client-side. Existing 2s polling provides all data needed.

### Alert conditions

| Trigger | Source field | Threshold | Sound | Priority |
|---------|------------|-----------|-------|----------|
| Fuel critical | `intelligence.fuel_status` | `"critical"` (< 2 min) | alarm chime | high |
| Fuel warning | `intelligence.fuel_status` | `"warning"` (< 5 min) | soft beep | medium |
| Pit window opening | `window_status[].status` | transition → `"open"` | double beep | high |
| Pit window closing | `window_status[].status` | transition → `"closing"` | urgent tone | high |
| Swap suggestion | `intelligence.swap_suggestion` | not null | notification ding | medium |
| Neutralization start/end | `is_neutralized` | state change | siren / horn | high |
| Stint time limit | active stint elapsed | > 90% of `max_stint_s` | warning beep | medium |

### AlertManager class

```javascript
class AlertManager {
    constructor() {
        this.previousState = {};  // last-seen values for edge detection
        this.muted = false;
        this.cooldowns = {};      // per-type cooldown timestamps
        this.audioCtx = null;     // lazy-init Web Audio API
        this.history = [];        // last 20 alerts
    }

    check(state) { /* compare vs previousState, fire on transitions */ }
    playTone(frequency, duration) { /* Web Audio oscillator */ }
    notify(title, body, priority) { /* Notification API + toast */ }
}
```

- **Edge detection**: alerts fire on state transitions only, not every poll
- **Cooldown**: 30s per alert type to prevent spam
- **Audio**: Web Audio API oscillator tones (no sound files)
- **Browser notifications**: `Notification.requestPermission()` on first interaction
- **Mute toggle**: bell icon in toolbar, persisted in localStorage
- **Toast strip**: slides in below window status bar, auto-dismiss 8s, click to dismiss
- **History**: expandable log at bottom, last 20 alerts with timestamps

## Schema Changes

Version bump: v23 → v24. All additive via `ensure_schema()`.

```sql
CREATE TABLE IF NOT EXISTS race_neutralizations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id   INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    start_s   INTEGER NOT NULL,
    end_s     INTEGER,
    reason    TEXT DEFAULT 'safety_car'
);

CREATE TABLE IF NOT EXISTS race_rivals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id    INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    team_name  TEXT NOT NULL,
    car_number TEXT,
    notes      TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS race_rival_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id    INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    rival_id   INTEGER NOT NULL REFERENCES race_rivals(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    at_s       INTEGER NOT NULL,
    detail     TEXT,
    created_at TEXT
);
```

## Files Touched

| File | Action | Description |
|------|--------|-------------|
| `telemetry_tool/race_intelligence.py` | **NEW** | Stateless intelligence: finish predictor, fuel alerts, pace analysis, swap suggestion, rival analysis |
| `telemetry_tool/race_state_engine.py` | MODIFY | Neutralization periods: load/save/cascade with fuel burn pause |
| `telemetry_tool/db/schema.py` | MODIFY | v24: 3 new tables |
| `telemetry_tool/db/migrate.py` | MODIFY | v24 migration block |
| `telemetry_tool/web/routes/race_strategy_v2.py` | MODIFY | Rival CRUD endpoints, neutralization toggle, intelligence in api_state |
| `telemetry_tool/web/templates/race_strategy/live.html` | MODIFY | SC button, alert toasts, rival panel, notification bell |
| `telemetry_tool/web/static/js/race_strategy_live.js` | MODIFY | AlertManager, rival panel rendering, neutralization UI, intelligence display |
| `telemetry_tool/web/static/css/race_strategy.css` | MODIFY | Neutralization bar, alert toasts, rival cards, mute button |
| `telemetry_tool/tests/test_race_state_engine.py` | MODIFY | Neutralization cascade tests |
| `telemetry_tool/tests/test_race_intelligence.py` | **NEW** | Intelligence module unit tests |
| `telemetry_tool/tests/test_race_strategy_v2.py` | MODIFY | Schema v24, rival CRUD, neutralization API tests |

## What's NOT in Tier 6

- Multi-device sync / role-based views → Tier 7
- Live timing API ingest (Apex/MyLaps) → Tier 7
- Shared team workspace → Tier 7
- Push notifications to phone (service worker) → Tier 7
