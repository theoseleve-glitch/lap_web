"""
columns.py
----------
Canonical column names for the kart_envelope pipeline and the
RaceChrono-raw → canonical mapping with ``*calc`` preference.
"""
from __future__ import annotations

import logging
import re
from typing import Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_G: Final[float] = 9.80665  # m/s²

# ---------------------------------------------------------------------------
# Canonical internal column names
# ---------------------------------------------------------------------------
COL_TIME: Final[str] = "time_s"
COL_SPEED: Final[str] = "speed_mps"
COL_DIST: Final[str] = "distance_m"
COL_LAP: Final[str] = "lap_number"
COL_LAT: Final[str] = "lat_deg"
COL_LON: Final[str] = "lon_deg"
COL_X: Final[str] = "x_m"
COL_Y: Final[str] = "y_m"
COL_ACCEL_LONG: Final[str] = "accel_long_mps2"
COL_ACCEL_LAT: Final[str] = "accel_lat_mps2"
COL_YAW_RATE: Final[str] = "yaw_rate_dps"
COL_HEADING: Final[str] = "heading_deg"
COL_ALTITUDE: Final[str] = "altitude_m"
COL_SATELLITES: Final[str] = "satellites"
COL_ACCURACY: Final[str] = "accuracy_m"

# ---------------------------------------------------------------------------
# Ordered mapping: RaceChrono raw name → (canonical name, needs_G_conversion)
# *calc variants appear BEFORE their non-*calc counterparts so the first
# match wins when both columns are present.
# ---------------------------------------------------------------------------
_RAW_MAP: list[tuple[str, str, bool]] = [
    ("Time (s)",                              COL_TIME,       False),
    ("Speed (m/s) *calc",                     COL_SPEED,      False),
    ("Speed (m/s)",                           COL_SPEED,      False),
    ("Distance (m)",                          COL_DIST,       False),
    ("Lap #",                                 COL_LAP,        False),
    ("Latitude (deg)",                        COL_LAT,        False),
    ("Longitude (deg)",                       COL_LON,        False),
    ("X-position (m)",                        COL_X,          False),
    ("X (m)",                                 COL_X,          False),
    ("Y-position (m)",                        COL_Y,          False),
    ("Y (m)",                                 COL_Y,          False),
    ("Longitudinal acceleration (G) *calc",   COL_ACCEL_LONG, True),
    ("Longitudinal acceleration (G)",         COL_ACCEL_LONG, True),
    ("Lateral acceleration (G) *calc",        COL_ACCEL_LAT,  True),
    ("Lateral acceleration (G)",              COL_ACCEL_LAT,  True),
    ("Yaw rate (deg/s)",                      COL_YAW_RATE,   False),
    ("Bearing (deg)",                         COL_HEADING,     False),
    ("Altitude (m)",                          COL_ALTITUDE,    False),
    ("Satellites (sats)",                     COL_SATELLITES,  False),
    ("Satellites",                            COL_SATELLITES,  False),
    ("Accuracy (m)",                          COL_ACCURACY,    False),
]

# Quick look-up: raw_name → canonical
RAW_TO_CANONICAL: dict[str, str] = {raw: canon for raw, canon, _ in _RAW_MAP}

# Columns that store G-force values needing *9.80665 → m/s²
_G_SOURCES: frozenset[str] = frozenset(raw for raw, _, g in _RAW_MAP if g)

# Minimal columns required after normalisation
REQUIRED_COLUMNS: frozenset[str] = frozenset({COL_TIME, COL_SPEED, COL_DIST, COL_LAP})

# Reverse mapping: canonical → first raw name (for bridging to telemetry_tool)
CANONICAL_TO_RAW: dict[str, str] = {}
for _raw, _canon, _ in _RAW_MAP:
    if _canon not in CANONICAL_TO_RAW:
        CANONICAL_TO_RAW[_canon] = _raw

# Suffix pattern that pandas appends to duplicate column names
_DUP_SUFFIX_RE = re.compile(r"\.\d+$")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Apply ``*calc`` preference, rename to canonical names, convert G → m/s².

    The function never mutates the input DataFrame.

    Steps
    -----
    1. Strip pandas duplicate suffixes (.1, .2 …) — keep the *first* occurrence.
    2. For each canonical target, find the first matching raw column
       (``*calc`` variants are listed first so they win).
    3. Rename matched columns; drop unmatched duplicates.
    4. Convert G-unit columns to m/s².

    Returns
    -------
    pd.DataFrame
        Copy with canonical column names.  Columns that do not map to any
        canonical name are kept as-is (may be useful downstream).
    """
    out = df.copy()

    # Step 1 — de-duplicate: keep original, drop .N copies
    seen: set[str] = set()
    keep_cols: list[str] = []
    for c in out.columns:
        base = _DUP_SUFFIX_RE.sub("", c)
        if base not in seen:
            seen.add(base)
            keep_cols.append(c)
        else:
            logger.debug("Dropping duplicate column %r (keeping %r)", c, base)
    out = out[keep_cols]
    # rename .N suffix cols to their base names
    rename_dup = {c: _DUP_SUFFIX_RE.sub("", c) for c in keep_cols
                  if _DUP_SUFFIX_RE.search(c)}
    if rename_dup:
        out = out.rename(columns=rename_dup)

    # Step 2 — build rename map (first match per canonical target wins)
    # Also skip if the canonical name already exists (e.g. from derived_channels)
    rename_map: dict[str, str] = {}
    g_convert: list[str] = []
    drop_raw: list[str] = []  # raw columns to drop when canonical already exists
    claimed: set[str] = set(out.columns)  # pre-claim existing canonical names

    for raw_name, canon, is_g in _RAW_MAP:
        if canon in claimed:
            # Canonical column already exists; drop the raw column to avoid
            # duplicates when bridging back to raw names.
            if raw_name in out.columns and raw_name != canon:
                drop_raw.append(raw_name)
            continue
        if raw_name in out.columns:
            rename_map[raw_name] = canon
            claimed.add(canon)
            if is_g:
                g_convert.append(canon)

    # Drop raw columns whose canonical equivalent already exists
    if drop_raw:
        out = out.drop(columns=drop_raw, errors="ignore")

    # Step 3 — rename
    out = out.rename(columns=rename_map)

    # Step 4 — G → m/s²
    for col in g_convert:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce") * _G

    # Validate required columns
    missing = REQUIRED_COLUMNS - set(out.columns)
    if missing:
        logger.warning("Normalised DataFrame missing required columns: %s", missing)

    return out
