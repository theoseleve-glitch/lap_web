"""sensor_quality.py — per-session sensor-quality + map-confidence metrics.

Extracted from ``scripts/build_ok_raw.py`` lines 195-523 / 1102-1122 (Day-10
RC6) to live as a reusable producer next to ``attitude_correction.py``,
``road_attitude_field.py``, ``phone_mount_estimator.py``, and
``road_attitude_estimator.py``.

The four metrics produced match the contract the frontend Sensor Quality
panel was originally written against (see ``track-surface-ok.html`` ``sq.``
references):

  * ``orientation_quality`` — per-bin scalar in ``[0, 1]``; weighted
    sum of (sample density / excitation fraction / calibration
    consistency). Smoothed (savgol w=11).
  * ``curvature_agreement`` — per-bin median ratio of measured |a_lat|
    to expected centripetal |v²κ|. 1.0 = perfect agreement.
    Computed only where ≥ 4 samples exist; defaults to 0 elsewhere.
  * ``bank_sensitivity_deg`` — per-bin bank-angle estimate inferred
    from the centripetal cross-check residual, clamped to ±5 deg.
    Smoothed (savgol w=21).
  * ``map_confidence.excited_sample_frac`` — scalar in [0,1]: fraction
    of all in-lap samples that were near-limit (|a_lat| above session
    p70 threshold).

Plus a session-aggregated ``attitude_correction.*`` diagnostics block
merged from per-lap diagnostics via
:func:`track_surface.attitude_correction.merge_session_diagnostics`.

Public API
----------

``compute_session_sensor_quality(resampled_laps, track_surface) -> dict | None``
    Returns a ``sensor_quality`` dict suitable for storing in
    ``analysis_json["sensor_quality"]`` and emitting in the
    ``/sessions/<id>/track-surface`` response. Returns ``None`` when the
    inputs are insufficient (no laps, no IMU columns, or no centerline);
    callers MUST handle that case explicitly and emit a low-confidence
    sentinel rather than placeholder "--" strings.

Graceful degradation: per-side metrics that cannot be computed (e.g.
``bank_sensitivity_deg`` when ``curvature_agreement`` had no samples)
default to ``0.0`` rather than NaN so the bin-array length contract is
preserved. The frontend panel renders ``confidence < 0.05`` cells as a
"low confidence" grey state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

logger = logging.getLogger(__name__)

_G = 9.80665

# ── Internals ──────────────────────────────────────────────────────────


def _savgol_smooth_wrap(arr: np.ndarray, window: int = 11, polyorder: int = 3) -> np.ndarray:
    """Closed-loop Savitzky-Golay (wrap-padded). Matches build_ok_raw.savgol_smooth."""
    n = len(arr)
    if n < window:
        return arr.copy()
    if window % 2 == 0:
        window += 1
    if polyorder >= window:
        polyorder = max(1, window - 2)
    pad = window
    ext = np.concatenate([arr[-pad:], arr, arr[:pad]])
    sm = savgol_filter(ext, window, polyorder)
    return sm[pad:pad + n]


# Canonical column-name candidates. The pipeline normalises RaceChrono
# headers, but we accept both canonical (snake_case) and RaceChrono
# (parenthetical) names for robustness.
_LAT_COLS = ("lat_deg", "latitude_deg", "Latitude (deg)")
_LON_COLS = ("lon_deg", "longitude_deg", "Longitude (deg)")
_SPEED_COLS = ("speed_mps", "Speed (m/s)", "speed_kmh", "Speed (km/h)")
_TIME_COLS = ("time_s", "Time (s)")
_ALAT_G_COLS = ("accel_lat_g", "Lateral acceleration (G) *calc", "Lateral acceleration (G)")
_ALAT_MPS2_COLS = ("accel_lat_mps2",)
_ALONG_G_COLS = ("accel_long_g", "Longitudinal acceleration (G) *calc",
                 "Longitudinal acceleration (G)")
_ALONG_MPS2_COLS = ("accel_long_mps2",)
_BEARING_COLS = ("bearing_deg", "Bearing (deg)")


def _first_col(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _extract_lap_arrays(df: pd.DataFrame) -> dict[str, np.ndarray] | None:
    """Pull the canonical arrays out of one resampled-lap DataFrame.

    Returns None when the minimum required columns (lat / lon / speed /
    a_lat) are absent — that lap will be skipped in the accumulator.
    """
    lat_c = _first_col(df, _LAT_COLS)
    lon_c = _first_col(df, _LON_COLS)
    spd_c = _first_col(df, _SPEED_COLS)
    if not (lat_c and lon_c and spd_c):
        return None

    speed = pd.to_numeric(df[spd_c], errors="coerce").to_numpy(dtype=float)
    if spd_c in ("speed_kmh", "Speed (km/h)"):
        speed = speed / 3.6  # → m/s

    # Lateral accel: prefer G column; fall back to mps2/G conversion.
    alat_c_g = _first_col(df, _ALAT_G_COLS)
    alat_c_mps2 = _first_col(df, _ALAT_MPS2_COLS)
    if alat_c_g:
        alat_g = pd.to_numeric(df[alat_c_g], errors="coerce").to_numpy(dtype=float)
    elif alat_c_mps2:
        alat_g = pd.to_numeric(df[alat_c_mps2], errors="coerce").to_numpy(dtype=float) / _G
    else:
        return None

    return {
        "lat": pd.to_numeric(df[lat_c], errors="coerce").to_numpy(dtype=float),
        "lon": pd.to_numeric(df[lon_c], errors="coerce").to_numpy(dtype=float),
        "speed": speed,
        "alat_g": alat_g,
    }


def _to_local_xy(
    lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Equirectangular projection matching build_ok_raw.to_xy."""
    cos_lat = np.cos(np.radians(lat0))
    return (
        (lon - lon0) * cos_lat * 111_320.0,
        (lat - lat0) * 111_320.0,
    )


def _accumulate_per_bin_samples(
    laps_arrays: list[dict[str, np.ndarray]],
    track_surface: Any,
    *,
    n_bins: int,
    excitation_threshold_g: float = 0.5,
) -> dict[str, Any]:
    """Project each lap onto the centerline's s-grid and accumulate per-bin
    samples needed for the sensor-quality computation.

    Returns:
        demand_samp: list[list[float]] length n_bins of |a_lat| samples
        demand_excited: list[list[float]] length n_bins of excited |a_lat|
        centripetal_ratio: list[list[float]] length n_bins of |a_lat| / |v²κ|
        n_total_samples, n_excited_samples: scalar counters
    """
    # Centerline geometry from the TrackSurface frenet frame.
    cl_xy = np.asarray(track_surface.frenet.centerline_xy)
    s_grid = np.asarray(track_surface.frenet.s_grid)
    track_length = float(s_grid[-1])

    # Curvature along s for centripetal cross-check.
    dx_c = np.gradient(cl_xy[:, 0])
    dy_c = np.gradient(cl_xy[:, 1])
    heading = np.unwrap(np.arctan2(dy_c, dx_c))
    ds = np.maximum(
        np.append(np.hypot(np.diff(cl_xy[:, 0]), np.diff(cl_xy[:, 1])), 1e-3),
        1e-3,
    )
    kappa = np.gradient(heading) / ds
    kappa_abs = np.clip(np.abs(kappa), 0.0, 0.35)
    # Resample kappa onto the n_bins-grid used by the producer (same grid as
    # s_grid, since centerline already lives on a uniform-ish s-grid).
    if len(kappa_abs) != n_bins:
        kappa_abs = np.interp(np.linspace(0, 1, n_bins),
                              np.linspace(0, 1, len(kappa_abs)), kappa_abs)

    demand_samp: list[list[float]] = [[] for _ in range(n_bins)]
    demand_excited: list[list[float]] = [[] for _ in range(n_bins)]
    centripetal_ratio: list[list[float]] = [[] for _ in range(n_bins)]
    n_total = 0
    n_excited = 0

    # Use the track_surface's projection reference, falling back to the lap
    # mean if it's not available (older TrackSurface lacked these attrs).
    lat0 = getattr(track_surface, "lat_ref_rad", None)
    lon0 = getattr(track_surface, "lon_ref_rad", None)
    if lat0 is None or lon0 is None:
        all_lats = np.concatenate([la["lat"] for la in laps_arrays])
        all_lons = np.concatenate([la["lon"] for la in laps_arrays])
        finite = np.isfinite(all_lats) & np.isfinite(all_lons)
        lat0 = float(np.mean(all_lats[finite])) if finite.any() else 0.0
        lon0 = float(np.mean(all_lons[finite])) if finite.any() else 0.0
    else:
        lat0 = float(np.degrees(lat0))
        lon0 = float(np.degrees(lon0))

    s_uniform = np.linspace(0, track_length, n_bins)

    for lap in laps_arrays:
        lx, ly = _to_local_xy(lap["lat"], lap["lon"], lat0, lon0)
        finite = np.isfinite(lx) & np.isfinite(ly) & np.isfinite(lap["speed"]) & np.isfinite(lap["alat_g"])
        if finite.sum() < 50:
            continue
        lx, ly = lx[finite], ly[finite]
        spd = lap["speed"][finite]
        alat = lap["alat_g"][finite]

        dlx = np.diff(lx)
        dly = np.diff(ly)
        dls = np.hypot(dlx, dly)
        lap_dist = np.concatenate([[0.0], np.cumsum(dls)])
        lap_len = lap_dist[-1]
        # Skip laps whose length is way off the centerline length (likely
        # in/out lap that slipped through).
        if lap_len <= 0 or abs(lap_len - track_length) > 0.12 * track_length:
            continue

        spd_s = np.interp(s_uniform, lap_dist, spd)
        alat_s = np.interp(s_uniform, lap_dist, alat)

        # Excitation: lap-specific p70 of |a_lat| above 5 m/s (matches
        # build_ok_raw's per-session threshold).
        moving = spd_s > 5.0
        if moving.any():
            session_thresh = float(np.percentile(np.abs(alat_s[moving]), 70))
        else:
            session_thresh = excitation_threshold_g
        session_thresh = max(session_thresh, 0.2)

        for i in range(n_bins):
            n_total += 1
            a_abs = abs(float(alat_s[i]))
            demand_samp[i].append(a_abs)

            v = float(spd_s[i])
            k = float(kappa_abs[i])
            a_centripetal_g = (v * v * k) / _G  # G
            if a_centripetal_g > 0.05 and a_abs > 0.05:
                centripetal_ratio[i].append(a_abs / a_centripetal_g)

            if a_abs >= session_thresh and v > 5.0:
                demand_excited[i].append(a_abs)
                n_excited += 1

    return {
        "demand_samp": demand_samp,
        "demand_excited": demand_excited,
        "centripetal_ratio": centripetal_ratio,
        "n_total": n_total,
        "n_excited": n_excited,
    }


def _compute_per_bin_metrics(accum: dict[str, Any], n_bins: int) -> dict[str, np.ndarray]:
    """Per-bin confidence / cal_bias / bank — matches build_ok_raw 477-515."""
    demand_samp = accum["demand_samp"]
    demand_excited = accum["demand_excited"]
    centripetal_ratio = accum["centripetal_ratio"]

    confidence = np.zeros(n_bins)
    cal_bias = np.zeros(n_bins)
    bank_estimate_deg = np.zeros(n_bins)
    lat_demand_all = np.zeros(n_bins)

    for i in range(n_bins):
        n_all = len(demand_samp[i])
        n_exc = len(demand_excited[i])

        count_score = min(1.0, n_all / 30.0)
        exc_frac = n_exc / max(n_all, 1)
        exc_score = min(1.0, exc_frac / 0.3)

        cal_score = 0.5
        if len(centripetal_ratio[i]) > 3:
            median_ratio = float(np.median(centripetal_ratio[i]))
            cal_bias[i] = median_ratio
            cal_score = max(0.0, 1.0 - abs(median_ratio - 1.0))

        confidence[i] = 0.4 * count_score + 0.35 * exc_score + 0.25 * cal_score

        if n_all > 5:
            lat_demand_all[i] = float(np.percentile(demand_samp[i], 90))

    confidence = np.clip(_savgol_smooth_wrap(confidence, window=11, polyorder=3), 0.0, 1.0)

    # Bank estimate — only in real corners (demand > 0.3G) with ≥5 cross-check samples.
    for i in range(n_bins):
        if len(centripetal_ratio[i]) > 5 and lat_demand_all[i] > 0.3:
            median_r = float(np.median(centripetal_ratio[i]))
            excess_g = (median_r - 1.0) * lat_demand_all[i]
            excess_g = float(np.clip(excess_g, -0.09, 0.09))
            bank_estimate_deg[i] = float(np.degrees(np.arcsin(excess_g)))
    bank_estimate_deg = np.clip(
        _savgol_smooth_wrap(bank_estimate_deg, window=21, polyorder=3),
        -5.0, 5.0,
    )

    return {
        "confidence": confidence,
        "cal_bias": cal_bias,
        "bank_estimate_deg": bank_estimate_deg,
        "lat_demand_all": lat_demand_all,
    }


def _run_attitude_corrections(
    resampled_laps: dict[int, pd.DataFrame],
) -> list[dict[str, Any]]:
    """Per-lap attitude_correction.apply_attitude_correction call. Returns
    the list of diagnostic dicts that ``merge_session_diagnostics`` consumes.

    Skips silently if IMU 3-axis columns are absent in the resampled
    dataframes — the pipeline normalises only a few canonical channels
    and the raw IMU may not survive resampling.
    """
    diags: list[dict[str, Any]] = []
    try:
        from phone_mount_estimator import estimate_phone_mount
        from track_surface.attitude_correction import (
            MIN_ATTITUDE_QUALITY_FOR_CORRECTION,
            apply_attitude_correction,
        )
    except ImportError:
        logger.debug("attitude_correction modules unavailable; skipping")
        return diags

    accel_cols = ("accel_x_mps2", "accel_y_mps2", "accel_z_mps2")
    gyro_cols = ("gyro_x_dps", "gyro_y_dps", "gyro_z_dps")

    for lap_no, df in resampled_laps.items():
        if not all(c in df.columns for c in accel_cols + gyro_cols):
            continue
        accel = df[list(accel_cols)].to_numpy(dtype=float)
        gyro = df[list(gyro_cols)].to_numpy(dtype=float)
        spd_c = _first_col(df, _SPEED_COLS)
        t_c = _first_col(df, _TIME_COLS)
        alat_c = _first_col(df, _ALAT_G_COLS)
        if not (spd_c and t_c and alat_c):
            continue
        speed = pd.to_numeric(df[spd_c], errors="coerce").to_numpy(dtype=float)
        if spd_c in ("speed_kmh", "Speed (km/h)"):
            speed = speed / 3.6
        timestamps = pd.to_numeric(df[t_c], errors="coerce").to_numpy(dtype=float)
        alat_g = pd.to_numeric(df[alat_c], errors="coerce").to_numpy(dtype=float)

        try:
            mount = estimate_phone_mount(accel, gyro, speed, timestamps)
        except Exception as exc:
            logger.debug("phone_mount estimation failed (lap %s): %s", lap_no, exc)
            continue

        along_c = _first_col(df, _ALONG_G_COLS)
        along_g = (pd.to_numeric(df[along_c], errors="coerce").to_numpy(dtype=float)
                   if along_c else None)
        bearing_c = _first_col(df, _BEARING_COLS)
        bearing = (pd.to_numeric(df[bearing_c], errors="coerce").to_numpy(dtype=float)
                   if bearing_c else None)

        try:
            result = apply_attitude_correction(
                accel, gyro, speed, timestamps,
                alat_g_kart=alat_g,
                along_g_kart=along_g,
                gps_heading=bearing,
                mount_estimate=mount,
                min_attitude_quality=MIN_ATTITUDE_QUALITY_FOR_CORRECTION,
            )
            d = dict(result.diagnostics or {})
            d["lap"] = lap_no
            diags.append(d)
        except Exception as exc:
            logger.debug("apply_attitude_correction failed (lap %s): %s", lap_no, exc)

    return diags


# ── Public API ─────────────────────────────────────────────────────────


def compute_session_sensor_quality(
    resampled_laps: dict[int, pd.DataFrame] | None,
    track_surface: Any,
) -> dict[str, Any] | None:
    """Compute per-session sensor-quality + map-confidence summary.

    See module docstring for the contract. Returns None when inputs are
    insufficient — callers MUST handle that case explicitly (the frontend
    renders ``sensor_quality is null`` as a grey low-confidence state).
    """
    if not resampled_laps or len(resampled_laps) == 0:
        logger.debug("sensor_quality: no resampled_laps; returning None")
        return None
    if track_surface is None or not hasattr(track_surface, "frenet"):
        logger.debug("sensor_quality: no track_surface; returning None")
        return None

    n_bins = int(getattr(track_surface.frenet, "n_points", 0))
    if n_bins < 50:
        logger.debug("sensor_quality: n_bins=%d too small", n_bins)
        return None

    laps_arrays = []
    for lap_no, df in resampled_laps.items():
        arr = _extract_lap_arrays(df)
        if arr is not None:
            laps_arrays.append(arr)

    if not laps_arrays:
        logger.info("sensor_quality: no laps with required canonical columns")
        return None

    accum = _accumulate_per_bin_samples(laps_arrays, track_surface, n_bins=n_bins)
    per_bin = _compute_per_bin_metrics(accum, n_bins=n_bins)

    # Per-lap attitude correction diagnostics — skip silently if IMU columns
    # are absent in resampled data (common for the production path).
    per_lap_attitude = _run_attitude_corrections(resampled_laps)
    attitude_correction: dict[str, Any] = {}
    if per_lap_attitude:
        try:
            from track_surface.attitude_correction import merge_session_diagnostics
            attitude_correction = merge_session_diagnostics(per_lap_attitude)
        except Exception as exc:
            logger.debug("merge_session_diagnostics failed: %s", exc)

    sample_density = accum["n_total"] / max(n_bins, 1)
    excited_frac = accum["n_excited"] / max(accum["n_total"], 1)

    return {
        "orientation_quality": [round(float(v), 3) for v in per_bin["confidence"]],
        "curvature_agreement": [round(float(v), 3) for v in per_bin["cal_bias"]],
        "bank_sensitivity_deg": [round(float(v), 2) for v in per_bin["bank_estimate_deg"]],
        "attitude_correction": {
            k: (round(v, 4) if isinstance(v, float)
                else (int(v) if isinstance(v, (int, np.integer)) else v))
            for k, v in attitude_correction.items()
        },
        "map_confidence": {
            "excited_sample_frac": round(excited_frac, 3),
            "sample_density_per_bin": round(sample_density, 1),
            "n_bins": n_bins,
            "confidence_per_bin": [round(float(v), 3) for v in per_bin["confidence"]],
        },
    }
