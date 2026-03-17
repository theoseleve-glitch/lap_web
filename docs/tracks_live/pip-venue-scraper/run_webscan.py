"""Quick website scanner — scan curated track URLs for Apex Timing references."""

import asyncio
import aiohttp
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrapers.apex_slug_validator import validate_slug
from utils.database import get_connection, upsert_venue, init_db

APEX_PATTERN = re.compile(
    r'(?:apex-timing\.com|live\.apex-timing\.com)/(?:live-timing/)?([a-z0-9][a-z0-9_-]{2,40}?)(?:/|["\'\s?#<>])',
    re.IGNORECASE,
)

SUBPAGES = ["", "/live-timing", "/live", "/resultats", "/results",
            "/classement", "/chrono", "/timing", "/en-direct"]

SKIP_SLUGS = {
    "en", "fr", "it", "de", "es", "live-timing", "live",
    "index.html", "css", "js", "img", "images", "assets",
}

KNOWN_WEBSITES = {
    # French tracks
    "Karting du Laquais": "https://www.circuitdulaquais.com",
    "Albi Kart": "https://www.albi-kart.fr",
    "DB Karting": "https://www.dbkarting.fr",
    "Karting Six-Fours": "https://www.kartingsixfours.com",
    "GP Circuit Lamballe": "https://www.gpcircuit.fr",
    "KART56": "https://www.kart56.com",
    "Eurokart Valence": "https://www.eurokart.fr",
    "KCP Karting": "https://www.kcp-karting.fr",
    "Racing Kart Jade": "https://www.racingkartjade.fr",
    "Racing Kart Beaucaire": "https://www.racingkartbeaucaire.fr",
    "Sens Espaces Karting": "https://www.senskarting.fr",
    "PKL Lommerange": "https://www.pkl-karting.fr",
    "Kerlabo Kart": "https://www.kerlabo-kart.com",
    "Puissance Kart": "https://www.puissance-kart.com",
    "DKS-Motors": "https://www.dks-motors.com",
    "Wattkart": "https://www.wattkart.com",
    "MP Karting Lanas": "https://www.mpkarting.fr",
    "Circuit Berdery": "https://www.circuitberdery.com",
    "Sundgau Kart": "https://www.sundgaukart.fr",
    "Cosne Karting": "https://www.cosnekarting.fr",
    "Formule Kart": "https://www.formulekart.fr",
    "Lille Karting": "https://www.lillekarting.com",
    "New Kart Poitiers": "https://www.newkart.fr",
    "La Briqueterie": "https://www.la-briqueterie.com",
    "Folembray Arena": "https://www.folembray.com",
    "ClotKart": "https://www.clotkart.com",
    "Circuit des Renardieres": "https://www.circuit-renardieres.com",
    "Karting Ozan": "https://www.karting-ozan.fr",
    "Win Kart Carcassonne": "https://www.winkart.fr",
    "Circuit Jura Sud": "https://www.circuit-jura-sud.fr",
    "Kartmania": "https://www.kartmania.fr",
    "Karting Philippe Alliot": "https://www.kartingphilippealliot.com",
    "Karting Evasion Bully": "https://www.karting-evasion.fr",
    "Karting de Beauvais": "https://www.kartingdebeauvais.fr",
    "Made in Kart Joigny": "https://www.madeinkart.fr",
    "Karting Escource": "https://www.kartingescource.com",
    "Plerin Komplex": "https://www.komplex.fr",
    "Karting de l'Etang": "https://www.karting-etang.com",
    "Karting St-Cyprien": "https://www.kartingsaintcyprien.com",
    # UK tracks
    "Buckmore Park": "https://www.buckmore.co.uk",
    "Rye House": "https://www.ryehouse.co.uk",
    "Three Sisters": "https://www.threesisterscircuit.co.uk",
    "PF International": "https://www.pfi.org.uk",
    "Daytona": "https://www.daytona.co.uk",
    "Clay Pigeon": "https://www.claypigeonkartclub.co.uk",
    "Ellough Park": "https://www.elloughpark.co.uk",
    "Lydd Kart": "https://www.lyddkartcircuit.com",
    "GYG Karting": "https://www.gygkarting.com",
    "Capital Karts": "https://www.capitalkarts.com",
    # Italian tracks
    "La Conca": "https://www.laconca.it",
    "Val Vibrata": "https://www.kartodromovalvibrata.it",
    "Ottobiano": "https://www.ottobianomotorsport.com",
    "7 Laghi Kart": "https://www.7laghikart.it",
    "Varano": "https://www.autodromodivarano.it",
}


async def scan_one(session, name, url):
    """Scan a track website + subpages for Apex Timing references."""
    for subpath in SUBPAGES:
        full_url = url.rstrip("/") + subpath
        try:
            async with session.get(
                full_url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text(errors="replace")
                matches = APEX_PATTERN.findall(html)
                for match in matches:
                    slug = match.lower().strip("/")
                    if slug and slug not in SKIP_SLUGS and len(slug) >= 3:
                        return slug
        except Exception:
            continue
    return None


async def main():
    init_db()
    found = 0
    new_slugs = []

    connector = aiohttp.TCPConnector(limit=5, ssl=False)
    async with aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": "Mozilla/5.0 (compatible; PIP-RaceStrategy/1.0)"},
    ) as session:
        for name, url in KNOWN_WEBSITES.items():
            slug = await scan_one(session, name, url)
            if slug:
                result = await validate_slug(session, slug)
                if result:
                    # Try to find in DB
                    conn = get_connection()
                    search_name = name.split("(")[0].strip()
                    venue = conn.execute(
                        "SELECT id, name FROM venues WHERE name LIKE ? AND timing_slug IS NULL",
                        (f"%{search_name}%",),
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
                            found += 1
                            new_slugs.append(f"{name} -> {slug}")
                            print(f"  ✓ {name} -> {slug} (matched: {venue['name']})")
                        except Exception as e:
                            print(f"  ! {name} -> {slug} (DB error: {e})")
                    else:
                        new_slugs.append(f"{name} -> {slug} (no DB match)")
                        print(f"  ~ {name} -> {slug} (no unresolved DB match)")
                else:
                    print(f"  ✗ {name} -> {slug} (slug invalid)")
            else:
                print(f"  - {name}: no Apex reference found")

            await asyncio.sleep(0.3)

    print(f"\n=== Website Scan Results ===")
    print(f"Total new Apex slugs found: {found}")
    if new_slugs:
        print("Discoveries:")
        for s in new_slugs:
            print(f"  {s}")


asyncio.run(main())
