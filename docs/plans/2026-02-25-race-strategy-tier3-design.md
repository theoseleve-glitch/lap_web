# Race Strategy — Tier 3 Features

**Date:** 2026-02-25
**Status:** Approved
**Depends on:** Tier 1 (complete), Tier 2 (complete)

## Overview

Four features that complete the race strategy tool: TeamTalk live chat with driver COM channels, light/dark theme toggle, multilingual support (7 languages), and weather integration with pace correlation, fuel adjustment, and rain radar.

Schema changes: one new table (`race_messages`), one new column (`com_channel` on `race_drivers`). Schema version 20 → 21.

---

## Feature 1: TeamTalk (Live Race Chat + Driver COM)

### Schema

```sql
ALTER TABLE race_drivers ADD COLUMN com_channel TEXT;

CREATE TABLE race_messages (
    msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    author TEXT NOT NULL,
    message TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TEXT DEFAULT (datetime('now'))
);
```

Categories: `general`, `pit`, `driver`, `weather`, `flag`

### Live Dashboard

- New card (7th, full-width) below the stint log
- Scrollable message list, auto-scrolls to bottom on new messages
- Input field + category dropdown + send button
- Messages loaded via existing `/api/state` response (new `messages` key)
- Sent via `POST /race-strategy/<id>/api/messages`
- Category color coding: pit = red, weather = blue, flag = yellow, driver = green, general = default

### Driver COM Channel

- New optional field in config form driver rows: "COM Channel" (free text)
- Shown in:
  - Drivers table on detail page (new column)
  - "Current Driver" card on live dashboard (below driver name)
  - Export JSON (included in driver data)

---

## Feature 2: Light Theme

### Approach

CSS custom properties with `data-theme` attribute on `<html>`.

### Implementation

- `:root` keeps current dark theme values (default)
- `:root[data-theme="light"]` overrides all color variables with light equivalents
- Auto-detect: `prefers-color-scheme` media query on first visit
- Manual toggle: button in nav bar (visible on all pages)
- Preference saved to `localStorage` key `theme`
- `theme.js` loaded in `<head>` before CSS to prevent flash of wrong theme
- Scope: entire web app (applies to `main.css` variables used globally)

### Color Mapping

| Variable | Dark (current) | Light |
|----------|---------------|-------|
| `--bg` | #0d1117 | #ffffff |
| `--bg-secondary` | #161b22 | #f6f8fa |
| `--text` | #e6edf3 | #1f2328 |
| `--text-secondary` | #8b949e | #656d76 |
| `--border` | #30363d | #d0d7de |
| `--blue` | #58a6ff | #0969da |
| `--green` | #3fb950 | #1a7f37 |
| `--red` | #f85149 | #cf222e |
| `--yellow` | #d29922 | #9a6700 |

---

## Feature 3: Multilingual (i18n)

### Languages

English (en), French (fr), Italian (it), German (de), Spanish (es), Portuguese (pt), Chinese (zh)

### Architecture

- JSON translation files in `telemetry_tool/web/i18n/` (one per language)
- Flask `before_request` hook loads the selected language's JSON
- Injected into Jinja context as `t` dict
- Templates use `{{ t.race }}` instead of hardcoded strings
- Fallback: English key used if translation is missing
- Language selection: dropdown in nav bar, saved to `localStorage` key `lang`, sent via cookie `lang`

### Scope

Race strategy pages only (6 templates: index, config, detail, live, summary + nav link). ~80-100 translatable strings.

### Translation File Structure

```json
{
  "race_strategy": "Race Strategy",
  "new_race": "New Race",
  "import": "Import",
  "export_json": "Export JSON",
  "race": "Race",
  "duration": "Duration",
  "stints": "Stints",
  "drivers": "Drivers",
  "driver": "Driver",
  "pit_stops": "Pit Stops",
  "optimize": "Optimize Stints",
  "go_live": "Go Live",
  "finish_race": "Finish Race",
  "status": "Status",
  "draft": "Draft",
  "ready": "Ready",
  "live": "Live",
  "finished": "Finished",
  "planned": "Planned",
  "actual": "Actual",
  "delta": "Delta",
  "ballast": "Ballast",
  "notes": "Notes",
  "fuel": "Fuel",
  "weight": "Weight",
  "qualifying": "Qualifying",
  "pit_window": "Pit Window",
  "team_talk": "Team Talk",
  "weather": "Weather",
  "com_channel": "COM Channel",
  "send": "Send",
  "remaining": "Remaining",
  "elapsed": "Elapsed",
  "current_driver": "Current Driver",
  "next_driver": "Next Driver",
  "on_plan": "On Plan",
  "ahead": "Ahead",
  "behind": "Behind",
  "grid_view": "Grid",
  "vertical_view": "Vertical",
  "back": "Back",
  "edit_config": "Edit Config",
  "delete": "Delete",
  "duplicate": "Duplicate",
  "view_summary": "View Summary",
  "view_config": "View Config"
}
```

---

## Feature 4: Weather Integration

### Prerequisite

Track must have known lat/lon coordinates (matched via `meteo_service.get_known_tracks()`). If no coordinates found, weather cards are hidden.

### 4a. Weather Conditions Card

- New card in live dashboard grid (8th card, half-width)
- Shows: temperature, humidity, wind speed, rain, cloud cover, weather description (WMO text)
- Fetched via `/api/meteo/current?lat=X&lon=Y`
- Refreshed every 5 minutes (separate interval from 2s state poll)
- Track coordinates resolved server-side from `track_name`

### 4b. Forecast Timeline Overlay

- Hourly forecast bars rendered above the stint timeline on the live dashboard
- Shows rain probability (blue intensity) + temperature per hour
- Uses `/api/meteo/forecast?lat=X&lon=Y&hours=<race_hours>`
- Fetched once at page load, refreshed every 15 minutes
- Small colored dots/bars above stint blocks

### 4c. Weather-Pace Correlation

- If 5+ sessions exist for this track: show pace estimate in weather card
- Uses `pace_estimator.estimate_pace()` for blended physics+data estimate
- Display: "Pace impact: +2.1s vs dry (grip: 0.85)"
- New API route: `GET /race-strategy/<id>/api/weather` returning current + forecast + pace estimate

### 4d. Rain Radar

- Embedded image from RainViewer API (free, no key required)
- Small card or expandable panel on live dashboard
- Centered on track lat/lon
- Refreshed every 10 minutes
- RainViewer provides radar tile URLs for given coordinates

### 4e. Weather-Fuel Consumption Adjustment

- When conditions change (dry → wet → drying), adjust fuel autonomy estimate
- Formula: `adjusted_autonomy = base_autonomy * grip_factor`
- Grip factor from `wet_physics.get_grip_factor(track_state)`
- Wet = 0.68 grip → autonomy drops ~32%
- Display in Fuel & Ballast card: "Fuel: 38:00 (wet est: ~26:00)"
- Track state computed from current weather via `estimate_track_conditions()`

---

## File Changes

```
telemetry_tool/
  db/schema.py                         # + Phase 16: race_messages table, com_channel column
  db/migrate.py                        # + version 21
  race_strategy_v2.py                  # (no changes)
  web/
    app.py                             # + i18n before_request hook
    routes/
      race_strategy_v2.py              # + messages API, weather API, i18n context
    i18n/
      en.json                          # English (source)
      fr.json                          # French
      it.json                          # Italian
      de.json                          # German
      es.json                          # Spanish
      pt.json                          # Portuguese
      zh.json                          # Chinese
    templates/
      base.html                        # + theme toggle button, lang picker, theme.js
      race_strategy/
        index.html                     # + i18n strings
        config.html                    # + com_channel field, i18n strings
        detail.html                    # + COM column in drivers table, i18n strings
        live.html                      # + TeamTalk card, weather cards, i18n strings
        summary.html                   # + i18n strings
    static/
      js/
        theme.js                       # Theme detection + toggle (loaded in <head>)
        race_strategy_live.js          # + TeamTalk rendering, weather fetch, fuel adjustment
      css/
        main.css                       # + :root[data-theme="light"] variables
        race_strategy.css              # + TeamTalk card, weather card, radar styles
  tests/
    test_race_strategy_v2.py           # + tests for messages, i18n, weather integration
```

## Testing

- TeamTalk: messages insert/retrieve, category filtering, cascade delete
- COM channel: stored and exported correctly
- Theme: light variables defined, toggle sets data-theme attribute
- i18n: translation loading, fallback to English, missing key handling
- Weather card: API returns current conditions for known track
- Fuel adjustment: grip factor correctly scales autonomy
- Pace estimate: returns delta when 5+ sessions available
