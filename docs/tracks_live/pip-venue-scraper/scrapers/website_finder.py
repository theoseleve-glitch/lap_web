"""
Website finder — discovers actual track websites for venues in the database,
then scans them for embedded Apex Timing iframes/links.

Uses Google search to find track websites, then scrapes those websites
looking for apex-timing.com references.
"""

import asyncio
import re
import sys
import os
import json
import aiohttp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import get_connection, upsert_venue, init_db

# Regex to find Apex Timing references in HTML
APEX_PATTERN = re.compile(
    r'(?:apex-timing\.com|live\.apex-timing\.com)/(?:live-timing/)?([a-z0-9][a-z0-9_-]{2,40}?)(?:/|["\'\s?#<>])',
    re.IGNORECASE,
)

# Subpages to check on each track website
SUBPAGES = [
    "", "/live-timing", "/live", "/resultats", "/results",
    "/classement", "/ranking", "/chrono", "/timing",
    "/en-direct", "/temps", "/courses", "/races",
]

# Slugs to skip (not actual venues)
SKIP_SLUGS = {
    "en", "fr", "it", "de", "es", "live-timing", "live",
    "index.html", "css", "js", "img", "images", "assets",
}


async def find_website_google(session: aiohttp.ClientSession, name: str, city: str, country: str) -> str | None:
    """
    Use Google's 'I'm Feeling Lucky' redirect to find a track's website.
    Falls back to parsing search results page.
    """
    country_name = {"FR": "France", "GB": "UK", "IT": "Italy"}.get(country, "")
    query = f"{name} {city} {country_name} karting"

    # Try Google's redirect (doesn't always work)
    url = f"https://www.google.com/search?q={aiohttp.helpers.quote(query)}&btnI=1"
    try:
        async with session.get(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ) as resp:
            final_url = str(resp.url)
            if "google.com" not in final_url and resp.status == 200:
                return final_url
    except:
        pass

    return None


async def scan_website_for_apex(session: aiohttp.ClientSession, base_url: str) -> str | None:
    """
    Scan a track's website (homepage + subpages) for Apex Timing references.
    Returns the discovered slug, or None.
    """
    for subpath in SUBPAGES:
        url = base_url.rstrip("/") + subpath
        try:
            async with session.get(
                url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=12),
                headers={"User-Agent": "Mozilla/5.0 (compatible; PIP-RaceStrategy/1.0)"},
            ) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text(errors="replace")

                # Search for Apex Timing URLs
                matches = APEX_PATTERN.findall(html)
                for match in matches:
                    slug = match.lower().strip("/")
                    if slug and slug not in SKIP_SLUGS and len(slug) >= 3:
                        return slug

        except Exception:
            continue

    return None


async def discover_websites_and_slugs(concurrency: int = 3, limit: int = None) -> int:
    """
    For each venue without a website or timing_slug:
    1. Find the track's website via Google
    2. Scan it for Apex Timing iframes
    3. Validate and store the slug
    """
    init_db()
    conn = get_connection()

    # Get venues that need websites or slugs
    query = """
        SELECT * FROM venues
        WHERE timing_slug IS NULL
        AND country IN ('FR', 'GB', 'IT')
        ORDER BY country, name
    """
    venues = [dict(r) for r in conn.execute(query).fetchall()]
    conn.close()

    if limit:
        venues = venues[:limit]

    print(f"\n[WEBFIND] Searching websites for {len(venues)} unresolved venues...")

    sem = asyncio.Semaphore(concurrency)
    found_count = 0
    websites_found = 0

    async with aiohttp.ClientSession() as session:

        async def process_venue(venue):
            nonlocal found_count, websites_found
            async with sem:
                name = venue["name"]
                city = venue.get("city") or ""
                country = venue.get("country", "FR")

                # Step 1: Find the website
                website = venue.get("website_url")
                if not website or "chronokart.net" in (website or ""):
                    website = await find_website_google(session, name, city, country)
                    if website:
                        websites_found += 1
                        upsert_venue({"id": venue["id"], "website_url": website})

                if not website:
                    return

                # Step 2: Scan for Apex Timing
                slug = await scan_website_for_apex(session, website)
                if slug:
                    # Step 3: Validate the slug
                    from scrapers.apex_slug_validator import validate_slug
                    result = await validate_slug(session, slug)
                    if result:
                        try:
                            upsert_venue({
                                "id": venue["id"],
                                "timing_system": "apex_timing",
                                "timing_slug": slug,
                                "live_timing_url": result["url"],
                                "timing_verified": True,
                                "status": "verified",
                                "website_url": website,
                            })
                            found_count += 1
                            print(f"  ✓ {name} -> {slug} (via {website})")
                        except Exception:
                            pass
                        return

                # Rate limit Google
                await asyncio.sleep(2.0)

        tasks = [process_venue(v) for v in venues]
        await asyncio.gather(*tasks)

    print(f"\n[WEBFIND] Results:")
    print(f"  Websites discovered: {websites_found}")
    print(f"  Apex slugs found:    {found_count}")
    return found_count


async def scan_known_track_websites() -> int:
    """
    Scan a curated list of known track websites for Apex Timing references.
    This bypasses Google search and goes straight to scraping.
    """
    # Manually curated track website URLs for high-value targets
    KNOWN_WEBSITES = {
        # French tracks with known websites
        "Karting du Laquais": "https://www.circuitdulaquais.com",
        "Albi Kart Expérience": "https://www.albi-kart.fr",
        "Karting de Beauvais": "https://www.kartingdebeauvais.fr",
        "Made in Kart Joigny": "https://www.madeinkart.fr",
        "DB Karting St-Lyé": "https://www.dbkarting.fr",
        "Karting Six-Fours": "https://www.kartingsixfours.com",
        "Karting Escource": "https://www.kartingescource.com",
        "Karting Evasion Bully": "https://www.karting-evasion.fr",
        "GP Circuit Lamballe": "https://www.gpcircuit.fr",
        "Karting de Ploemel - KART56": "https://www.kart56.com",
        "Plérin Komplex Indoor": "https://www.komplex.fr",
        "Eurokart Valence": "https://www.eurokart.fr",
        "KCP Karting Cuges-les-Pins": "https://www.kcp-karting.fr",
        "Karting de l'Etang": "https://www.karting-etang.com",
        "Racing Kart Jade": "https://www.racingkartjade.fr",
        "Racing Kart Beaucaire": "https://www.racingkartbeaucaire.fr",
        "Sens Espaces Karting": "https://www.senskarting.fr",
        "PKL Lommerange": "https://www.pkl-karting.fr",
        "Kerlabo Kart": "https://www.kerlabo-kart.com",
        "Puissance Kart Indoor": "https://www.puissance-kart.com",
        "DKS-Motors": "https://www.dks-motors.com",
        "Wattkart indoor Phalsbourg": "https://www.wattkart.com",
        "MP Karting Lanas": "https://www.mpkarting.fr",
        "Circuit Berdery": "https://www.circuitberdery.com",
        "Sundgau Kart": "https://www.sundgaukart.fr",
        "Cosne Karting": "https://www.cosnekarting.fr",
        "Formule Kart Villeperdue": "https://www.formulekart.fr",
        "Lille Karting (Piste extérieure)": "https://www.lillekarting.com",
        "New Kart Poitiers": "https://www.newkart.fr",
        "La Briqueterie Les Étards 1600m": "https://www.la-briqueterie.com",
        "Folembray Arena": "https://www.folembray.com",
        "ClotKart": "https://www.clotkart.com",
        "Circuit des Renardières": "https://www.circuit-renardieres.com",
        "Karting Ozan": "https://www.karting-ozan.fr",
        "Karting Montrevel-en-Bresse": "https://www.karting-montrevel.fr",
        "Karting St-Cyprien 66": "https://www.kartingsaintcyprien.com",
        "Win'Kart Carcassonne": "https://www.winkart.fr",
        "Circuit Jura Sud": "https://www.circuit-jura-sud.fr",
        "Kartmania Pouilly-en-Auxois": "https://www.kartmania.fr",
        "Karting Philippe Alliot": "https://www.kartingphilippealliot.com",
        # UK tracks
        "Buckmore Park": "https://www.buckmore.co.uk",
        "Rye House Kart Raceway": "https://www.ryehouse.co.uk",
        "Three Sisters Circuit": "https://www.threesisterscircuit.co.uk",
        "PF International": "https://www.pfi.org.uk",
        "Daytona Sandown Park": "https://www.daytona.co.uk",
        "Clay Pigeon Kart Club": "https://www.claypigeonkartclub.co.uk",
        "Ellough Park Raceway": "https://www.elloughpark.co.uk",
        "Lydd Kart Circuit": "https://www.lyddkartcircuit.com",
        "GYG Karting": "https://www.gygkarting.com",
        "Capital Karts": "https://www.capitalkarts.com",
        # Italian tracks
        "Kartodromo La Conca": "https://www.laconca.it",
        "Kartodromo Val Vibrata": "https://www.kartodromovalvibrata.it",
        "Ottobiano Motorsport": "https://www.ottobianomotorsport.com",
        "Rush Speed Arena": "https://www.rushspeedarena.it",
        "7 Laghi Kart": "https://www.7laghikart.it",
        "Autodromo Riccardo Paletti": "https://www.autodromodivarano.it",
    }

    print(f"\n[WEBSCAN] Scanning {len(KNOWN_WEBSITES)} curated track websites...")
    found_count = 0

    async with aiohttp.ClientSession() as session:
        for name, url in KNOWN_WEBSITES.items():
            slug = await scan_website_for_apex(session, url)
            if slug:
                from scrapers.apex_slug_validator import validate_slug
                result = await validate_slug(session, slug)
                if result:
                    # Find the venue in the database
                    conn = get_connection()
                    venue = conn.execute(
                        "SELECT id FROM venues WHERE name LIKE ?",
                        (f"%{name.split('(')[0].strip()}%",),
                    ).fetchone()
                    conn.close()

                    if venue:
                        try:
                            upsert_venue({
                                "id": venue["id"],
                                "timing_system": "apex_timing",
                                "timing_slug": slug,
                                "live_timing_url": result["url"],
                                "timing_verified": True,
                                "status": "verified",
                                "website_url": url,
                            })
                            found_count += 1
                            print(f"  ✓ {name} -> {slug} (from {url})")
                        except Exception:
                            pass
                    else:
                        print(f"  ✓ {name} -> {slug} (no DB match)")
                        found_count += 1
            else:
                pass  # Silently skip — most won't have Apex Timing

            await asyncio.sleep(0.5)

    print(f"\n[WEBSCAN] Found {found_count} Apex slugs from curated websites")
    return found_count


if __name__ == "__main__":
    asyncio.run(scan_known_track_websites())
