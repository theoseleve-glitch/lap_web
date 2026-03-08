"""
theoretical_adapter.py
----------------------
Adapter layer that bridges the ``kart_envelope`` solver to the
``telemetry_tool`` pipeline contract.

The pipeline works with RaceChrono column names and curvature DataFrames;
kart_envelope works with canonical column names, ``TrackGeometry``, and
``CapabilityEnvelope``.  This module translates between the two worlds.

All kart_envelope imports are lazy (inside functions) so the module can be
imported even when kart_envelope optional dependencies are missing.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_G: float = 9.80665

# ---------------------------------------------------------------------------
# Column mapping: RaceChrono / pipeline names -> kart_envelope canonical names
# ---------------------------------------------------------------------------
# Ordered list of (raw_name, canonical_name, needs_G_to_mps2_conversion).
# First match for each canonical target wins (avoids duplicate columns).
# *calc variants appear first to get priority.

_COLUMN_MAP: list[tuple[str, str, bool]] = [
    # Distance
    ("Distance (m)",                              "distance_m",       False),
    ("distance_m",                                "distance_m",       False),

    # Speed
    ("Speed (m/s) *calc",                         "speed_mps",        False),
    ("Speed (m/s)",                               "speed_mps",        False),
    ("speed_mps",                                 "speed_mps",        False),

    # Time
    ("Time (s)",                                  "time_s",           False),
    ("time_s",                                    "time_s",           False),

    # Lap number
    ("Lap #",                                     "lap_number",       False),
    ("lap_number",                                "lap_number",       False),

    # Longitudinal acceleration (G variants need conversion)
    ("Longitudinal acceleration (G) *calc",       "accel_long_mps2",  True),
    ("Longitudinal acceleration (G)",             "accel_long_mps2",  True),
    # m/s^2 variants -- no conversion
    ("Longitudinal acceleration (m/s\u00b2)",     "accel_long_mps2",  False),
    ("accel_long_mps2",                           "accel_long_mps2",  False),

    # Lateral acceleration (G variants need conversion)
    ("Lateral acceleration (G) *calc",            "accel_lat_mps2",   True),
    ("Lateral acceleration (G)",                  "accel_lat_mps2",   True),
    # m/s^2 variants -- no conversion
    ("Lateral acceleration (m/s\u00b2)",          "accel_lat_mps2",   False),
    ("accel_lat_mps2",                            "accel_lat_mps2",   False),

    # GPS / XY
    ("Latitude (deg)",                            "lat_deg",          False),
    ("lat_deg",                                   "lat_deg",          False),
    ("Longitude (deg)",                           "lon_deg",          False),
    ("lon_deg",                                   "lon_deg",          False),
    ("X-position (m)",                            "x_m",              False),
    ("X (m)",                                     "x_m",              False),
    ("x_m",                                       "x_m",              False),
    ("Y-position (m)",                            "y_m",              False),
    ("Y (m)",                                     "y_m",              False),
    ("y_m",                                       "y_m",              False),

    # Yaw / heading
    ("Yaw rate (deg/s)",                          "yaw_rate_dps",     False),
    ("yaw_rate_dps",                              "yaw_rate_dps",     False),
    ("Bearing (deg)",                             "heading_deg",      False),
    ("heading_deg",                               "heading_deg",      False),
]


def _map_columns_to_canonical(df: pd.DataFrame) -> pd.DataFrame:
    """Map RaceChrono / pipeline column names to kart_envelope canonical names.

    - First match per canonical target wins (``*calc`` preferred over non-calc).
    - Columns already using canonical names pass through.
    - G-unit acceleration columns are converted to m/s^2 (x 9.80665).
    - Unrecognised columns are preserved as-is.

    Returns a **copy** (no mutation of the input).
    """
    rename_map: dict[str, str] = {}
    g_convert: list[str] = []
    claimed: set[str] = set()
    # Pre-claim canonical names that already exist as column names in df,
    # but ONLY if they aren't also a raw source for a different canonical.
    # This prevents overwriting a column that's already canonical.
    for col in df.columns:
        # Check if this column name IS a canonical name
        is_canonical = any(canon == col for _, canon, _ in _COLUMN_MAP)
        if is_canonical:
            claimed.add(col)

    for raw_name, canon, is_g in _COLUMN_MAP:
        if canon in claimed and raw_name != canon:
            # Canonical already claimed; skip this raw source
            continue
        if canon in claimed:
            # Already claimed by same name (passthrough); no rename needed
            continue
        if raw_name in df.columns:
            if raw_name != canon:
                rename_map[raw_name] = canon
            claimed.add(canon)
            if is_g:
                g_convert.append(canon)

    out = df.copy()
    if rename_map:
        out = out.rename(columns=rename_map)

    # G -> m/s^2 conversion
    for col in g_convert:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce") * _G

    return out


# ---------------------------------------------------------------------------
# AdapterResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class AdapterResult:
    """Result of the kart_envelope adapter computation.

    Attributes
    ----------
    theoretical_df : pd.DataFrame
        Pipeline-format DataFrame with columns:
        ``distance_m``, ``v_env_mps``, ``accel_max_mps2``, ``brake_max_mps2``.
    theoretical_result : Any
        The ``TheoreticalResult`` from the solver, or ``None``.
    method : str
        Provenance string, e.g. ``"kart_envelope_qss"``.
    corner_coaching : list[dict] | None
        Per-corner coaching results (from ``analyze_corner_performance``).
    delta_map : pd.DataFrame | None
        Distance-aligned delta-time map.
    session_scalars : Any | None
        ``SessionScalars`` object from session inference.
    """

    theoretical_df: pd.DataFrame
    theoretical_result: Any
    method: str
    corner_coaching: list[dict] | None = None
    delta_map: pd.DataFrame | None = None
    session_scalars: Any | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_geometry_from_curvature(curv_df: pd.DataFrame) -> Any:
    """Build a ``TrackGeometry`` from a curvature-profile DataFrame.

    Accepts ``"curvature"`` or ``"curvature_1pm"`` as the curvature column.
    Derives heading and XY by integration if missing.

    Returns
    -------
    TrackGeometry
    """
    from kart_envelope.track.geometry import TrackGeometry

    # Distance
    if "distance_m" in curv_df.columns:
        dist = curv_df["distance_m"].values.astype(float)
    elif "Distance (m)" in curv_df.columns:
        dist = curv_df["Distance (m)"].values.astype(float)
    else:
        raise ValueError(
            "Curvature profile must have a 'distance_m' or 'Distance (m)' column."
        )

    # Curvature
    if "curvature_1pm" in curv_df.columns:
        kappa = curv_df["curvature_1pm"].values.astype(float)
    elif "curvature" in curv_df.columns:
        kappa = curv_df["curvature"].values.astype(float)
    else:
        raise ValueError(
            "Curvature profile must have a 'curvature' or 'curvature_1pm' column."
        )

    # Clip curvature to physical bounds (min radius ~1 m)
    kappa = np.clip(np.abs(kappa), 0.0, 1.0)

    n = len(dist)
    ds = np.diff(dist)

    # Heading: integrate curvature if not provided
    if "heading_rad" in curv_df.columns:
        heading = curv_df["heading_rad"].values.astype(float)
    elif "heading" in curv_df.columns:
        heading = curv_df["heading"].values.astype(float)
    else:
        heading = np.zeros(n, dtype=float)
        for i in range(1, n):
            heading[i] = heading[i - 1] + kappa[i - 1] * ds[i - 1]

    # XY: integrate from heading if not provided
    x_col = _first_col(curv_df, ["x_ref_m", "x_m", "X (m)"])
    y_col = _first_col(curv_df, ["y_ref_m", "y_m", "Y (m)"])

    if x_col is not None:
        x = curv_df[x_col].values.astype(float)
    else:
        x = np.zeros(n, dtype=float)
        for i in range(1, n):
            x[i] = x[i - 1] + ds[i - 1] * np.cos(heading[i - 1])

    if y_col is not None:
        y = curv_df[y_col].values.astype(float)
    else:
        y = np.zeros(n, dtype=float)
        for i in range(1, n):
            y[i] = y[i - 1] + ds[i - 1] * np.sin(heading[i - 1])

    lap_length = float(dist[-1] - dist[0]) if n > 1 else 0.0

    geom = TrackGeometry(
        distance_m=dist,
        curvature_1pm=kappa,
        heading_rad=heading,
        x_ref_m=x,
        y_ref_m=y,
        lap_length_m=lap_length,
        track_id="",
    )
    logger.info(
        "Built TrackGeometry from curvature profile: %.0f m, %d points, "
        "mean kappa=%.5f 1/m.",
        lap_length, n, float(np.mean(kappa)),
    )
    return geom


def _first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    """Return the first column name from *names* that exists in *df*."""
    for name in names:
        if name in df.columns:
            return name
    return None


def _result_to_pipeline_df(
    result: Any,
    envelope: Any,
) -> pd.DataFrame:
    """Convert a ``TheoreticalResult`` + envelope to the pipeline DataFrame format.

    Output columns:
    - ``distance_m``: distance grid [m]
    - ``v_env_mps``: theoretical speed profile [m/s]
    - ``accel_max_mps2``: traction limit at each speed point [m/s^2]
    - ``brake_max_mps2``: braking limit at each speed point [m/s^2]
    """
    dist = result.distance_m
    v = result.speed_profile_mps

    # Envelope limits at each speed point
    accel_max = np.abs(envelope.traction_max(v))
    brake_max = np.abs(envelope.braking_max(v))

    return pd.DataFrame({
        "distance_m": dist,
        "v_env_mps": v,
        "accel_max_mps2": accel_max,
        "brake_max_mps2": brake_max,
    })


def _run_coaching(
    mapped_laps: dict[int, pd.DataFrame],
    theo_result: Any,
    geometry: Any,
    config: Any,
) -> tuple[list[dict] | None, pd.DataFrame | None]:
    """Run coaching analysis (corner detection + delta map) best-effort.

    Returns (corner_coaching, delta_map). Both may be None on failure.
    """
    try:
        from kart_envelope.coaching.corner_coaching import (
            analyze_corner_performance,
            detect_corners_from_curvature,
        )
        from kart_envelope.coaching.delta_analysis import compute_delta_map
    except ImportError:
        logger.debug("Coaching modules not available; skipping.")
        return None, None

    corner_coaching: list[dict] | None = None
    delta_map: pd.DataFrame | None = None

    try:
        # Detect corners from geometry
        corners = detect_corners_from_curvature(
            kappa=geometry.curvature_1pm,
            distance=geometry.distance_m,
            threshold=getattr(config, "solver_apex_curvature_threshold", 0.005)
            if config is not None else 0.005,
            min_length_m=10.0,
            merge_gap_m=15.0,
        )

        # Pick the best (fastest) lap for coaching
        best_lap_key = _pick_best_lap(mapped_laps)
        if best_lap_key is not None:
            best_lap = mapped_laps[best_lap_key]

            # Delta map
            try:
                n_segments = getattr(config, "coaching_n_segments", 20) if config else 20
                delta_map = compute_delta_map(
                    driver_lap=best_lap,
                    theoretical=theo_result,
                    n_segments=n_segments,
                )
                if delta_map is not None and delta_map.empty:
                    delta_map = None
            except Exception as exc:
                logger.debug("Delta map computation failed: %s", exc)

            # Corner performance analysis
            if corners:
                try:
                    perf_list = analyze_corner_performance(
                        driver_lap=best_lap,
                        theoretical=theo_result,
                        corners=corners,
                    )
                    corner_coaching = [cp.to_dict() for cp in perf_list]
                except Exception as exc:
                    logger.debug("Corner performance analysis failed: %s", exc)

    except Exception as exc:
        logger.warning("Coaching analysis failed (non-fatal): %s", exc)

    return corner_coaching, delta_map


def _pick_best_lap(mapped_laps: dict[int, pd.DataFrame]) -> int | None:
    """Return the key of the fastest lap (smallest time span)."""
    best_key: int | None = None
    best_time = float("inf")

    for key, lap_df in mapped_laps.items():
        if "time_s" not in lap_df.columns:
            continue
        t = lap_df["time_s"].values
        valid = t[np.isfinite(t)]
        if len(valid) < 2:
            continue
        lap_time = float(valid[-1] - valid[0])
        if 0 < lap_time < best_time:
            best_time = lap_time
            best_key = key

    return best_key


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_theoretical_via_envelope(
    resampled_laps: dict[int, pd.DataFrame],
    curvature_profile: pd.DataFrame | None,
    vehicle_params: Any,
    data_quality_rpt: Any,
    *,
    best_driver_time_s: float | None = None,
    config: Any = None,
) -> AdapterResult:
    """Compute a theoretical lap via the kart_envelope solver.

    This is the main adapter function, called from pipeline Step 10.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        Resampled laps from the pipeline (RaceChrono or canonical column names).
    curvature_profile : pd.DataFrame | None
        Curvature profile from the pipeline's reference line step.
        Must have ``distance_m`` and ``curvature`` (or ``curvature_1pm``) columns.
    vehicle_params : Any
        Vehicle parameters (currently unused; reserved for future enrichment).
    data_quality_rpt : Any
        Data quality report (currently unused; reserved for future enrichment).
    best_driver_time_s : float | None
        Best driver lap time for sanity checking (optional).
    config : Any | None
        ``KartEnvelopeConfig`` override.  If ``None``, uses ``default_config()``.

    Returns
    -------
    AdapterResult
        Contains the theoretical DataFrame, TheoreticalResult, coaching data,
        session scalars, and provenance metadata.

    Raises
    ------
    ValueError
        If ``curvature_profile`` is ``None``.
    """
    # Lazy imports to avoid import-time failures when kart_envelope deps missing
    from kart_envelope.config import default_config as _default_config
    from kart_envelope.envelope.capability import train_capability_envelope
    from kart_envelope.inference.session_scalars import infer_session_scalars
    from kart_envelope.solver.min_time import compute_theoretical_lap

    if curvature_profile is None:
        raise ValueError(
            "curvature_profile is None -- cannot compute theoretical lap via "
            "kart_envelope. A curvature profile (from reference line / track "
            "detection) is required."
        )

    cfg = config if config is not None else _default_config()

    # -- 1. Map all lap columns to canonical names --
    mapped_laps: dict[int, pd.DataFrame] = {
        k: _map_columns_to_canonical(v) for k, v in resampled_laps.items()
    }
    logger.info(
        "Mapped %d laps to canonical column names.", len(mapped_laps),
    )

    # -- 2. Build TrackGeometry from curvature profile --
    geometry = _build_geometry_from_curvature(curvature_profile)

    # -- 3. Train CapabilityEnvelope from mapped laps --
    envelope = train_capability_envelope(
        sessions=[mapped_laps],
        config=cfg,
    )
    logger.info(
        "Envelope trained: %d laps, p_combined=%.2f.",
        envelope.n_laps, envelope.p_combined,
    )

    # -- 4. Infer SessionScalars --
    scalars = infer_session_scalars(
        resampled_laps=mapped_laps,
        envelope=envelope,
        config=cfg,
    )
    logger.info(
        "Session scalars: mu=%.3f, p=%.3f, b=%.3f (confidence=%.2f).",
        scalars.mu_session, scalars.p_session, scalars.b_session,
        scalars.confidence,
    )

    # -- 5. Compute theoretical lap --
    theo_result = compute_theoretical_lap(
        geometry=geometry,
        envelope=envelope,
        scalars=scalars,
        config=cfg,
    )
    logger.info(
        "Theoretical lap computed: %.3f s (method=%s, backend=%s).",
        theo_result.lap_time_s, theo_result.method, theo_result.solver_backend,
    )

    # Sanity check against driver's best time
    if best_driver_time_s is not None and math.isfinite(best_driver_time_s):
        ratio = theo_result.lap_time_s / best_driver_time_s
        if ratio < 0.5 or ratio > 2.0:
            logger.warning(
                "Theoretical time (%.2fs) is %.0f%% of driver best (%.2fs) "
                "-- may indicate a solver or data issue.",
                theo_result.lap_time_s, ratio * 100, best_driver_time_s,
            )

    # -- 6. Convert to pipeline DataFrame format --
    theo_df = _result_to_pipeline_df(theo_result, envelope)

    # -- 7. Run coaching (best-effort) --
    corner_coaching, delta_map = _run_coaching(
        mapped_laps, theo_result, geometry, cfg,
    )

    # -- 8. Build method string --
    method = f"kart_envelope_{theo_result.solver_backend}"

    return AdapterResult(
        theoretical_df=theo_df,
        theoretical_result=theo_result,
        method=method,
        corner_coaching=corner_coaching,
        delta_map=delta_map,
        session_scalars=scalars,
    )


def caps_from_kart_envelope(
    resampled_laps: dict[int, "pd.DataFrame"],
    curvature_profile: "pd.DataFrame | None",
    *,
    vehicle_params: Any = None,
    config: Any = None,
) -> "OptimalCaps | None":
    """Build OptimalCaps from kart_envelope training.

    Returns None if kart_envelope is not available or curvature_profile is missing.

    Parameters
    ----------
    resampled_laps : lap data
    curvature_profile : curvature from reference line
    vehicle_params : optional vehicle parameters
    config : optional KartEnvelopeConfig

    Returns
    -------
    OptimalCaps or None if unavailable.
    """
    if curvature_profile is None or not resampled_laps:
        return None

    try:
        from kart_envelope.config import default_config as _default_config
        from kart_envelope.envelope.capability import train_capability_envelope
        from kart_envelope.inference.session_scalars import infer_session_scalars
    except ImportError:
        logger.debug("kart_envelope not installed; caps_from_kart_envelope unavailable.")
        return None

    try:
        from optimal_solver import OptimalCaps

        cfg = config if config is not None else _default_config()

        # Map columns
        mapped_laps = {k: _map_columns_to_canonical(v) for k, v in resampled_laps.items()}

        # Build geometry
        geometry = _build_geometry_from_curvature(curvature_profile)

        # Train envelope
        envelope = train_capability_envelope(sessions=[mapped_laps], config=cfg)

        # Infer session scalars
        scalars = infer_session_scalars(
            resampled_laps=mapped_laps, envelope=envelope, config=cfg,
        )

        # Extract caps from envelope
        dist = geometry.distance_m
        n = len(dist)
        curvature = geometry.curvature_1pm

        # Speed cap from envelope + geometry
        v_cap = np.full(n, 80.0)
        mu = scalars.mu_session
        for i in range(n):
            kappa = abs(curvature[i])
            if kappa > 1e-6:
                v_cap[i] = min(v_cap[i], math.sqrt(mu * _G / kappa))

        # Accel/brake from envelope
        v_sample = np.clip(v_cap, 1.0, 80.0)
        ax_accel = np.abs(envelope.traction_max(v_sample))
        ax_brake = np.abs(envelope.braking_max(v_sample))
        ax_accel = np.clip(ax_accel, 0.5, 20.0)
        ax_brake = np.clip(ax_brake, 0.5, 30.0)

        return OptimalCaps(
            distance_m=dist,
            v_cap=np.clip(v_cap, 1.0, 80.0),
            ax_accel=ax_accel,
            ax_brake=ax_brake,
            curvature=np.abs(curvature),
            mu=np.full(n, mu),
            cap_source=["kart_qss"] * n,
            solver_version="optimal_v2_1.0",
        )
    except Exception as exc:
        logger.warning("caps_from_kart_envelope failed: %s", exc)
        return None
