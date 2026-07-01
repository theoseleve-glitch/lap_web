"""
meteo_service.py
----------------
Weather/meteo service: fetch current and historical weather data for
track locations, provide forecast and rain radar estimates.

Uses Open-Meteo (free, no API key required) for actual data.
Provides fallback estimates when offline.

Public API
~~~~~~~~~~
``fetch_current_weather(lat, lon)``
    Get current weather at coordinates.
``fetch_historical_weather(lat, lon, date_str)``
    Get weather for a past date at coordinates.
``estimate_track_conditions(weather)``
    Convert weather data to track condition assessment.
``get_weather_forecast(lat, lon, hours)``
    Get hourly forecast for upcoming hours.
"""

from __future__ import annotations

import json
import logging
import math
import traceback
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Open-Meteo API base (free, no key)
_OPEN_METEO_BASE = "https://api.open-meteo.com/v1"

# ── Unified track locations ──────────────────────────────────


def get_all_track_locations(conn) -> dict[str, Any]:
    """
    Return unified track locations from user DB + predefined geocoded tracks.
    Returns dict with keys 'user_tracks' and 'predefined_tracks'.
    """
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
    Backward-compatible: if conn is None, returns empty list.
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


def fetch_current_weather(
    lat: float, lon: float,
) -> dict[str, Any]:
    """
    Fetch current weather from Open-Meteo API.

    Parameters
    ----------
    lat, lon : float
        Location coordinates.

    Returns
    -------
    dict with air_temp_c, humidity_pct, wind_speed_mps, wind_dir_deg,
    rain_mm, cloud_cover_pct, is_raining, weather_code, description.
    """
    try:
        import urllib.request
        url = (
            f"{_OPEN_METEO_BASE}/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,"
            f"wind_speed_10m,wind_direction_10m,rain,cloud_cover,weather_code"
            f"&wind_speed_unit=ms&timezone=auto"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        current = data.get("current", {})
        wcode = current.get("weather_code", 0)

        return {
            "air_temp_c": current.get("temperature_2m"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "wind_speed_mps": current.get("wind_speed_10m"),
            "wind_dir_deg": current.get("wind_direction_10m"),
            "rain_mm": current.get("rain", 0),
            "cloud_cover_pct": current.get("cloud_cover"),
            "weather_code": wcode,
            "is_raining": (current.get("rain", 0) or 0) > 0.1,
            "description": _weather_code_to_text(wcode),
            "source": "open-meteo",
            "fetched_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.warning("Failed to fetch weather: %s", e)
        return {
            "error": str(e),
            "source": "unavailable",
            "air_temp_c": None,
            "humidity_pct": None,
            "wind_speed_mps": None,
        }


_FORECAST_PAST_DAYS_MAX = 92


def _pick_historical_strategy(date_str: str) -> str:
    """Decide which API to use for historical weather."""
    from datetime import date as dt_date
    target = dt_date.fromisoformat(date_str)
    days_ago = (dt_date.today() - target).days
    if days_ago <= 0:
        return "forecast_current"
    elif days_ago <= _FORECAST_PAST_DAYS_MAX:
        return "forecast_past_days"
    else:
        return "archive"


def _parse_hourly_response(
    data: dict, date_str: str, source: str,
) -> dict[str, Any]:
    """
    Parse hourly weather response data into a summary dict.
    Filters hours to only those matching date_str.
    """
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    n = len(times)

    hours = []
    for i in range(n):
        t = times[i]
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

    # Daily summary
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


def _fetch_via_archive(lat, lon, date_str):
    """Fetch historical weather from Open-Meteo Archive API (for old dates)."""
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
        logger.warning("Failed to fetch archive weather: %s", e)
        return {"error": str(e), "source": "unavailable", "date": date_str}


def _fetch_via_forecast_past_days(lat, lon, date_str):
    """Fetch recent historical weather via Forecast API with past_days."""
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


def _fetch_via_forecast_current(lat, lon, date_str):
    """Fetch weather for today/future via Forecast API."""
    try:
        import urllib.request
        url = (
            f"{_OPEN_METEO_BASE}/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&forecast_days=2"
            f"&hourly=temperature_2m,relative_humidity_2m,"
            f"wind_speed_10m,rain,cloud_cover,weather_code"
            f"&wind_speed_unit=ms&timezone=auto"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return _parse_hourly_response(data, date_str, "open-meteo-forecast")
    except Exception as e:
        logger.warning("Failed to fetch forecast weather: %s", e)
        return {"error": str(e), "source": "unavailable", "date": date_str}


def fetch_historical_weather(
    lat: float, lon: float, date_str: str,
) -> dict[str, Any]:
    """
    Fetch historical weather with smart date routing.

    Routes recent dates (<=92 days) through the Forecast API with past_days,
    today/future through the Forecast API, and older dates through the Archive API.

    Parameters
    ----------
    lat, lon : float
        Location coordinates.
    date_str : str
        Date in YYYY-MM-DD format.

    Returns
    -------
    dict with hourly weather data for the date.
    """
    strategy = _pick_historical_strategy(date_str)
    if strategy == "forecast_current":
        return _fetch_via_forecast_current(lat, lon, date_str)
    elif strategy == "forecast_past_days":
        return _fetch_via_forecast_past_days(lat, lon, date_str)
    else:
        return _fetch_via_archive(lat, lon, date_str)


def get_weather_forecast(
    lat: float, lon: float, hours: int = 12,
) -> dict[str, Any]:
    """
    Get hourly weather forecast for upcoming hours.

    Parameters
    ----------
    lat, lon : float
        Location coordinates.
    hours : int
        Number of hours to forecast (max 384 = 16 days, Open-Meteo's hourly
        horizon). Race Brief windows a future race date on this span; the old
        48 h cap made any race > 2 days out fall back to a blank forecast.

    Returns
    -------
    dict with hourly forecast data, rain probability, temp trend.
    """
    hours = min(hours, 384)
    try:
        import urllib.request
        url = (
            f"{_OPEN_METEO_BASE}/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,relative_humidity_2m,"
            f"wind_speed_10m,precipitation_probability,rain,weather_code"
            f"&wind_speed_unit=ms&timezone=auto"
            f"&forecast_hours={hours}"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        n = min(len(times), hours)

        forecast = []
        for i in range(n):
            forecast.append({
                "time": times[i],
                "air_temp_c": hourly.get("temperature_2m", [None] * n)[i],
                "humidity_pct": hourly.get("relative_humidity_2m", [None] * n)[i],
                "wind_speed_mps": hourly.get("wind_speed_10m", [None] * n)[i],
                "rain_prob_pct": hourly.get("precipitation_probability", [0] * n)[i],
                "rain_mm": hourly.get("rain", [0] * n)[i],
                "weather_code": hourly.get("weather_code", [0] * n)[i],
                "description": _weather_code_to_text(
                    hourly.get("weather_code", [0] * n)[i]
                ),
            })

        # Rain risk assessment
        rain_probs = [f.get("rain_prob_pct", 0) or 0 for f in forecast]
        max_rain_prob = max(rain_probs) if rain_probs else 0
        avg_rain_prob = sum(rain_probs) / len(rain_probs) if rain_probs else 0

        if max_rain_prob > 70:
            rain_risk = "high"
        elif max_rain_prob > 40:
            rain_risk = "moderate"
        elif max_rain_prob > 15:
            rain_risk = "low"
        else:
            rain_risk = "minimal"

        return {
            "forecast": forecast,
            "rain_risk": rain_risk,
            "max_rain_probability_pct": round(max_rain_prob, 1),
            "avg_rain_probability_pct": round(avg_rain_prob, 1),
            "source": "open-meteo",
        }

    except Exception as e:
        logger.warning("Failed to fetch forecast: %s", e)
        return {"error": str(e), "source": "unavailable"}


def estimate_track_conditions(
    weather: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert weather data to track condition assessment.

    Parameters
    ----------
    weather : dict
        Must have air_temp_c. Optional: humidity_pct, rain_mm, wind_speed_mps.

    Returns
    -------
    dict with track_temp_est_c, grip_level, track_state, recommended_compound,
    coaching advice.
    """
    air_temp = weather.get("air_temp_c")
    humidity = weather.get("humidity_pct")
    humidity = humidity if humidity is not None else 50
    rain = weather.get("rain_mm")
    rain = rain if rain is not None else 0
    wind = weather.get("wind_speed_mps")
    wind = wind if wind is not None else 0

    if air_temp is None:
        return {"error": "No temperature data"}

    # Estimate track temp (typically 10-25C above air temp in sun)
    # Reduced by cloud cover and wind
    cloud = weather.get("cloud_cover_pct")
    cloud = cloud if cloud is not None else 30
    sun_factor = 1.0 - (cloud / 100.0) * 0.6
    wind_cooling = min(wind * 0.5, 5.0)
    track_temp_est = air_temp + 15 * sun_factor - wind_cooling

    # Grip assessment
    grip_score = 100  # baseline

    # Temperature effects
    if track_temp_est < 15:
        grip_score -= 15  # cold = low grip
    elif track_temp_est > 50:
        grip_score -= 10  # very hot = greasy
    elif 25 <= track_temp_est <= 40:
        grip_score += 5  # optimal range

    # Rain effects
    if rain > 5:
        grip_score -= 40
        track_state = "wet"
    elif rain > 1:
        grip_score -= 25
        track_state = "damp"
    elif rain > 0.1:
        grip_score -= 10
        track_state = "greasy"
    else:
        track_state = "dry"

    # Humidity (high humidity = lower grip)
    if humidity > 80:
        grip_score -= 5

    grip_score = max(0, min(100, grip_score))

    # Grip level classification
    if grip_score >= 85:
        grip_level = "excellent"
    elif grip_score >= 70:
        grip_level = "good"
    elif grip_score >= 50:
        grip_level = "moderate"
    elif grip_score >= 30:
        grip_level = "low"
    else:
        grip_level = "very low"

    # Compound recommendation
    if track_state == "wet":
        compound = "wet"
    elif track_state in ("damp", "greasy"):
        compound = "inter"
    elif track_temp_est < 20:
        compound = "soft"  # need heat generation
    elif track_temp_est > 45:
        compound = "hard"  # protect from overheating
    else:
        compound = "medium"

    # Coaching
    coaching_parts = []
    if track_state != "dry":
        coaching_parts.append(f"Track is {track_state} — be cautious at turn-in.")
    if track_temp_est < 20:
        coaching_parts.append(
            "Cold track — expect low grip on outlap. "
            "Use weaving/braking to generate tire heat."
        )
    elif track_temp_est > 45:
        coaching_parts.append(
            "Hot track — tire degradation will be higher. "
            "Manage pace to preserve rubber."
        )
    if wind > 8:
        coaching_parts.append(
            f"Strong wind ({wind:.0f} m/s) — expect instability on straights "
            "and reduced grip in crosswind corners."
        )
    if not coaching_parts:
        coaching_parts.append("Good conditions for fast laps.")

    return {
        "air_temp_c": round(air_temp, 1),
        "track_temp_est_c": round(track_temp_est, 1),
        "humidity_pct": round(humidity, 1) if humidity is not None else None,
        "wind_speed_mps": round(wind, 1) if wind is not None else None,
        "rain_mm": round(rain, 1),
        "grip_score": grip_score,
        "grip_level": grip_level,
        "track_state": track_state,
        "recommended_compound": compound,
        "coaching": " ".join(coaching_parts),
    }


def _weather_code_to_text(code: int) -> str:
    """Convert WMO weather code to description."""
    codes = {
        0: "Clear sky",
        1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Depositing rime fog",
        51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
        61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
        66: "Light freezing rain", 67: "Heavy freezing rain",
        71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
        77: "Snow grains",
        80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
        85: "Slight snow showers", 86: "Heavy snow showers",
        95: "Thunderstorm", 96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    return codes.get(code, f"Code {code}")


# ── Inline tests ──────────────────────────────────────────────

def _run_tests() -> None:
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name, fn):
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # Test 1: Track conditions - dry warm
    def t_dry_warm():
        result = estimate_track_conditions({
            "air_temp_c": 25.0, "humidity_pct": 50,
            "rain_mm": 0, "wind_speed_mps": 2, "cloud_cover_pct": 20,
        })
        assert result["track_state"] == "dry"
        assert result["grip_level"] in ("good", "excellent")
        assert result["track_temp_est_c"] > 25

    _test("dry_warm_conditions", t_dry_warm)

    # Test 2: Wet conditions
    def t_wet():
        result = estimate_track_conditions({
            "air_temp_c": 15.0, "rain_mm": 10, "cloud_cover_pct": 100,
        })
        assert result["track_state"] == "wet"
        assert result["recommended_compound"] == "wet"
        assert result["grip_score"] < 70

    _test("wet_conditions", t_wet)

    # Test 3: Cold track
    def t_cold():
        result = estimate_track_conditions({
            "air_temp_c": 5.0, "cloud_cover_pct": 80, "wind_speed_mps": 10,
        })
        assert result["track_temp_est_c"] < 20
        assert result["recommended_compound"] == "soft"

    _test("cold_track", t_cold)

    # Test 4: Damp conditions
    def t_damp():
        result = estimate_track_conditions({
            "air_temp_c": 18.0, "rain_mm": 2.0,
        })
        assert result["track_state"] == "damp"
        assert result["recommended_compound"] == "inter"

    _test("damp_conditions", t_damp)

    # Test 5: Weather code lookup
    def t_codes():
        assert _weather_code_to_text(0) == "Clear sky"
        assert _weather_code_to_text(63) == "Moderate rain"
        assert "Code" in _weather_code_to_text(999)

    _test("weather_codes", t_codes)

    # Test 6: Known tracks (backward compat — no conn returns empty list)
    def t_tracks():
        tracks = get_known_tracks()
        assert isinstance(tracks, list)
        assert len(tracks) == 0  # No DB connection → empty list

    _test("known_tracks", t_tracks)

    # Test 7: Missing temperature
    def t_no_temp():
        result = estimate_track_conditions({})
        assert "error" in result

    _test("no_temperature", t_no_temp)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nMeteo Service Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
