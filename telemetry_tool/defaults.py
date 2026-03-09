"""
defaults
~~~~~~~~
Shared constants and default values used across the telemetry pipeline.

Module-specific thresholds stay in their modules (e.g., scoring/constants.py,
distance_integrity.py).  This file holds cross-cutting defaults that multiple
modules reference.
"""
from __future__ import annotations

import os


# ── Environment variable helpers ─────────────────────────────────

def env_bool(name: str, default: str = "0") -> bool:
    """Read a boolean environment variable.

    Truthy values: ``"1"``, ``"true"``, ``"yes"`` (case-insensitive).
    Everything else (including unset) is falsy.

    Usage::

        USE_PG = env_bool("USE_PG")             # default False
        DEBUG  = env_bool("TELEMETRY_DEBUG")     # default False
    """
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


# ── Pipeline defaults ─────────────────────────────────────────────
MIN_LAPS_FOR_ANALYSIS: int = 3
MIN_LAPS_FOR_CONSISTENCY: int = 4
MIN_LAPS_FOR_THEORETICAL: int = 3
DEFAULT_RESAMPLE_HZ: int = 10
DEFAULT_CORNER_MIN_ANGLE_DEG: float = 15.0
DEFAULT_GPS_FILTER_MAX_JUMP_M: float = 50.0

# ── Upload & ingest ──────────────────────────────────────────────
MAX_UPLOAD_SIZE_BYTES: int = 12 * 1024 * 1024 * 1024  # 12 GB
SUPPORTED_CSV_ENCODINGS: tuple[str, ...] = ("utf-8", "latin-1", "cp1252", "iso-8859-1")
SUPPORTED_DELIMITERS: tuple[str, ...] = (",", ";", "\t")

# ── API pagination ───────────────────────────────────────────────
DEFAULT_PAGE_SIZE: int = 25
MAX_PAGE_SIZE: int = 100
MIN_PAGE_SIZE: int = 1

# ── Scoring grade thresholds ─────────────────────────────────────
# (Primary definitions in scoring/constants.py — these are aliases
#  for code outside the scoring package that needs grade info.)
GRADE_THRESHOLDS: dict[str, float] = {
    "A+": 95.0,
    "A":  90.0,
    "A-": 85.0,
    "B+": 80.0,
    "B":  75.0,
    "B-": 70.0,
    "C+": 65.0,
    "C":  60.0,
    "C-": 55.0,
    "D":  50.0,
    "F":  0.0,
}

# ── Time formatting ──────────────────────────────────────────────
LAP_TIME_DECIMALS: int = 3  # e.g., 1:23.456
SCORE_DECIMALS: int = 2

# ── Session types ────────────────────────────────────────────────
VALID_SESSION_TYPES: tuple[str, ...] = (
    "practice",
    "qualifying",
    "race",
    "test",
    "warmup",
    "endurance",
)
