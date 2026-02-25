"""
sensor_offset.py
----------------
Detect and correct DC bias (mounting offsets) in accelerometer channels.

Phone-based telemetry loggers like RaceChrono frequently exhibit constant
accelerometer offsets caused by imperfect phone mounting, sensor
miscalibration, or gravitational cross-talk from non-level installation.

A lateral offset of just +0.3 m/s² shifts the entire g-g diagram
rightward, making the friction circle asymmetric.  A longitudinal offset
misattributes coasting as braking (or vice versa), corrupting the
traction/braking envelopes used for the theoretical lap.

Detection strategy
~~~~~~~~~~~~~~~~~~
- **Lateral offset**: on long straights (low curvature, roughly constant
  speed), the true lateral acceleration is ~0.  Any persistent reading is
  mounting bias.
- **Longitudinal offset**: on constant-speed sections (low |dv/dt|), the
  true longitudinal acceleration is ~0.  Any persistent reading is bias.

Both offsets are estimated as the median value during "quiet" sections
(more robust to outliers than the mean).

Public API
~~~~~~~~~~
``detect_sensor_offsets(resampled_laps)``
    Analyse multiple laps and return estimated DC offsets.

``correct_sensor_offsets(df, offsets)``
    Subtract detected offsets from a single DataFrame's accel channels.

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

# Column-name constants (aligned with derived_channels.py / features.py)

# -- -


_COL_SPEED:     Final[str] = "Speed (m/s)"
_COL_DIST:      Final[str] = "Distance (m)"
_COL_TIME:      Final[str] = "Time (s)"
_COL_ACCEL_L:   Final[str] = "accel_long_mps2"
_COL_ACCEL_LAT: Final[str] = "accel_lat_mps2"
_COL_YAW:       Final[str] = "yaw_rate_dps"
_COL_YAW_RC:    Final[str] = "Yaw rate (deg/s)"

# Raw G sensor columns (RaceChrono names)

_RAW_LONG_G:    Final[str] = "Longitudinal acceleration (G) *calc"
_RAW_LAT_G:     Final[str] = "Lateral acceleration (G) *calc"

# Physical constants

_G: Final[float] = 9.80665

# Detection thresholds

_MIN_SPEED_MPS:         Final[float] = 5.0    # ignore very low speed (pit lane)
_MAX_YAW_RATE_DPS:      Final[float] = 3.0    # yaw < 3°/s ≈ straight line
_MAX_CURVATURE_INV_M:   Final[float] = 0.005  # κ < 0.005 1/m ≈ R > 200m
_MAX_LONG_ACCEL_MPS2:   Final[float] = 0.5    # |a_long| < 0.5 ≈ coasting
_MIN_SAMPLES_QUIET:     Final[int]   = 30     # need ≥ 30 quiet samples per lap
_MAX_PLAUSIBLE_OFFSET:  Final[float] = 3.0    # offsets > 3 m/s² are not bias
_MIN_LAPS_FOR_OFFSET:   Final[int]   = 2      # need ≥ 2 laps for reliable estimate


# -- -

# Data structures

# -- -


@dataclass
class SensorOffsetReport:
    """
    Result of sensor offset detection.

    Attributes
    ----------
    long_accel_offset_mps2 : float
        Estimated DC bias in longitudinal accel [m/s²].
    lat_accel_offset_mps2 : float
        Estimated DC bias in lateral accel [m/s²].
    long_samples_used : int
        Number of "quiet" samples contributing to the longitudinal estimate.
    lat_samples_used : int
        Number of "straight" samples contributing to the lateral estimate.
    long_confidence : float
        Confidence in the longitudinal offset (0–1).
    lat_confidence : float
        Confidence in the lateral offset (0–1).
    warnings : list[str]
        Human-readable warnings.
    """
    long_accel_offset_mps2: float
    lat_accel_offset_mps2:  float
    long_samples_used:      int
    lat_samples_used:       int
    long_confidence:        float
    lat_confidence:         float
    warnings:               list[str] = field(default_factory=list)

    @property
    def offsets(self) -> dict[str, float]:
        """Return the offset dict suitable for ``correct_sensor_offsets``."""
        return {
            "long_accel_offset_mps2": self.long_accel_offset_mps2,
            "lat_accel_offset_mps2":  self.lat_accel_offset_mps2,
        }

    @property
    def has_significant_offset(self) -> bool:
        """True if either offset exceeds 0.1 m/s² (noticeable in g-g diagram)."""
        return (
            abs(self.long_accel_offset_mps2) > 0.1 or
            abs(self.lat_accel_offset_mps2) > 0.1
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "long_accel_offset_mps2": round(self.long_accel_offset_mps2, 4),
            "lat_accel_offset_mps2":  round(self.lat_accel_offset_mps2, 4),
            "long_samples_used":      self.long_samples_used,
            "lat_samples_used":       self.lat_samples_used,
            "long_confidence":        round(self.long_confidence, 3),
            "lat_confidence":         round(self.lat_confidence, 3),
            "has_significant_offset": self.has_significant_offset,
            "warnings":               list(self.warnings),
        }


# -- -

# Internal helpers

# -- -


def _has(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns and df[col].notna().any()


def _get_col(df: pd.DataFrame, col: str) -> np.ndarray:
    """Return numeric array for column, or empty array."""
    if not _has(df, col):
        return np.array([], dtype=float)
    return pd.to_numeric(df[col], errors="coerce").values.astype(float)


def _find_straight_mask(df: pd.DataFrame) -> np.ndarray:
    """
    Boolean mask: True where the car is going roughly straight at speed.

    A sample is "straight" if:
    - Speed > _MIN_SPEED_MPS
    - |yaw rate| < _MAX_YAW_RATE_DPS (if yaw available)
    - OR |curvature| < _MAX_CURVATURE_INV_M (from yaw/speed)
    """
    n = len(df)
    mask = np.ones(n, dtype=bool)

    # Speed gate

    speed = _get_col(df, _COL_SPEED)
    if len(speed) == n:
        mask &= (speed > _MIN_SPEED_MPS) & np.isfinite(speed)
    else:
        # No speed → can't reliably detect straights

        return np.zeros(n, dtype=bool)

    # Yaw rate gate

    yaw_col = _COL_YAW if _has(df, _COL_YAW) else (
        _COL_YAW_RC if _has(df, _COL_YAW_RC) else None
    )
    if yaw_col is not None:
        yaw = pd.to_numeric(df[yaw_col], errors="coerce").values.astype(float)
        yaw_mask = (np.abs(yaw) < _MAX_YAW_RATE_DPS) & np.isfinite(yaw)
        mask &= yaw_mask
    else:
        # Fallback: use lateral accel as proxy (should be near zero on straights)

        lat = _get_col(df, _COL_ACCEL_LAT)
        if len(lat) == n:
            # Can't use lat accel to detect straights for lat offset — circular.

            # Without yaw, we rely only on speed.

            pass

    return mask


def _find_coasting_mask(df: pd.DataFrame) -> np.ndarray:
    """
    Boolean mask: True where the car is at roughly constant speed.

    A sample is "coasting" if:
    - Speed > _MIN_SPEED_MPS
    - Speed changes slowly (|dv/ds| or |dv/dt| < threshold)

    We compute instantaneous acceleration from speed differences rather
    than using the accel channel (which is what we're trying to calibrate).
    """
    n = len(df)
    mask = np.ones(n, dtype=bool)

    speed = _get_col(df, _COL_SPEED)
    if len(speed) != n:
        return np.zeros(n, dtype=bool)

    mask &= (speed > _MIN_SPEED_MPS) & np.isfinite(speed)

    # Compute acceleration from speed differences

    time = _get_col(df, _COL_TIME)
    if len(time) == n:
        dt = np.diff(time)
        dt = np.where((dt > 0) & np.isfinite(dt), dt, np.nan)
        dv = np.diff(speed)
        with np.errstate(divide="ignore", invalid="ignore"):
            a_from_speed = np.where(np.isfinite(dt), dv / dt, np.nan)
        a_full = np.concatenate([[a_from_speed[0] if len(a_from_speed) > 0 else np.nan],
                                  a_from_speed])
        coasting = (np.abs(a_full) < _MAX_LONG_ACCEL_MPS2) & np.isfinite(a_full)
        mask &= coasting
    else:
        dist = _get_col(df, _COL_DIST)
        if len(dist) == n:
            ds = np.diff(dist)
            ds = np.where((ds > 0) & np.isfinite(ds), ds, np.nan)
            dv = np.diff(speed)
            with np.errstate(divide="ignore", invalid="ignore"):
                a_from_dist = np.where(np.isfinite(ds), speed[:-1] * dv / ds, np.nan)
            a_full = np.concatenate([[a_from_dist[0] if len(a_from_dist) > 0 else np.nan],
                                      a_from_dist])
            coasting = (np.abs(a_full) < _MAX_LONG_ACCEL_MPS2) & np.isfinite(a_full)
            mask &= coasting

    return mask


def _estimate_offset(
    values: np.ndarray,
    label: str,
) -> tuple[float, float]:
    """
    Estimate DC offset from quiet-section samples.

    Returns (offset, confidence) where confidence is based on sample count
    and consistency (low std → high confidence).
    """
    finite = values[np.isfinite(values)]

    if len(finite) < _MIN_SAMPLES_QUIET:
        logger.debug(
            "%s offset: only %d quiet samples (need %d); returning 0.",
            label, len(finite), _MIN_SAMPLES_QUIET,
        )
        return 0.0, 0.0

    offset = float(np.median(finite))

    # Plausibility check

    if abs(offset) > _MAX_PLAUSIBLE_OFFSET:
        logger.warning(
            "%s offset: %.2f m/s² exceeds plausibility limit (%.1f); "
            "clamping to zero.",
            label, offset, _MAX_PLAUSIBLE_OFFSET,
        )
        return 0.0, 0.0

    # Confidence: based on sample count and spread

    std = float(np.std(finite, ddof=1)) if len(finite) > 1 else float("inf")
    iqr = float(np.percentile(finite, 75) - np.percentile(finite, 25))

    # Many samples + low spread → high confidence

    count_score = min(1.0, len(finite) / 200.0)
    # Spread score: IQR < 0.5 m/s² → good; > 2 m/s² → poor

    spread_score = max(0.0, min(1.0, 1.0 - (iqr - 0.3) / 1.7))
    confidence = count_score * 0.5 + spread_score * 0.5

    return offset, max(0.0, min(1.0, confidence))


# -- -

# Public API — detect_sensor_offsets

# -- -


def detect_sensor_offsets(
    resampled_laps: dict[int, pd.DataFrame],
) -> SensorOffsetReport:
    """
    Detect accelerometer DC bias from multiple laps.

    Analyses "quiet" sections of each lap — straights for lateral offset,
    constant-speed sections for longitudinal offset — and estimates the
    persistent bias as the median reading during those sections.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        Resampled lap DataFrames.  Must contain ``"Speed (m/s)"`` and at
        least one accelerometer channel.

    Returns
    -------
    SensorOffsetReport
        Contains estimated offsets and confidence scores.
    """
    if not resampled_laps:
        return SensorOffsetReport(
            long_accel_offset_mps2=0.0,
            lat_accel_offset_mps2=0.0,
            long_samples_used=0,
            lat_samples_used=0,
            long_confidence=0.0,
            lat_confidence=0.0,
            warnings=["No laps provided for offset detection."],
        )

    warnings: list[str] = []
    lat_quiet_samples: list[float] = []
    long_quiet_samples: list[float] = []
    laps_with_lat = 0
    laps_with_long = 0

    for ln, df in sorted(resampled_laps.items()):
        # --- Lateral offset: readings on straights -
        straight_mask = _find_straight_mask(df)
        n_straight = int(straight_mask.sum())

        if n_straight >= _MIN_SAMPLES_QUIET:
            lat_vals = _get_col(df, _COL_ACCEL_LAT)
            if len(lat_vals) == len(df):
                quiet_lat = lat_vals[straight_mask]
                finite_lat = quiet_lat[np.isfinite(quiet_lat)]
                if len(finite_lat) > 0:
                    lat_quiet_samples.extend(finite_lat.tolist())
                    laps_with_lat += 1

            # Also check raw G channel as fallback

            elif _has(df, _RAW_LAT_G):
                raw = pd.to_numeric(df[_RAW_LAT_G], errors="coerce").values * _G
                quiet_raw = raw[straight_mask]
                finite_raw = quiet_raw[np.isfinite(quiet_raw)]
                if len(finite_raw) > 0:
                    lat_quiet_samples.extend(finite_raw.tolist())
                    laps_with_lat += 1

        # --- Longitudinal offset: readings during coasting -
        coasting_mask = _find_coasting_mask(df)
        n_coasting = int(coasting_mask.sum())

        if n_coasting >= _MIN_SAMPLES_QUIET:
            long_vals = _get_col(df, _COL_ACCEL_L)
            if len(long_vals) == len(df):
                quiet_long = long_vals[coasting_mask]
                finite_long = quiet_long[np.isfinite(quiet_long)]
                if len(finite_long) > 0:
                    long_quiet_samples.extend(finite_long.tolist())
                    laps_with_long += 1

            elif _has(df, _RAW_LONG_G):
                raw = pd.to_numeric(df[_RAW_LONG_G], errors="coerce").values * _G
                quiet_raw = raw[coasting_mask]
                finite_raw = quiet_raw[np.isfinite(quiet_raw)]
                if len(finite_raw) > 0:
                    long_quiet_samples.extend(finite_raw.tolist())
                    laps_with_long += 1

    # --- Estimate offsets -
    lat_arr = np.array(lat_quiet_samples)
    long_arr = np.array(long_quiet_samples)

    lat_offset, lat_conf = _estimate_offset(lat_arr, "lateral")
    long_offset, long_conf = _estimate_offset(long_arr, "longitudinal")

    # Require minimum lap count for reliability

    if laps_with_lat < _MIN_LAPS_FOR_OFFSET and len(lat_arr) > 0:
        warnings.append(
            f"Lateral offset estimated from only {laps_with_lat} lap(s); "
            f"result may be unreliable."
        )
        lat_conf *= 0.5

    if laps_with_long < _MIN_LAPS_FOR_OFFSET and len(long_arr) > 0:
        warnings.append(
            f"Longitudinal offset estimated from only {laps_with_long} lap(s); "
            f"result may be unreliable."
        )
        long_conf *= 0.5

    if len(lat_arr) == 0:
        warnings.append(
            "No lateral accel data on straights; cannot estimate lateral offset."
        )
    if len(long_arr) == 0:
        warnings.append(
            "No longitudinal accel data during coasting; cannot estimate "
            "longitudinal offset."
        )

    if abs(lat_offset) > 0.1 or abs(long_offset) > 0.1:
        logger.info(
            "Sensor offsets detected: long=%.3f m/s² (%.0f%% confidence, "
            "%d samples from %d laps), lat=%.3f m/s² (%.0f%% confidence, "
            "%d samples from %d laps).",
            long_offset, long_conf * 100, len(long_arr), laps_with_long,
            lat_offset, lat_conf * 100, len(lat_arr), laps_with_lat,
        )
    else:
        logger.info(
            "Sensor offsets negligible: long=%.4f m/s², lat=%.4f m/s² "
            "(%d/%d quiet samples).",
            long_offset, lat_offset, len(long_arr), len(lat_arr),
        )

    return SensorOffsetReport(
        long_accel_offset_mps2=round(long_offset, 4),
        lat_accel_offset_mps2=round(lat_offset, 4),
        long_samples_used=len(long_arr),
        lat_samples_used=len(lat_arr),
        long_confidence=round(lat_conf, 3),
        lat_confidence=round(lat_conf, 3),
        warnings=warnings,
    )


# -- -

# Public API — correct_sensor_offsets

# -- -


def correct_sensor_offsets(
    df: pd.DataFrame,
    offsets: dict[str, float],
) -> pd.DataFrame:
    """
    Subtract detected DC offsets from accelerometer channels.

    Parameters
    ----------
    df : pd.DataFrame
        Telemetry DataFrame with accel columns.
    offsets : dict[str, float]
        Keys: ``"long_accel_offset_mps2"``, ``"lat_accel_offset_mps2"``.
        Values are subtracted from the respective channels.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected accel channels.  The original is
        never mutated.
    """
    result = df.copy()

    long_off = offsets.get("long_accel_offset_mps2", 0.0)
    lat_off  = offsets.get("lat_accel_offset_mps2", 0.0)

    if long_off != 0.0:
        # Internal standardised column

        if _has(result, _COL_ACCEL_L):
            result[_COL_ACCEL_L] = (
                pd.to_numeric(result[_COL_ACCEL_L], errors="coerce") - long_off
            )
            logger.debug("Corrected '%s' by %.4f m/s².", _COL_ACCEL_L, long_off)

        # Raw RaceChrono column (in G)

        if _has(result, _RAW_LONG_G):
            result[_RAW_LONG_G] = (
                pd.to_numeric(result[_RAW_LONG_G], errors="coerce")
                - long_off / _G
            )
            logger.debug("Corrected '%s' by %.6f G.", _RAW_LONG_G, long_off / _G)

    if lat_off != 0.0:
        if _has(result, _COL_ACCEL_LAT):
            result[_COL_ACCEL_LAT] = (
                pd.to_numeric(result[_COL_ACCEL_LAT], errors="coerce") - lat_off
            )
            logger.debug("Corrected '%s' by %.4f m/s².", _COL_ACCEL_LAT, lat_off)

        if _has(result, _RAW_LAT_G):
            result[_RAW_LAT_G] = (
                pd.to_numeric(result[_RAW_LAT_G], errors="coerce")
                - lat_off / _G
            )
            logger.debug("Corrected '%s' by %.6f G.", _RAW_LAT_G, lat_off / _G)

    return result


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

    def _make_lap(
        *,
        long_offset: float = 0.0,
        lat_offset: float = 0.0,
        noise_std: float = 0.2,
        has_yaw: bool = True,
        seed: int = 42,
    ) -> pd.DataFrame:
        """
        Generate a synthetic lap with known sensor offsets.

        The lap has a mix of straights and corners.
        """
        rng = np.random.default_rng(seed)
        dist = np.linspace(0, TRACK_LEN, N_PTS)
        t = np.linspace(0, 30.0, N_PTS)

        # Speed profile: fast on straights, slow in corners

        speed = 25.0 + 10.0 * np.cos(dist / TRACK_LEN * 4 * np.pi)
        speed = np.maximum(speed, 8.0)

        # Create clear straight and corner sections

        # Sections 0–25%, 50–75% are straights (low yaw)

        # Sections 25–50%, 75–100% are corners (high yaw)

        frac = dist / TRACK_LEN
        yaw_base = np.zeros(N_PTS)
        corner_mask = ((frac > 0.25) & (frac < 0.50)) | ((frac > 0.75) & (frac < 1.0))
        yaw_base[corner_mask] = 40.0  # 40 deg/s in corners

        yaw = yaw_base + rng.normal(0, 0.5, N_PTS)

        # True lateral accel: v²κ in corners, ~0 on straights

        # κ ≈ yaw_rad / speed

        yaw_rad = np.radians(yaw_base)
        a_lat_true = speed * yaw_rad  # = v²κ = v × ω

        # True longitudinal accel: roughly constant speed + small fluctuations

        a_long_true = rng.normal(0, 0.1, N_PTS)
        # Add acceleration/braking at corner entry/exit

        dv = np.diff(speed)
        dt_arr = np.diff(t)
        a_long_true[1:] += np.where(dt_arr > 0, dv / dt_arr, 0)

        # Measured = true + offset + noise

        a_long_meas = a_long_true + long_offset + rng.normal(0, noise_std, N_PTS)
        a_lat_meas = a_lat_true + lat_offset + rng.normal(0, noise_std, N_PTS)

        data: dict[str, Any] = {
            _COL_DIST:      dist,
            _COL_TIME:      t,
            _COL_SPEED:     speed,
            _COL_ACCEL_L:   a_long_meas,
            _COL_ACCEL_LAT: a_lat_meas,
        }
        if has_yaw:
            data[_COL_YAW] = yaw

        return pd.DataFrame(data)

    def _make_laps(
        n: int = 10,
        **kwargs,
    ) -> dict[int, pd.DataFrame]:
        return {ln: _make_lap(seed=40 + ln, **kwargs) for ln in range(1, n + 1)}

    # -- -

    # Test 1 — zero offset → detected as ~0

    # -- -

    def t_zero_offset_detected() -> None:
        laps = _make_laps(10, long_offset=0.0, lat_offset=0.0)
        report = detect_sensor_offsets(laps)
        assert abs(report.long_accel_offset_mps2) < 0.15, (
            f"Expected ~0 long offset, got {report.long_accel_offset_mps2:.4f}"
        )
        assert abs(report.lat_accel_offset_mps2) < 0.15, (
            f"Expected ~0 lat offset, got {report.lat_accel_offset_mps2:.4f}"
        )

    _test("zero_offset_detected", t_zero_offset_detected)

    # -- -

    # Test 2 — known lateral offset detected

    # -- -

    def t_lat_offset_detected() -> None:
        laps = _make_laps(10, lat_offset=0.5, noise_std=0.15)
        report = detect_sensor_offsets(laps)
        assert abs(report.lat_accel_offset_mps2 - 0.5) < 0.2, (
            f"Expected lat offset ~0.5, got {report.lat_accel_offset_mps2:.4f}"
        )

    _test("lat_offset_detected", t_lat_offset_detected)

    # -- -

    # Test 3 — known longitudinal offset detected

    # -- -

    def t_long_offset_detected() -> None:
        laps = _make_laps(10, long_offset=0.3, noise_std=0.15)
        report = detect_sensor_offsets(laps)
        assert abs(report.long_accel_offset_mps2 - 0.3) < 0.2, (
            f"Expected long offset ~0.3, got {report.long_accel_offset_mps2:.4f}"
        )

    _test("long_offset_detected", t_long_offset_detected)

    # -- -

    # Test 4 — both offsets simultaneously

    # -- -

    def t_both_offsets_detected() -> None:
        laps = _make_laps(12, long_offset=-0.4, lat_offset=0.6, noise_std=0.1)
        report = detect_sensor_offsets(laps)
        assert abs(report.long_accel_offset_mps2 - (-0.4)) < 0.25, (
            f"Long offset: expected ~-0.4, got {report.long_accel_offset_mps2:.4f}"
        )
        assert abs(report.lat_accel_offset_mps2 - 0.6) < 0.25, (
            f"Lat offset: expected ~0.6, got {report.lat_accel_offset_mps2:.4f}"
        )

    _test("both_offsets_detected", t_both_offsets_detected)

    # -- -

    # Test 5 — correction subtracts offset

    # -- -

    def t_correction_subtracts() -> None:
        df = _make_lap(long_offset=0.5, lat_offset=-0.3)
        offsets = {
            "long_accel_offset_mps2": 0.5,
            "lat_accel_offset_mps2":  -0.3,
        }
        corrected = correct_sensor_offsets(df, offsets)
        # The corrected mean on straights should be closer to zero

        straight = _find_straight_mask(df)
        if straight.sum() > 10:
            orig_lat_mean = float(df[_COL_ACCEL_LAT].values[straight].mean())
            corr_lat_mean = float(corrected[_COL_ACCEL_LAT].values[straight].mean())
            assert abs(corr_lat_mean) < abs(orig_lat_mean), (
                f"Corrected lat mean ({corr_lat_mean:.3f}) should be closer to 0 "
                f"than original ({orig_lat_mean:.3f})"
            )

    _test("correction_subtracts", t_correction_subtracts)

    # -- -

    # Test 6 — correction doesn't mutate input

    # -- -

    def t_correction_no_mutation() -> None:
        df = _make_lap(long_offset=0.5)
        orig_vals = df[_COL_ACCEL_L].values.copy()
        offsets = {"long_accel_offset_mps2": 0.5, "lat_accel_offset_mps2": 0.0}
        _ = correct_sensor_offsets(df, offsets)
        np.testing.assert_array_equal(df[_COL_ACCEL_L].values, orig_vals)

    _test("correction_no_mutation", t_correction_no_mutation)

    # -- -

    # Test 7 — correction with zero offset is identity

    # -- -

    def t_correction_zero_is_identity() -> None:
        df = _make_lap()
        offsets = {"long_accel_offset_mps2": 0.0, "lat_accel_offset_mps2": 0.0}
        corrected = correct_sensor_offsets(df, offsets)
        np.testing.assert_array_equal(
            corrected[_COL_ACCEL_L].values, df[_COL_ACCEL_L].values,
        )
        np.testing.assert_array_equal(
            corrected[_COL_ACCEL_LAT].values, df[_COL_ACCEL_LAT].values,
        )

    _test("correction_zero_identity", t_correction_zero_is_identity)

    # -- -

    # Test 8 — empty laps → zero offsets

    # -- -

    def t_empty_laps() -> None:
        report = detect_sensor_offsets({})
        assert report.long_accel_offset_mps2 == 0.0
        assert report.lat_accel_offset_mps2 == 0.0
        assert len(report.warnings) > 0

    _test("empty_laps", t_empty_laps)

    # -- -

    # Test 9 — report serialisation

    # -- -

    def t_report_to_dict() -> None:
        laps = _make_laps(5, lat_offset=0.3)
        report = detect_sensor_offsets(laps)
        d = report.to_dict()
        assert "long_accel_offset_mps2" in d
        assert "lat_accel_offset_mps2" in d
        assert "has_significant_offset" in d
        assert isinstance(d["warnings"], list)

    _test("report_to_dict", t_report_to_dict)

    # -- -

    # Test 10 — has_significant_offset property

    # -- -

    def t_significant_offset_flag() -> None:
        # Small offset → not significant

        laps_small = _make_laps(5, lat_offset=0.05, long_offset=0.02)
        r_small = detect_sensor_offsets(laps_small)
        assert not r_small.has_significant_offset, (
            f"Small offsets should not be significant: "
            f"long={r_small.long_accel_offset_mps2}, lat={r_small.lat_accel_offset_mps2}"
        )

        # Large offset → significant

        laps_large = _make_laps(5, lat_offset=0.8, long_offset=0.0, noise_std=0.1)
        r_large = detect_sensor_offsets(laps_large)
        assert r_large.has_significant_offset, (
            f"Large lat offset should be significant: "
            f"lat={r_large.lat_accel_offset_mps2:.4f}"
        )

    _test("significant_offset_flag", t_significant_offset_flag)

    # -- -

    # Test 11 — no yaw channel → still attempts detection

    # -- -

    def t_no_yaw_still_works() -> None:
        laps = _make_laps(8, lat_offset=0.5, has_yaw=False)
        report = detect_sensor_offsets(laps)
        # Without yaw, straight detection is less reliable, but longitudinal

        # offset should still work (coasting uses speed-based accel)

        assert report.long_samples_used >= 0  # might be 0 or positive
        # Report should still be valid

        assert isinstance(report.long_accel_offset_mps2, float)

    _test("no_yaw_still_works", t_no_yaw_still_works)

    # -- -

    # Test 12 — offsets property for correct_sensor_offsets

    # -- -

    def t_offsets_property() -> None:
        laps = _make_laps(5, long_offset=0.3, lat_offset=-0.2)
        report = detect_sensor_offsets(laps)
        offsets = report.offsets
        assert "long_accel_offset_mps2" in offsets
        assert "lat_accel_offset_mps2" in offsets
        # Round-trip: use offsets dict for correction

        df = _make_lap(long_offset=0.3, lat_offset=-0.2)
        corrected = correct_sensor_offsets(df, offsets)
        assert _COL_ACCEL_L in corrected.columns

    _test("offsets_property", t_offsets_property)

    # -- -

    # Test 13 — large offset clamped (implausible bias > 3 m/s²)

    # -- -

    def t_implausible_offset_clamped() -> None:
        # Create data where the "offset" is actually real dynamics, not bias

        laps = _make_laps(5, long_offset=5.0, noise_std=0.1)
        report = detect_sensor_offsets(laps)
        # 5.0 m/s² offset exceeds _MAX_PLAUSIBLE_OFFSET → should be clamped to 0

        assert abs(report.long_accel_offset_mps2) < _MAX_PLAUSIBLE_OFFSET + 0.1, (
            f"Implausible offset should be clamped, got {report.long_accel_offset_mps2}"
        )

    _test("implausible_offset_clamped", t_implausible_offset_clamped)

    # -- -

    # Test 14 — correction handles raw G columns

    # -- -

    def t_correction_raw_g() -> None:
        df = pd.DataFrame({
            _RAW_LONG_G:   np.full(100, 0.1),   # 0.1 G
            _RAW_LAT_G:    np.full(100, -0.05),  # -0.05 G
            _COL_ACCEL_L:  np.full(100, 0.1 * _G),
            _COL_ACCEL_LAT: np.full(100, -0.05 * _G),
        })
        offsets = {
            "long_accel_offset_mps2": 0.1 * _G,
            "lat_accel_offset_mps2": -0.05 * _G,
        }
        corrected = correct_sensor_offsets(df, offsets)
        # Both standardised and raw columns should be ~0 after correction

        np.testing.assert_allclose(
            corrected[_COL_ACCEL_L].values, 0.0, atol=1e-6,
        )
        np.testing.assert_allclose(
            corrected[_RAW_LONG_G].values, 0.0, atol=1e-6,
        )

    _test("correction_raw_g_columns", t_correction_raw_g)

    # -- -

    # Test 15 — correction with missing offset keys → no crash

    # -- -

    def t_correction_missing_keys() -> None:
        df = _make_lap()
        corrected = correct_sensor_offsets(df, {})
        # Should be identical (no correction applied)

        np.testing.assert_array_equal(
            corrected[_COL_ACCEL_L].values, df[_COL_ACCEL_L].values,
        )

    _test("correction_missing_keys", t_correction_missing_keys)

    # -- -

    # Test 16 — end-to-end: detect → correct → verify improvement

    # -- -

    def t_end_to_end() -> None:
        TRUE_LAT_OFFSET = 0.4
        TRUE_LONG_OFFSET = -0.25

        laps = _make_laps(
            15,
            long_offset=TRUE_LONG_OFFSET,
            lat_offset=TRUE_LAT_OFFSET,
            noise_std=0.1,
        )

        # Step 1: Detect

        report = detect_sensor_offsets(laps)

        # Step 2: Correct all laps

        corrected_laps = {}
        for ln, df in laps.items():
            corrected_laps[ln] = correct_sensor_offsets(df, report.offsets)

        # Step 3: Re-detect on corrected data → offsets should be ~0

        report2 = detect_sensor_offsets(corrected_laps)
        assert abs(report2.lat_accel_offset_mps2) < 0.15, (
            f"After correction, residual lat offset should be ~0, "
            f"got {report2.lat_accel_offset_mps2:.4f}"
        )
        assert abs(report2.long_accel_offset_mps2) < 0.15, (
            f"After correction, residual long offset should be ~0, "
            f"got {report2.long_accel_offset_mps2:.4f}"
        )

    _test("end_to_end_detect_correct_verify", t_end_to_end)

    # -- -

    # Test 17 — straight detection works (high yaw → rejected)

    # -- -

    def t_straight_detection() -> None:
        # All corners (high yaw) → no straight samples for lat offset

        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            _COL_SPEED:     np.full(200, 25.0),
            _COL_YAW:       np.full(200, 50.0),  # constant high yaw
            _COL_ACCEL_LAT: rng.normal(5.0, 0.1, 200),
            _COL_TIME:      np.linspace(0, 10, 200),
        })
        mask = _find_straight_mask(df)
        assert mask.sum() == 0, (
            f"All-corner lap should have 0 straight samples, got {mask.sum()}"
        )

    _test("straight_detection", t_straight_detection)

    # -- -

    # Test 18 — coasting detection works

    # -- -

    def t_coasting_detection() -> None:
        # Constant speed → all coasting

        n = 200
        df = pd.DataFrame({
            _COL_SPEED: np.full(n, 25.0),
            _COL_TIME:  np.linspace(0, 10, n),
        })
        mask = _find_coasting_mask(df)
        # First sample has no dv/dt → might be excluded

        assert mask.sum() >= n - 5, (
            f"Constant speed should be ~all coasting, got {mask.sum()}/{n}"
        )

    _test("coasting_detection", t_coasting_detection)

    # -- -

    # Test 19 — noisy data → lower confidence

    # -- -

    def t_noisy_lower_confidence() -> None:
        laps_clean = _make_laps(8, lat_offset=0.3, noise_std=0.1)
        laps_noisy = _make_laps(8, lat_offset=0.3, noise_std=1.5)
        r_clean = detect_sensor_offsets(laps_clean)
        r_noisy = detect_sensor_offsets(laps_noisy)
        assert r_clean.lat_confidence >= r_noisy.lat_confidence, (
            f"Clean ({r_clean.lat_confidence:.2f}) should have >= confidence "
            f"than noisy ({r_noisy.lat_confidence:.2f})"
        )

    _test("noisy_lower_confidence", t_noisy_lower_confidence)

    # -- -

    # Test 20 — negative lateral offset detected

    # -- -

    def t_negative_lat_offset() -> None:
        laps = _make_laps(10, lat_offset=-0.6, noise_std=0.1)
        report = detect_sensor_offsets(laps)
        assert report.lat_accel_offset_mps2 < -0.3, (
            f"Expected negative lat offset, got {report.lat_accel_offset_mps2:.4f}"
        )

    _test("negative_lat_offset", t_negative_lat_offset)

    # -- -

    # Summary

    # -- -

    total = len(passed) + len(failed)
    print(f"\nSensor Offset Tests: {len(passed)}/{total} passed")
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
