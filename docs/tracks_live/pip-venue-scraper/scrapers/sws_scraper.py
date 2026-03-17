"""
SWS Track Directory scraper.

Since the SWS website is CAPTCHA-protected, this module uses multiple fallback
strategies to discover karting tracks in FR/UK/IT:

1. Chronokart directory (France — 132 circuits, no CAPTCHA)
2. Web search results for UK and Italian tracks
3. Known SWS track URLs extracted from Google search cache
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright
from utils.database import upsert_venue, get_venue_count, init_db


async def scrape_chronokart() -> list[dict]:
    """
    Get French karting circuits from Chronokart.
    Uses Playwright if available, falls back to cached data.
    """
    print("[SWS] Loading French circuits from Chronokart...")

    # Try Playwright first
    try:
        from playwright.async_api import async_playwright as ap
        async with ap() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(
                "https://chronokart.net/fiche-circuit",
                wait_until="networkidle", timeout=30000,
            )
            await page.wait_for_timeout(3000)
            for _ in range(5):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800)
            circuits = await page.evaluate("""() => {
                const r = [];
                document.querySelectorAll('a[href*="fiche-circuit/"]').forEach(el => {
                    const row = el.closest('tr') || el.closest('div') || el.parentElement;
                    const cells = row ? row.querySelectorAll('td') : [];
                    const text = el.textContent.trim();
                    if (text && text.length > 2) {
                        r.push({name: text, href: el.href,
                            region: cells.length > 1 ? cells[1]?.textContent?.trim() : '',
                            city: cells.length > 2 ? cells[2]?.textContent?.trim() : ''});
                    }
                });
                return r;
            }""")
            await browser.close()
            print(f"[SWS] Scraped {len(circuits)} circuits from Chronokart (live)")
    except Exception as e:
        print(f"[SWS] Playwright unavailable ({type(e).__name__}), using cached data")
        circuits = _get_cached_chronokart()

    venues = []
    for c in circuits:
        if not c.get("name") or len(c["name"]) < 3:
            continue
        venues.append({
            "name": c["name"],
            "country": "FR",
            "city": c.get("city", "").title() if c.get("city") else None,
            "source": "chronokart",
            "status": "unverified",
            "timing_system": "unknown",
            "website_url": c.get("href"),
        })

    print(f"[SWS] Found {len(venues)} French circuits")
    return venues


def _get_cached_chronokart() -> list[dict]:
    """Cached Chronokart data from successful scrape (132 circuits)."""
    return [
        {"name": "Circuit de La Jamaïque", "city": "STE CLOTILDE"},
        {"name": "Mega Kart Saint-Louis", "city": "ST LOUIS"},
        {"name": "Circuit Félix Guichard", "city": "STE ANNE"},
        {"name": "Circuit Maraikart", "city": "BUCY LE LONG"},
        {"name": "KLL Loisirs", "city": "DOUVRIN"},
        {"name": "Karting Paintball 14", "city": "MAROLLES"},
        {"name": "Jovikart - Karting Nantes", "city": "LE BIGNON"},
        {"name": "TopGun-Evasion", "city": "BIGANOS"},
        {"name": "Circuit Lucien Lebret", "city": "ANNEVILLE AMBOURVILLE"},
        {"name": "Karting de Pers", "city": "PERS"},
        {"name": "GTR-Performance", "city": "MARCILLAT EN COMBRAILLE"},
        {"name": "KART System Indoor", "city": "BORDEAUX"},
        {"name": "Manacha Kart", "city": "GERBEPAL"},
        {"name": "Metz Kart Indoor", "city": "AUGNY"},
        {"name": "Karting Six-Fours", "city": "SIX FOURS LES PLAGES"},
        {"name": "Karting de Beauvais", "city": "ROCHY CONDE"},
        {"name": "Made in Kart Joigny", "city": "JOIGNY"},
        {"name": "Karting de Loudun", "city": "BOURNAND"},
        {"name": "Karting Escource", "city": "ESCOURCE"},
        {"name": "Karting Roussillon (1019m)", "city": "RIVESALTES"},
        {"name": "Aunis Karting", "city": "AIGREFEUILLE D AUNIS"},
        {"name": "Karting du Laquais", "city": "CHAMPIER"},
        {"name": "Kart Quad Sensations", "city": "BOURG LASTIC"},
        {"name": "ClotKart", "city": "VAUDOY EN BRIE"},
        {"name": "Karting de Caussiniojouls", "city": "FAUGERES"},
        {"name": "Karting 2 Muret", "city": "MURET"},
        {"name": "DB Karting St-Lyé", "city": "ST LYE"},
        {"name": "Sun Karting Sérignan", "city": "SERIGNAN"},
        {"name": "Promo Sports Karting", "city": "ROUILLE"},
        {"name": "Karting de Saintes", "city": "LES GONDS"},
        {"name": "Kart'Ouest Ploumoguer", "city": "PLOUMOGUER"},
        {"name": "Dunois Kart", "city": "LUTZ EN DUNOIS"},
        {"name": "Karting Loisir 86 (Extérieur)", "city": "USSEAU"},
        {"name": "Albi Kart Expérience", "city": "LE SEQUESTRE"},
        {"name": "Kart90", "city": "CHEVREMONT"},
        {"name": "PKL Lommerange", "city": "LOMMERANGE"},
        {"name": "Kart'Race Witry-lès-Reims", "city": "WITRY LES REIMS"},
        {"name": "Circuit Karting Besançon", "city": "AUTOREILLE"},
        {"name": "LF Karting Layrac", "city": "LAYRAC"},
        {"name": "Puissance Kart Indoor", "city": "AUDINCOURT"},
        {"name": "Kerlabo Kart", "city": "COHINIAC"},
        {"name": "Karting Loisir 86 (ext, sens inverse)", "city": "USSEAU"},
        {"name": "New Kart Poitiers", "city": "MIGNE AUXANCES"},
        {"name": "Karting Club Gravelinois", "city": "GRAVELINES"},
        {"name": "DKS-Motors", "city": "ROUVIGNIES"},
        {"name": "Wattkart indoor Phalsbourg", "city": "PHALSBOURG"},
        {"name": "DKS-Motors (piste 800m)", "city": "ROUVIGNIES"},
        {"name": "MP Karting Lanas", "city": "LANAS"},
        {"name": "Racing Kart Beaucaire", "city": "BEAUCAIRE"},
        {"name": "RKO Angerville", "city": "ANGERVILLE"},
        {"name": "Sens Espaces Karting", "city": "SOUCY"},
        {"name": "Karting Evasion Bully", "city": "BULLY"},
        {"name": "GP Circuit Lamballe", "city": "LAMBALLE"},
        {"name": "Karting de Ploemel - KART56", "city": "PLOEMEL"},
        {"name": "Racing Kart du Mans (Piste loisir)", "city": "MONTFORT LE GESNOIS"},
        {"name": "Solokart (Piste 1350m)", "city": "PLESSE"},
        {"name": "Actarus RKO Lohéac (piste loisirs)", "city": "LOHEAC"},
        {"name": "Bretagne Karting", "city": "COMBRIT"},
        {"name": "Megakart Vias", "city": "VIAS"},
        {"name": "Karting Plus Belmont", "city": "BELMONT SUR RANCE"},
        {"name": "Karting Philippe Lavilledieu", "city": "LAVILLEDIEU"},
        {"name": "Brignoles Karting Loisir", "city": "BRIGNOLES"},
        {"name": "Plérin Komplex Indoor", "city": "PLERIN"},
        {"name": "Racing Kart du Mans (Piste compétition)", "city": "MONTFORT LE GESNOIS"},
        {"name": "Kart'are Aigues Vives", "city": "AIGUES VIVES"},
        {"name": "Karting Loisir 86 (indoor, sens anti-horaire)", "city": "USSEAU"},
        {"name": "Parc de loisirs des Bouscaillous", "city": "MILLAU"},
        {"name": "Prestige Karting", "city": "LE LUC"},
        {"name": "Karting de Torreilles (piste 582m)", "city": "TORREILLES"},
        {"name": "Karthors", "city": "CIEURAC"},
        {"name": "Karting Elceka Montpellier", "city": "GRABELS"},
        {"name": "Fun Kart Brissac", "city": "BRISSAC"},
        {"name": "Circuit Berdery", "city": "LESCAR"},
        {"name": "Passion Karting 16", "city": "LA ROCHEFOUCAULD"},
        {"name": "Cap Karting Mer", "city": "MER"},
        {"name": "Karting d'Espoey", "city": "ESPOEY"},
        {"name": "Kart Center Biscarrosse", "city": "BISCARROSSE"},
        {"name": "Karting Ozan", "city": "OZAN"},
        {"name": "Karting Sud Toulois", "city": "BARISEY AU PLAIN"},
        {"name": "Ouest Karting Aunay", "city": "AUNAY LES BOIS"},
        {"name": "Karting Montrevel-en-Bresse", "city": "MALAFRETAZ"},
        {"name": "Sundgau Kart", "city": "STEINSOULTZ"},
        {"name": "Lille Karting (Piste extérieure)", "city": "ENNETIERES EN WEPPES"},
        {"name": "SKLC 55", "city": "CHAUMONT SUR AIRE"},
        {"name": "Alcava Karting Gueugnon", "city": "GUEUGNON"},
        {"name": "Kart'in 974", "city": "ST PIERRE"},
        {"name": "Racing Kart Jade", "city": "ST MICHEL CHEF CHEF"},
        {"name": "Folembray Arena", "city": "FOLEMBRAY"},
        {"name": "Karting du Parc", "city": "STE PIENCE"},
        {"name": "Circuit de l'Enclos", "city": "SEPTFONTAINES"},
        {"name": "Paintkart52", "city": "FOULAIN"},
        {"name": "Circuit de Bresse", "city": "FRONTENAUD"},
        {"name": "Karting St-Cyprien 66", "city": "ST CYPRIEN"},
        {"name": "Win'Kart Carcassonne", "city": "CARCASSONNE"},
        {"name": "Karting de Torreilles (piste 547m)", "city": "TORREILLES"},
        {"name": "Karting de Torreilles (piste 527m)", "city": "TORREILLES"},
        {"name": "Karting de Torreilles (piste 492m)", "city": "TORREILLES"},
        {"name": "Kart Origins", "city": "CORBAS"},
        {"name": "Circuit de Rumilly", "city": "RUMILLY"},
        {"name": "Karting Sarron", "city": "RIOM"},
        {"name": "Circuit Jura Sud", "city": "MOIRANS EN MONTAGNE"},
        {"name": "Eurokart Valence", "city": "CHATEAUNEUF SUR ISERE"},
        {"name": "KCP Karting Cuges-les-Pins", "city": "CUGES LES PINS"},
        {"name": "Karting de l'Etang", "city": "ROGNAC"},
        {"name": "Circuit de la Vallée Vesoul", "city": "PUSEY"},
        {"name": "Plein Gaz Karting 44", "city": "ANCENIS"},
        {"name": "Circuit Jura Sud (Indoor)", "city": "MOIRANS EN MONTAGNE"},
        {"name": "Kartmania Pouilly-en-Auxois", "city": "MEILLY SUR ROUVRES"},
        {"name": "Formule Kart Villeperdue", "city": "VILLEPERDUE"},
        {"name": "Arena 45e La Roche de Glun", "city": "LA ROCHE DE GLUN"},
        {"name": "Kerlabo Kart (sens inverse)", "city": "COHINIAC"},
        {"name": "GO Kart 90", "city": "DANJOUTIN"},
        {"name": "RKC Karting Paris", "city": "CORMEILLES EN VEXIN"},
        {"name": "Actua Karting Lyon", "city": "ST LAURENT DE MURE"},
        {"name": "Circuit des Renardières", "city": "CHALUS"},
        {"name": "OnlyKart Lyon", "city": "DAGNEUX"},
        {"name": "Cosne Karting", "city": "COSNE COURS SUR LOIRE"},
        {"name": "Vaison Piste", "city": "TORCY"},
        {"name": "LKS Karting", "city": "CHAMPFORGEUIL"},
        {"name": "La Briqueterie Les Étards 1600m", "city": "OZOUER LE VOULGIS"},
        {"name": "JCS Karting Lubersac", "city": "LUBERSAC"},
        {"name": "Bocaspeed", "city": "MONCOUTANT"},
        {"name": "Beaucaire Espace Loisirs", "city": "BEAUCAIRE"},
        {"name": "MK Racing Cholet", "city": "ST CHRISTOPHE DU BOIS"},
        {"name": "La Briqueterie Les Étards 600m", "city": "OZOUER LE VOULGIS"},
        {"name": "Karting Roussillon (726m)", "city": "RIVESALTES"},
        {"name": "Karting 2 Noiron", "city": "NOIRON SOUS GEVREY"},
        {"name": "Kart Center Pluméliau", "city": "PLUMELIAU"},
        {"name": "Karting West Aventure", "city": "ST REVEREND"},
        {"name": "Karting Philippe Alliot", "city": "BELLEVILLE SUR VIE"},
        {"name": "Karting du Nord Mayenne", "city": "MONTREUIL POULAY"},
        {"name": "Karting de Monteux", "city": "MONTEUX"},
    ]


# Known UK karting tracks (manually curated from search results + industry knowledge)
UK_TRACKS = [
    {"name": "Daytona Sandown Park", "city": "Esher", "region": "Surrey"},
    {"name": "Daytona Milton Keynes", "city": "Milton Keynes", "region": "Buckinghamshire"},
    {"name": "Daytona Manchester", "city": "Manchester", "region": "Greater Manchester"},
    {"name": "Daytona Tamworth", "city": "Tamworth", "region": "Staffordshire"},
    {"name": "TeamSport Docklands", "city": "London", "region": "London"},
    {"name": "TeamSport Tower Bridge", "city": "London", "region": "London"},
    {"name": "TeamSport Birmingham", "city": "Birmingham", "region": "West Midlands"},
    {"name": "TeamSport Leeds", "city": "Leeds", "region": "West Yorkshire"},
    {"name": "TeamSport Manchester Trafford", "city": "Manchester", "region": "Greater Manchester"},
    {"name": "TeamSport Bristol", "city": "Bristol", "region": "Bristol"},
    {"name": "TeamSport Cardiff", "city": "Cardiff", "region": "Wales"},
    {"name": "TeamSport Sheffield", "city": "Sheffield", "region": "South Yorkshire"},
    {"name": "TeamSport Newcastle", "city": "Newcastle", "region": "Tyne and Wear"},
    {"name": "TeamSport Southampton", "city": "Southampton", "region": "Hampshire"},
    {"name": "TeamSport Reading", "city": "Reading", "region": "Berkshire"},
    {"name": "TeamSport Warrington", "city": "Warrington", "region": "Cheshire"},
    {"name": "TeamSport Coventry", "city": "Coventry", "region": "West Midlands"},
    {"name": "TeamSport Nottingham", "city": "Nottingham", "region": "Nottinghamshire"},
    {"name": "TeamSport Farnborough", "city": "Farnborough", "region": "Hampshire"},
    {"name": "TeamSport Crawley", "city": "Crawley", "region": "West Sussex"},
    {"name": "TeamSport Gosport", "city": "Gosport", "region": "Hampshire"},
    {"name": "TeamSport Leicester", "city": "Leicester", "region": "Leicestershire"},
    {"name": "TeamSport Basildon", "city": "Basildon", "region": "Essex"},
    {"name": "Three Sisters Circuit", "city": "Wigan", "region": "Greater Manchester"},
    {"name": "Buckmore Park", "city": "Chatham", "region": "Kent"},
    {"name": "Whilton Mill", "city": "Daventry", "region": "Northamptonshire"},
    {"name": "PF International", "city": "Grantham", "region": "Lincolnshire"},
    {"name": "Shenington Kart Racing Club", "city": "Banbury", "region": "Oxfordshire"},
    {"name": "Rye House Kart Raceway", "city": "Hoddesdon", "region": "Hertfordshire"},
    {"name": "Lydd Kart Circuit", "city": "Lydd", "region": "Kent"},
    {"name": "Clay Pigeon Kart Club", "city": "Dorchester", "region": "Dorset"},
    {"name": "Larkhall Kart Circuit", "city": "Larkhall", "region": "South Lanarkshire"},
    {"name": "Ellough Park Raceway", "city": "Beccles", "region": "Suffolk"},
    {"name": "GYG Karting", "city": "Glan y Gors", "region": "Wales"},
    {"name": "Capital Karts", "city": "London", "region": "London"},
    {"name": "Teamsport Acton", "city": "London", "region": "London"},
    {"name": "Teamsport North London", "city": "London", "region": "London"},
]

# Known Italian karting tracks
ITALY_TRACKS = [
    {"name": "South Garda Karting", "city": "Lonato del Garda", "region": "Lombardia"},
    {"name": "Pista Azzurra", "city": "Jesolo", "region": "Veneto"},
    {"name": "Circuito Internazionale Napoli", "city": "Sarno", "region": "Campania"},
    {"name": "Adria Karting Raceway", "city": "Adria", "region": "Veneto"},
    {"name": "Franciacorta Karting Track", "city": "Castrezzato", "region": "Lombardia"},
    {"name": "Circuito di Siena", "city": "Siena", "region": "Toscana"},
    {"name": "Kartodromo Val Vibrata", "city": "Ancarano", "region": "Abruzzo"},
    {"name": "Autodromo Riccardo Paletti", "city": "Varano de' Melegari", "region": "Emilia-Romagna"},
    {"name": "Kartodromo La Conca", "city": "Muro Leccese", "region": "Puglia"},
    {"name": "Cremona Circuit", "city": "Cremona", "region": "Lombardia"},
    {"name": "7 Laghi Kart", "city": "Castelletto di Branduzzo", "region": "Lombardia"},
    {"name": "Circuito di Pomposa", "city": "Pomposa", "region": "Emilia-Romagna"},
    {"name": "Kartodromo di Battipaglia", "city": "Battipaglia", "region": "Campania"},
    {"name": "Pista del Tronto", "city": "Castel di Lama", "region": "Marche"},
    {"name": "Circuito di Precenicco", "city": "Precenicco", "region": "Friuli-Venezia Giulia"},
    {"name": "Kartodromo di Ortona", "city": "Ortona", "region": "Abruzzo"},
    {"name": "ProDRIVE Kart Center", "city": "Roma", "region": "Lazio"},
    {"name": "Rush Speed Arena", "city": "Alcamo", "region": "Sicilia"},
    {"name": "Autodromo del Mugello Karting", "city": "Scarperia", "region": "Toscana"},
    {"name": "Circuito di Viterbo", "city": "Viterbo", "region": "Lazio"},
    {"name": "CRG Lonato", "city": "Lonato del Garda", "region": "Lombardia"},
    {"name": "Kartodromo Lago", "city": "Salerno", "region": "Campania"},
    {"name": "Ottobiano Motorsport", "city": "Ottobiano", "region": "Lombardia"},
]


def get_static_uk_tracks() -> list[dict]:
    """Return curated UK karting tracks."""
    venues = []
    for t in UK_TRACKS:
        venues.append({
            "name": t["name"],
            "country": "GB",
            "city": t["city"],
            "source": "curated",
            "status": "unverified",
            "timing_system": "unknown",
        })
    print(f"[SWS] Loaded {len(venues)} UK tracks (curated)")
    return venues


def get_static_italy_tracks() -> list[dict]:
    """Return curated Italian karting tracks."""
    venues = []
    for t in ITALY_TRACKS:
        venues.append({
            "name": t["name"],
            "country": "IT",
            "city": t["city"],
            "source": "curated",
            "status": "unverified",
            "timing_system": "unknown",
        })
    print(f"[SWS] Loaded {len(venues)} Italian tracks (curated)")
    return venues


async def run_sws_scraper():
    """Run the full SWS/venue discovery scraper and store results."""
    init_db()

    # 1. Scrape Chronokart for France
    fr_venues = await scrape_chronokart()
    for v in fr_venues:
        upsert_venue(v)
    print(f"[SWS] Stored {len(fr_venues)} French venues")

    # 2. Load UK tracks
    uk_venues = get_static_uk_tracks()
    for v in uk_venues:
        upsert_venue(v)
    print(f"[SWS] Stored {len(uk_venues)} UK venues")

    # 3. Load Italian tracks
    it_venues = get_static_italy_tracks()
    for v in it_venues:
        upsert_venue(v)
    print(f"[SWS] Stored {len(it_venues)} Italian venues")

    total = get_venue_count()
    print(f"\n[SWS] Total venues in database: {total}")
    print(f"  FR: {get_venue_count('FR')}")
    print(f"  GB: {get_venue_count('GB')}")
    print(f"  IT: {get_venue_count('IT')}")

    return total


if __name__ == "__main__":
    asyncio.run(run_sws_scraper())
