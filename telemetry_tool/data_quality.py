"""
data_quality.py
---------------
Scores the quality of input telemetry data and produces adaptive
processing recommendations.  When lap count is low, GPS is noisy, or
sensors are absent, the theoretical lap computation needs softer
percentile thresholds to avoid producing unrealistically fast envelopes.

Public API
~~~~~~~~~~
``score_data_quality(resampled_laps, lap_times)``
    Comprehensive quality assessment returning a ``DataQualityReport``.

``compute_gps_quality_score(laps)``
    GPS consistency and dropout assessment (0–1).

``compute_accel_quality_score(laps)``
    Accelerometer presence, noise, and plausibility (0–1).

``adaptive_percentile(n_laps, quality_score)``
    Recommended percentile for theoretical envelope computation.

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no side effects, no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs → identical outputs.
- Numpy / pandas only.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants (aligned with features.py / pipeline.py)

# -- -


_COL_DIST:      Final[str] = "Distance (m)"
_COL_SPEED:     Final[str] = "Speed (m/s)"
_COL_TIME:      Final[str] = "Time (s)"
_COL_X:         Final[str] = "X (m)"
_COL_Y:         Final[str] = "Y (m)"
_COL_LAT:       Final[str] = "Latitude (deg)"
_COL_LON:       Final[str] = "Longitude (deg)"
_COL_ACCEL_L:   Final[str] = "accel_long_mps2"
_COL_ACCEL_LAT: Final[str] = "accel_lat_mps2"
_COL_YAW:       Final[str] = "yaw_rate_dps"
_COL_YAW_RC:    Final[str] = "Yaw rate (deg/s)"

# Physical constants

_G: Final[float] = 9.80665

# Quality thresholds

_MIN_SAMPLES_PER_LAP: Final[int]   = 50     # below this a lap is suspect
_MAX_PLAUSIBLE_G:     Final[float] = 5.0    # above 5 g → sensor error
_GPS_SCATTER_GOOD_M:  Final[float] = 1.0    # < 1 m scatter = excellent GPS
_GPS_SCATTER_BAD_M:   Final[float] = 5.0    # > 5 m scatter = poor GPS
_DROPOUT_THRESHOLD_S: Final[float] = 0.5    # time gap > 0.5 s = dropout
_NOISE_FLOOR_GOOD:    Final[float] = 0.3    # RMS high-freq < 0.3 m/s² = clean
_NOISE_FLOOR_BAD:     Final[float] = 2.0    # > 2.0 m/s² = very noisy

# Adaptive percentile constants

_PERCENTILE_BASE:     Final[float] = 80.0
_PERCENTILE_LAP_RATE: Final[float] = 0.6
_PERCENTILE_MAX:      Final[float] = 98.0

# -- -

# Exceptions

# -- -


class DataQualityError(ValueError):
    """Raised when quality scoring encounters irrecoverable issues."""


# -- -

# DataQualityReport

# -- -


@dataclass
class DataQualityReport:
    """
    Comprehensive telemetry data quality assessment.

    Attributes
    ----------
    n_laps : int
        Total valid laps analysed.
    gps_quality : float
        GPS consistency score (0–1).  1 = very consistent cross-lap
        positions, no dropouts.
    accel_quality : float
        Accelerometer quality score (0–1).  1 = channels present, low
        noise, physically plausible.
    yaw_quality : float
        Yaw rate channel quality score (0–1).
    sample_rate_hz : float
        Estimated sample rate from time deltas.
    lap_time_consistency : float
        Lap time consistency score (0–1).  Low if huge outliers suggest
        bad lap splitting.
    overall_confidence : float
        Weighted composite quality score (0–1).
    recommended_speed_percentile : float
        Adaptive percentile for speed envelope computation.
    recommended_accel_percentile : float
        Adaptive percentile for accel/brake envelope computation.
    warnings : list[str]
        Human-readable quality warnings.
    """
    n_laps:                       int
    gps_quality:                  float
    accel_quality:                float
    yaw_quality:                  float
    sample_rate_hz:               float
    lap_time_consistency:         float
    overall_confidence:           float
    recommended_speed_percentile: float
    recommended_accel_percentile: float
    warnings:                     list[str] = field(default_factory=list)
    fusion_confidence:            float = -1.0  # -1 = not computed

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_laps":                       self.n_laps,
            "gps_quality":                  round(self.gps_quality, 3),
            "accel_quality":                round(self.accel_quality, 3),
            "yaw_quality":                  round(self.yaw_quality, 3),
            "sample_rate_hz":               round(self.sample_rate_hz, 1),
            "lap_time_consistency":         round(self.lap_time_consistency, 3),
            "overall_confidence":           round(self.overall_confidence, 3),
            "recommended_speed_percentile": round(self.recommended_speed_percentile, 1),
            "recommended_accel_percentile": round(self.recommended_accel_percentile, 1),
            "warnings":                     list(self.warnings),
            "fusion_confidence":            round(self.fusion_confidence, 3),
        }

    @property
    def confidence_level(self) -> str:
        """Human-readable confidence label."""
        if self.overall_confidence >= 0.75:
            return "high"
        if self.overall_confidence >= 0.45:
            return "medium"
        return "low"


# -- -

# Internal helpers

# -- -


def _has(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns and df[col].notna().any()


def _col_coverage(df: pd.DataFrame, col: str) -> float:
    """Fraction of non-NaN values for *col* in *df* (0–1)."""
    if col not in df.columns:
        return 0.0
    total = len(df)
    if total == 0:
        return 0.0
    return float(df[col].notna().sum()) / total


def _clamp01(v: float) -> float:
    """Clamp a value to [0, 1]."""
    return max(0.0, min(1.0, v))


def _estimate_sample_rate(
    resampled_laps: dict[int, pd.DataFrame],
) -> float:
    """Estimate median sample rate (Hz) from time deltas across all laps."""
    dts: list[float] = []
    for df in resampled_laps.values():
        if not _has(df, _COL_TIME):
            continue
        t = pd.to_numeric(df[_COL_TIME], errors="coerce").dropna().values
        if len(t) < 2:
            continue
        dt = np.diff(t)
        dt = dt[(dt > 0) & np.isfinite(dt)]
        if len(dt) > 0:
            dts.extend(dt.tolist())

    if not dts:
        return 0.0

    median_dt = float(np.median(dts))
    return 1.0 / median_dt if median_dt > 0 else 0.0


# -- -

# Public API — compute_gps_quality_score

# -- -


def compute_gps_quality_score(
    laps: dict[int, pd.DataFrame],
) -> float:
    """
    Score GPS data consistency and reliability (0–1).

    Factors
    ~~~~~~~
    1. **Cross-lap positional scatter** — at each distance bin, how tightly
       do laps agree on X/Y position?  Low scatter = high quality.
    2. **Dropout frequency** — fraction of time gaps that exceed a threshold.
    3. **Speed–distance consistency** — does ∫speed·dt ≈ total distance?

    Parameters
    ----------
    laps : dict[int, pd.DataFrame]
        Resampled lap DataFrames.

    Returns
    -------
    float
        Score in [0, 1].  1 = excellent GPS.
    """
    if not laps:
        return 0.0

    scores: list[float] = []

    # --- Factor 1: Positional scatter -
    scatter_score = _gps_scatter_score(laps)
    scores.append(scatter_score)

    # --- Factor 2: Dropout frequency -
    dropout_score = _gps_dropout_score(laps)
    scores.append(dropout_score)

    # --- Factor 3: Speed–distance consistency -
    consistency_score = _speed_distance_consistency(laps)
    scores.append(consistency_score)

    result = float(np.mean(scores))
    logger.debug(
        "GPS quality: scatter=%.2f, dropout=%.2f, speed_dist=%.2f → %.2f",
        scatter_score, dropout_score, consistency_score, result,
    )
    return _clamp01(result)


def _gps_scatter_score(laps: dict[int, pd.DataFrame]) -> float:
    """
    Score GPS quality from cross-lap positional scatter.

    Interpolates all laps onto a common distance grid and computes the
    mean standard deviation of X/Y positions across laps at each point.
    """
    first_df = next(iter(laps.values()))
    have_xy  = _has(first_df, _COL_X) and _has(first_df, _COL_Y)
    have_gps = _has(first_df, _COL_LAT) and _has(first_df, _COL_LON)

    if not have_xy and not have_gps:
        return 0.5   # no position data — neutral score

    if len(laps) < 2:
        return 0.7   # can't measure scatter with one lap

    # Build common grid

    all_d_max: list[float] = []
    all_d_min: list[float] = []
    for df in laps.values():
        if _has(df, _COL_DIST):
            d = pd.to_numeric(df[_COL_DIST], errors="coerce").dropna()
            if len(d) >= 2:
                all_d_min.append(float(d.iloc[0]))
                all_d_max.append(float(d.iloc[-1]))
    if not all_d_max:
        return 0.5

    d_min = float(np.median(all_d_min))
    d_max = float(np.median(all_d_max))
    if d_max <= d_min:
        return 0.5
    grid = np.linspace(d_min, d_max, 200)

    x_col = _COL_X if have_xy else _COL_LAT
    y_col = _COL_Y if have_xy else _COL_LON

    x_matrix: list[np.ndarray] = []
    y_matrix: list[np.ndarray] = []

    for df in laps.values():
        d = pd.to_numeric(df[_COL_DIST], errors="coerce").values if _has(df, _COL_DIST) else None
        xv = pd.to_numeric(df[x_col], errors="coerce").values if _has(df, x_col) else None
        yv = pd.to_numeric(df[y_col], errors="coerce").values if _has(df, y_col) else None
        if d is None or xv is None or yv is None:
            continue

        mask = np.isfinite(d) & np.isfinite(xv) & np.isfinite(yv)
        if mask.sum() < 2:
            continue
        d_c, x_c, y_c = d[mask], xv[mask], yv[mask]
        order = np.argsort(d_c)
        _, ui = np.unique(d_c[order], return_index=True)
        xi = np.interp(grid, d_c[order][ui], x_c[order][ui])
        yi = np.interp(grid, d_c[order][ui], y_c[order][ui])
        x_matrix.append(xi)
        y_matrix.append(yi)

    if len(x_matrix) < 2:
        return 0.5

    X = np.array(x_matrix)
    Y = np.array(y_matrix)

    # For lat/lon, convert scatter to approximate metres

    if not have_xy:
        cos_lat = np.cos(np.radians(np.nanmean(X)))
        X_scatter = np.nanstd(X, axis=0) * 111_320  # deg lat → m
        Y_scatter = np.nanstd(Y, axis=0) * 111_320 * cos_lat  # deg lon → m
    else:
        X_scatter = np.nanstd(X, axis=0)
        Y_scatter = np.nanstd(Y, axis=0)

    mean_scatter = float(np.nanmean(np.sqrt(X_scatter ** 2 + Y_scatter ** 2)))

    # Map scatter to 0–1 score

    if mean_scatter <= _GPS_SCATTER_GOOD_M:
        return 1.0
    if mean_scatter >= _GPS_SCATTER_BAD_M:
        return 0.0
    return _clamp01(
        1.0 - (mean_scatter - _GPS_SCATTER_GOOD_M)
        / (_GPS_SCATTER_BAD_M - _GPS_SCATTER_GOOD_M)
    )


def _gps_dropout_score(laps: dict[int, pd.DataFrame]) -> float:
    """Score based on fraction of time gaps exceeding the dropout threshold."""
    total_gaps   = 0
    dropout_gaps = 0

    for df in laps.values():
        if not _has(df, _COL_TIME):
            continue
        t = pd.to_numeric(df[_COL_TIME], errors="coerce").dropna().values
        if len(t) < 2:
            continue
        dt = np.diff(t)
        valid = dt[np.isfinite(dt) & (dt > 0)]
        if len(valid) == 0:
            continue
        total_gaps += len(valid)
        dropout_gaps += int((valid > _DROPOUT_THRESHOLD_S).sum())

    if total_gaps == 0:
        return 0.5

    dropout_frac = dropout_gaps / total_gaps
    # 0% dropouts → 1.0, 10%+ → 0.0

    return _clamp01(1.0 - dropout_frac * 10.0)


def _speed_distance_consistency(laps: dict[int, pd.DataFrame]) -> float:
    """
    Score consistency between speed integrated over time and recorded distance.

    On a clean dataset ∫speed·dt should closely match total distance.
    """
    ratios: list[float] = []

    for df in laps.values():
        if not (_has(df, _COL_SPEED) and _has(df, _COL_TIME) and _has(df, _COL_DIST)):
            continue
        speed = pd.to_numeric(df[_COL_SPEED], errors="coerce").values
        time  = pd.to_numeric(df[_COL_TIME],  errors="coerce").values
        dist  = pd.to_numeric(df[_COL_DIST],  errors="coerce").values

        mask = np.isfinite(speed) & np.isfinite(time) & np.isfinite(dist)
        if mask.sum() < 10:
            continue

        dt = np.diff(time[mask])
        integrated_dist = float(np.sum(speed[mask][:-1] * dt[dt > 0]))
        recorded_dist   = float(dist[mask][-1] - dist[mask][0])

        if recorded_dist > 1.0:
            ratio = integrated_dist / recorded_dist
            ratios.append(ratio)

    if not ratios:
        return 0.5

    # Perfect consistency → ratio = 1.0

    mean_ratio = float(np.mean(ratios))
    deviation  = abs(mean_ratio - 1.0)
    # 0% deviation → 1.0, 20%+ → 0.0

    return _clamp01(1.0 - deviation * 5.0)


# -- -

# Public API — compute_accel_quality_score

# -- -


def compute_accel_quality_score(
    laps: dict[int, pd.DataFrame],
) -> float:
    """
    Score accelerometer data quality (0–1).

    Factors
    ~~~~~~~
    1. **Channel presence** — are longitudinal and lateral accel columns
       present with good coverage?
    2. **Noise floor** — high-frequency energy in the signal (second
       difference proxy).
    3. **Physical plausibility** — are peak g-forces within the expected
       motorsport range (< 5 g)?

    Returns
    -------
    float
        Score in [0, 1].  1 = clean, plausible accel data.
    """
    if not laps:
        return 0.0

    scores: list[float] = []

    # --- Factor 1: Channel presence & coverage -
    presence_score = _accel_presence_score(laps)
    scores.append(presence_score)

    if presence_score < 0.1:
        # No accel data at all → can't score noise or plausibility

        return 0.0

    # --- Factor 2: Noise floor -
    noise_score = _accel_noise_score(laps)
    scores.append(noise_score)

    # --- Factor 3: Physical plausibility -
    plausibility_score = _accel_plausibility_score(laps)
    scores.append(plausibility_score)

    result = float(np.mean(scores))
    logger.debug(
        "Accel quality: presence=%.2f, noise=%.2f, plausibility=%.2f → %.2f",
        presence_score, noise_score, plausibility_score, result,
    )
    return _clamp01(result)


def _accel_presence_score(laps: dict[int, pd.DataFrame]) -> float:
    """Score based on whether accel channels exist and have good coverage."""
    long_coverage: list[float] = []
    lat_coverage:  list[float] = []

    for df in laps.values():
        long_coverage.append(_col_coverage(df, _COL_ACCEL_L))
        lat_coverage.append(_col_coverage(df, _COL_ACCEL_LAT))

    mean_long = float(np.mean(long_coverage))
    mean_lat  = float(np.mean(lat_coverage))

    # Both channels present with > 90% coverage → 1.0

    # Only one channel → 0.5

    # Neither → 0.0

    if mean_long > 0.5 and mean_lat > 0.5:
        return _clamp01((mean_long + mean_lat) / 2.0)
    if mean_long > 0.5 or mean_lat > 0.5:
        return 0.5 * max(mean_long, mean_lat)
    return 0.0


def _accel_noise_score(laps: dict[int, pd.DataFrame]) -> float:
    """
    Score accelerometer noise using the RMS of the second difference
    (proxy for high-frequency energy).
    """
    noise_levels: list[float] = []

    for df in laps.values():
        for col in (_COL_ACCEL_L, _COL_ACCEL_LAT):
            if not _has(df, col):
                continue
            arr = pd.to_numeric(df[col], errors="coerce").dropna().values
            if len(arr) < 10:
                continue
            # Second difference captures high-frequency content

            d2 = np.diff(arr, n=2)
            rms = float(np.sqrt(np.mean(d2 ** 2)))
            noise_levels.append(rms)

    if not noise_levels:
        return 0.5

    mean_noise = float(np.mean(noise_levels))

    if mean_noise <= _NOISE_FLOOR_GOOD:
        return 1.0
    if mean_noise >= _NOISE_FLOOR_BAD:
        return 0.0
    return _clamp01(
        1.0 - (mean_noise - _NOISE_FLOOR_GOOD)
        / (_NOISE_FLOOR_BAD - _NOISE_FLOOR_GOOD)
    )


def _accel_plausibility_score(laps: dict[int, pd.DataFrame]) -> float:
    """
    Score whether g-forces are within physically plausible range.

    If a significant fraction of samples exceed 5 g, the sensor is likely
    miscalibrated or corrupted.
    """
    total_samples   = 0
    implausible     = 0

    for df in laps.values():
        for col in (_COL_ACCEL_L, _COL_ACCEL_LAT):
            if not _has(df, col):
                continue
            arr = pd.to_numeric(df[col], errors="coerce").dropna().values
            total_samples += len(arr)
            implausible += int((np.abs(arr) > _MAX_PLAUSIBLE_G * _G).sum())

    if total_samples == 0:
        return 0.5

    implausible_frac = implausible / total_samples
    # 0% implausible → 1.0; 5%+ → 0.0

    return _clamp01(1.0 - implausible_frac * 20.0)


# -- -

# Yaw quality

# -- -


def _compute_yaw_quality(laps: dict[int, pd.DataFrame]) -> float:
    """Score yaw rate channel quality (0–1)."""
    if not laps:
        return 0.0

    coverages: list[float] = []
    for df in laps.values():
        cov = max(_col_coverage(df, _COL_YAW), _col_coverage(df, _COL_YAW_RC))
        coverages.append(cov)

    mean_cov = float(np.mean(coverages)) if coverages else 0.0

    if mean_cov < 0.1:
        return 0.0

    # Check noise on yaw channel

    noise_levels: list[float] = []
    for df in laps.values():
        yaw_col = _COL_YAW if _has(df, _COL_YAW) else (
            _COL_YAW_RC if _has(df, _COL_YAW_RC) else None
        )
        if yaw_col is None:
            continue
        arr = pd.to_numeric(df[yaw_col], errors="coerce").dropna().values
        if len(arr) < 10:
            continue
        d2 = np.diff(arr, n=2)
        rms = float(np.sqrt(np.mean(d2 ** 2)))
        noise_levels.append(rms)

    noise_score = 1.0
    if noise_levels:
        mean_noise = float(np.mean(noise_levels))
        # Yaw noise thresholds (deg/s² RMS of second diff)

        if mean_noise > 50.0:
            noise_score = 0.0
        elif mean_noise > 10.0:
            noise_score = _clamp01(1.0 - (mean_noise - 10.0) / 40.0)

    return _clamp01(mean_cov * 0.6 + noise_score * 0.4)


# -- -

# Lap time consistency

# -- -


def _compute_lap_time_consistency(lap_times: list[float]) -> float:
    """
    Score lap time consistency (0–1).

    Low score = huge outliers suggesting bad lap detection / in-laps.
    """
    valid = [t for t in lap_times if math.isfinite(t) and t > 0]

    if len(valid) < 2:
        return 0.5   # can't assess with < 2 laps

    arr = np.array(valid)
    median_t = float(np.median(arr))
    if median_t <= 0:
        return 0.5

    # Coefficient of variation

    cv = float(np.std(arr, ddof=1)) / median_t

    # Check for extreme outliers (> 2× or < 0.5× median)

    outlier_frac = float(((arr > median_t * 2) | (arr < median_t * 0.5)).sum()) / len(arr)

    # CV < 2% → excellent; > 15% → poor

    cv_score = _clamp01(1.0 - (cv - 0.02) / 0.13)

    # Outlier fraction: 0% → 1.0; > 20% → 0.0

    outlier_score = _clamp01(1.0 - outlier_frac * 5.0)

    return cv_score * 0.6 + outlier_score * 0.4


# -- -

# Public API — adaptive_percentile

# -- -


def adaptive_percentile(
    n_laps: int,
    quality_score: float,
) -> float:
    """
    Compute the recommended percentile for theoretical envelope building.

    With few laps, high percentiles (p98) select near-maximum values at
    every distance bin, creating an impossibly fast composite.  This
    function scales the percentile down with fewer laps and lower data
    quality.

    Formula::

        base  = min(98, 80 + n_laps × 0.6)
        floor = 75
        result = floor + (base − floor) × quality_score

    The quality score scales the *boost above the floor*, so even poor
    quality data gets at least p75, while excellent quality with many laps
    approaches p98.

    Examples
    --------
    - 30 laps, quality 1.0  → base=98,  result = 75 + 23×1.0 = 98.0
    - 12 laps, quality 1.0  → base=87.2, result = 75 + 12.2×1.0 = 87.2
    - 12 laps, quality 0.7  → base=87.2, result = 75 + 12.2×0.7 = 83.5
    -  5 laps, quality 1.0  → base=83.0, result = 75 + 8×1.0 = 83.0
    -  5 laps, quality 0.5  → base=83.0, result = 75 + 8×0.5 = 79.0

    The result is clamped to [75, 98].

    Parameters
    ----------
    n_laps : int
        Number of valid laps.
    quality_score : float
        Overall data quality (0–1).

    Returns
    -------
    float
        Recommended percentile.
    """
    _FLOOR = 75.0
    base = min(_PERCENTILE_MAX, _PERCENTILE_BASE + n_laps * _PERCENTILE_LAP_RATE)
    q = max(0.0, min(1.0, quality_score))
    scaled = _FLOOR + (base - _FLOOR) * q
    return max(_FLOOR, min(_PERCENTILE_MAX, scaled))


# -- -

# Public API — score_data_quality

# -- -


def score_data_quality(
    resampled_laps: dict[int, pd.DataFrame],
    lap_times: list[float],
) -> DataQualityReport:
    """
    Comprehensive telemetry data quality assessment.

    Evaluates GPS consistency, accelerometer quality, yaw channel quality,
    sample rate, and lap time consistency.  Produces adaptive percentile
    recommendations for the theoretical lap computation.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        Distance-resampled lap DataFrames.
    lap_times : list[float]
        Lap durations in seconds.

    Returns
    -------
    DataQualityReport
    """
    if not resampled_laps:
        return DataQualityReport(
            n_laps=0,
            gps_quality=0.0,
            accel_quality=0.0,
            yaw_quality=0.0,
            sample_rate_hz=0.0,
            lap_time_consistency=0.0,
            overall_confidence=0.0,
            recommended_speed_percentile=75.0,
            recommended_accel_percentile=75.0,
            warnings=["No valid laps provided."],
        )

    n_laps = len(resampled_laps)
    warnings: list[str] = []

    # --- Component scores -
    gps_q   = compute_gps_quality_score(resampled_laps)
    accel_q = compute_accel_quality_score(resampled_laps)
    yaw_q   = _compute_yaw_quality(resampled_laps)
    sr      = _estimate_sample_rate(resampled_laps)
    lt_cons = _compute_lap_time_consistency(lap_times)

    # --- Warnings -
    if n_laps < 5:
        warnings.append(
            f"Very few laps ({n_laps}); statistical metrics will be unreliable."
        )
    elif n_laps < 15:
        warnings.append(
            f"Moderate lap count ({n_laps}); theoretical lap may be optimistic."
        )

    if gps_q < 0.4:
        warnings.append(
            f"Poor GPS quality ({gps_q:.2f}); positional scatter or dropouts detected."
        )

    if accel_q < 0.3:
        warnings.append(
            "Accelerometer data absent or very noisy; friction model will be imprecise."
        )
    elif accel_q < 0.6:
        warnings.append(
            f"Moderate accelerometer quality ({accel_q:.2f}); some noise detected."
        )

    if yaw_q < 0.3:
        warnings.append("Yaw rate channel absent or very noisy.")

    if sr > 0 and sr < 5.0:
        warnings.append(
            f"Low sample rate ({sr:.1f} Hz); telemetry may miss transient events."
        )

    if lt_cons < 0.4:
        warnings.append(
            "Lap time outliers detected; some laps may include pit stops "
            "or bad detection."
        )

    # Check for undersized laps

    short_laps = 0
    for df in resampled_laps.values():
        if len(df) < _MIN_SAMPLES_PER_LAP:
            short_laps += 1
    if short_laps > 0:
        warnings.append(
            f"{short_laps} lap(s) have fewer than {_MIN_SAMPLES_PER_LAP} samples."
        )

    # --- Overall confidence -
    # Lap count contribution: ramps from 0 (1 lap) to 1 (≥ 20 laps)

    lap_count_score = _clamp01((n_laps - 1) / 19.0)

    overall = (
        gps_q   * 0.25 +
        accel_q * 0.20 +
        yaw_q   * 0.10 +
        lt_cons * 0.15 +
        lap_count_score * 0.30
    )
    overall = _clamp01(overall)

    # --- Adaptive percentiles -
    speed_pct = adaptive_percentile(n_laps, overall)
    accel_pct = adaptive_percentile(n_laps, overall)
    # Accel percentile should be slightly higher (fewer extreme outliers)

    accel_pct = min(_PERCENTILE_MAX, accel_pct + 1.0)

    report = DataQualityReport(
        n_laps=n_laps,
        gps_quality=round(gps_q, 3),
        accel_quality=round(accel_q, 3),
        yaw_quality=round(yaw_q, 3),
        sample_rate_hz=round(sr, 1),
        lap_time_consistency=round(lt_cons, 3),
        overall_confidence=round(overall, 3),
        recommended_speed_percentile=round(speed_pct, 1),
        recommended_accel_percentile=round(accel_pct, 1),
        warnings=warnings,
    )

    logger.info(
        "Data quality: n_laps=%d, gps=%.2f, accel=%.2f, yaw=%.2f, "
        "sr=%.1fHz, lt_consistency=%.2f → confidence=%.2f (%s), "
        "speed_pct=%.1f, accel_pct=%.1f, warnings=%d",
        n_laps, gps_q, accel_q, yaw_q, sr, lt_cons,
        overall, report.confidence_level,
        speed_pct, accel_pct, len(warnings),
    )
    return report


# ============================================================================

# Inline tests

# ============================================================================


def _run_tests() -> None:
    """
    Inline unit tests using synthetic data.
    Raises AssertionError on failure; prints a pass/fail summary.
    """
    import traceback

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:  # type: ignore[type-arg]
        try:
            fn()
            passed.append(name)
        except Exception:  # noqa: BLE001
            failed.append((name, traceback.format_exc()))

    # -- -

    # Fixtures

    # -- -

    N_PTS = 500
    TRACK_LEN = 700.0

    def _make_clean_laps(
        n_laps: int = 12,
        noise_m: float = 0.5,
        has_accel: bool = True,
        has_yaw: bool = True,
        sample_rate_hz: float = 25.0,
    ) -> tuple[dict[int, pd.DataFrame], list[float]]:
        """Generate clean synthetic laps."""
        rng = np.random.default_rng(42)
        laps: dict[int, pd.DataFrame] = {}
        lap_times: list[float] = []

        for ln in range(1, n_laps + 1):
            dist = np.linspace(0, TRACK_LEN, N_PTS)
            # Circular-ish track: X/Y from parametric

            theta = dist / TRACK_LEN * 2 * np.pi
            x = 100 * np.cos(theta) + rng.normal(0, noise_m, N_PTS)
            y = 100 * np.sin(theta) + rng.normal(0, noise_m, N_PTS)
            speed = 20.0 + 5.0 * np.sin(theta * 4)
            dt_val = 1.0 / sample_rate_hz
            t = np.arange(N_PTS) * dt_val
            lap_time = float(t[-1] - t[0]) * (1 + rng.normal(0, 0.01))
            lap_times.append(lap_time)

            data: dict[str, Any] = {
                _COL_DIST:  dist,
                _COL_X:     x,
                _COL_Y:     y,
                _COL_SPEED: speed,
                _COL_TIME:  t,
            }
            if has_accel:
                data[_COL_ACCEL_L]   = rng.normal(0, 2, N_PTS)
                data[_COL_ACCEL_LAT] = rng.normal(0, 3, N_PTS)
            if has_yaw:
                data[_COL_YAW] = rng.normal(0, 30, N_PTS)

            laps[ln] = pd.DataFrame(data)
        return laps, lap_times

    # -- -

    # Test 1 — clean data → high confidence

    # -- -

    def t_clean_high_confidence() -> None:
        laps, times = _make_clean_laps(n_laps=20, noise_m=0.3)
        report = score_data_quality(laps, times)
        assert report.n_laps == 20
        assert report.overall_confidence > 0.6, (
            f"Clean 20-lap data should have high confidence, got {report.overall_confidence:.2f}"
        )
        assert report.confidence_level in ("high", "medium")
        assert report.recommended_speed_percentile > 85

    _test("clean_high_confidence", t_clean_high_confidence)

    # -- -

    # Test 2 — few laps → lower confidence

    # -- -

    def t_few_laps_lower_confidence() -> None:
        laps_20, times_20 = _make_clean_laps(n_laps=20)
        laps_5, times_5   = _make_clean_laps(n_laps=5)
        r20 = score_data_quality(laps_20, times_20)
        r5  = score_data_quality(laps_5, times_5)
        assert r5.overall_confidence < r20.overall_confidence, (
            f"5 laps ({r5.overall_confidence:.2f}) should have lower "
            f"confidence than 20 ({r20.overall_confidence:.2f})"
        )

    _test("few_laps_lower_confidence", t_few_laps_lower_confidence)

    # -- -

    # Test 3 — no accel channels → lower accel quality

    # -- -

    def t_no_accel_low_score() -> None:
        laps, times = _make_clean_laps(has_accel=False)
        report = score_data_quality(laps, times)
        assert report.accel_quality == 0.0
        assert any("cceleromet" in w for w in report.warnings)

    _test("no_accel_low_score", t_no_accel_low_score)

    # -- -

    # Test 4 — no yaw → lower yaw quality

    # -- -

    def t_no_yaw_low_score() -> None:
        laps, times = _make_clean_laps(has_yaw=False)
        report = score_data_quality(laps, times)
        assert report.yaw_quality == 0.0

    _test("no_yaw_low_score", t_no_yaw_low_score)

    # -- -

    # Test 5 — GPS scatter: clean vs noisy

    # -- -

    def t_gps_scatter_impact() -> None:
        laps_clean, _ = _make_clean_laps(noise_m=0.2)
        laps_noisy, _ = _make_clean_laps(noise_m=4.0)
        q_clean = compute_gps_quality_score(laps_clean)
        q_noisy = compute_gps_quality_score(laps_noisy)
        assert q_clean > q_noisy, (
            f"Clean GPS ({q_clean:.2f}) should score higher than noisy ({q_noisy:.2f})"
        )

    _test("gps_scatter_impact", t_gps_scatter_impact)

    # -- -

    # Test 6 — accel quality: clean vs noisy

    # -- -

    def t_accel_quality_clean_vs_noisy() -> None:
        rng = np.random.default_rng(99)
        # Clean: low-noise accel

        laps_clean: dict[int, pd.DataFrame] = {}
        for ln in range(1, 6):
            laps_clean[ln] = pd.DataFrame({
                _COL_ACCEL_L:   rng.normal(0, 0.5, 200),
                _COL_ACCEL_LAT: rng.normal(0, 0.5, 200),
            })

        # Noisy: high-noise + implausible spikes

        laps_noisy: dict[int, pd.DataFrame] = {}
        for ln in range(1, 6):
            a_long = rng.normal(0, 5, 200)
            a_long[50] = 200.0  # implausible spike
            laps_noisy[ln] = pd.DataFrame({
                _COL_ACCEL_L:   a_long,
                _COL_ACCEL_LAT: rng.normal(0, 5, 200),
            })

        q_clean = compute_accel_quality_score(laps_clean)
        q_noisy = compute_accel_quality_score(laps_noisy)
        assert q_clean > q_noisy, (
            f"Clean accel ({q_clean:.2f}) > noisy ({q_noisy:.2f})"
        )

    _test("accel_quality_clean_vs_noisy", t_accel_quality_clean_vs_noisy)

    # -- -

    # Test 7 — adaptive percentile scales with laps

    # -- -

    def t_adaptive_percentile_scaling() -> None:
        p5  = adaptive_percentile(5,  1.0)
        p12 = adaptive_percentile(12, 1.0)
        p30 = adaptive_percentile(30, 1.0)
        assert p5 < p12 < p30, f"p5={p5}, p12={p12}, p30={p30}"
        assert p30 <= 98.0
        assert p5  >= 75.0

    _test("adaptive_percentile_scaling", t_adaptive_percentile_scaling)

    # -- -

    # Test 8 — adaptive percentile: low quality reduces percentile

    # -- -

    def t_adaptive_percentile_quality() -> None:
        p_good = adaptive_percentile(12, 1.0)
        p_bad  = adaptive_percentile(12, 0.5)
        assert p_bad < p_good, f"p_bad={p_bad} should be < p_good={p_good}"

    _test("adaptive_percentile_quality", t_adaptive_percentile_quality)

    # -- -

    # Test 9 — adaptive percentile known values

    # -- -

    def t_adaptive_percentile_values() -> None:
        # 30 laps, quality 1.0 → 98.0

        assert adaptive_percentile(30, 1.0) == 98.0
        # 12 laps, quality 1.0 → min(98, 80+7.2) = 87.2

        p12 = adaptive_percentile(12, 1.0)
        assert abs(p12 - 87.2) < 0.1, f"Expected 87.2, got {p12}"
        # 5 laps, quality 1.0 → min(98, 80+3) = 83.0

        p5 = adaptive_percentile(5, 1.0)
        assert abs(p5 - 83.0) < 0.1, f"Expected 83.0, got {p5}"

    _test("adaptive_percentile_values", t_adaptive_percentile_values)

    # -- -

    # Test 10 — empty laps → zero confidence

    # -- -

    def t_empty_laps_zero() -> None:
        report = score_data_quality({}, [])
        assert report.overall_confidence == 0.0
        assert report.n_laps == 0

    _test("empty_laps_zero", t_empty_laps_zero)

    # -- -

    # Test 11 — lap time outliers detected

    # -- -

    def t_lap_time_outliers() -> None:
        good_times = [55.0, 55.5, 54.8, 55.2, 55.1, 54.9, 55.3]
        bad_times  = [55.0, 55.5, 200.0, 55.2, 10.0, 54.9, 55.3]
        c_good = _compute_lap_time_consistency(good_times)
        c_bad  = _compute_lap_time_consistency(bad_times)
        assert c_good > c_bad, (
            f"Good times ({c_good:.2f}) should be more consistent than "
            f"bad times ({c_bad:.2f})"
        )

    _test("lap_time_outliers", t_lap_time_outliers)

    # -- -

    # Test 12 — sample rate estimation

    # -- -

    def t_sample_rate_estimation() -> None:
        laps, _ = _make_clean_laps(sample_rate_hz=25.0)
        sr = _estimate_sample_rate(laps)
        assert abs(sr - 25.0) < 1.0, f"Expected ~25 Hz, got {sr:.1f} Hz"

    _test("sample_rate_estimation", t_sample_rate_estimation)

    # -- -

    # Test 13 — DataQualityReport serialisation

    # -- -

    def t_report_to_dict() -> None:
        laps, times = _make_clean_laps()
        report = score_data_quality(laps, times)
        d = report.to_dict()
        assert "n_laps" in d
        assert "overall_confidence" in d
        assert "warnings" in d
        assert isinstance(d["warnings"], list)

    _test("report_to_dict", t_report_to_dict)

    # -- -

    # Test 14 — confidence_level property

    # -- -

    def t_confidence_level() -> None:
        r = DataQualityReport(
            n_laps=10, gps_quality=1.0, accel_quality=1.0,
            yaw_quality=1.0, sample_rate_hz=25.0,
            lap_time_consistency=1.0, overall_confidence=0.8,
            recommended_speed_percentile=90.0,
            recommended_accel_percentile=91.0,
        )
        assert r.confidence_level == "high"
        r2 = DataQualityReport(
            n_laps=3, gps_quality=0.5, accel_quality=0.5,
            yaw_quality=0.5, sample_rate_hz=10.0,
            lap_time_consistency=0.5, overall_confidence=0.5,
            recommended_speed_percentile=80.0,
            recommended_accel_percentile=81.0,
        )
        assert r2.confidence_level == "medium"
        r3 = DataQualityReport(
            n_laps=2, gps_quality=0.2, accel_quality=0.0,
            yaw_quality=0.0, sample_rate_hz=5.0,
            lap_time_consistency=0.3, overall_confidence=0.2,
            recommended_speed_percentile=75.0,
            recommended_accel_percentile=76.0,
        )
        assert r3.confidence_level == "low"

    _test("confidence_level_property", t_confidence_level)

    # -- -

    # Test 15 — warnings populated for bad data

    # -- -

    def t_warnings_populated() -> None:
        laps, times = _make_clean_laps(n_laps=3, has_accel=False, has_yaw=False)
        report = score_data_quality(laps, times)
        assert len(report.warnings) >= 2, (
            f"Expected ≥2 warnings for 3-lap no-accel data, got {report.warnings}"
        )

    _test("warnings_populated", t_warnings_populated)

    # -- -

    # Test 16 — GPS quality with no position data → neutral

    # -- -

    def t_gps_no_position() -> None:
        laps = {1: pd.DataFrame({_COL_DIST: np.linspace(0, 500, 100)})}
        q = compute_gps_quality_score(laps)
        assert 0.3 <= q <= 0.7, f"No position → neutral score, got {q:.2f}"

    _test("gps_no_position_neutral", t_gps_no_position)

    # -- -

    # Test 17 — speed–distance consistency: perfect match → high score

    # -- -

    def t_speed_dist_perfect() -> None:
        n = 200
        dist = np.linspace(0, 500, n)
        speed = np.full(n, 25.0)
        dt = np.diff(dist) / speed[:-1]
        t = np.concatenate([[0.0], np.cumsum(dt)])
        laps = {1: pd.DataFrame({
            _COL_DIST: dist, _COL_SPEED: speed, _COL_TIME: t,
        })}
        score = _speed_distance_consistency(laps)
        assert score > 0.8, f"Perfect speed/dist match should score > 0.8, got {score:.2f}"

    _test("speed_dist_perfect", t_speed_dist_perfect)

    # -- -

    # Test 18 — single lap → still produces a report

    # -- -

    def t_single_lap() -> None:
        laps, times = _make_clean_laps(n_laps=1)
        report = score_data_quality(laps, times)
        assert report.n_laps == 1
        assert report.overall_confidence >= 0.0
        assert report.recommended_speed_percentile >= 75.0

    _test("single_lap_report", t_single_lap)

    # -- -

    # Test 19 — adaptive percentile floor at 75

    # -- -

    def t_percentile_floor() -> None:
        p = adaptive_percentile(2, 0.0)
        assert p == 75.0, f"Floor should be 75, got {p}"

    _test("percentile_floor_75", t_percentile_floor)

    # -- -

    # Test 20 — dropout score: no dropouts → 1.0

    # -- -

    def t_dropout_no_dropouts() -> None:
        t = np.linspace(0, 10, 500)  # uniform 50 Hz, no gaps
        laps = {1: pd.DataFrame({_COL_TIME: t})}
        score = _gps_dropout_score(laps)
        assert score == 1.0, f"No dropouts → 1.0, got {score:.2f}"

    _test("dropout_no_dropouts", t_dropout_no_dropouts)

    # -- -

    # Summary

    # -- -

    total = len(passed) + len(failed)
    print(f"\nData Quality Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  ✓ {name}")
    for name, tb in failed:
        print(f"  ✗ {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
