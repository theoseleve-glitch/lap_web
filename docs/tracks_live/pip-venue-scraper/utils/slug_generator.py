"""
Apex Timing slug generator — produces candidate slugs from track names.

Based on observed real-world Apex Timing slug patterns:
  - "Circuit de Bresse" -> circuitdebresse
  - "Racing Kart Cormeilles" -> rkc
  - "Karting du Laquais" -> karting-du-laquais
  - "OnlyKart Lyon" -> onlykart
  - "TopGun-Evasion" -> topgun-evasion
  - "MK Racing Cholet" -> mkracing
  - "Plein Gaz Karting 44" -> pleingazkarting44
  - "Kart Center Biscarrosse" -> kartcenter-biscarrosse
"""

import re
import unicodedata


def normalize_text(text: str) -> str:
    """Remove accents and normalize to ASCII."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def generate_slug_candidates(name: str, city: str = None) -> list[str]:
    """
    Generate candidate Apex Timing slugs from a track name.
    Returns a list of slug candidates ordered by likelihood.
    """
    candidates = []
    clean = normalize_text(name.strip())

    # Strip common parenthetical suffixes like "(Piste 1350m)" or "(ext)"
    clean_base = re.sub(r"\s*\(.*?\)\s*$", "", clean).strip()
    if not clean_base:
        clean_base = clean

    filler_words = {
        "circuit", "karting", "kart", "piste", "de", "du", "le", "la", "les",
        "l", "d", "des", "en", "sur", "et", "the", "of", "indoor", "outdoor",
        "centre", "center", "racing", "loisir", "loisirs", "parc",
        "circuito", "di", "del", "della", "il", "lo",
    }

    words = re.findall(r"[a-z0-9]+", clean_base.lower())
    meaningful = [w for w in words if w not in filler_words and len(w) > 1]
    all_lower = clean_base.lower()

    # === PATTERN 1: Hyphenated full name (most common) ===
    # "TopGun-Evasion" -> "topgun-evasion"
    slug = re.sub(r"[^a-z0-9]+", "-", all_lower).strip("-")
    slug = re.sub(r"-+", "-", slug)
    candidates.append(slug)

    # === PATTERN 2: Joined (no separator) ===
    # "Plein Gaz Karting 44" -> "pleingazkarting44"
    joined = re.sub(r"[^a-z0-9]", "", all_lower)
    candidates.append(joined)

    # === PATTERN 3: Meaningful words only, hyphenated ===
    # "Karting de Loudun" -> "loudun"
    # "Circuit de l'Enclos" -> "enclos"
    if meaningful:
        candidates.append("-".join(meaningful))
        if len(meaningful) > 1:
            candidates.append("".join(meaningful))

    # === PATTERN 4: karting-{city/key_word} (very common French pattern) ===
    # "Karting de Saintes" -> "karting-de-saintes"
    # "Karting d'Espoey" -> "karting-espoey"
    if meaningful:
        for m in meaningful[:2]:
            kc = f"karting-{m}"
            candidates.append(kc)

    # === PATTERN 5: {name}-{city} or {name}{city} ===
    if city and meaningful:
        city_clean = normalize_text(city.strip())
        city_slug = re.sub(r"[^a-z0-9]+", "-", city_clean.lower()).strip("-")
        city_joined = re.sub(r"[^a-z0-9]", "", city_clean.lower())

        # "Kart Center Biscarrosse" -> "kartcenter-biscarrosse"
        if len(meaningful) >= 1:
            base = "".join(meaningful[:2]) if len(meaningful) >= 2 else meaningful[0]
            candidates.append(f"{base}-{city_slug}")

        # Just city
        candidates.append(city_slug)
        candidates.append(f"karting-{city_slug}")

    # === PATTERN 6: First word(s) only ===
    # "OnlyKart Lyon" -> "onlykart"
    # "Bretagne Karting" -> "bretagne-karting"
    if len(meaningful) >= 1:
        candidates.append(meaningful[0])
        if len(meaningful) >= 2:
            candidates.append(f"{meaningful[0]}-{meaningful[1]}")
            candidates.append(f"{meaningful[0]}{meaningful[1]}")

    # === PATTERN 7: Acronym (3+ chars only) ===
    # "Racing Kart Cormeilles" -> "rkc"
    # "LF Karting" -> skip (too short from meaningful words)
    if len(words) >= 2:
        acronym = "".join(w[0] for w in words if w not in filler_words)
        if len(acronym) >= 3:
            candidates.append(acronym)

    # === PATTERN 8: Include filler words (some tracks keep them) ===
    # "Karting du Laquais" -> "karting-du-laquais"
    # "Circuit de Bresse" -> "circuit-de-bresse"
    if len(words) >= 2:
        with_fillers = "-".join(words)
        candidates.append(with_fillers)

    # === PATTERN 9: Prefix patterns ===
    if meaningful:
        base = meaningful[0]
        for prefix in ["karting", "circuit", "kart"]:
            candidates.append(f"{prefix}-{base}")
        if city:
            city_clean = re.sub(r"[^a-z0-9]+", "-", normalize_text(city.strip()).lower()).strip("-")
            candidates.append(f"karting-{city_clean}")

    # Deduplicate while preserving order, skip too short
    seen = set()
    unique = []
    for c in candidates:
        if c and c not in seen and len(c) >= 3:
            seen.add(c)
            unique.append(c)

    return unique
