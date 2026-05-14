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


# ── Factor 3: Wind exposure ───────────────────────────────────────────


# Spec §7 Factor 3 zone boundaries (in degrees) + wind-speed thresholds
# (km/h) + factors. Zones: angle from wind-FROM direction to segment
# tangent (direction of travel).
_WIND_ZONE_WINDWARD_DEG: float = 60.0   # angle < 60° → windward
_WIND_ZONE_LEEWARD_DEG: float = 120.0   # angle > 120° → leeward
_WIND_SPEED_HIGH_KMH: float = 15.0      # > 15 = high
_WIND_SPEED_WEAK_KMH: float = 5.0       # < 5 = weak

_WIND_FACTOR_WINDWARD_HIGH: float = 0.85
_WIND_FACTOR_WINDWARD_MODERATE: float = 0.95
_WIND_FACTOR_NEUTRAL: float = 1.00
_WIND_FACTOR_LEEWARD: float = 1.10
_WIND_FACTOR_LEEWARD_WEAK: float = 1.15

# FP boundary tolerance: arccos(±0.5) in numpy float64 gives
# 60.00000000000001° / 120.00000000000001° (both ε above the
# exact boundary). Bucket inclusion at the boundary per spec
# semantics: windward INCLUSIVE at 60°, leeward EXCLUSIVE at 120°
# (boundary stays perpendicular).
_WIND_BOUNDARY_TOL_DEG: float = 1e-6


def wind_factor(
    wind_direction_deg: float,
    wind_speed_kmh: float,
    segment_tangents: np.ndarray,
) -> np.ndarray:
    """Spec §7 Factor 3 — per-segment wind-exposure factor.

    Args:
        wind_direction_deg: compass-FROM degrees per Open-Meteo
            (0°=N wind FROM north, 90°=E, etc.).
        wind_speed_kmh: wind speed (km/h).
        segment_tangents: shape (N_s, 3) tangent vectors per s-bin in
            ENU frame (direction of travel). Z-component is dropped;
            wind is horizontal.

    Returns:
        Per-segment factor in {0.85, 0.95, 1.00, 1.10, 1.15}.

    Lookup:
        angle = arccos(dot(t_xy_unit, wind_from_xy)) ∈ [0°, 180°]
        windward (angle < 60°):
            wind > 15 km/h → 0.85; 5 ≤ wind ≤ 15 → 0.95; wind < 5 → 1.00
        perpendicular (60° ≤ angle ≤ 120°): 1.00 (any wind speed)
        leeward (angle > 120°):
            wind < 5 → 1.15; wind ≥ 5 → 1.10

    Grounding: Penman evaporation includes wind-speed term
    ``f(u) = a + b·u``; iRacing dynamic-water uses identical
    per-segment wind reasoning.
    """
    segment_tangents = np.asarray(segment_tangents, dtype=np.float64)
    # Horizontal projection (drop z) + renormalize
    t_xy = segment_tangents[:, :2]
    norms = np.linalg.norm(t_xy, axis=1, keepdims=True)
    norms = np.where(norms < 1e-9, 1.0, norms)
    t_xy_unit = t_xy / norms

    # Wind-FROM unit vector in ENU XY (compass convention 0=N → (0, 1))
    wind_rad = np.deg2rad(wind_direction_deg)
    wind_from_xy = np.array([np.sin(wind_rad), np.cos(wind_rad)])

    # Per-segment angle in degrees ∈ [0, 180]
    cos_theta = np.clip(t_xy_unit @ wind_from_xy, -1.0, 1.0)
    angle_deg = np.rad2deg(np.arccos(cos_theta))

    n = len(angle_deg)
    factors = np.full(n, _WIND_FACTOR_NEUTRAL, dtype=np.float64)

    windward_mask = angle_deg < _WIND_ZONE_WINDWARD_DEG + _WIND_BOUNDARY_TOL_DEG
    leeward_mask = angle_deg > _WIND_ZONE_LEEWARD_DEG + _WIND_BOUNDARY_TOL_DEG
    # Perpendicular zone stays at neutral default.

    # Windward bucket depends on overall wind speed.
    if wind_speed_kmh > _WIND_SPEED_HIGH_KMH:
        factors[windward_mask] = _WIND_FACTOR_WINDWARD_HIGH
    elif wind_speed_kmh >= _WIND_SPEED_WEAK_KMH:
        factors[windward_mask] = _WIND_FACTOR_WINDWARD_MODERATE
    # else weak wind → windward stays at neutral (1.00)

    # Leeward bucket.
    if wind_speed_kmh < _WIND_SPEED_WEAK_KMH:
        factors[leeward_mask] = _WIND_FACTOR_LEEWARD_WEAK
    else:
        factors[leeward_mask] = _WIND_FACTOR_LEEWARD

    return factors


# ── Combined factor + condition-aware clamping ────────────────────────


# Spec §7 combined formula clamps. Dry conditions: variance muted to
# [0.9, 1.1] (still some sunny-vs-shaded effect on track temp, but
# nothing dramatic). Wet/damp/greasy: full [0.6, 1.5] range — this is
# where the spatial grip-map story matters most.
_DRY_CLAMP_LOW: float = 0.9
_DRY_CLAMP_HIGH: float = 1.1
_WET_CLAMP_LOW: float = 0.6
_WET_CLAMP_HIGH: float = 1.5

_VALID_CONDITION_LABELS = frozenset({"dry", "damp", "wet", "greasy"})


def compute_spatial_factor(
    drainage: np.ndarray,
    sun: np.ndarray,
    wind: np.ndarray,
    condition_label: str,
) -> np.ndarray:
    """Spec §7 combined per-segment spatial μ multiplier.

    Args:
        drainage: per-segment Factor 1 (drainage), shape (N_s,).
        sun: per-segment Factor 2 (sun exposure), shape (N_s,).
        wind: per-segment Factor 3 (wind exposure), shape (N_s,).
        condition_label: one of {dry, damp, wet, greasy} from
            :class:`WeatherCondition.label`. Determines clamp range:
              dry         → [0.9, 1.1] (tight)
              damp/wet/greasy → [0.6, 1.5] (full spatial story)

    Returns:
        Per-segment mu_spatial_factor in the chosen clamp range.

    Formula (spec §7):
        mu_spatial_factor(s) = 1.0 / (drainage(s) · sun(s) · wind(s))
        mu_spatial_factor(s) = clamp(mu_spatial_factor(s), lower, upper)

    Inversion: factor > 1 means "wetter section" (drains less, sun-shaded,
    leeward). We want the effective μ multiplier lower on wetter
    sections → divide by the product.
    """
    if condition_label not in _VALID_CONDITION_LABELS:
        raise ValueError(
            f"condition_label {condition_label!r} not in {sorted(_VALID_CONDITION_LABELS)}"
        )
    drainage = np.asarray(drainage, dtype=np.float64)
    sun = np.asarray(sun, dtype=np.float64)
    wind = np.asarray(wind, dtype=np.float64)

    product = drainage * sun * wind
    factor = 1.0 / product

    if condition_label == "dry":
        return np.clip(factor, _DRY_CLAMP_LOW, _DRY_CLAMP_HIGH)
    return np.clip(factor, _WET_CLAMP_LOW, _WET_CLAMP_HIGH)
