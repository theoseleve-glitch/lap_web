"""Day-12 — per-segment spatial μ modifier factors.

Spec ``LAP_V1_CONDITIONS_ENGINE_SPEC.md`` §7. Three independent factors
multiplied per segment to produce a wetness multiplier; final spatial
factor inverts the product (factors > 1 = wetter section → lower
effective μ → divide).

Pure functions. No I/O. Each factor returns a numpy array of the same
shape as its primary input.

Coordinate convention for sun + wind:
    ENU (east-north-up) local frame. The mesh projection produces XY
    with +X = east, +Y = north (equirectangular about lat/lon origin).
    Solar azimuth degrees CW from north (pvlib convention); elevation
    above horizon (pvlib ``apparent_elevation``).
"""
from __future__ import annotations

import logging
from datetime import datetime

import numpy as np

logger = logging.getLogger(__name__)


# ── Factor 1: Drainage ────────────────────────────────────────────────


# Spec §7 Factor 1 lookup (treats slope as absolute; signed climb/descent
# drain identically). Boundary inclusion: higher-slope bucket wins.
_DRAINAGE_BOUNDARIES_PCT = (0.5, 2.0, 5.0)
_DRAINAGE_FACTORS = (1.30, 1.10, 1.00, 0.85)


def drainage_factor(slope_pct: np.ndarray) -> np.ndarray:
    """Spec §7 Factor 1 — drainage from local longitudinal slope.

    Args:
        slope_pct: per-segment slope in percent (`dz/ds × 100`).
            Sign-agnostic: |slope| used; descent drains same as climb.

    Returns:
        Per-segment factor in ``{0.85, 1.00, 1.10, 1.30}``.

    Spec table (treating slope as absolute):
        |slope| < 0.5%   → 1.30 (flat: water pools)
        0.5% ≤ |s| < 2%  → 1.10 (mild: slow drainage)
        2%   ≤ |s| < 5%  → 1.00 (good: neutral)
        |slope| ≥ 5%     → 0.85 (steep: drains fast, dries first)

    Boundary convention: at boundary values (0.5%, 2.0%, 5.0%) the
    higher-slope bucket applies (lower factor — more drainage).
    Grounding: AASHTO Drainage Manual identifies < 0.5% grade as the
    threshold for ponding risk on asphalt.
    """
    abs_slope = np.abs(np.asarray(slope_pct, dtype=np.float64))
    # Bucket index 0..3 via right-edge inclusive boundaries.
    # np.digitize with right=False returns indices of buckets such that
    # bins[i-1] <= x < bins[i]. For boundary inclusion at top, use
    # right=True: bins[i-1] < x <= bins[i]. We want at 0.5% to map to
    # bucket 1 (mild), so we want strictly-less-than for upper edges:
    # use right=False, which gives < behavior, then take the result
    # directly as bucket index.
    bucket = np.digitize(abs_slope, _DRAINAGE_BOUNDARIES_PCT, right=False)
    # Validate: bucket ∈ [0, 3]
    factors = np.array(_DRAINAGE_FACTORS, dtype=np.float64)
    return factors[bucket]


# ── Factor 2: Sun exposure ────────────────────────────────────────────


# Spec §7 Factor 2 alignment thresholds + factors.
_SUN_ALIGN_FULL: float = 0.7
_SUN_ALIGN_PARTIAL: float = 0.3
_SUN_FACTOR_FULL: float = 0.85
_SUN_FACTOR_PARTIAL: float = 0.95
_SUN_FACTOR_SHADED: float = 1.15
_SUN_LOW_ALTITUDE_DEG: float = 10.0
_SUN_LOW_ALTITUDE_MODIFIER: float = 1.10


def sun_vector_enu(
    when: datetime,
    lat: float,
    lon: float,
    *,
    return_az_el: bool = False,
):
    """Unit vector pointing TO the sun in ENU local frame at (lat, lon, when).

    Uses pvlib for solar geometry (NREL-maintained Python library).
    Returned vector convention:
        x = cos(elevation) · sin(azimuth)    # east
        y = cos(elevation) · cos(azimuth)    # north
        z = sin(elevation)                    # up

    Args:
        when: UTC datetime (must be timezone-aware).
        lat, lon: WGS84 location degrees.
        return_az_el: If True, return ``(az_deg, el_deg)`` instead of
            the unit vector — used by tests for setup verification.

    Returns:
        np.ndarray shape (3,) — unit vector to the sun, OR
        tuple ``(az_deg, el_deg)`` if ``return_az_el=True``.
    """
    # Import pvlib lazily — keeps the module import fast for callers that
    # don't need solar geometry.
    import pandas as pd
    import pvlib

    loc = pvlib.location.Location(lat, lon, tz="UTC")
    sp = loc.get_solarposition(pd.DatetimeIndex([when]))
    az_deg = float(sp["azimuth"].iloc[0])
    el_deg = float(sp["apparent_elevation"].iloc[0])
    if return_az_el:
        return az_deg, el_deg

    az_rad = np.deg2rad(az_deg)
    el_rad = np.deg2rad(el_deg)
    return np.array([
        np.cos(el_rad) * np.sin(az_rad),
        np.cos(el_rad) * np.cos(az_rad),
        np.sin(el_rad),
    ])


def sun_factor(
    when: datetime,
    lat: float,
    lon: float,
    segment_normals: np.ndarray,
) -> np.ndarray:
    """Spec §7 Factor 2 — per-segment sun-exposure factor.

    Args:
        when: UTC datetime (timezone-aware) at session start.
        lat, lon: WGS84 location degrees.
        segment_normals: shape (N_s, 3) unit normals per s-bin in ENU
            frame. Track substrate produces these from the centerline
            heading + slope.

    Returns:
        Per-segment factor shape (N_s,). Bucket values:
            full sun (alignment > 0.7) → 0.85
            partial (0.3 ≤ a ≤ 0.7)    → 0.95
            shaded (alignment < 0.3)   → 1.15
        Multiplied by 1.10 when sun elevation < 10°. When sun is below
        horizon, returns 1.15 everywhere (nighttime).

    Grounding: TRB pavement-temperature studies show surface heating
    scales linearly with cos(solar_zenith_angle) × (1 − albedo).
    Terrain shadowing via ray-trace deferred to V1.5 (spec §11).
    """
    segment_normals = np.asarray(segment_normals, dtype=np.float64)
    n = segment_normals.shape[0]

    # Solar geometry
    az_deg, el_deg = sun_vector_enu(when, lat, lon, return_az_el=True)

    # Nighttime → all shaded.
    if el_deg < 0:
        logger.warning(
            "Sun below horizon (el=%.2f°) at %s; treating all segments as shaded",
            el_deg, when.isoformat(),
        )
        return np.full(n, _SUN_FACTOR_SHADED, dtype=np.float64)

    az_rad = np.deg2rad(az_deg)
    el_rad = np.deg2rad(el_deg)
    sun_vec = np.array([
        np.cos(el_rad) * np.sin(az_rad),
        np.cos(el_rad) * np.cos(az_rad),
        np.sin(el_rad),
    ])

    # Per-segment alignment = dot(normal, sun_vec). Both are unit vectors;
    # result is cos(angle) ∈ [-1, 1].
    alignments = segment_normals @ sun_vec

    # Bucket factor by alignment.
    factors = np.full(n, _SUN_FACTOR_PARTIAL, dtype=np.float64)
    factors[alignments > _SUN_ALIGN_FULL] = _SUN_FACTOR_FULL
    factors[alignments < _SUN_ALIGN_PARTIAL] = _SUN_FACTOR_SHADED

    # Low-sun modifier
    if el_deg < _SUN_LOW_ALTITUDE_DEG:
        factors *= _SUN_LOW_ALTITUDE_MODIFIER

    return factors
