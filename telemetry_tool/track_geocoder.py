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

_COUNTRY_CODES = {
    "france": "FR",
    "united kingdom": "GB",
}


def get_ungeocoded_venues(conn) -> list[dict[str, Any]]:
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
    conn.execute(
        "INSERT OR REPLACE INTO predefined_track_coords "
        "(track_name, city, country, latitude, longitude) "
        "VALUES (?, ?, ?, ?, ?)",
        (track_name, city, country_code, lat, lon),
    )


def get_cached_coords(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT track_name, city, country, latitude, longitude "
        "FROM predefined_track_coords"
    ).fetchall()
    return [dict(r) for r in rows]


def geocode_city(city: str, country_code: str = "FR") -> Optional[tuple[float, float]]:
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
            logger.info("Geocoded '%s' (%s) -> %.4f, %.4f", v["track_name"], city, lat, lon)
        else:
            logger.warning("Could not geocode '%s' (%s)", v["track_name"], city)
    if count:
        conn.commit()
    return count
