# Meteo Dashboard & Weather-Pace Integration Design

> **Date:** 2026-02-25
> **Status:** Approved
> **Scope:** Meteo dashboard track selection overhaul, weather service fix, weather-pace lap time estimation, race strategy integration.

## Goal

Redesign the Live Meteo Dashboard to use real track locations (predefined CSV + user DB tracks), fix the broken historical weather API, add a two-tier weather-pace lap time estimator (physics + data-driven), and wire the weather-based pace adjustment into the race strategy tool.

## Architecture

The meteo service (`meteo_service.py`) currently hardcodes 16 F1 track coordinates that are irrelevant for a karting platform. The redesign replaces this with a unified track source that merges predefined tracks (geocoded from the CSV) with user tracks (already have GPS from session fingerprinting). Historical weather uses Open-Meteo Archive API which has a 7-day lag — we fix this by routing recent dates through the Forecast API's `past_days` parameter.

The weather-pace lap time estimator uses two tiers:
1. **Physics-based** (always available): `wet_physics.py` grip scaling applied to the track's theoretical lap time.
2. **Data-driven** (5+ sessions with weather data): `weather_correlation.py` regression model trained on the driver's actual sessions.

---

## Section 1: Track Selection Overhaul

### Problem
`meteo_service._TRACK_COORDS` is a hardcoded dict of 16 F1 circuits. The predefined track list CSV (`predefined_track_list.csv`) has ~100+ French/UK karting venues but no GPS coordinates. User tracks in the `tracks` DB table have `start_lat`/`start_lon` from GPS fingerprinting.

### Solution
**Unified track source** combining three sources:
1. **User tracks** (DB `tracks` table) — already have `start_lat`, `start_lon`. High priority: these are tracks the user actually visits.
2. **Predefined tracks** (CSV) — geocode using Open-Meteo's free Geocoding API (`https://geocoding-api.open-meteo.com/v1/search?name={city}&country=FR`). One-time lookup per venue, cached in a new `latitude`/`longitude` column added to the CSV or a DB table.
3. **Manual/custom** — keep ability to enter arbitrary lat/lon.

### API Change
`GET /api/meteo/tracks` currently returns 16 F1 tracks. After redesign:
```json
{
  "user_tracks": [
    {"id": "db:42", "name": "Kartland Paris - Piste location (layout A)", "lat": 48.5926, "lon": 2.5741, "source": "database"}
  ],
  "predefined_tracks": [
    {"id": "csv:kartland-paris", "name": "Kartland Paris (Moissy-Cramayel)", "lat": 48.5926, "lon": 2.5741, "source": "predefined"}
  ]
}
```

### Geocoding Strategy
- Use Open-Meteo Geocoding API (free, no key, same provider as weather).
- Geocode by **city name + country code** (e.g., `name=Moissy-Cramayel&country=FR`).
- Extract unique venue cities from the CSV (~60 unique cities).
- Store results in a new `predefined_track_coords` DB table: `(track_name TEXT PRIMARY KEY, city TEXT, latitude REAL, longitude REAL, geocoded_at TEXT)`.
- Geocode lazily: first time a venue is needed, call the API and cache. Or batch-geocode at app startup if table is empty.
- Fallback: if geocoding fails for a venue, exclude it from the weather dropdown.

### Key Venues (from CSV)
The CSV contains these unique venue groups (each with multiple layout rows):
- Kartland Paris (Moissy-Cramayel), Solokart (Pless), Sologne Karting (Salbris), Karting de Muret, Karting Belval (Belval-sous-Chtillon), Kart Center (Biscarrosse), BRK (Karting Yvelines 78), Racing Kart Jade (RKJ, Saint-Michel-Chef-Chef), Bretagne Karting (Combrit), Karting Loisirs Neuilly (Neuilly-sous-Clermont), Brignoles Karting Loisir, Karting Circuit Paul Ricard (Le Castellet), Circuit Sarron, Circuit Karting Besanon (Autoreille), ManachaKart (Gerbpal), EIA Circuit Pont-l'vque, ASK Angerville, ASK Lohac, RKC Racing Kart de Cormeilles, and ~80 more from RaceChrono directory.

---

## Section 2: Weather Service Fix

### Problem
`fetch_historical_weather()` uses the Open-Meteo Archive API (`/v1/archive`) which has a **7-day delay** — it cannot return weather for the last 7 days. Users typically want to check weather for recent sessions (yesterday, last weekend).

### Solution
**Smart routing by date**:
```python
def fetch_historical_weather(lat, lon, date_str):
    from datetime import datetime, date
    target = date.fromisoformat(date_str)
    days_ago = (date.today() - target).days

    if days_ago <= 0:
        # Future or today: use forecast API
        return _from_forecast(lat, lon, date_str)
    elif days_ago <= 16:
        # Recent past (within 16 days): use forecast API with past_days
        return _from_forecast_past_days(lat, lon, date_str, days_ago)
    else:
        # Older: use archive API (existing code)
        return _from_archive(lat, lon, date_str)
```

Open-Meteo Forecast API supports `past_days` up to 92 days, so the 16-day threshold is conservative. We use 16 to match the forecast window (16 days ahead + past_days behind = full coverage).

### Key Detail
The Forecast API with `past_days` returns **hourly data in the same format** as the archive API, so the response parsing is identical. The only difference is the URL:
- Archive: `https://api.open-meteo.com/v1/archive?start_date=...&end_date=...`
- Forecast+past_days: `https://api.open-meteo.com/v1/forecast?past_days=N&forecast_days=0`

We filter the response to return only hours matching the requested date.

---

## Section 3: Weather-Pace Lap Time Estimation

### Problem
The meteo dashboard shows weather but gives no insight into how conditions will affect lap times. The weather correlation page exists separately but only shows scatter plots after the fact.

### Solution
**Two-tier estimator** producing an expected lap time delta for given weather conditions:

#### Tier 1: Physics-Based (Always Available)
Uses `wet_physics.py` grip scaling factors + theoretical lap time:
```
estimated_lap_time = theoretical_dry_time / grip_factor
```
Where:
- `theoretical_dry_time` comes from the track's best theoretical lap (from `sessions.theoretical_best_s`)
- `grip_factor` comes from `wet_physics.get_grip_factor(track_state)` where `track_state` is derived from `meteo_service.estimate_track_conditions(weather)`

This gives a physics-grounded estimate even with zero session history.

#### Tier 2: Data-Driven Refinement (5+ Sessions)
When the driver has 5+ sessions on a track with weather data in `session_weather`:
- Query `session_weather` + `sessions` for the track
- Use `weather_correlation.compute_weather_pace_correlation()` to get coefficients
- Build a simple linear model: `predicted_time = base_time + sum(coeff_i * delta_i)` where `delta_i` is the difference from mean conditions
- Use `compute_optimal_conditions()` to show the driver their sweet spot

The data-driven tier **blends** with the physics tier:
- If data-driven prediction is available: weight = 0.7 data-driven + 0.3 physics
- If not enough data: 100% physics

#### API Endpoint
New `GET /api/meteo/pace-estimate`:
```
?track_id=42&lat=48.59&lon=2.57&driver_id=1
```
Returns:
```json
{
  "weather": { "air_temp_c": 18, "track_state": "damp", ... },
  "estimate": {
    "expected_lap_time_s": 52.3,
    "delta_vs_dry_s": 3.1,
    "delta_pct": 6.3,
    "tier": "physics+data",
    "confidence": 0.82,
    "grip_factor": 0.85,
    "components": {
      "physics_estimate_s": 52.9,
      "data_estimate_s": 52.0,
      "blend_weight_data": 0.7
    }
  },
  "context": {
    "dry_reference_s": 49.2,
    "n_weather_sessions": 12,
    "optimal_conditions": { "air_temp_c": {"min": 18, "max": 24} }
  }
}
```

### UI Integration
The meteo dashboard gets a new **"Lap Time Impact"** panel below the current/forecast sections:
- Shows estimated lap time delta for current conditions
- Bar chart comparing estimated time vs dry reference
- If data-driven available: shows scatter plot from weather_correlation
- Dropdown to select driver (for data-driven tier)

---

## Section 4: Race Strategy Integration

### Problem
`race_strategy.py` has a trivial weather effect: `(air_temp - 25) * 0.01` s per degree. This ignores rain, humidity, track state.

### Solution
Wire the pace estimator into `simulate_race()`:
```python
# Replace the simple temp_delta calculation with:
weather_delta = estimate_weather_lap_delta(
    params.get("weather"),
    params.get("track_id"),
    params.get("driver_id"),
    base_time,
)
```

Where `estimate_weather_lap_delta()` is a thin wrapper around the Tier 1/2 estimator that returns just the delta in seconds. This keeps `race_strategy.py` clean while using the full physics model.

### Race Strategy UI
The race strategy page already accepts weather parameters. We add:
- "Fetch Live Weather" button that auto-populates weather fields from the meteo service
- The simulation result includes `weather_impact_total_s` showing cumulative weather effect

---

## Section 5: Schema & Data Changes

### New DB Table
```sql
CREATE TABLE IF NOT EXISTS predefined_track_coords (
    track_name   TEXT PRIMARY KEY,
    city         TEXT,
    country      TEXT DEFAULT 'FR',
    latitude     REAL,
    longitude    REAL,
    geocoded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```
Added to Phase 19 migration (schema v19).

### Existing Tables Used (no changes)
- `session_weather` — already stores per-session weather data
- `sessions` — has `theoretical_best_s`, `best_lap_time_s`
- `tracks` — has `start_lat`, `start_lon`

---

## Section 6: Testing

### Unit Tests
1. **Weather service routing**: test that dates <7 days ago route to forecast+past_days, older dates route to archive
2. **Track source merging**: test that user tracks + predefined tracks produce correct unified list
3. **Pace estimator Tier 1**: test physics-based estimate with known grip factors
4. **Pace estimator Tier 2**: test data-driven blending with mock session data
5. **Race strategy integration**: test that weather delta is properly applied in simulation

### Integration Tests
- Mock Open-Meteo API responses for geocoding, forecast, archive
- End-to-end: select track -> fetch weather -> get pace estimate -> feed into strategy

### Existing Tests Preserved
- All 259 existing tests remain unchanged
- `meteo_service._run_tests()` inline tests updated for new track source
- `weather_correlation._run_tests()` unchanged (no API changes)
- `wet_physics._run_tests()` unchanged (no API changes)

---

## Out of Scope
- **Weight Impact Simulator** — cancelled per user request
- **Custom weather providers** — Open-Meteo is sufficient (free, reliable)
- **Weather data auto-fetch during ingestion** — future enhancement (fetch and store weather when processing a session CSV)
