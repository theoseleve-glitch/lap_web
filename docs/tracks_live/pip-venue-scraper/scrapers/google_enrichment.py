"""
Google Places API enrichment module.

Enriches venue records with:
  - Verified GPS coordinates
  - Full address
  - Google Place ID
  - Phone number
  - Website URL
  - Rating

Requires a Google Maps API key with Places API enabled.
Set via environment variable: GOOGLE_MAPS_API_KEY
"""

import asyncio
import os
import sys
import json
import aiohttp
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import get_venues, upsert_venue, get_connection, init_db

GOOGLE_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

PLACES_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


async def search_place(
    session: aiohttp.ClientSession, query: str
) -> dict | None:
    """Search Google Places for a karting venue."""
    params = {
        "input": query,
        "inputtype": "textquery",
        "fields": "place_id,name,formatted_address,geometry",
        "key": GOOGLE_API_KEY,
    }
    try:
        async with session.get(PLACES_SEARCH_URL, params=params) as resp:
            data = await resp.json()
            if data.get("status") == "OK" and data.get("candidates"):
                return data["candidates"][0]
    except Exception as e:
        print(f"  [Google] Search error for '{query}': {e}")
    return None


async def get_place_details(
    session: aiohttp.ClientSession, place_id: str
) -> dict | None:
    """Get detailed info for a Google Place."""
    params = {
        "place_id": place_id,
        "fields": "name,formatted_address,formatted_phone_number,website,rating,geometry,url",
        "key": GOOGLE_API_KEY,
    }
    try:
        async with session.get(PLACES_DETAILS_URL, params=params) as resp:
            data = await resp.json()
            if data.get("status") == "OK":
                return data.get("result")
    except Exception as e:
        print(f"  [Google] Details error for '{place_id}': {e}")
    return None


def _build_search_query(venue: dict) -> str:
    """Build a Google Places search query from venue data."""
    parts = [venue["name"]]
    if venue.get("city"):
        parts.append(venue["city"])

    country_names = {"FR": "France", "GB": "United Kingdom", "IT": "Italy"}
    country = country_names.get(venue.get("country", ""), "")
    if country:
        parts.append(country)

    # Add "karting" if not already in the name
    name_lower = venue["name"].lower()
    if "kart" not in name_lower and "circuit" not in name_lower:
        parts.append("karting")

    return " ".join(parts)


async def enrich_venue(
    session: aiohttp.ClientSession,
    venue: dict,
    sem: asyncio.Semaphore,
) -> bool:
    """Enrich a single venue with Google Places data."""
    async with sem:
        query = _build_search_query(venue)
        place = await search_place(session, query)

        if not place:
            print(f"  ✗ No Google result for: {venue['name']}")
            return False

        place_id = place.get("place_id")
        if not place_id:
            return False

        # Get detailed info
        details = await get_place_details(session, place_id)
        if not details:
            return False

        # Extract coordinates
        geo = details.get("geometry", {}).get("location", {})
        lat = geo.get("lat")
        lng = geo.get("lng")

        update = {
            "id": venue["id"],
            "google_place_id": place_id,
            "latitude": lat,
            "longitude": lng,
            "address": details.get("formatted_address"),
            "phone": details.get("formatted_phone_number"),
            "rating": details.get("rating"),
        }

        # Only update website if we don't already have one
        if not venue.get("website_url") and details.get("website"):
            update["website_url"] = details["website"]

        upsert_venue(update)
        print(f"  ✓ {venue['name']} -> {details.get('formatted_address', 'no addr')}")

        # Rate limit: Google Places allows 10 QPS
        await asyncio.sleep(0.2)
        return True


async def run_google_enrichment(country: str = None, limit: int = None):
    """
    Enrich all venues (or a subset) with Google Places data.
    Requires GOOGLE_MAPS_API_KEY environment variable.
    """
    if not GOOGLE_API_KEY:
        print("[Google] ⚠ No GOOGLE_MAPS_API_KEY set.")
        print("[Google] To enable enrichment, set the environment variable:")
        print("  export GOOGLE_MAPS_API_KEY='your-api-key-here'")
        print("[Google] Skipping enrichment. Venues will work without it.")
        print("[Google] You can run enrichment later with:")
        print("  GOOGLE_MAPS_API_KEY=xxx python3 -m scrapers.google_enrichment")
        return 0

    init_db()

    # Get venues that need enrichment (no google_place_id yet)
    conn = get_connection()
    query = "SELECT * FROM venues WHERE google_place_id IS NULL"
    params = []
    if country:
        query += " AND country = ?"
        params.append(country)
    if limit:
        query += f" LIMIT {limit}"
    venues = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()

    print(f"\n[Google] Enriching {len(venues)} venues...")

    sem = asyncio.Semaphore(5)  # 5 concurrent requests
    enriched = 0

    async with aiohttp.ClientSession(
        headers={"User-Agent": "PIP-RaceStrategy/1.0"}
    ) as session:
        tasks = [enrich_venue(session, v, sem) for v in venues]
        results = await asyncio.gather(*tasks)
        enriched = sum(1 for r in results if r)

    print(f"\n[Google] Enriched {enriched}/{len(venues)} venues")
    return enriched


# --------------------------------------------------------------------------
# Fallback: Free geocoding via Nominatim (OpenStreetMap) — no API key needed
# --------------------------------------------------------------------------

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


async def geocode_nominatim(
    session: aiohttp.ClientSession, query: str
) -> dict | None:
    """Geocode using OpenStreetMap Nominatim (free, 1 req/sec)."""
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
    }
    headers = {"User-Agent": "PIP-RaceStrategy/1.0 (venue-discovery)"}
    try:
        async with session.get(NOMINATIM_URL, params=params, headers=headers) as resp:
            data = await resp.json()
            if data:
                return data[0]
    except Exception as e:
        print(f"  [Nominatim] Error for '{query}': {e}")
    return None


async def run_free_geocoding(country: str = None):
    """
    Geocode venues using Nominatim (free, no API key).
    Slower (1 req/sec) but works without setup.
    """
    init_db()

    conn = get_connection()
    query = "SELECT * FROM venues WHERE latitude IS NULL"
    params = []
    if country:
        query += " AND country = ?"
        params.append(country)
    venues = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()

    print(f"\n[Nominatim] Geocoding {len(venues)} venues (free, ~1 req/sec)...")

    geocoded = 0
    async with aiohttp.ClientSession() as session:
        for venue in venues:
            query_str = _build_search_query(venue)
            result = await geocode_nominatim(session, query_str)

            if result:
                lat = float(result.get("lat", 0))
                lon = float(result.get("lon", 0))
                addr = result.get("display_name", "")

                if lat and lon:
                    upsert_venue({
                        "id": venue["id"],
                        "latitude": lat,
                        "longitude": lon,
                        "address": addr,
                    })
                    geocoded += 1
                    print(f"  ✓ {venue['name']} -> ({lat:.4f}, {lon:.4f})")
                else:
                    print(f"  ✗ {venue['name']} -> no coords")
            else:
                print(f"  ✗ {venue['name']} -> not found")

            await asyncio.sleep(1.1)  # Nominatim requires 1 req/sec

    print(f"\n[Nominatim] Geocoded {geocoded}/{len(venues)} venues")
    return geocoded


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Google Places / Nominatim enrichment")
    parser.add_argument("--country", help="Country code (FR, GB, IT)")
    parser.add_argument("--limit", type=int, help="Max venues to enrich")
    parser.add_argument(
        "--free", action="store_true",
        help="Use free Nominatim geocoding (no API key needed)"
    )
    args = parser.parse_args()

    if args.free:
        asyncio.run(run_free_geocoding(args.country))
    else:
        asyncio.run(run_google_enrichment(args.country, args.limit))
