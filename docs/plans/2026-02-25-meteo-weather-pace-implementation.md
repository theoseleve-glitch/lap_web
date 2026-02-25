# Meteo Dashboard & Weather-Pace Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the Live Meteo Dashboard with real track locations, fix broken historical weather, add weather-pace lap time estimation, and wire it into race strategy.

**Architecture:** Replace hardcoded F1 track coords in `meteo_service.py` with a unified source (user DB tracks + geocoded predefined CSV tracks). Fix historical weather by routing recent dates through Forecast API `past_days`. Add a two-tier pace estimator (physics via `wet_physics.py` + data-driven via `weather_correlation.py`). Wire the estimator into `race_strategy.py`.

**Tech Stack:** Python 3.x, Flask, SQLite, Open-Meteo API (free, no key), urllib.request, `wet_physics.py`, `weather_correlation.py`

---

### Task 1: Schema v19 — predefined_track_coords table

Add a new DB table to cache geocoded coordinates for predefined track venues.

**Files:**
- Modify: `telemetry_tool/db/schema.py:9` (bump version), `:736` (add phase + ALL_TABLES)
- Modify: `telemetry_tool/db/migrate.py:355-359` (add phase 19 migration)
- Test: `telemetry_tool/tests/test_driver_features.py`

**Step 1: Write the failing test**

Add at the end of `telemetry_tool/tests/test_driver_features.py`:

```python
class TestMeteoSchema:
    """Task 1: predefined_track_coords table exists after migration."""

    def test_predefined_track_coords_table_exists(self, db):
        """The predefined_track_coords table should exist after ensure_schema."""
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='predefined_track_coords'"
        ).fetchone()
        assert row is not None, "predefined_track_coords table not created"

    def test_predefined_track_coords_columns(self, db):
        """Table should have expected columns."""
        cols = {r[1] for r in db.execute("PRAGMA table_info(predefined_track_coords)").fetchall()}
        assert "track_name" in cols
        assert "city" in cols
        assert "country" in cols
        assert "latitude" in cols
        assert "longitude" in cols
        assert "geocoded_at" in cols

    def test_schema_version_19(self, db):
        """Schema version 19 should be recorded."""
        row = db.execute("SELECT version FROM schema_version WHERE version = 19").fetchone()
        assert row is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestMeteoSchema -v`
Expected: FAIL — table does not exist, version 19 not recorded

**Step 3: Write minimal implementation**

In `telemetry_tool/db/schema.py`:

1. Change line 9: `SCHEMA_VERSION = 19`

2. After the `PHASE_13_TABLES` block (after line 733), add:

```python
# ------------------------------------------------------------------
# Phase 14 tables (meteo geocoding cache)
# ------------------------------------------------------------------

_PREDEFINED_TRACK_COORDS_TABLE = """
CREATE TABLE IF NOT EXISTS predefined_track_coords (
    track_name   TEXT PRIMARY KEY,
    city         TEXT,
    country      TEXT DEFAULT 'FR',
    latitude     REAL,
    longitude    REAL,
    geocoded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

PHASE_14_TABLES: list[tuple[str, str]] = [
    ("predefined_track_coords", _PREDEFINED_TRACK_COORDS_TABLE),
]
```

3. Update `ALL_TABLES` at the end to append `+ PHASE_14_TABLES`

In `telemetry_tool/db/migrate.py`, after the Phase 18 block (after line 358), add:

```python
    cur.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) "
        "VALUES (?, ?);",
        (19, "Phase 19 schema — predefined_track_coords geocoding cache"),
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestMeteoSchema -v`
Expected: 3 PASSED

**Step 5: Run full test suite**

Run: `pytest telemetry_tool/tests/ -v`
Expected: All 259 + 3 = 262 tests pass

**Step 6: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/migrate.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: schema v19 — add predefined_track_coords table for geocoding cache"
```

---

### Task 2: Track geocoder module

Create a module that geocodes city names using the Open-Meteo Geocoding API and caches results in the DB table from Task 1.

**Files:**
- Create: `telemetry_tool/track_geocoder.py`
- Test: `telemetry_tool/tests/test_driver_features.py`

**Step 1: Write the failing tests**

Add at the end of `telemetry_tool/tests/test_driver_features.py`:

```python
class TestTrackGeocoder:
    """Task 2: geocoding predefined track venues."""

    def test_parse_predefined_csv_unique_venues(self, db):
        """Should extract unique venue names with cities from predefined_tracks."""
        # Seed some predefined tracks (already imported by ensure_schema if CSV exists,
        # but let's insert manually for test isolation).
        db.execute(
            "INSERT INTO predefined_tracks (track_name, city, country) VALUES (?, ?, ?)",
            ("Kartland Paris", "Moissy-Cramayel", "France"),
        )
        db.execute(
            "INSERT INTO predefined_tracks (track_name, city, country) VALUES (?, ?, ?)",
            ("Kartland Paris", "Moissy-Cramayel", "France"),  # duplicate venue name
        )
        db.execute(
            "INSERT INTO predefined_tracks (track_name, city, country) VALUES (?, ?, ?)",
            ("Solokart", "Plessé", "France"),
        )
        db.commit()

        from track_geocoder import get_ungeocoded_venues
        venues = get_ungeocoded_venues(db)
        names = [v["track_name"] for v in venues]
        # Should have 2 unique venues (Kartland Paris + Solokart), not 3 rows
        assert len(venues) == 2
        assert "Kartland Paris" in names
        assert "Solokart" in names

    def test_cache_geocode_result(self, db):
        """Should store geocoded lat/lon in predefined_track_coords table."""
        from track_geocoder import cache_geocode_result
        cache_geocode_result(db, "Kartland Paris", "Moissy-Cramayel", "FR", 48.5926, 2.5741)
        db.commit()
        row = db.execute(
            "SELECT latitude, longitude FROM predefined_track_coords WHERE track_name = ?",
            ("Kartland Paris",),
        ).fetchone()
        assert row is not None
        assert abs(row["latitude"] - 48.5926) < 0.001
        assert abs(row["longitude"] - 2.5741) < 0.001

    def test_cache_is_idempotent(self, db):
        """Caching the same venue twice should not raise or duplicate."""
        from track_geocoder import cache_geocode_result
        cache_geocode_result(db, "Kartland Paris", "Moissy-Cramayel", "FR", 48.5926, 2.5741)
        cache_geocode_result(db, "Kartland Paris", "Moissy-Cramayel", "FR", 48.5926, 2.5741)
        db.commit()
        count = db.execute(
            "SELECT COUNT(*) FROM predefined_track_coords WHERE track_name = ?",
            ("Kartland Paris",),
        ).fetchone()[0]
        assert count == 1

    def test_get_cached_coords(self, db):
        """Should retrieve all cached coordinates."""
        from track_geocoder import cache_geocode_result, get_cached_coords
        cache_geocode_result(db, "Kartland Paris", "Moissy-Cramayel", "FR", 48.59, 2.57)
        cache_geocode_result(db, "Solokart", "Plessé", "FR", 47.53, -1.86)
        db.commit()
        coords = get_cached_coords(db)
        assert len(coords) == 2
        by_name = {c["track_name"]: c for c in coords}
        assert abs(by_name["Kartland Paris"]["latitude"] - 48.59) < 0.01
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestTrackGeocoder -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'track_geocoder'`

**Step 3: Write minimal implementation**

Create `telemetry_tool/track_geocoder.py`:

```python
"""
track_geocoder.py
-----------------
Geocode predefined track venues using Open-Meteo's free Geocoding API.
Results are cached in the ``predefined_track_coords`` DB table.

Public API
~~~~~~~~~~
``get_ungeocoded_venues(conn)``
    Return venues from predefined_tracks that have no cached coords.
``cache_geocode_result(conn, track_name, city, country_code, lat, lon)``
    Store a geocoded result (INSERT OR REPLACE, idempotent).
``get_cached_coords(conn)``
    Return all cached coordinates.
``geocode_city(city, country_code)``
    Call Open-Meteo Geocoding API. Returns (lat, lon) or None.
``geocode_all_pending(conn)``
    Geocode all ungeocoded venues and cache results.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_GEOCODING_BASE = "https://geocoding-api.open-meteo.com/v1/search"

# Country name → ISO 2-letter code for geocoding API
_COUNTRY_CODES = {
    "france": "FR",
    "united kingdom": "GB",
}


def get_ungeocoded_venues(conn) -> list[dict[str, Any]]:
    """
    Return unique venues from predefined_tracks that have no cached coords.

    Returns list of dicts with keys: track_name, city, country.
    """
    rows = conn.execute(
        """SELECT DISTINCT pt.track_name, pt.city, pt.country
           FROM predefined_tracks pt
           LEFT JOIN predefined_track_coords ptc ON pt.track_name = ptc.track_name
           WHERE ptc.track_name IS NULL
             AND pt.city IS NOT NULL AND pt.city != ''"""
    ).fetchall()
    return [dict(r) for r in rows]


def cache_geocode_result(
    conn, track_name: str, city: str, country_code: str,
    lat: float, lon: float,
) -> None:
    """Store geocoded result. Idempotent (INSERT OR REPLACE)."""
    conn.execute(
        "INSERT OR REPLACE INTO predefined_track_coords "
        "(track_name, city, country, latitude, longitude) "
        "VALUES (?, ?, ?, ?, ?)",
        (track_name, city, country_code, lat, lon),
    )


def get_cached_coords(conn) -> list[dict[str, Any]]:
    """Return all cached coordinates as list of dicts."""
    rows = conn.execute(
        "SELECT track_name, city, country, latitude, longitude "
        "FROM predefined_track_coords"
    ).fetchall()
    return [dict(r) for r in rows]


def geocode_city(city: str, country_code: str = "FR") -> Optional[tuple[float, float]]:
    """
    Call Open-Meteo Geocoding API for a city name.

    Returns (lat, lon) tuple or None on failure.
    """
    try:
        import urllib.request
        import urllib.parse
        url = (
            f"{_GEOCODING_BASE}"
            f"?name={urllib.parse.quote(city)}"
            f"&count=1&language=en&format=json"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        results = data.get("results", [])
        if not results:
            logger.warning("Geocoding failed for city '%s': no results", city)
            return None

        best = results[0]
        lat = best.get("latitude")
        lon = best.get("longitude")
        if lat is not None and lon is not None:
            return (float(lat), float(lon))
        return None

    except Exception as exc:
        logger.warning("Geocoding error for city '%s': %s", city, exc)
        return None


def geocode_all_pending(conn) -> int:
    """
    Geocode all venues with no cached coords. Returns count geocoded.
    """
    venues = get_ungeocoded_venues(conn)
    count = 0
    for v in venues:
        city = v.get("city", "")
        country_raw = (v.get("country") or "France").lower()
        country_code = _COUNTRY_CODES.get(country_raw, "FR")

        result = geocode_city(city, country_code)
        if result:
            lat, lon = result
            cache_geocode_result(conn, v["track_name"], city, country_code, lat, lon)
            count += 1
            logger.info("Geocoded '%s' (%s) → %.4f, %.4f", v["track_name"], city, lat, lon)
        else:
            logger.warning("Could not geocode '%s' (%s)", v["track_name"], city)

    if count:
        conn.commit()
    return count
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestTrackGeocoder -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/track_geocoder.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: add track_geocoder module with Open-Meteo geocoding + DB cache"
```

---

### Task 3: Unified track source in meteo_service

Replace hardcoded `_TRACK_COORDS` dict with a function that merges user DB tracks + geocoded predefined tracks.

**Files:**
- Modify: `telemetry_tool/meteo_service.py:37-63` (replace `_TRACK_COORDS` + `get_known_tracks`)
- Test: `telemetry_tool/tests/test_driver_features.py`

**Step 1: Write the failing tests**

Add at the end of `telemetry_tool/tests/test_driver_features.py`:

```python
class TestUnifiedTrackSource:
    """Task 3: unified track source merging DB + predefined tracks."""

    def test_get_all_track_locations_user_tracks(self, db):
        """User tracks with lat/lon should appear in the unified list."""
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m, start_lat, start_lon) "
            "VALUES ('trk1', 'My Kart Track', 800.0, 48.59, 2.57)"
        )
        db.commit()
        from meteo_service import get_all_track_locations
        result = get_all_track_locations(db)
        user = result["user_tracks"]
        assert len(user) == 1
        assert user[0]["name"] == "My Kart Track"
        assert abs(user[0]["lat"] - 48.59) < 0.01

    def test_get_all_track_locations_predefined(self, db):
        """Predefined tracks with cached coords should appear."""
        from track_geocoder import cache_geocode_result
        cache_geocode_result(db, "Kartland Paris", "Moissy-Cramayel", "FR", 48.59, 2.57)
        db.commit()
        from meteo_service import get_all_track_locations
        result = get_all_track_locations(db)
        pred = result["predefined_tracks"]
        assert len(pred) >= 1
        names = [p["name"] for p in pred]
        assert "Kartland Paris" in names

    def test_get_all_track_locations_no_latlon_excluded(self, db):
        """Tracks without lat/lon should not appear."""
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) "
            "VALUES ('trk2', 'No GPS Track', 500.0)"
        )
        db.commit()
        from meteo_service import get_all_track_locations
        result = get_all_track_locations(db)
        user_names = [t["name"] for t in result["user_tracks"]]
        assert "No GPS Track" not in user_names

    def test_get_known_tracks_backward_compat(self, db):
        """get_known_tracks() still returns a flat list for backward compat."""
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m, start_lat, start_lon) "
            "VALUES ('trk1', 'My Track', 800.0, 48.59, 2.57)"
        )
        db.commit()
        from meteo_service import get_known_tracks
        result = get_known_tracks(db)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "name" in result[0]
        assert "lat" in result[0]
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestUnifiedTrackSource -v`
Expected: FAIL — `get_all_track_locations` does not exist, `get_known_tracks` doesn't accept conn

**Step 3: Write minimal implementation**

In `telemetry_tool/meteo_service.py`, replace lines 37-62 (the `_TRACK_COORDS` dict and `get_known_tracks` function) with:

```python
def get_all_track_locations(conn) -> dict[str, list[dict[str, Any]]]:
    """
    Return unified track locations from user DB + predefined geocoded tracks.

    Returns dict with keys 'user_tracks' and 'predefined_tracks'.
    Each entry has: id, name, lat, lon, source.
    """
    # User tracks from DB (those with GPS coordinates)
    user_rows = conn.execute(
        "SELECT track_id, track_name, start_lat, start_lon "
        "FROM tracks "
        "WHERE start_lat IS NOT NULL AND start_lon IS NOT NULL "
        "ORDER BY track_name"
    ).fetchall()
    user_tracks = [
        {
            "id": f"db:{r['track_id']}",
            "name": r["track_name"],
            "lat": r["start_lat"],
            "lon": r["start_lon"],
            "source": "database",
        }
        for r in user_rows
    ]

    # Predefined tracks from geocoding cache
    pred_rows = conn.execute(
        "SELECT track_name, latitude, longitude "
        "FROM predefined_track_coords "
        "WHERE latitude IS NOT NULL AND longitude IS NOT NULL "
        "ORDER BY track_name"
    ).fetchall()
    predefined_tracks = [
        {
            "id": f"csv:{r['track_name']}",
            "name": r["track_name"],
            "lat": r["latitude"],
            "lon": r["longitude"],
            "source": "predefined",
        }
        for r in pred_rows
    ]

    return {
        "user_tracks": user_tracks,
        "predefined_tracks": predefined_tracks,
    }


def get_known_tracks(conn=None) -> list[dict[str, Any]]:
    """
    Return flat list of all known track locations for dropdown.

    Backward-compatible: if conn is provided, returns unified source.
    If conn is None, returns empty list (callers must pass conn).
    """
    if conn is None:
        return []

    all_locs = get_all_track_locations(conn)
    flat = []
    for t in all_locs["user_tracks"]:
        flat.append({"id": t["id"], "name": t["name"], "lat": t["lat"], "lon": t["lon"]})
    for t in all_locs["predefined_tracks"]:
        flat.append({"id": t["id"], "name": t["name"], "lat": t["lat"], "lon": t["lon"]})
    return flat
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestUnifiedTrackSource -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/meteo_service.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: replace hardcoded F1 tracks with unified DB + predefined track source"
```

---

### Task 4: Fix historical weather — smart date routing

Refactor `fetch_historical_weather()` to route recent dates (<= 92 days) through the Forecast API with `past_days` instead of the broken Archive API.

**Files:**
- Modify: `telemetry_tool/meteo_service.py:121-188` (refactor `fetch_historical_weather`)
- Test: `telemetry_tool/tests/test_driver_features.py`

**Step 1: Write the failing tests**

Add at the end of `telemetry_tool/tests/test_driver_features.py`:

```python
class TestHistoricalWeatherRouting:
    """Task 4: smart date routing for historical weather."""

    def test_route_recent_date_uses_forecast(self):
        """Dates within 92 days should route to forecast+past_days."""
        from meteo_service import _pick_historical_strategy
        from datetime import date, timedelta
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        strategy = _pick_historical_strategy(yesterday)
        assert strategy == "forecast_past_days"

    def test_route_old_date_uses_archive(self):
        """Dates older than 92 days should route to archive."""
        from meteo_service import _pick_historical_strategy
        old_date = "2024-06-15"
        strategy = _pick_historical_strategy(old_date)
        assert strategy == "archive"

    def test_route_today_uses_forecast(self):
        """Today's date should route to forecast (past_days=0 or current)."""
        from meteo_service import _pick_historical_strategy
        from datetime import date
        today = date.today().isoformat()
        strategy = _pick_historical_strategy(today)
        assert strategy in ("forecast_past_days", "forecast_current")

    def test_route_future_uses_forecast(self):
        """Future date should route to forecast."""
        from meteo_service import _pick_historical_strategy
        from datetime import date, timedelta
        future = (date.today() + timedelta(days=3)).isoformat()
        strategy = _pick_historical_strategy(future)
        assert strategy == "forecast_current"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestHistoricalWeatherRouting -v`
Expected: FAIL — `_pick_historical_strategy` does not exist

**Step 3: Write minimal implementation**

In `telemetry_tool/meteo_service.py`, add a new routing function before `fetch_historical_weather` and refactor the existing function.

Add this helper function:

```python
# Maximum age (in days) for using forecast API with past_days
_FORECAST_PAST_DAYS_MAX = 92


def _pick_historical_strategy(date_str: str) -> str:
    """
    Decide which API to use for a historical weather request.

    Returns:
        'forecast_current' — date is today or in the future
        'forecast_past_days' — date is 1-92 days ago (Open-Meteo forecast + past_days)
        'archive' — date is older than 92 days (Open-Meteo archive API)
    """
    from datetime import date as dt_date
    target = dt_date.fromisoformat(date_str)
    days_ago = (dt_date.today() - target).days

    if days_ago <= 0:
        return "forecast_current"
    elif days_ago <= _FORECAST_PAST_DAYS_MAX:
        return "forecast_past_days"
    else:
        return "archive"
```

Then refactor `fetch_historical_weather` to use it:

```python
def fetch_historical_weather(
    lat: float, lon: float, date_str: str,
) -> dict[str, Any]:
    """
    Fetch historical weather — smart-routes by date.

    - Today/future → forecast API
    - Within 92 days → forecast API with past_days (fixes 7-day archive lag)
    - Older → archive API
    """
    strategy = _pick_historical_strategy(date_str)

    if strategy == "forecast_current":
        return _fetch_via_forecast_current(lat, lon, date_str)
    elif strategy == "forecast_past_days":
        return _fetch_via_forecast_past_days(lat, lon, date_str)
    else:
        return _fetch_via_archive(lat, lon, date_str)
```

Add `_fetch_via_forecast_past_days`:

```python
def _fetch_via_forecast_past_days(
    lat: float, lon: float, date_str: str,
) -> dict[str, Any]:
    """Fetch recent historical weather via forecast API past_days parameter."""
    from datetime import date as dt_date
    target = dt_date.fromisoformat(date_str)
    days_ago = (dt_date.today() - target).days

    try:
        import urllib.request
        url = (
            f"{_OPEN_METEO_BASE}/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&past_days={days_ago}&forecast_days=0"
            f"&hourly=temperature_2m,relative_humidity_2m,"
            f"wind_speed_10m,rain,cloud_cover,weather_code"
            f"&wind_speed_unit=ms&timezone=auto"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        return _parse_hourly_response(data, date_str, "open-meteo-forecast-past")

    except Exception as e:
        logger.warning("Failed to fetch recent historical weather: %s", e)
        return {"error": str(e), "source": "unavailable", "date": date_str}


def _fetch_via_forecast_current(
    lat: float, lon: float, date_str: str,
) -> dict[str, Any]:
    """Fetch today/future weather via forecast API."""
    try:
        import urllib.request
        url = (
            f"{_OPEN_METEO_BASE}/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,relative_humidity_2m,"
            f"wind_speed_10m,rain,cloud_cover,weather_code"
            f"&wind_speed_unit=ms&timezone=auto"
            f"&forecast_days=2"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        return _parse_hourly_response(data, date_str, "open-meteo-forecast")

    except Exception as e:
        logger.warning("Failed to fetch forecast weather: %s", e)
        return {"error": str(e), "source": "unavailable", "date": date_str}
```

Rename the old `fetch_historical_weather` body into `_fetch_via_archive`:

```python
def _fetch_via_archive(
    lat: float, lon: float, date_str: str,
) -> dict[str, Any]:
    """Fetch old historical weather from Open-Meteo Archive API."""
    try:
        import urllib.request
        url = (
            f"{_OPEN_METEO_BASE}/archive"
            f"?latitude={lat}&longitude={lon}"
            f"&start_date={date_str}&end_date={date_str}"
            f"&hourly=temperature_2m,relative_humidity_2m,"
            f"wind_speed_10m,rain,cloud_cover,weather_code"
            f"&wind_speed_unit=ms&timezone=auto"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        return _parse_hourly_response(data, date_str, "open-meteo-archive")

    except Exception as e:
        logger.warning("Failed to fetch historical weather: %s", e)
        return {"error": str(e), "source": "unavailable", "date": date_str}
```

Extract the shared parsing logic from the old `fetch_historical_weather` into:

```python
def _parse_hourly_response(
    data: dict, date_str: str, source: str,
) -> dict[str, Any]:
    """Parse Open-Meteo hourly response, filtering to target date."""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    n = len(times)

    hours = []
    for i in range(n):
        t = times[i]
        # Filter to target date (response may include multiple days)
        if not t.startswith(date_str):
            continue
        hours.append({
            "time": t,
            "air_temp_c": hourly.get("temperature_2m", [None] * n)[i],
            "humidity_pct": hourly.get("relative_humidity_2m", [None] * n)[i],
            "wind_speed_mps": hourly.get("wind_speed_10m", [None] * n)[i],
            "rain_mm": hourly.get("rain", [0] * n)[i],
            "cloud_cover_pct": hourly.get("cloud_cover", [None] * n)[i],
            "weather_code": hourly.get("weather_code", [0] * n)[i],
        })

    temps = [h["air_temp_c"] for h in hours if h["air_temp_c"] is not None]
    humids = [h["humidity_pct"] for h in hours if h["humidity_pct"] is not None]
    rains = [h["rain_mm"] for h in hours if h["rain_mm"] is not None]

    return {
        "date": date_str,
        "hours": hours,
        "summary": {
            "temp_min_c": round(min(temps), 1) if temps else None,
            "temp_max_c": round(max(temps), 1) if temps else None,
            "temp_mean_c": round(sum(temps) / len(temps), 1) if temps else None,
            "humidity_mean_pct": round(sum(humids) / len(humids), 1) if humids else None,
            "total_rain_mm": round(sum(rains), 1) if rains else 0,
            "had_rain": any(r > 0.1 for r in rains),
        },
        "source": source,
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestHistoricalWeatherRouting -v`
Expected: 4 PASSED

**Step 5: Run full test suite**

Run: `pytest telemetry_tool/tests/ -v`
Expected: All tests pass (the existing inline tests in `meteo_service.py` are not run by pytest; they use `_run_tests()` under `__main__`)

**Step 6: Commit**

```bash
git add telemetry_tool/meteo_service.py telemetry_tool/tests/test_driver_features.py
git commit -m "fix: route recent historical weather through forecast API past_days"
```

---

### Task 5: Pace estimator — Tier 1 physics-based

Create the pace estimator module with physics-based lap time estimation using `wet_physics.py` grip factors.

**Files:**
- Create: `telemetry_tool/pace_estimator.py`
- Test: `telemetry_tool/tests/test_driver_features.py`

**Step 1: Write the failing tests**

Add at the end of `telemetry_tool/tests/test_driver_features.py`:

```python
class TestPaceEstimatorPhysics:
    """Task 5: physics-based pace estimation (Tier 1)."""

    def test_dry_conditions_no_delta(self):
        """Dry conditions should produce zero or near-zero delta."""
        from pace_estimator import estimate_physics_lap_time
        weather = {"air_temp_c": 22.0, "rain_mm": 0, "humidity_pct": 50, "cloud_cover_pct": 20}
        result = estimate_physics_lap_time(weather, dry_reference_s=50.0)
        assert result["grip_factor"] == 1.0
        assert abs(result["estimated_s"] - 50.0) < 0.01
        assert abs(result["delta_s"]) < 0.01

    def test_wet_conditions_slower(self):
        """Wet conditions should produce a slower estimated lap time."""
        from pace_estimator import estimate_physics_lap_time
        weather = {"air_temp_c": 15.0, "rain_mm": 10.0, "humidity_pct": 90, "cloud_cover_pct": 100}
        result = estimate_physics_lap_time(weather, dry_reference_s=50.0)
        assert result["grip_factor"] < 1.0
        assert result["estimated_s"] > 50.0
        assert result["delta_s"] > 0
        assert result["track_state"] == "wet"

    def test_damp_conditions_between_dry_and_wet(self):
        """Damp conditions: delta between dry and wet."""
        from pace_estimator import estimate_physics_lap_time
        dry_ref = 50.0
        weather_damp = {"air_temp_c": 18.0, "rain_mm": 2.0}
        weather_wet = {"air_temp_c": 15.0, "rain_mm": 10.0}
        result_damp = estimate_physics_lap_time(weather_damp, dry_reference_s=dry_ref)
        result_wet = estimate_physics_lap_time(weather_wet, dry_reference_s=dry_ref)
        assert dry_ref < result_damp["estimated_s"] < result_wet["estimated_s"]

    def test_missing_reference_returns_error(self):
        """No dry reference → error in result."""
        from pace_estimator import estimate_physics_lap_time
        weather = {"air_temp_c": 22.0}
        result = estimate_physics_lap_time(weather, dry_reference_s=None)
        assert "error" in result
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestPaceEstimatorPhysics -v`
Expected: FAIL — no module `pace_estimator`

**Step 3: Write minimal implementation**

Create `telemetry_tool/pace_estimator.py`:

```python
"""
pace_estimator.py
-----------------
Two-tier weather-pace lap time estimator.

Tier 1 (physics): Uses wet_physics grip scaling + meteo track conditions.
Tier 2 (data-driven): Linear model from driver's session history (5+ sessions).
Blended output when both available.

Public API
~~~~~~~~~~
``estimate_physics_lap_time(weather, dry_reference_s)``
    Tier 1: physics-only estimate.
``estimate_data_driven_lap_time(conn, track_id, driver_id, weather)``
    Tier 2: data-driven estimate (or None if insufficient data).
``estimate_pace(conn, track_id, driver_id, weather)``
    Full two-tier blended estimate.
``estimate_weather_lap_delta(weather, track_id, driver_id, base_time, conn)``
    Thin wrapper returning just the delta in seconds (for race_strategy).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Blend weights when both tiers are available
_DATA_WEIGHT = 0.7
_PHYSICS_WEIGHT = 0.3


def estimate_physics_lap_time(
    weather: dict[str, Any],
    dry_reference_s: Optional[float] = None,
) -> dict[str, Any]:
    """
    Tier 1: Physics-based lap time estimate.

    Uses wet_physics grip scaling applied to a dry reference lap time.
    Formula: estimated = dry_reference / grip_factor
    (lower grip → higher time)

    Parameters
    ----------
    weather : dict
        Weather data with air_temp_c, rain_mm, humidity_pct, etc.
    dry_reference_s : float or None
        Best dry lap time for the track (from sessions.best_lap_time_s
        or sessions.theoretical_best_s).

    Returns
    -------
    dict with estimated_s, delta_s, delta_pct, grip_factor, track_state, tier.
    """
    if dry_reference_s is None or not math.isfinite(dry_reference_s):
        return {"error": "No dry reference lap time available", "tier": "physics"}

    try:
        from meteo_service import estimate_track_conditions
        from wet_physics import get_grip_factor
    except ImportError as e:
        return {"error": f"Missing module: {e}", "tier": "physics"}

    conditions = estimate_track_conditions(weather)
    if "error" in conditions:
        return {"error": conditions["error"], "tier": "physics"}

    track_state = conditions.get("track_state", "dry")
    grip = get_grip_factor(track_state)

    # Lower grip → longer lap time: estimated = reference / grip_factor
    estimated = dry_reference_s / grip if grip > 0 else dry_reference_s
    delta = estimated - dry_reference_s
    delta_pct = (delta / dry_reference_s) * 100 if dry_reference_s > 0 else 0

    return {
        "estimated_s": round(estimated, 3),
        "delta_s": round(delta, 3),
        "delta_pct": round(delta_pct, 2),
        "grip_factor": grip,
        "track_state": track_state,
        "grip_level": conditions.get("grip_level", "unknown"),
        "tier": "physics",
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestPaceEstimatorPhysics -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/pace_estimator.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: add pace_estimator module with Tier 1 physics-based estimation"
```

---

### Task 6: Pace estimator — Tier 2 data-driven + blending

Add the data-driven tier and blended estimate to the pace estimator.

**Files:**
- Modify: `telemetry_tool/pace_estimator.py` (add Tier 2 + blend)
- Test: `telemetry_tool/tests/test_driver_features.py`

**Step 1: Write the failing tests**

Add at the end of `telemetry_tool/tests/test_driver_features.py`:

```python
class TestPaceEstimatorDataDriven:
    """Task 6: data-driven pace estimation (Tier 2) + blending."""

    def _seed_weather_sessions(self, db, n=8, track_id="trk1", driver_id=1):
        """Seed driver, track, and N sessions with weather data."""
        db.execute(
            "INSERT OR IGNORE INTO drivers (driver_id, driver_name) VALUES (?, ?)",
            (driver_id, "TestDriver"),
        )
        db.execute(
            "INSERT OR IGNORE INTO tracks (track_id, track_name, lap_length_m, start_lat, start_lon) "
            "VALUES (?, ?, ?, ?, ?)",
            (track_id, "Test Track", 800, 48.59, 2.57),
        )
        for i in range(n):
            sid = f"ws{i}"
            temp = 15.0 + i * 2.0  # 15, 17, 19, ..., 29
            pace = 50.0 + i * 0.3  # 50.0, 50.3, 50.6, ... (hotter → slower)
            db.execute(
                "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
                "session_type, session_date, best_lap_time_s) "
                "VALUES (?, ?, ?, ?, 'practice', ?, ?)",
                (sid, f"f{i}.csv", driver_id, track_id, f"2026-01-{i+1:02d}", pace),
            )
            db.execute(
                "INSERT INTO session_weather (session_id, air_temp_c) VALUES (?, ?)",
                (sid, temp),
            )
        db.commit()

    def test_data_driven_returns_none_insufficient(self, db):
        """With < 5 sessions, data-driven should return None."""
        self._seed_weather_sessions(db, n=3)
        from pace_estimator import estimate_data_driven_lap_time
        result = estimate_data_driven_lap_time(db, "trk1", 1, {"air_temp_c": 20.0})
        assert result is None

    def test_data_driven_returns_estimate(self, db):
        """With 8 sessions, data-driven should return an estimate."""
        self._seed_weather_sessions(db, n=8)
        from pace_estimator import estimate_data_driven_lap_time
        result = estimate_data_driven_lap_time(db, "trk1", 1, {"air_temp_c": 20.0})
        assert result is not None
        assert "estimated_s" in result
        assert result["tier"] == "data"

    def test_blended_estimate_both_tiers(self, db):
        """Full estimate should blend physics + data when both available."""
        self._seed_weather_sessions(db, n=8)
        from pace_estimator import estimate_pace
        weather = {"air_temp_c": 20.0, "rain_mm": 0, "humidity_pct": 50}
        result = estimate_pace(db, "trk1", 1, weather)
        assert "estimate" in result
        est = result["estimate"]
        assert est["tier"] in ("physics+data", "physics")
        assert "expected_lap_time_s" in est
        assert "components" in est

    def test_blended_falls_back_to_physics_only(self, db):
        """With no session data, should fall back to physics only."""
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t2', 'T2', 800)"
        )
        db.execute(
            "INSERT OR IGNORE INTO drivers (driver_id, driver_name) VALUES (99, 'NewDriver')"
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date, best_lap_time_s) "
            "VALUES ('dryref', 'f.csv', 99, 't2', 'practice', '2026-01-01', 50.0)"
        )
        db.commit()
        from pace_estimator import estimate_pace
        weather = {"air_temp_c": 22.0, "rain_mm": 0, "humidity_pct": 50}
        result = estimate_pace(db, "t2", 99, weather)
        assert result["estimate"]["tier"] == "physics"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestPaceEstimatorDataDriven -v`
Expected: FAIL — `estimate_data_driven_lap_time` and `estimate_pace` do not exist

**Step 3: Write minimal implementation**

Add to `telemetry_tool/pace_estimator.py`:

```python
def _get_dry_reference(conn, track_id: str, driver_id: int) -> Optional[float]:
    """Get the best dry lap time for a driver on a track."""
    row = conn.execute(
        "SELECT MIN(s.best_lap_time_s) as best "
        "FROM sessions s "
        "WHERE s.track_id = :tid AND s.driver_id = :did "
        "AND s.best_lap_time_s IS NOT NULL",
        {"tid": track_id, "did": driver_id},
    ).fetchone()
    if row and row["best"] is not None:
        return float(row["best"])
    return None


def _get_weather_sessions(conn, track_id: str, driver_id: int) -> list[dict]:
    """Get sessions with weather data for a driver+track."""
    rows = conn.execute(
        """SELECT sw.air_temp_c, sw.humidity_pct, sw.wind_speed_mps,
                  s.best_lap_time_s, s.session_date
           FROM session_weather sw
           JOIN sessions s ON sw.session_id = s.session_id
           WHERE s.track_id = :tid AND s.driver_id = :did
             AND s.best_lap_time_s IS NOT NULL
           ORDER BY s.session_date""",
        {"tid": track_id, "did": driver_id},
    ).fetchall()
    return [dict(r) for r in rows]


def estimate_data_driven_lap_time(
    conn, track_id: str, driver_id: int,
    weather: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """
    Tier 2: Data-driven pace estimate from session history.

    Requires 5+ sessions with weather data. Uses a simple linear
    model based on weather-pace correlation coefficients.

    Returns dict with estimated_s, delta_s, tier, or None if insufficient data.
    """
    sessions = _get_weather_sessions(conn, track_id, driver_id)
    if len(sessions) < 5:
        return None

    try:
        from weather_correlation import compute_weather_pace_correlation
    except ImportError:
        return None

    result = compute_weather_pace_correlation(sessions)
    correlations = result.get("correlations", {})

    # Compute mean conditions and mean pace from historical data
    mean_pace = sum(s["best_lap_time_s"] for s in sessions) / len(sessions)

    # Build simple linear prediction: base + sum(r * std_y * (x - mean_x) / std_x)
    # Simplified: use correlation coefficient as sensitivity indicator
    import numpy as np
    paces = np.array([s["best_lap_time_s"] for s in sessions])
    std_pace = float(np.std(paces, ddof=1)) if len(paces) > 1 else 0

    predicted_delta = 0.0
    for var_key in ("air_temp_c", "humidity_pct", "wind_speed_mps"):
        corr_info = correlations.get(var_key, {})
        r = corr_info.get("r")
        if r is None:
            continue

        vals = [s.get(var_key) for s in sessions if s.get(var_key) is not None]
        if not vals:
            continue

        arr = np.array(vals, dtype=float)
        mean_x = float(np.mean(arr))
        std_x = float(np.std(arr, ddof=1))
        if std_x < 1e-9:
            continue

        current_x = weather.get(var_key)
        if current_x is None:
            continue

        # Linear regression delta: r * (std_y / std_x) * (x_current - x_mean)
        predicted_delta += r * (std_pace / std_x) * (float(current_x) - mean_x)

    estimated = mean_pace + predicted_delta
    delta = estimated - min(s["best_lap_time_s"] for s in sessions)

    return {
        "estimated_s": round(estimated, 3),
        "delta_s": round(delta, 3),
        "n_sessions": len(sessions),
        "tier": "data",
    }


def estimate_pace(
    conn, track_id: str, driver_id: int,
    weather: dict[str, Any],
) -> dict[str, Any]:
    """
    Full two-tier blended pace estimate.

    Returns dict with keys: weather, estimate, context.
    """
    dry_ref = _get_dry_reference(conn, track_id, driver_id)

    # Tier 1: physics
    physics = estimate_physics_lap_time(weather, dry_reference_s=dry_ref)

    # Tier 2: data-driven
    data = estimate_data_driven_lap_time(conn, track_id, driver_id, weather)

    # Blend
    if data and "estimated_s" in data and "estimated_s" in physics:
        blended = (
            _DATA_WEIGHT * data["estimated_s"]
            + _PHYSICS_WEIGHT * physics["estimated_s"]
        )
        tier = "physics+data"
        confidence = min(0.95, 0.5 + data["n_sessions"] * 0.05)
        components = {
            "physics_estimate_s": physics["estimated_s"],
            "data_estimate_s": data["estimated_s"],
            "blend_weight_data": _DATA_WEIGHT,
        }
    elif "estimated_s" in physics:
        blended = physics["estimated_s"]
        tier = "physics"
        confidence = 0.5
        components = {
            "physics_estimate_s": physics["estimated_s"],
        }
    else:
        return {
            "weather": weather,
            "estimate": {"error": physics.get("error", "No estimate available"), "tier": "none"},
            "context": {},
        }

    delta = blended - dry_ref if dry_ref else 0
    delta_pct = (delta / dry_ref * 100) if dry_ref and dry_ref > 0 else 0

    # Optimal conditions (if enough data)
    optimal = None
    if data and data.get("n_sessions", 0) >= 5:
        try:
            from weather_correlation import compute_optimal_conditions
            sessions = _get_weather_sessions(conn, track_id, driver_id)
            optimal = compute_optimal_conditions(sessions)
        except ImportError:
            pass

    return {
        "weather": weather,
        "estimate": {
            "expected_lap_time_s": round(blended, 3),
            "delta_vs_dry_s": round(delta, 3),
            "delta_pct": round(delta_pct, 2),
            "tier": tier,
            "confidence": round(confidence, 2),
            "grip_factor": physics.get("grip_factor", 1.0),
            "components": components,
        },
        "context": {
            "dry_reference_s": round(dry_ref, 3) if dry_ref else None,
            "n_weather_sessions": data["n_sessions"] if data else 0,
            "optimal_conditions": optimal,
        },
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestPaceEstimatorDataDriven -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/pace_estimator.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: add Tier 2 data-driven pace estimation + blended output"
```

---

### Task 7: API endpoint updates

Update the meteo API routes to use the unified track source, pass DB connections, and add the new pace-estimate endpoint.

**Files:**
- Modify: `telemetry_tool/web/routes/api_data.py:3800-3885` (meteo routes)
- Test: `telemetry_tool/tests/test_driver_features.py`

**Step 1: Write the failing tests**

Add at the end of `telemetry_tool/tests/test_driver_features.py`:

```python
class TestMeteoAPI:
    """Task 7: meteo API endpoints."""

    def _make_app(self, db):
        """Create a Flask test app from the in-memory DB."""
        import tempfile, shutil, os
        from web.app import create_app
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        file_conn = __import__("sqlite3").connect(db_path)
        db.backup(file_conn)
        file_conn.close()
        from web.config import Config
        cfg = Config()
        cfg.DB_PATH = db_path
        cfg.TESTING = True
        app = create_app(cfg)
        app._tmpdir = tmpdir
        return app

    def test_meteo_tracks_returns_grouped(self, db):
        """GET /api/meteo/tracks should return user_tracks + predefined_tracks."""
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m, start_lat, start_lon) "
            "VALUES ('trk1', 'My Track', 800, 48.59, 2.57)"
        )
        db.commit()
        app = self._make_app(db)
        with app.test_client() as c:
            resp = c.get("/api/meteo/tracks")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "user_tracks" in data
            assert "predefined_tracks" in data
            assert len(data["user_tracks"]) == 1
        import shutil
        shutil.rmtree(app._tmpdir, ignore_errors=True)

    def test_meteo_current_with_latlon(self, db):
        """GET /api/meteo/current?lat=...&lon=... should not crash."""
        # We can't test the actual API call, but we can test the route exists.
        app = self._make_app(db)
        with app.test_client() as c:
            # Missing lat/lon should return 400
            resp = c.get("/api/meteo/current")
            assert resp.status_code == 400
        import shutil
        shutil.rmtree(app._tmpdir, ignore_errors=True)

    def test_pace_estimate_no_track(self, db):
        """GET /api/meteo/pace-estimate without track should return 400."""
        app = self._make_app(db)
        with app.test_client() as c:
            resp = c.get("/api/meteo/pace-estimate")
            assert resp.status_code == 400
        import shutil
        shutil.rmtree(app._tmpdir, ignore_errors=True)
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestMeteoAPI -v`
Expected: FAIL — `/api/meteo/tracks` returns flat list, `pace-estimate` 404

**Step 3: Write minimal implementation**

Replace the meteo routes block in `telemetry_tool/web/routes/api_data.py` (lines 3800-3885):

```python
# ------------------------------------------------------------------
# Meteo / Weather API
# ------------------------------------------------------------------

def _resolve_track_coords(request_args, conn):
    """Resolve lat/lon from request — by direct params or track ID."""
    lat = request_args.get("lat", type=float)
    lon = request_args.get("lon", type=float)
    track_id = request_args.get("track")

    if lat is not None and lon is not None:
        return lat, lon

    if track_id and track_id.startswith("db:"):
        # User track from DB
        real_id = track_id[3:]
        row = conn.execute(
            "SELECT start_lat, start_lon FROM tracks WHERE track_id = :tid",
            {"tid": real_id},
        ).fetchone()
        if row and row["start_lat"] is not None:
            return row["start_lat"], row["start_lon"]
    elif track_id and track_id.startswith("csv:"):
        # Predefined track from geocoding cache
        name = track_id[4:]
        row = conn.execute(
            "SELECT latitude, longitude FROM predefined_track_coords WHERE track_name = :n",
            {"n": name},
        ).fetchone()
        if row and row["latitude"] is not None:
            return row["latitude"], row["longitude"]

    return None, None


@bp.route("/meteo/current")
def api_meteo_current():
    """Get current weather at coordinates or known track."""
    conn = get_db_connection()
    lat, lon = _resolve_track_coords(request.args, conn)

    if lat is None or lon is None:
        return jsonify({"error": "Provide track ID or lat/lon"}), 400

    try:
        from meteo_service import fetch_current_weather, estimate_track_conditions
        weather = fetch_current_weather(lat, lon)
        conditions = estimate_track_conditions(weather)
        weather["track_conditions"] = conditions
        return jsonify(weather)
    except ImportError:
        return jsonify({"error": "meteo_service module not available"}), 500


@bp.route("/meteo/historical")
def api_meteo_historical():
    """Get historical weather for a date at coordinates."""
    conn = get_db_connection()
    lat, lon = _resolve_track_coords(request.args, conn)
    date_str = request.args.get("date", "")

    if not date_str:
        return jsonify({"error": "date parameter required (YYYY-MM-DD)"}), 400
    if lat is None or lon is None:
        return jsonify({"error": "Provide track ID or lat/lon"}), 400

    try:
        from meteo_service import fetch_historical_weather
        result = fetch_historical_weather(lat, lon, date_str)
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "meteo_service module not available"}), 500


@bp.route("/meteo/forecast")
def api_meteo_forecast():
    """Get weather forecast for upcoming hours."""
    conn = get_db_connection()
    lat, lon = _resolve_track_coords(request.args, conn)
    hours = request.args.get("hours", 12, type=int)

    if lat is None or lon is None:
        return jsonify({"error": "Provide track ID or lat/lon"}), 400

    try:
        from meteo_service import get_weather_forecast
        result = get_weather_forecast(lat, lon, hours)
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "meteo_service module not available"}), 500


@bp.route("/meteo/tracks")
def api_meteo_tracks():
    """Get grouped track locations for weather — user tracks + predefined."""
    conn = get_db_connection()
    try:
        from meteo_service import get_all_track_locations
        return jsonify(get_all_track_locations(conn))
    except ImportError:
        return jsonify({"error": "meteo_service module not available"}), 500


@bp.route("/meteo/pace-estimate")
def api_meteo_pace_estimate():
    """Get weather-based pace estimate for a track and driver."""
    conn = get_db_connection()
    track_id = request.args.get("track_id")
    driver_id = request.args.get("driver_id", type=int)
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)

    if not track_id:
        return jsonify({"error": "track_id required"}), 400

    # Resolve actual track_id from the ID format (db:xxx or csv:xxx)
    actual_track_id = track_id
    if track_id.startswith("db:"):
        actual_track_id = track_id[3:]

    try:
        from pace_estimator import estimate_pace

        # Fetch current weather if lat/lon available
        weather = {}
        resolved_lat, resolved_lon = _resolve_track_coords(request.args, conn)
        if resolved_lat is not None:
            from meteo_service import fetch_current_weather
            weather = fetch_current_weather(resolved_lat, resolved_lon)

        result = estimate_pace(conn, actual_track_id, driver_id or 0, weather)
        return jsonify(result)
    except ImportError as e:
        return jsonify({"error": f"Module not available: {e}"}), 500
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestMeteoAPI -v`
Expected: 3 PASSED

**Step 5: Run full test suite**

Run: `pytest telemetry_tool/tests/ -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/api_data.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: update meteo API routes — unified tracks, pace-estimate endpoint"
```

---

### Task 8: Race strategy integration

Replace the trivial weather delta in `race_strategy.py` with the physics-based pace estimator.

**Files:**
- Modify: `telemetry_tool/race_strategy.py:155-159` (replace weather delta)
- Test: `telemetry_tool/tests/test_driver_features.py`

**Step 1: Write the failing tests**

Add at the end of `telemetry_tool/tests/test_driver_features.py`:

```python
class TestRaceStrategyWeather:
    """Task 8: race strategy uses physics-based weather delta."""

    def test_weather_delta_wet_conditions(self):
        """Wet weather should produce a positive delta (slower laps)."""
        from race_strategy import _compute_weather_delta
        weather = {"air_temp_c": 15.0, "rain_mm": 10.0, "humidity_pct": 90, "cloud_cover_pct": 100}
        delta = _compute_weather_delta(weather, base_time=50.0)
        assert delta > 0, f"Wet conditions should add time, got delta={delta}"

    def test_weather_delta_dry_conditions(self):
        """Dry weather should produce zero or near-zero delta."""
        from race_strategy import _compute_weather_delta
        weather = {"air_temp_c": 22.0, "rain_mm": 0, "humidity_pct": 50}
        delta = _compute_weather_delta(weather, base_time=50.0)
        assert abs(delta) < 0.1, f"Dry conditions should have ~0 delta, got {delta}"

    def test_weather_delta_none_weather(self):
        """No weather data should produce zero delta."""
        from race_strategy import _compute_weather_delta
        delta = _compute_weather_delta(None, base_time=50.0)
        assert delta == 0.0

    def test_weather_delta_empty_weather(self):
        """Empty weather dict should produce zero delta."""
        from race_strategy import _compute_weather_delta
        delta = _compute_weather_delta({}, base_time=50.0)
        assert delta == 0.0
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestRaceStrategyWeather -v`
Expected: FAIL — `_compute_weather_delta` does not exist

**Step 3: Write minimal implementation**

In `telemetry_tool/race_strategy.py`, add this function near the top (after imports):

```python
def _compute_weather_delta(
    weather: Optional[dict[str, Any]],
    base_time: float,
) -> float:
    """
    Compute lap time delta from weather conditions using physics model.

    Uses wet_physics grip scaling via pace_estimator for a physics-grounded
    weather effect (replacing the old +0.01s/degree above 25C heuristic).

    Returns delta in seconds (positive = slower).
    """
    if not weather or not weather.get("air_temp_c"):
        return 0.0

    try:
        from pace_estimator import estimate_physics_lap_time
        result = estimate_physics_lap_time(weather, dry_reference_s=base_time)
        if "error" in result:
            return 0.0
        return result.get("delta_s", 0.0)
    except ImportError:
        # Fallback: simple temperature model
        air_temp = weather.get("air_temp_c")
        if air_temp is not None and air_temp > 25:
            return (air_temp - 25) * 0.01
        return 0.0
```

Then replace lines 155-159 in `simulate_race()`:

```python
        # Weather effect (physics-based via pace estimator)
        temp_delta = _compute_weather_delta(params.get("weather"), base_time)
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_driver_features.py::TestRaceStrategyWeather -v`
Expected: 4 PASSED

**Step 5: Run full test suite**

Run: `pytest telemetry_tool/tests/ -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add telemetry_tool/race_strategy.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: replace trivial weather delta in race strategy with physics model"
```

---

### Task 9: Meteo dashboard UI update

Update the meteo dashboard template for grouped track selector (optgroups) and add the Lap Time Impact panel with driver selector.

**Files:**
- Modify: `telemetry_tool/web/templates/meteo_dashboard.html` (full rewrite of JS track loading + new pace panel)
- Modify: `telemetry_tool/web/routes/analytics.py:87-90` (pass drivers to template)

**Step 1: Update the analytics route**

In `telemetry_tool/web/routes/analytics.py`, update the `meteo_page` function:

```python
@bp.route("/meteo")
def meteo_page():
    """Live and historical meteo dashboard."""
    conn = get_db_connection()
    drivers = conn.execute(
        "SELECT driver_id, driver_name FROM drivers ORDER BY driver_name"
    ).fetchall()
    return render_template("meteo_dashboard.html", drivers=[dict(d) for d in drivers])
```

**Step 2: Update the template track selector**

In `telemetry_tool/web/templates/meteo_dashboard.html`, replace the track `<select>` (lines 17-19) with:

```html
        <select id="meteo-track" class="form-control" style="max-width:400px;">
            <option value="">-- Select a track --</option>
        </select>
```

No change needed here — the options are populated by JS. But change the JS track-loading section (around line 93-102) to use optgroups:

```javascript
    // Load tracks with optgroups
    FetchHelper.fetch("/api/meteo/tracks").then(function(data) {
        var select = document.getElementById("meteo-track");
        if (data.user_tracks && data.user_tracks.length > 0) {
            var grp = document.createElement("optgroup");
            grp.label = "Your Tracks";
            data.user_tracks.forEach(function(t) {
                var opt = document.createElement("option");
                opt.value = t.id;
                opt.textContent = t.name;
                opt.dataset.lat = t.lat;
                opt.dataset.lon = t.lon;
                grp.appendChild(opt);
            });
            select.appendChild(grp);
        }
        if (data.predefined_tracks && data.predefined_tracks.length > 0) {
            var grp2 = document.createElement("optgroup");
            grp2.label = "Predefined Tracks";
            data.predefined_tracks.forEach(function(t) {
                var opt = document.createElement("option");
                opt.value = t.id;
                opt.textContent = t.name;
                opt.dataset.lat = t.lat;
                opt.dataset.lon = t.lon;
                grp2.appendChild(opt);
            });
            select.appendChild(grp2);
        }
    });
```

**Step 3: Add the Lap Time Impact panel**

Add between the Forecast and Historical sections (after line 57, before line 59):

```html
<!-- Lap Time Impact Panel -->
<section class="section" id="meteo-pace-section" style="display:none;">
    <h2>Lap Time Impact</h2>
    <div style="display:flex;gap:0.5rem;align-items:flex-end;flex-wrap:wrap;margin-bottom:1rem;">
        <div class="form-group" style="margin-bottom:0;">
            <label for="meteo-driver">Driver</label>
            <select id="meteo-driver" class="form-control" style="max-width:250px;">
                <option value="">-- Select driver --</option>
                {% for d in drivers %}
                <option value="{{ d.driver_id }}">{{ d.driver_name }}</option>
                {% endfor %}
            </select>
        </div>
        <button id="meteo-pace-btn" class="btn btn-secondary" disabled>Estimate Pace Impact</button>
    </div>
    <div id="meteo-pace-results"></div>
</section>
```

**Step 4: Add the pace estimate JS**

In the `<script>` block, add after the historical weather handler (before the resize handler):

```javascript
    // Pace estimate
    document.getElementById("meteo-pace-btn").addEventListener("click", function() {
        var trackSel = document.getElementById("meteo-track");
        var trackId = trackSel.value;
        var driverId = document.getElementById("meteo-driver").value;
        if (!trackId) return;

        var selectedOpt = trackSel.options[trackSel.selectedIndex];
        var lat = selectedOpt ? selectedOpt.dataset.lat : "";
        var lon = selectedOpt ? selectedOpt.dataset.lon : "";

        var url = "/api/meteo/pace-estimate?track_id=" + encodeURIComponent(trackId);
        if (driverId) url += "&driver_id=" + encodeURIComponent(driverId);
        if (lat) url += "&lat=" + encodeURIComponent(lat) + "&lon=" + encodeURIComponent(lon);

        FetchHelper.fetch(url).then(function(data) {
            var container = document.getElementById("meteo-pace-results");
            document.getElementById("meteo-pace-section").style.display = "";

            if (data.estimate && data.estimate.error) {
                container.textContent = data.estimate.error;
                return;
            }

            var est = data.estimate || {};
            var ctx = data.context || {};

            var html = document.createElement("div");
            html.style.cssText = "display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:1rem;";

            function addCard(label, value, color) {
                var card = document.createElement("div");
                card.style.cssText = "background:var(--card-bg);border-radius:8px;padding:0.6rem 1rem;border-top:3px solid " + (color || "var(--accent)") + ";min-width:100px;flex:1;max-width:180px;";
                var lbl = document.createElement("div");
                lbl.style.cssText = "font-size:0.7rem;color:var(--text-secondary);text-transform:uppercase;";
                lbl.textContent = label;
                var val = document.createElement("div");
                val.style.cssText = "font-size:1.1rem;font-weight:700;color:" + (color || "var(--text-primary)") + ";";
                val.textContent = String(value);
                card.appendChild(lbl);
                card.appendChild(val);
                html.appendChild(card);
            }

            if (est.expected_lap_time_s != null) addCard("Est. Lap Time", est.expected_lap_time_s.toFixed(2) + "s", "var(--accent)");
            if (est.delta_vs_dry_s != null) {
                var dCol = est.delta_vs_dry_s > 0.5 ? "var(--red)" : (est.delta_vs_dry_s > 0.1 ? "var(--yellow)" : "var(--green)");
                addCard("Delta vs Dry", (est.delta_vs_dry_s >= 0 ? "+" : "") + est.delta_vs_dry_s.toFixed(2) + "s", dCol);
            }
            if (est.grip_factor != null) addCard("Grip Factor", est.grip_factor.toFixed(2), est.grip_factor < 0.9 ? "var(--red)" : "var(--green)");
            if (est.tier) addCard("Model", est.tier, "#888");
            if (ctx.dry_reference_s != null) addCard("Dry Reference", ctx.dry_reference_s.toFixed(2) + "s", "var(--green)");
            if (ctx.n_weather_sessions) addCard("Weather Sessions", ctx.n_weather_sessions, "var(--blue)");

            container.replaceChildren(html);

            // Add confidence note
            if (est.confidence != null) {
                var note = document.createElement("div");
                note.style.cssText = "font-size:0.8rem;color:var(--text-secondary);margin-top:0.3rem;";
                note.textContent = "Confidence: " + (est.confidence * 100).toFixed(0) + "% | Tier: " + est.tier;
                container.appendChild(note);
            }
        });
    });

    // Enable pace button when track selected
    document.getElementById("meteo-track").addEventListener("change", function() {
        document.getElementById("meteo-pace-btn").disabled = !this.value;
    });
```

**Step 5: Run full test suite**

Run: `pytest telemetry_tool/tests/ -v`
Expected: All tests pass (UI changes don't break anything)

**Step 6: Commit**

```bash
git add telemetry_tool/web/templates/meteo_dashboard.html telemetry_tool/web/routes/analytics.py telemetry_tool/tests/test_driver_features.py
git commit -m "feat: update meteo dashboard UI — grouped tracks, pace impact panel"
```

---

## Summary

| Task | Description | New Tests | Files |
|------|-------------|-----------|-------|
| 1 | Schema v19 — predefined_track_coords table | 3 | schema.py, migrate.py |
| 2 | Track geocoder module | 4 | track_geocoder.py (new) |
| 3 | Unified track source in meteo_service | 4 | meteo_service.py |
| 4 | Historical weather fix — past_days routing | 4 | meteo_service.py |
| 5 | Pace estimator Tier 1 — physics | 4 | pace_estimator.py (new) |
| 6 | Pace estimator Tier 2 — data-driven + blend | 4 | pace_estimator.py |
| 7 | API endpoint updates | 3 | api_data.py |
| 8 | Race strategy integration | 4 | race_strategy.py |
| 9 | Meteo dashboard UI | 0 | meteo_dashboard.html, analytics.py |
| **Total** | | **30** | |

Expected final test count: 259 + 30 = **289 tests**.
