"""
Mega slug discovery — validate ALL slugs found from App Store mining,
Google dorking, and creative variations. Then match to DB venues.
"""

import asyncio
import aiohttp
import sys
import os
import re
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrapers.apex_slug_validator import validate_slug, KNOWN_APEX_SLUGS
from utils.database import get_connection, upsert_venue, init_db


def _normalize(text):
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


# ===========================================================================
# ALL DISCOVERED SLUGS from App Stores + Google dorking
# Format: slug -> display_name (used for matching)
# ===========================================================================
ALL_DISCOVERED_SLUGS = {
    # === From Google Play Store ===
    "kartingevasion": "Karting Evasion Bully",
    "kartingevasionrumilly": "Karting Evasion Rumilly",
    "kartingevasionlecreusot": "Karting Evasion Le Creusot",
    "topgunevasion": "Karting TopGun Evasion",
    "brignoleskartingloisir": "Brignoles Karting Loisir",
    "kartingdechartres": "Karting de Chartres",
    "gpkart": "GP Kart",
    "metzkartindoor": "Metz Kart Indoor",
    "kartindoorchrono": "Kart Indoor Chrono",
    "selestatkartin": "Selestat Kart Indoor",
    "gameparc": "Gameparc Poitiers",
    "ekartinpark": "E-Kart'in Park Andrezieux",
    "interracingkartfrejus": "Inter Racing Kart Frejus",
    "planetkarting": "Planet Karting",
    "racingkartjpr": "Racing Kart JPR",
    "kartandgo": "Kart and Go",
    "kartingmuret": "Karting Muret",
    "aco": "ACO Le Mans Karting",
    "lillekarting": "Lille Karting",
    "sundgaukarting": "Sundgau Karting",
    "bke": "Brest Karting Electrique",
    "onlykart": "OnlyKart Lyon",
    "funkartbarsurloup": "Fun Kart Bar-sur-Loup",
    "kartingpayerne": "Karting Payerne",
    "ekart": "E-Kart",
    "kartingbassecourt": "Karting Bassecourt",
    "defisparc": "Defis Parc",
    "circuitofernandoalonso": "Circuito Fernando Alonso",
    "straskart": "Stras Kart Strasbourg",
    "solokart": "Solokart",
    "capkarting": "Cap Karting",

    # === From Apple App Store ===
    "holykartroma": "Holy Kart Roma",
    "elkmotorsport": "ELK Motorsport",
    "m4karting": "M4 Karting",

    # === From APK sites ===
    "lylinternationalkarting": "LYL International Karting",
    "kartingdesfagnes": "Karting des Fagnes",
    "vmaxkarting": "VMax Karting",
    "fastlanekarting": "Fastlane Karting Bilzen",
    "prokartraceland": "Prokart Raceland",
    "kartodromobarimaxturchese": "Kartodromo Barimax",
    "kartbahn": "Kartbahn Spreitenbach",

    # === Previously found in brute-force ===
    "kartinggenk": "Karting Genk",
    "brusselskart": "Brussels Kart",
    "wavreindoorkarting": "Wavre Indoor Karting",
    "xtremekartingedinburgh": "Xtreme Karting Edinburgh",
    "stevalkartcircuit": "St Eval Kart Circuit",
    "piccadillykartracing": "Piccadilly Kart Racing",
    "kcrkarting": "KCR Karting",
    "tbcindoorracing": "TBC Indoor Racing",
    "circuitokartcarasco": "Circuito Kart Carasco",
    "rushspeedarena": "Rush Speed Arena",
    "racetrackmoncalieri": "45 Kart Indoor Moncalieri",
    "monacoindoorkarting": "Monaco Indoor Karting",
    "limpark": "Limpark",
    "styriakarting": "Styria Karting",
    "shkarting": "SH Karting",
    "slovakiaringkarting": "Slovak Karting Center",
    "topfuelracing": "Top Fuel Racing Arena",
    "funarenaingolstadt": "FunArena Ingolstadt",
    "familyfunpark": "Family Fun Park",
    "extremekart": "Extreme Kart",
    "speeders": "Speeders",
    "racewaystamford": "RPM Raceway Stamford",

    # === Dashed variants of app slugs (live timing may use dashes) ===
    "karting-evasion": "Karting Evasion (alt)",
    "karting-evasion-rumilly": "Karting Evasion Rumilly (alt)",
    "karting-evasion-le-creusot": "Karting Evasion Le Creusot (alt)",
    "topgun-evasion-bully": "TopGun Evasion Bully (alt)",
    "brignoles-karting-loisir": "Brignoles Karting (alt)",
    "brignoles-karting": "Brignoles Karting (alt2)",
    "karting-de-chartres": "Karting de Chartres (alt)",
    "gp-kart": "GP Kart (alt)",
    "metz-kart-indoor": "Metz Kart Indoor (alt)",
    "kart-indoor-chrono": "Kart Indoor Chrono (alt)",
    "selestat-kart-indoor": "Selestat Kart Indoor (alt)",
    "selestat-karting": "Selestat Karting (alt)",
    "e-kartin-park": "E-Kart'in Park (alt)",
    "inter-racing-kart-frejus": "Inter Racing Kart Frejus (alt)",
    "inter-racing-kart": "Inter Racing Kart (alt)",
    "planet-karting": "Planet Karting (alt)",
    "racing-kart-jpr": "Racing Kart JPR (alt)",
    "kart-and-go": "Kart and Go (alt)",
    "lille-karting": "Lille Karting (alt)",
    "sundgau-karting": "Sundgau Karting (alt)",
    "sundgau-kart": "Sundgau Kart (alt)",
    "brest-karting-electrique": "Brest Karting Electrique (alt)",
    "only-kart": "OnlyKart (alt)",
    "fun-kart-bar-sur-loup": "Fun Kart Bar-sur-Loup (alt)",
    "stras-kart": "Stras Kart (alt)",
    "solo-kart": "Solokart (alt)",
    "cap-karting": "Cap Karting (alt)",
    "holy-kart-roma": "Holy Kart Roma (alt)",
    "elk-motorsport": "ELK Motorsport (alt)",
    "m4-karting": "M4 Karting (alt)",
    "lyl-karting": "LYL Karting (alt)",
    "karting-des-fagnes": "Karting des Fagnes (alt)",
    "vmax-karting": "VMax Karting (alt)",
    "fastlane-karting": "Fastlane Karting (alt)",
    "prokart-raceland": "Prokart Raceland (alt)",

    # === Khub Arras from AppBrain mention ===
    "khubarraskarting": "Khub Arras Karting",
    "khub-arras-karting": "Khub Arras Karting (alt)",
    "khub-arras": "Khub Arras (alt)",

    # === More creative patterns for French tracks ===
    "kartingdebeauvais": "Karting de Beauvais",
    "karting-de-beauvais": "Karting de Beauvais (alt)",
    "madeinkart": "Made in Kart Joigny",
    "made-in-kart": "Made in Kart (alt)",
    "folembray": "Folembray Arena",
    "folembray-arena": "Folembray Arena (alt)",
    "cosnekarting": "Cosne Karting",
    "cosne-karting": "Cosne Karting (alt)",
    "formulekart": "Formule Kart",
    "formule-kart": "Formule Kart (alt)",
    "formule-kart-villeperdue": "Formule Kart Villeperdue",
    "circuit-renardieres": "Circuit des Renardieres",
    "circuitrenardieres": "Circuit Renardieres",
    "renardieres": "Renardieres",
    "karting-ozan": "Karting Ozan",
    "kartingozan": "Karting Ozan",
    "winkart": "Win Kart Carcassonne",
    "win-kart": "Win Kart (alt)",
    "circuit-jura-sud": "Circuit Jura Sud",
    "circuitjurasud": "Circuit Jura Sud",
    "kartmania": "Kartmania",
    "karting-philippe-alliot": "Karting Philippe Alliot",
    "kartingphilippealliot": "Karting Philippe Alliot",
    "philippe-alliot": "Philippe Alliot",
    "karting-escource": "Karting Escource",
    "kartingescource": "Karting Escource",
    "circuit-berdery": "Circuit Berdery",
    "circuitberdery": "Circuit Berdery",
    "berdery": "Berdery",
    "circuit-du-laquais": "Circuit du Laquais",
    "circuitdulaquais": "Circuit du Laquais",
    "laquais": "Laquais",
    "puissance-kart": "Puissance Kart Indoor",
    "puissancekart": "Puissance Kart Indoor",
    "pkl": "PKL Lommerange",
    "pkl-karting": "PKL Karting (alt)",
    "pkl-lommerange": "PKL Lommerange (alt)",
    "kerlabo-kart": "Kerlabo Kart",
    "kerlabokart": "Kerlabo Kart",
    "dks-motors": "DKS Motors",
    "dksmotors": "DKS Motors",
    "wattkart": "Wattkart Phalsbourg",
    "mp-karting": "MP Karting Lanas",
    "mpkarting": "MP Karting Lanas",
    "racing-kart-beaucaire": "Racing Kart Beaucaire",
    "racingkartbeaucaire": "Racing Kart Beaucaire",
    "sens-karting": "Sens Espaces Karting",
    "senskarting": "Sens Karting",
    "karting-evasion-bully": "Karting Evasion Bully (alt)",
    "gp-circuit": "GP Circuit Lamballe",
    "gpcircuit": "GP Circuit",
    "kart56": "KART56 Ploemel",
    "eurokart": "Eurokart Valence",
    "eurokart-valence": "Eurokart Valence (alt)",
    "kcp": "KCP Karting",
    "kcp-karting": "KCP Karting (alt)",
    "racing-kart-jade": "Racing Kart Jade",
    "racingkartjade": "Racing Kart Jade",
    "new-kart": "New Kart Poitiers",
    "newkart": "New Kart Poitiers",
    "briqueterie": "La Briqueterie Les Etards",
    "la-briqueterie": "La Briqueterie (alt)",
    "clotkart": "ClotKart",
    "clot-kart": "ClotKart (alt)",
    "karting-komplex": "Plerin Komplex Indoor",
    "komplex": "Komplex Indoor",
    "plerin-komplex": "Plerin Komplex",

    # === For UK tracks ===
    "buckmore": "Buckmore Park",
    "buckmore-park": "Buckmore Park (alt)",
    "ryehouse": "Rye House",
    "rye-house": "Rye House (alt)",
    "three-sisters": "Three Sisters Circuit",
    "threesisters": "Three Sisters",
    "pfi": "PF International",
    "pf-international": "PF International (alt)",
    "daytona": "Daytona",
    "daytona-sandown": "Daytona Sandown",
    "teamsport": "TeamSport",
    "teamsportkarting": "TeamSport Karting",
    "team-sport": "TeamSport (alt)",
    "clay-pigeon": "Clay Pigeon Kart Club",
    "claypigeon": "Clay Pigeon",
    "elloughpark": "Ellough Park",
    "ellough-park": "Ellough Park (alt)",
    "lydd-kart": "Lydd Kart Circuit",
    "lyddkart": "Lydd Kart",
    "gygkarting": "GYG Karting",
    "gyg-karting": "GYG Karting (alt)",
    "capitalkarts": "Capital Karts",
    "capital-karts": "Capital Karts (alt)",

    # === For Italian tracks ===
    "laconca": "La Conca",
    "la-conca": "La Conca (alt)",
    "kartodromolaconca": "Kartodromo La Conca",
    "val-vibrata": "Val Vibrata",
    "valvibrata": "Val Vibrata",
    "ottobiano": "Ottobiano Motorsport",
    "ottobiano-motorsport": "Ottobiano Motorsport (alt)",
    "7laghi": "7 Laghi Kart",
    "7laghikart": "7 Laghi Kart",
    "7-laghi-kart": "7 Laghi Kart (alt)",
    "varano": "Autodromo Varano",
    "autodromo-varano": "Autodromo Varano (alt)",
    "mugello-karting": "Mugello Karting",
    "mugello": "Mugello",
    "napoli-karting": "Circuito Internazionale Napoli",
    "circuito-napoli": "Circuito Napoli",
    "battipaglia": "Battipaglia",
    "kartodromo-battipaglia": "Kartodromo Battipaglia",
    "precenicco": "Precenicco",
    "circuito-precenicco": "Circuito Precenicco",
    "ortona": "Ortona",
    "kartodromo-ortona": "Kartodromo Ortona",
    "prodrive": "ProDRIVE Kart Center",
    "crg-lonato": "CRG Lonato",
    "crgtrack": "CRG Track",
    "viterbo": "Circuito Viterbo",
    "circuito-viterbo": "Circuito Viterbo (alt)",
    "kartodromo-lago": "Kartodromo Lago",
    "pistaazzurra": "Pista Azzurra",
    "pista-azzurra-jesolo": "Pista Azzurra Jesolo",
}


def match_venue(slug, app_name, unresolved_venues):
    """Try to match a validated slug to an unresolved venue."""
    app_lower = _normalize(app_name)
    slug_lower = slug.lower()
    slug_compact = re.sub(r"[^a-z0-9]", "", slug_lower)

    best_venue = None
    best_score = 0

    for v in unresolved_venues:
        v_name = _normalize(v["name"])
        v_city = _normalize(v.get("city") or "")
        v_compact = re.sub(r"[^a-z0-9]", "", v_name)

        score = 0

        # Direct slug containment (strong signal)
        if slug_compact in v_compact:
            score += 3.0
        elif v_compact in slug_compact and len(v_compact) > 5:
            score += 2.5

        # City in slug
        if v_city and len(v_city) >= 3:
            city_compact = re.sub(r"[^a-z0-9]", "", v_city)
            if city_compact in slug_compact and len(city_compact) >= 4:
                score += 2.0

        # App name words vs venue name words
        app_words = set(re.findall(r"[a-z]{3,}", app_lower))
        v_words = set(re.findall(r"[a-z]{3,}", v_name))
        filler = {
            "karting", "kart", "circuit", "piste", "indoor", "outdoor",
            "centre", "center", "racing", "loisir", "loisirs", "alt",
            "parc", "park", "arena", "the", "les", "des", "une",
        }
        app_meaningful = app_words - filler
        v_meaningful = v_words - filler
        if app_meaningful and v_meaningful:
            overlap = len(app_meaningful & v_meaningful)
            if overlap > 0:
                score += overlap * 1.5

        # Slug words vs venue name
        slug_words = set(slug_lower.replace("-", " ").split())
        slug_meaningful = slug_words - filler
        if slug_meaningful and v_meaningful:
            overlap = len(slug_meaningful & v_meaningful)
            if overlap > 0:
                score += overlap * 1.0

        if score > best_score:
            best_score = score
            best_venue = v

    return best_venue, best_score


async def main():
    init_db()

    # Get existing slugs
    conn = get_connection()
    existing_slugs = set()
    for row in conn.execute("SELECT timing_slug FROM venues WHERE timing_slug IS NOT NULL"):
        existing_slugs.add(row["timing_slug"])
    unresolved = [dict(r) for r in conn.execute(
        "SELECT * FROM venues WHERE timing_slug IS NULL"
    ).fetchall()]
    conn.close()

    # Filter out already-known slugs
    to_test = {
        s: n for s, n in ALL_DISCOVERED_SLUGS.items()
        if s not in existing_slugs and s not in KNOWN_APEX_SLUGS
    }

    print(f"Already have {len(existing_slugs)} slugs in DB")
    print(f"Unresolved venues: {len(unresolved)}")
    print(f"Slugs to validate: {len(to_test)} (after filtering known)")
    print()

    # Step 1: Validate all slugs
    validated = []
    sem = asyncio.Semaphore(15)

    async with aiohttp.ClientSession(
        headers={"User-Agent": "PIP-RaceStrategy/1.0"},
        timeout=aiohttp.ClientTimeout(total=8),
    ) as session:
        async def check(slug, name):
            async with sem:
                result = await validate_slug(session, slug)
                if result:
                    validated.append((slug, name, result))
                await asyncio.sleep(0.06)

        tasks = [check(slug, name) for slug, name in to_test.items()]
        await asyncio.gather(*tasks)

    print(f"\n=== Validated {len(validated)} slugs ===\n")
    for s, n, r in sorted(validated, key=lambda x: x[0]):
        print(f"  ✓ {s} ({n})")

    # Step 2: Match to unresolved venues
    matched = 0
    matched_ids = set()
    used_slugs = set()

    for slug, app_name, result in validated:
        venue, score = match_venue(slug, app_name, unresolved)

        if venue and score >= 2.0 and venue["id"] not in matched_ids and slug not in used_slugs:
            try:
                upsert_venue({
                    "id": venue["id"],
                    "timing_system": "apex_timing",
                    "timing_slug": slug,
                    "live_timing_url": result["url"],
                    "timing_verified": True,
                    "status": "verified",
                })
                matched += 1
                matched_ids.add(venue["id"])
                used_slugs.add(slug)
                unresolved = [v for v in unresolved if v["id"] != venue["id"]]
                print(f"\n  MATCHED: {slug} -> {venue['name']} (score={score:.1f})")
            except Exception as e:
                print(f"\n  ERROR: {slug} -> {venue['name']}: {e}")
        elif venue:
            if score > 0:
                print(f"  LOW: {slug} ({app_name}) ~ {venue['name']} (score={score:.1f})")

    # Step 3: Also add unmatched validated slugs as new venues
    added = 0
    for slug, app_name, result in validated:
        if slug in used_slugs:
            continue
        if "(alt" in app_name:
            continue  # Skip alt variants for new venue creation
        # Add as new venue
        try:
            upsert_venue({
                "name": app_name,
                "timing_system": "apex_timing",
                "timing_slug": slug,
                "live_timing_url": result["url"],
                "timing_verified": True,
                "status": "verified",
                "source": "appstore_discovery",
            })
            added += 1
            used_slugs.add(slug)
            print(f"  + NEW: {slug} -> {app_name}")
        except Exception:
            pass

    print(f"\n{'='*60}")
    print(f"  Validated slugs: {len(validated)}")
    print(f"  Matched to existing venues: {matched}")
    print(f"  Added as new venues: {added}")

    # Final stats
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) as c FROM venues").fetchone()["c"]
    verified = conn.execute("SELECT COUNT(*) as c FROM venues WHERE timing_verified = 1").fetchone()["c"]
    by_country = {}
    for row in conn.execute("""
        SELECT country, COUNT(*) as total,
               SUM(CASE WHEN timing_verified = 1 THEN 1 ELSE 0 END) as verified
        FROM venues GROUP BY country ORDER BY total DESC
    """).fetchall():
        by_country[row["country"]] = (row["total"], row["verified"])
    conn.close()

    print(f"\n  Database: {total} venues, {verified} verified ({verified/total*100:.1f}%)")
    print(f"\n  By country:")
    for c, (t, v) in by_country.items():
        print(f"    {c}: {v}/{t} verified ({v/t*100:.0f}%)")


asyncio.run(main())
