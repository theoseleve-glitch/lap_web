"""Day-12 — SpatialMuModifier producer.

Consumes:
    - Session ``WeatherCondition`` (Day-11; supplies wind direction/speed
      from ``raw_inputs.winddirection_10m`` + ``P8``, and ``label`` for
      clamp selection).
    - Session :class:`track_surface.model.TrackSurface` (supplies
      per-bin slope_pct + FrenetFrame heading_rad + boundary_source).
    - Session ``SessionInputs.started_at_utc`` + track centroid → solar
      geometry via pvlib.

Produces:
    :class:`SpatialMuModifier` per spec §8 schema, with per-segment
    factor arrays (drainage / sun / wind / combined) + diagnostic
    fields (sun azimuth/altitude, wind direction/speed, mesh source).

Failure modes:
    - Track centroid unresolved → ``FileNotFoundError`` (caller's
      responsibility).
    - Mesh has no elevation → slope is treated as zero everywhere
      (drainage will be all 1.30 = flat-pooling).
    - WeatherCondition's raw_inputs missing wind keys (e.g., safe-dry
      fallback) → wind 0 km/h, 0° → all neutral.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from .spatial_factors import (
    compute_spatial_factor,
    drainage_factor,
    sun_factor,
    sun_vector_enu,
    wind_factor,
)
from .track_centroid import resolve_track_centroid
from .types import SessionInputs, SpatialMuModifier, WeatherCondition

logger = logging.getLogger(__name__)


def compute_spatial_modifier(
    weather_condition: WeatherCondition,
    track_id: str,
    session_inputs: SessionInputs,
    track_surface: Any,
) -> SpatialMuModifier:
    """Compute the per-segment spatial μ modifier for one session.

    Args:
        weather_condition: scalar classification (Day-11 output). Provides
            wind direction/speed from ``raw_inputs`` and the ``label``
            for clamp selection.
        track_id: canonical alias (for centroid resolution).
        session_inputs: provides ``started_at_utc`` for solar geometry.
        track_surface: a :class:`track_surface.model.TrackSurface`
            instance with ``frenet`` (FrenetFrame) + ``slope_pct`` +
            ``boundary_source``.

    Returns:
        :class:`SpatialMuModifier` populated with N_s-length arrays for
        each factor + scalar diagnostic fields.

    Raises:
        FileNotFoundError: track centroid unresolvable.
    """
    lat, lon = resolve_track_centroid(track_id)

    frenet = track_surface.frenet
    s_grid = np.asarray(frenet.s_grid, dtype=np.float64)
    heading_rad = np.asarray(frenet.heading_rad, dtype=np.float64)

    # Slope in % from track_surface; fall back to zero (flat-track default)
    # when elevation isn't available (bronze tier sessions).
    if getattr(track_surface, "slope_pct", None) is not None:
        slope_pct = np.asarray(track_surface.slope_pct, dtype=np.float64)
    else:
        slope_pct = np.zeros_like(s_grid)
    slope_unit = slope_pct / 100.0  # dz/ds (fractional)

    # Per-segment tangent unit vector in ENU (heading + slope).
    tangents = np.column_stack([
        np.cos(heading_rad),
        np.sin(heading_rad),
        slope_unit,
    ])
    t_norm = np.linalg.norm(tangents, axis=1, keepdims=True)
    t_norm = np.where(t_norm < 1e-9, 1.0, t_norm)
    tangents = tangents / t_norm

    # Per-segment surface normal: rotate (0,0,1) by slope around cross-track axis.
    # N_unnormalized = (-slope·cos(h), -slope·sin(h), 1)
    nx = -slope_unit * np.cos(heading_rad)
    ny = -slope_unit * np.sin(heading_rad)
    nz = np.ones_like(slope_unit)
    normals = np.column_stack([nx, ny, nz])
    n_norm = np.linalg.norm(normals, axis=1, keepdims=True)
    n_norm = np.where(n_norm < 1e-9, 1.0, n_norm)
    normals = normals / n_norm

    # Wind inputs from WeatherCondition.raw_inputs. Safe-dry fallback case
    # has raw_inputs = {"fallback_reason": ...} so .get returns None → 0.
    raw = weather_condition.raw_inputs or {}
    wind_dir_deg = float(raw.get("winddirection_10m") or 0.0)
    wind_speed_kmh = float(raw.get("P8") or 0.0)

    # Compute the three factors.
    drainage = drainage_factor(slope_pct)
    sun = sun_factor(session_inputs.started_at_utc, lat, lon, normals)
    wind = wind_factor(wind_dir_deg, wind_speed_kmh, tangents)

    # Diagnostic solar position (also used for spatial_modifier output).
    sun_az_deg, sun_el_deg = sun_vector_enu(
        session_inputs.started_at_utc, lat, lon, return_az_el=True
    )

    # Combined per-segment factor + clamp.
    combined = compute_spatial_factor(drainage, sun, wind, weather_condition.label)

    return SpatialMuModifier(
        arclength_samples=s_grid.tolist(),
        factor_values=combined.tolist(),
        drainage_components=drainage.tolist(),
        sun_components=sun.tolist(),
        wind_components=wind.tolist(),
        sun_altitude_deg=sun_el_deg,
        sun_azimuth_deg=sun_az_deg,
        wind_direction_deg=wind_dir_deg,
        wind_speed_kmh=wind_speed_kmh,
        mesh_source=(
            getattr(track_surface, "boundary_source", None) or "data_derived"
        ),
        spatial_version="spatial-v1.0",
    )


def attach_spatial_modifier(
    weather_condition: WeatherCondition,
    track_id: str,
    session_inputs: SessionInputs,
    track_surface: Any,
) -> WeatherCondition:
    """Convenience: compute spatial modifier and return a new
    ``WeatherCondition`` with ``spatial_modifier`` populated.

    On any failure (centroid unresolved, mesh malformed, etc.), logs a
    warning and returns the input ``weather_condition`` unchanged. The
    classifier's ``classifier_version`` is bumped from ``weather-v1.0``
    to ``weather-v1.0+spatial-v1.0`` to mark that spatial ran.
    """
    if weather_condition.dominant_factor == "safe_dry_fallback":
        # Weather lookup failed at Day-11 layer; no spatial computation.
        return weather_condition
    try:
        spatial = compute_spatial_modifier(
            weather_condition, track_id, session_inputs, track_surface
        )
    except Exception as exc:
        logger.warning(
            "Spatial modifier producer failed: %s. Returning scalar-only WeatherCondition.",
            exc,
        )
        return weather_condition
    return replace(
        weather_condition,
        spatial_modifier=spatial,
        classifier_version="weather-v1.0+spatial-v1.0",
    )
