"""
Discover Apex Timing slugs from Google Play Store app IDs.
App package: com.apextiming.{SLUG} -> slug is often the live timing slug.
"""

import asyncio
import aiohttp
import sys
import os
import re
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrapers.apex_slug_validator import validate_slug
from utils.database import get_connection, upsert_venue, init_db


def _normalize(text):
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


# All app IDs discovered from Google Play Store searches
# Format: slug_from_app_id -> app_display_name
APP_SLUGS = {
    # French tracks
    "kartingevasion": "Karting Evasion",
    "brignoleskartingloisir": "Brignoles Karting Loisir",
    "kartingdechartres": "Karting de Chartres",
    "kartingcircuitpaulricard": "Karting Circuit Paul Ricard",
    "gpkart": "GP Kart",
    "metzkartindoor": "Metz Kart Indoor",
    "kartindoorchrono": "Kart Indoor Chrono",
    "selestatkartin": "Selestat Kart Indoor",
    "gameparc": "Gameparc Poitiers",
    "ekartinpark": "E-Kart'in Park Andrezieux",
    "interracingkartfrejus": "Inter Racing Kart Frejus",
    "kartcenterbiscarrosse": "Kart Center Biscarrosse",
    "kartingloisirsneuilly": "Karting Loisirs Neuilly",
    "planetkarting": "Planet Karting",
    "racingkartjpr": "Racing Kart JPR",
    "kartandgo": "Kart&Go",
    "kartingmuret": "Karting Muret",
    "aco": "ACO Le Mans Karting",

    # Belgian tracks
    "kartinggenk": "Karting Genk",
    "brusselskart": "Brussels Kart",
    "wavreindoorkarting": "Wavre Indoor Karting",

    # UK tracks
    "xtremekartingedinburgh": "Xtreme Karting Edinburgh",
    "stevalkartcircuit": "St Eval Kart Circuit",
    "piccadillykartracing": "Piccadilly Kart Racing",
    "kcrkarting": "KCR Karting",
    "tbcindoorracing": "TBC Indoor Racing",

    # Italian tracks
    "circuitokartcarasco": "Circuito Kart Carasco",
    "rushspeedarena": "Rush Speed Arena",
    "racetrackmoncalieri": "45 Kart Indoor Moncalieri",

    # Other
    "monacoindoorkarting": "Monaco Indoor Karting",
    "arena45": "Arena 45",
    "limpark": "Limpark",
    "styriakarting": "Styria Karting",
    "shkarting": "SH Karting",
    "slovakiaringkarting": "Slovak Karting Center",
    "vmkartingcenter": "VM Karting Center",
    "kartcenter": "Kart Center",
    "topfuelracing": "Top Fuel Racing Arena",
    "funarenaingolstadt": "FunArena Ingolstadt",
    "familyfunpark": "Family Fun Park",
    "extremekart": "Extreme Kart",

    # Also try slug variations that might differ from app ID
    "karting-evasion": "Karting Evasion (alt)",
    "brignoles-karting": "Brignoles Karting (alt)",
    "karting-chartres": "Karting de Chartres (alt)",
    "metz-kart-indoor": "Metz Kart Indoor (alt)",
    "kart-indoor-chrono": "Kart Indoor Chrono (alt)",
    "selestat-karting": "Selestat Kart (alt)",
    "inter-racing-kart": "Inter Racing Kart (alt)",
    "planet-karting": "Planet Karting (alt)",
    "racing-kart-jpr": "Racing Kart JPR (alt)",
    "gp-kart": "GP Kart (alt)",
    "ekartinpark-andrezieux": "E-Kart'in Park (alt)",
    "xtreme-karting": "Xtreme Karting (alt)",
    "st-eval": "St Eval (alt)",
    "piccadilly": "Piccadilly (alt)",
    "piccadilly-karting": "Piccadilly Karting (alt)",
    "tbc-indoor": "TBC Indoor (alt)",
    "rush-speed-arena": "Rush Speed Arena (alt)",
    "circuito-carasco": "Circuito Carasco (alt)",
    "kart-carasco": "Kart Carasco (alt)",
}


async def main():
    init_db()

    # Get already-known slugs from DB
    conn = get_connection()
    existing_slugs = set()
    for row in conn.execute("SELECT timing_slug FROM venues WHERE timing_slug IS NOT NULL"):
        existing_slugs.add(row["timing_slug"])
    conn.close()

    print(f"Already have {len(existing_slugs)} slugs in DB")
    print(f"Testing {len(APP_SLUGS)} app-derived slug candidates...\n")

    validated = []
    async with aiohttp.ClientSession(
        headers={"User-Agent": "PIP-RaceStrategy/1.0"},
        timeout=aiohttp.ClientTimeout(total=8),
    ) as session:
        sem = asyncio.Semaphore(10)

        async def check(slug, name):
            async with sem:
                result = await validate_slug(session, slug)
                if result:
                    validated.append((slug, name, result))
                    status = "KNOWN" if slug in existing_slugs else "NEW"
                    print(f"  ✓ {slug} -> {result['url']} [{status}]")
                await asyncio.sleep(0.08)

        tasks = [check(slug, name) for slug, name in APP_SLUGS.items()]
        await asyncio.gather(*tasks)

    # Now match NEW validated slugs to unresolved DB venues
    new_slugs = [(s, n, r) for s, n, r in validated if s not in existing_slugs]
    print(f"\n=== Validated {len(validated)} total, {len(new_slugs)} NEW slugs ===\n")

    conn = get_connection()
    unresolved = [dict(r) for r in conn.execute(
        "SELECT * FROM venues WHERE timing_slug IS NULL"
    ).fetchall()]
    conn.close()

    matched = 0
    for slug, app_name, result in new_slugs:
        # Try to find a matching venue
        slug_lower = slug.lower()
        app_lower = _normalize(app_name)

        best_venue = None
        best_score = 0

        for v in unresolved:
            v_name = _normalize(v["name"])
            v_city = _normalize(v.get("city") or "")
            v_compact = re.sub(r"[^a-z0-9]", "", v_name)
            slug_compact = re.sub(r"[^a-z0-9]", "", slug_lower)

            score = 0

            # Direct slug containment
            if slug_compact in v_compact or v_compact in slug_compact:
                score += 3.0

            # City in slug
            if v_city and len(v_city) >= 3:
                city_compact = re.sub(r"[^a-z0-9]", "", v_city)
                if city_compact in slug_compact:
                    score += 2.0

            # App name word overlap with venue name
            app_words = set(re.findall(r"[a-z]{3,}", app_lower))
            v_words = set(re.findall(r"[a-z]{3,}", v_name))
            filler = {"karting", "kart", "circuit", "piste", "indoor", "outdoor",
                       "centre", "center", "racing", "loisir", "loisirs", "alt"}
            app_meaningful = app_words - filler
            v_meaningful = v_words - filler
            if app_meaningful and v_meaningful:
                overlap = len(app_meaningful & v_meaningful)
                if overlap > 0:
                    score += overlap * 1.5

            if score > best_score:
                best_score = score
                best_venue = v

        if best_venue and best_score >= 2.0:
            try:
                upsert_venue({
                    "id": best_venue["id"],
                    "timing_system": "apex_timing",
                    "timing_slug": slug,
                    "live_timing_url": result["url"],
                    "timing_verified": True,
                    "status": "verified",
                })
                matched += 1
                print(f"  MATCHED: {slug} -> {best_venue['name']} (score={best_score:.1f})")
                # Remove from unresolved
                unresolved = [v for v in unresolved if v["id"] != best_venue["id"]]
            except Exception as e:
                print(f"  ERROR: {slug} -> {e}")
        else:
            if best_venue:
                print(f"  LOW: {slug} ({app_name}) ~ {best_venue['name']} (score={best_score:.1f})")
            else:
                print(f"  UNMATCHED: {slug} ({app_name})")

    print(f"\n=== Results ===")
    print(f"  Validated app slugs: {len(validated)}")
    print(f"  New (not in DB): {len(new_slugs)}")
    print(f"  Matched to venues: {matched}")

    # Final stats
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) as c FROM venues").fetchone()["c"]
    verified = conn.execute("SELECT COUNT(*) as c FROM venues WHERE timing_verified = 1").fetchone()["c"]
    conn.close()
    print(f"\n  Database: {total} venues, {verified} verified ({verified/total*100:.1f}%)")


asyncio.run(main())
