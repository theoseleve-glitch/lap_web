"""Lightweight i18n for race strategy pages."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_I18N_DIR = Path(__file__).parent
_CACHE: dict[str, dict] = {}
SUPPORTED_LANGUAGES = ["en", "fr", "it", "de", "es", "pt", "zh"]


def load_translations(lang: str) -> dict:
    """Load translations for a language, falling back to English for missing keys."""
    if lang not in SUPPORTED_LANGUAGES:
        lang = "en"

    if lang in _CACHE:
        return _CACHE[lang]

    # Always load English as base
    en_path = _I18N_DIR / "en.json"
    try:
        en = json.loads(en_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        en = {}

    if lang == "en":
        _CACHE["en"] = en
        return en

    # Load target language and merge with English fallback
    lang_path = _I18N_DIR / f"{lang}.json"
    try:
        translations = json.loads(lang_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("Translation file %s not found, falling back to English", lang_path)
        translations = {}

    merged = {**en, **translations}
    _CACHE[lang] = merged
    return merged
