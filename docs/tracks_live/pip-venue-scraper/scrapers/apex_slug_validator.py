"""
Apex Timing slug discovery and validation.

Methods:
  A. Brute-force slug generation from track names + HTTP HEAD validation
  B. iframe discovery — scrape track websites for embedded Apex Timing iframes
  C. Known slugs from Google search index (pre-seeded)
"""

import asyncio
import re
import sys
import os
import aiohttp
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import get_venues, upsert_venue, get_connection, init_db
from utils.slug_generator import generate_slug_candidates

# ---------------------------------------------------------------------------
# Pre-seeded known Apex Timing slugs — VERIFIED WORKING via HTTP validation
# Format: slug -> { name, country, match_keywords[] }
# match_keywords help the fuzzy matcher find the right database venue
# ---------------------------------------------------------------------------
KNOWN_APEX_SLUGS = {
    # France — confirmed working
    "circuit-europe": {"name": "Circuit de l'Europe", "country": "FR", "keywords": ["europe", "sotteville"]},
    "rkc": {"name": "Racing Kart Cormeilles", "country": "FR", "keywords": ["rkc", "cormeilles"]},
    "circuitpaulricardkarting": {"name": "Circuit Paul Ricard Karting", "country": "FR", "keywords": ["paul ricard", "castellet"]},
    "circuit-sarron": {"name": "Karting Sarron", "country": "FR", "keywords": ["sarron", "riom"]},
    "circuit-de-lenclos": {"name": "Circuit de l'Enclos", "country": "FR", "keywords": ["enclos", "septfontaines"]},
    "lemans-karting": {"name": "Racing Kart du Mans", "country": "FR", "keywords": ["mans", "montfort"]},
    "karthors": {"name": "Karthors", "country": "FR", "keywords": ["karthors", "cieurac"]},
    "ligue-karting-idf": {"name": "Ligue Karting IDF", "country": "FR", "keywords": ["ligue", "idf"]},
    "ligue-karting-hf": {"name": "Ligue Karting Hauts de France", "country": "FR", "keywords": ["ligue", "hauts"]},
    "mk-circuit": {"name": "MK Circuit", "country": "FR", "keywords": ["mk"]},
    "circuitdebresse": {"name": "Circuit de Bresse", "country": "FR", "keywords": ["bresse", "frontenaud"]},
    "onlykart": {"name": "OnlyKart Lyon", "country": "FR", "keywords": ["onlykart", "dagneux"]},
    "fun-kart": {"name": "Fun Kart Brissac", "country": "FR", "keywords": ["fun kart", "brissac"]},
    "karting-roussillon": {"name": "Karting Roussillon", "country": "FR", "keywords": ["roussillon", "rivesaltes"]},
    "jovikart": {"name": "Jovikart - Karting Nantes", "country": "FR", "keywords": ["jovikart", "bignon"]},
    "solokart": {"name": "Solokart", "country": "FR", "keywords": ["solokart", "plesse"]},
    "bretagne-karting": {"name": "Bretagne Karting", "country": "FR", "keywords": ["bretagne", "combrit"]},
    "prestige-karting": {"name": "Prestige Karting", "country": "FR", "keywords": ["prestige", "luc"]},
    "ffsa-karting": {"name": "FFSA Karting", "country": "FR", "keywords": ["ffsa"]},
    "kln": {"name": "Karting Loisirs Neuilly", "country": "FR", "keywords": ["neuilly"]},
    "lfkarting": {"name": "LF Karting Layrac", "country": "FR", "keywords": ["lf karting", "layrac"]},
    "kart-origins-corbas": {"name": "Kart Origins", "country": "FR", "keywords": ["kart origins", "corbas"]},
    "mkracing": {"name": "MK Racing Cholet", "country": "FR", "keywords": ["mk racing", "cholet", "christophe"]},
    "racingkartdumans": {"name": "Racing Kart du Mans", "country": "FR", "keywords": ["racing kart", "mans", "montfort"]},
    "actarus-loheac": {"name": "Actarus RKO Lohéac", "country": "FR", "keywords": ["actarus", "loheac"]},
    "arena45": {"name": "Arena 45e La Roche de Glun", "country": "FR", "keywords": ["arena", "roche de glun"]},
    "capkarting": {"name": "Cap Karting Mer", "country": "FR", "keywords": ["cap karting", "mer"]},
    "kartcenter-biscarrosse": {"name": "Kart Center Biscarrosse", "country": "FR", "keywords": ["biscarrosse"]},
    "kartrace-witry": {"name": "Kart'Race Witry-lès-Reims", "country": "FR", "keywords": ["kart race", "witry"]},
    "kll-loisirs-douvrin": {"name": "KLL Loisirs", "country": "FR", "keywords": ["kll", "douvrin"]},
    "ouestkarting": {"name": "Ouest Karting Aunay", "country": "FR", "keywords": ["ouest", "aunay"]},
    "topgun-evasion": {"name": "TopGun-Evasion", "country": "FR", "keywords": ["topgun", "biganos"]},

    # Belgium
    "karting-eupen": {"name": "Karting Eupen", "country": "BE", "keywords": ["eupen"]},
    "karting-genk": {"name": "Karting Genk", "country": "BE", "keywords": ["genk"]},

    # UK — confirmed working
    "larkhall-circuit": {"name": "Larkhall Kart Circuit", "country": "GB", "keywords": ["larkhall"]},
    "shenington": {"name": "Shenington Kart Racing Club", "country": "GB", "keywords": ["shenington"]},
    "whiltonmill": {"name": "Whilton Mill", "country": "GB", "keywords": ["whilton"]},
    "hkrc": {"name": "Kimbolton Kart Club HKRC", "country": "GB", "keywords": ["kimbolton", "hkrc"]},

    # Italy — confirmed working
    "pista-azzurra": {"name": "Pista Azzurra", "country": "IT", "keywords": ["azzurra", "jesolo"]},
    "adria-karting": {"name": "Adria Karting Raceway", "country": "IT", "keywords": ["adria"]},
    "cremona-circuit": {"name": "Cremona Circuit", "country": "IT", "keywords": ["cremona"]},
    "southgardakarting": {"name": "South Garda Karting", "country": "IT", "keywords": ["south garda", "lonato"]},
    "franciacorta-karting-track": {"name": "Franciacorta Karting Track", "country": "IT", "keywords": ["franciacorta", "castrezzato"]},
    "circuito-di-pomposa": {"name": "Circuito di Pomposa", "country": "IT", "keywords": ["pomposa"]},
    "circuito-siena": {"name": "Circuito di Siena", "country": "IT", "keywords": ["siena"]},
    "ultratiming": {"name": "UltraTiming (IT)", "country": "IT", "keywords": ["ultratiming"]},

    # Competition/Federation — skip during venue matching
    "wsk": {"name": "WSK", "country": "XX", "keywords": []},
    "cik-fia": {"name": "CIK-FIA", "country": "XX", "keywords": []},
    "fiakarting": {"name": "FIA Karting", "country": "XX", "keywords": []},
    "rgmmc": {"name": "RGMMC", "country": "XX", "keywords": []},
    "rgmmc2": {"name": "RGMMC 2", "country": "XX", "keywords": []},
    "korridas": {"name": "Korridas", "country": "XX", "keywords": []},
    "crmc": {"name": "CRMC", "country": "XX", "keywords": []},
    "wfr": {"name": "WFR", "country": "XX", "keywords": []},
    "karttiming": {"name": "Kart Timing", "country": "XX", "keywords": []},
    "raktrack": {"name": "Raktrack", "country": "XX", "keywords": []},
    "dutchracingseries": {"name": "Dutch Racing Series", "country": "XX", "keywords": []},
    "ffsa-karting": {"name": "FFSA Karting", "country": "XX", "keywords": []},
}

# Non-venue slug set (skip during matching)
FEDERATION_SLUGS = {
    "wsk", "cik-fia", "fiakarting", "rgmmc", "rgmmc2", "korridas",
    "crmc", "wfr", "karttiming", "raktrack", "dutchracingseries",
    "ffsa-karting", "akkmotorsportry", "steelring", "worldkarts",
    "kartodromodeviana", "karting-pinto", "hkrc",
}

# Apex Timing URL patterns to try
APEX_URL_PATTERNS = [
    "http://www.apex-timing.com/live-timing/{slug}/index.html",
    "https://www.apex-timing.com/live-timing/{slug}/index.html",
    "http://live.apex-timing.com/{slug}/",
    "https://live.apex-timing.com/{slug}/",
]


def _normalize(text: str) -> str:
    """Remove accents and lowercase."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


async def validate_slug(session: aiohttp.ClientSession, slug: str) -> dict | None:
    """
    Check if an Apex Timing slug resolves to a working live timing page.
    Returns the working URL if valid, None otherwise.
    """
    for pattern in APEX_URL_PATTERNS:
        url = pattern.format(slug=slug)
        try:
            async with session.head(
                url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status == 200:
                    content_type = resp.headers.get("Content-Type", "")
                    if "text/html" in content_type or not content_type:
                        return {
                            "slug": slug,
                            "url": str(resp.url),
                            "status": resp.status,
                        }
        except (aiohttp.ClientError, asyncio.TimeoutError):
            continue
    return None


async def validate_known_slugs(concurrency: int = 10) -> list[dict]:
    """Validate all known pre-seeded Apex slugs."""
    print(f"\n[APEX] Validating {len(KNOWN_APEX_SLUGS)} known slugs...")

    sem = asyncio.Semaphore(concurrency)
    results = []

    async with aiohttp.ClientSession(
        headers={"User-Agent": "PIP-RaceStrategy/1.0 (venue-discovery)"}
    ) as session:

        async def check(slug, info):
            async with sem:
                result = await validate_slug(session, slug)
                if result:
                    result["name"] = info["name"]
                    result["country"] = info["country"]
                    result["keywords"] = info.get("keywords", [])
                    results.append(result)
                    print(f"  ✓ {slug}")
                else:
                    print(f"  ✗ {slug}")
                await asyncio.sleep(0.1)

        tasks = [check(slug, info) for slug, info in KNOWN_APEX_SLUGS.items()]
        await asyncio.gather(*tasks)

    print(f"[APEX] Validated {len(results)}/{len(KNOWN_APEX_SLUGS)} known slugs")
    return results


def _match_score(result: dict, venue: dict) -> float:
    """
    Compute a match score between a known Apex slug result and a database venue.
    Higher = better match. Returns 0 if clearly wrong.
    """
    venue_name = _normalize(venue["name"])
    venue_city = _normalize(venue.get("city") or "")
    target_name = _normalize(result["name"])
    slug_clean = result["slug"].replace("-", "")
    venue_compact = venue_name.replace(" ", "").replace("-", "")
    keywords = [_normalize(k) for k in result.get("keywords", [])]

    score = 0.0

    # 1. Keyword match (strongest signal — manually curated)
    for kw in keywords:
        if kw in venue_name or kw in venue_city:
            score += 2.0
            break

    # 2. Slug appears in venue name or vice versa
    if slug_clean in venue_compact:
        score += 1.5
    elif venue_compact in slug_clean and len(venue_compact) > 4:
        score += 1.0

    # 3. Word overlap between target name and venue name
    target_words = set(target_name.split())
    venue_words = set(venue_name.split())
    filler = {"de", "du", "le", "la", "les", "l", "d", "des", "en", "sur", "et",
              "karting", "kart", "circuit", "piste", "the", "of", "indoor", "outdoor"}
    target_meaningful = target_words - filler
    venue_meaningful = venue_words - filler
    if target_meaningful and venue_meaningful:
        overlap = len(target_meaningful & venue_meaningful)
        total = min(len(target_meaningful), len(venue_meaningful))
        if total > 0:
            score += (overlap / total) * 1.0

    # 4. Country must match (if known)
    if result.get("country") and result["country"] not in ("XX", ""):
        venue_country = venue.get("country", "")
        if venue_country and venue_country != result["country"]:
            return 0.0  # Wrong country = no match

    return score


async def bruteforce_venues(concurrency: int = 8) -> int:
    """
    For each venue without a timing_slug, generate candidate slugs
    and validate them against Apex Timing.
    """
    venues = get_venues(unresolved_only=True)
    print(f"\n[APEX] Brute-forcing slugs for {len(venues)} unresolved venues...")

    sem = asyncio.Semaphore(concurrency)
    found_count = 0

    async with aiohttp.ClientSession(
        headers={"User-Agent": "PIP-RaceStrategy/1.0 (venue-discovery)"}
    ) as session:

        async def try_venue(venue):
            nonlocal found_count
            async with sem:
                candidates = generate_slug_candidates(
                    venue["name"], venue.get("city")
                )
                for slug in candidates[:10]:  # Try top 10 candidates
                    if len(slug) < 3:
                        continue
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
                            })
                            found_count += 1
                            print(f"  ✓ {venue['name']} -> {slug}")
                        except Exception:
                            pass  # Slug already assigned to another venue
                        return
                    await asyncio.sleep(0.12)

                return

        tasks = [try_venue(v) for v in venues]
        await asyncio.gather(*tasks)

    print(f"[APEX] Found slugs for {found_count}/{len(venues)} venues via brute force")
    return found_count


async def match_known_slugs_to_venues():
    """
    Match pre-validated known slugs to existing venues in the database
    using keyword-based + fuzzy name matching.
    """
    print("\n[APEX] Matching known slugs to database venues...")
    validated = await validate_known_slugs()

    venues = get_venues()
    matched = 0

    for result in validated:
        # Skip non-venue slugs
        if result["slug"] in FEDERATION_SLUGS:
            continue

        # Score every venue and pick the best
        best_match = None
        best_score = 0.0

        for venue in venues:
            score = _match_score(result, venue)
            if score > best_score:
                best_score = score
                best_match = venue

        if best_match and best_score >= 1.5:
            upsert_venue({
                "id": best_match["id"],
                "timing_system": "apex_timing",
                "timing_slug": result["slug"],
                "live_timing_url": result["url"],
                "timing_verified": True,
                "status": "verified",
            })
            matched += 1
            print(f"  ✓ '{result['name']}' -> '{best_match['name']}' (score={best_score:.1f}, slug={result['slug']})")
        elif best_score > 0:
            # Low confidence match — insert as new venue instead of risking a mismatch
            upsert_venue({
                "name": result["name"],
                "country": result.get("country", "FR"),
                "timing_system": "apex_timing",
                "timing_slug": result["slug"],
                "live_timing_url": result["url"],
                "timing_verified": True,
                "status": "verified",
                "source": "apex_dork",
            })
            print(f"  + New venue: {result['name']} ({result['slug']}) [low match score={best_score:.1f}]")
        else:
            upsert_venue({
                "name": result["name"],
                "country": result.get("country", "FR"),
                "timing_system": "apex_timing",
                "timing_slug": result["slug"],
                "live_timing_url": result["url"],
                "timing_verified": True,
                "status": "verified",
                "source": "apex_dork",
            })
            print(f"  + New venue: {result['name']} ({result['slug']})")

    print(f"[APEX] Matched {matched} known slugs to existing venues")


# ---------------------------------------------------------------------------
# iframe discovery — scrape track websites for embedded Apex Timing URLs
# ---------------------------------------------------------------------------

async def discover_iframe_slugs(concurrency: int = 5) -> int:
    """
    For each venue with a website_url but no timing_slug,
    fetch the website and search for embedded Apex Timing iframes or links.
    """
    conn = get_connection()
    venues = [
        dict(r) for r in conn.execute(
            "SELECT * FROM venues WHERE website_url IS NOT NULL "
            "AND timing_slug IS NULL AND website_url LIKE 'http%'"
        ).fetchall()
    ]
    conn.close()

    if not venues:
        print("\n[IFRAME] No venues with websites to scan")
        return 0

    print(f"\n[IFRAME] Scanning {len(venues)} venue websites for Apex Timing iframes...")

    sem = asyncio.Semaphore(concurrency)
    found_count = 0

    # Regex to find Apex Timing URLs in page source
    apex_pattern = re.compile(
        r'(?:apex-timing\.com|live\.apex-timing\.com)/(?:live-timing/)?([a-z0-9][a-z0-9_-]+?)(?:/|["\'\s?#])',
        re.IGNORECASE
    )

    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0 (compatible; PIP-RaceStrategy/1.0)"},
        timeout=aiohttp.ClientTimeout(total=15),
    ) as session:

        async def scan_website(venue):
            nonlocal found_count
            async with sem:
                url = venue["website_url"]
                try:
                    async with session.get(url, allow_redirects=True) as resp:
                        if resp.status != 200:
                            return
                        html = await resp.text(errors="replace")

                    # Search for Apex Timing references
                    matches = apex_pattern.findall(html)
                    if matches:
                        # Take the first valid slug
                        slug = matches[0].lower().rstrip("/")
                        if len(slug) >= 3 and slug not in ("en", "fr", "live-timing", "live"):
                            # Validate it
                            result = await validate_slug(session, slug)
                            if result:
                                upsert_venue({
                                    "id": venue["id"],
                                    "timing_system": "apex_timing",
                                    "timing_slug": slug,
                                    "live_timing_url": result["url"],
                                    "timing_verified": True,
                                    "status": "verified",
                                })
                                found_count += 1
                                print(f"  ✓ {venue['name']} -> {slug} (from {url})")
                                return

                    # Also check common subpages for live timing links
                    for subpath in ["/live-timing", "/resultats", "/classement", "/results", "/live"]:
                        try:
                            sub_url = url.rstrip("/") + subpath
                            async with session.get(sub_url, allow_redirects=True) as sub_resp:
                                if sub_resp.status == 200:
                                    sub_html = await sub_resp.text(errors="replace")
                                    sub_matches = apex_pattern.findall(sub_html)
                                    if sub_matches:
                                        slug = sub_matches[0].lower().rstrip("/")
                                        if len(slug) >= 3 and slug not in ("en", "fr", "live-timing", "live"):
                                            result = await validate_slug(session, slug)
                                            if result:
                                                upsert_venue({
                                                    "id": venue["id"],
                                                    "timing_system": "apex_timing",
                                                    "timing_slug": slug,
                                                    "live_timing_url": result["url"],
                                                    "timing_verified": True,
                                                    "status": "verified",
                                                })
                                                found_count += 1
                                                print(f"  ✓ {venue['name']} -> {slug} (from {sub_url})")
                                                return
                        except:
                            continue

                except Exception as e:
                    pass  # Silently skip failed websites

                await asyncio.sleep(0.3)

        tasks = [scan_website(v) for v in venues]
        await asyncio.gather(*tasks)

    print(f"[IFRAME] Found {found_count} slugs via iframe/link discovery")
    return found_count


async def run_apex_discovery():
    """Run the full Apex Timing slug discovery pipeline."""
    init_db()

    # Step 1: Match known slugs to existing venues
    await match_known_slugs_to_venues()

    # Step 2: iframe discovery on venue websites
    await discover_iframe_slugs()

    # Step 3: Brute-force remaining unresolved venues
    await bruteforce_venues()

    # Print summary
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) as c FROM venues").fetchone()["c"]
    verified = conn.execute(
        "SELECT COUNT(*) as c FROM venues WHERE timing_verified = 1"
    ).fetchone()["c"]
    with_slug = conn.execute(
        "SELECT COUNT(*) as c FROM venues WHERE timing_slug IS NOT NULL"
    ).fetchone()["c"]
    conn.close()

    print(f"\n[APEX] === Discovery Summary ===")
    print(f"  Total venues: {total}")
    print(f"  With Apex slug: {with_slug}")
    print(f"  Verified working: {verified}")
    if total > 0:
        print(f"  Resolution rate: {verified/total*100:.1f}%")


if __name__ == "__main__":
    asyncio.run(run_apex_discovery())
