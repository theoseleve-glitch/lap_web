"""
distance_validation.py
----------------------
Post-resampling distance validation, normalisation, and anomaly detection.

GPS-recorded distance varies between laps due to satellite wander, multipath
effects, and corner-cutting differences.  If lap A measures the track as
660 m and lap B as 670 m, their speed traces are misaligned at the same
physical track locations, corrupting the percentile envelope that feeds
the theoretical lap computation.

This module provides three public functions to fix this:

``validate_lap_distances(resampled_laps, ...)``
    Flag laps whose total distance deviates from the cross-lap median.

``normalize_lap_distances_robust(resampled_laps, track_length_m)``
    Affine-scale every lap's distance column to a common reference length.

``detect_distance_anomalies(resampled_laps)``
    Per-lap scan for backward jumps, stalled distance, and mid-lap resets.

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

# Column-name constants (aligned with resampling.py / pipeline.py)

# -- -


_COL_DIST:  Final[str] = "Distance (m)"
_COL_SPEED: Final[str] = "Speed (m/s)"
_COL_TIME:  Final[str] = "Time (s)"

# Thresholds

_DEFAULT_TOLERANCE_PCT:     Final[float] = 5.0    # ±5% of median
_DEFAULT_MIN_SPEED_MPS:     Final[float] = 0.5    # below this, consider stationary
_DEFAULT_STALL_DIST_M:      Final[float] = 0.01   # distance delta below this = stalled
_DEFAULT_BACKWARD_THRESH_M: Final[float] = -0.001 # distance decreasing = backward jump
_DEFAULT_ZERO_RESET_FRAC:   Final[float] = 0.10   # if distance drops below 10% of max mid-lap


# -- -

# Data structures

# -- -


@dataclass
class DistanceValidationReport:
    """
    Summary of cross-lap distance validation.

    Attributes
    ----------
    median_distance_m : float
        Median total lap distance across all laps [m].
    distances : dict[int, float]
        Per-lap total distance [m].
    deviations_pct : dict[int, float]
        Per-lap deviation from median [%].
    flagged_laps : list[int]
        Lap numbers exceeding the tolerance.
    valid_laps : list[int]
        Lap numbers within tolerance.
    warnings : list[str]
        Human-readable warnings.
    """
    median_distance_m: float
    distances:         dict[int, float]
    deviations_pct:    dict[int, float]
    flagged_laps:      list[int]
    valid_laps:        list[int]
    warnings:          list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "median_distance_m": round(self.median_distance_m, 2),
            "distances":         {k: round(v, 2) for k, v in self.distances.items()},
            "deviations_pct":    {k: round(v, 2) for k, v in self.deviations_pct.items()},
            "flagged_laps":      list(self.flagged_laps),
            "valid_laps":        list(self.valid_laps),
            "warnings":          list(self.warnings),
        }


# -- -

# Exceptions

# -- -


class DistanceValidationError(ValueError):
    """Raised when distance validation encounters irrecoverable issues."""


# -- -

# Internal helpers

# -- -


def _has(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns and df[col].notna().any()


def _lap_total_distance(df: pd.DataFrame) -> float:
    """Return total distance spanned by a single lap [m]."""
    if not _has(df, _COL_DIST):
        return float("nan")
    d = pd.to_numeric(df[_COL_DIST], errors="coerce").dropna()
    if len(d) < 2:
        return float("nan")
    return float(d.iloc[-1] - d.iloc[0])


# -- -

# Public API — validate_lap_distances

# -- -


def validate_lap_distances(
    resampled_laps: dict[int, pd.DataFrame],
    *,
    tolerance_pct: float = _DEFAULT_TOLERANCE_PCT,
) -> DistanceValidationReport:
    """
    Validate that all laps have similar total distance.

    Computes the total distance for each lap, compares to the cross-lap
    median, and flags laps whose deviation exceeds *tolerance_pct*.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        Resampled lap DataFrames with ``"Distance (m)"`` column.
    tolerance_pct : float
        Maximum acceptable deviation from median [%].  Default: 5.0.

    Returns
    -------
    DistanceValidationReport
    """
    if not resampled_laps:
        return DistanceValidationReport(
            median_distance_m=0.0,
            distances={},
            deviations_pct={},
            flagged_laps=[],
            valid_laps=[],
            warnings=["No laps to validate."],
        )

    # Compute per-lap total distance

    distances: dict[int, float] = {}
    for ln, df in sorted(resampled_laps.items()):
        distances[ln] = _lap_total_distance(df)

    finite_dists = [d for d in distances.values() if math.isfinite(d) and d > 0]

    if not finite_dists:
        return DistanceValidationReport(
            median_distance_m=0.0,
            distances=distances,
            deviations_pct={},
            flagged_laps=list(distances.keys()),
            valid_laps=[],
            warnings=["No laps have valid distance data."],
        )

    median_d = float(np.median(finite_dists))
    warnings: list[str] = []

    # Compute deviations

    deviations: dict[int, float] = {}
    flagged: list[int] = []
    valid: list[int] = []

    for ln, d in sorted(distances.items()):
        if not math.isfinite(d) or d <= 0:
            deviations[ln] = float("nan")
            flagged.append(ln)
            continue

        dev_pct = (d - median_d) / median_d * 100.0
        deviations[ln] = dev_pct

        if abs(dev_pct) > tolerance_pct:
            flagged.append(ln)
        else:
            valid.append(ln)

    if flagged:
        flag_details = ", ".join(
            f"lap {ln} ({deviations.get(ln, float('nan')):+.1f}%)"
            for ln in flagged
        )
        warnings.append(
            f"Distance outlier(s) (>{tolerance_pct}% from median "
            f"{median_d:.1f}m): {flag_details}"
        )
        logger.warning(
            "Distance validation: %d of %d laps flagged (median=%.1fm, "
            "tolerance=±%.1f%%): %s",
            len(flagged), len(distances), median_d, tolerance_pct,
            flag_details,
        )
    else:
        logger.info(
            "Distance validation: all %d laps within ±%.1f%% of median "
            "%.1fm (range %.1f–%.1fm).",
            len(distances), tolerance_pct, median_d,
            min(finite_dists), max(finite_dists),
        )

    return DistanceValidationReport(
        median_distance_m=median_d,
        distances=distances,
        deviations_pct=deviations,
        flagged_laps=flagged,
        valid_laps=valid,
        warnings=warnings,
    )


def filter_valid_laps(
    resampled_laps: dict[int, pd.DataFrame],
    report: DistanceValidationReport,
) -> dict[int, pd.DataFrame]:
    """
    Return only the laps that passed distance validation.

    Convenience wrapper: extracts valid laps from the report and filters
    the dict.  If filtering would leave fewer than 2 laps, returns all
    laps with a warning.
    """
    if not report.valid_laps:
        logger.warning(
            "No laps passed distance validation; returning all %d laps unfiltered.",
            len(resampled_laps),
        )
        return resampled_laps

    if len(report.valid_laps) < 2 and len(resampled_laps) >= 2:
        logger.warning(
            "Only %d lap(s) passed validation; returning all %d to avoid "
            "data loss.",
            len(report.valid_laps), len(resampled_laps),
        )
        return resampled_laps

    filtered = {ln: resampled_laps[ln] for ln in report.valid_laps
                if ln in resampled_laps}

    logger.info(
        "Filtered to %d valid laps (removed %d flagged).",
        len(filtered), len(report.flagged_laps),
    )
    return filtered


# -- -

# Public API — normalize_lap_distances_robust

# -- -


def normalize_lap_distances_robust(
    resampled_laps: dict[int, pd.DataFrame],
    track_length_m: float | None = None,
) -> dict[int, pd.DataFrame]:
    """
    Affine-scale every lap's distance column to a common reference length.

    If *track_length_m* is known (e.g. from ``track_detection``), every
    lap is scaled to exactly that length.  Otherwise, the cross-lap median
    distance is used as the target.

    The transformation is:

        d_normalised = d_raw × (target_length / d_raw_max)

    This preserves the proportional position along the lap (a speed sample
    at 60% of the lap stays at 60%) while ensuring all laps share the same
    distance axis — essential for meaningful percentile computation.

    All other numeric columns that depend on distance (such as curvature
    or distance-normalised features) are left unchanged; only the distance
    column itself is rescaled.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        Resampled lap DataFrames.
    track_length_m : float or None
        Known track length [m].  If None, the median of per-lap distances
        is used.

    Returns
    -------
    dict[int, pd.DataFrame]
        New dict with copies whose distance columns are rescaled.
        Laps with invalid distance data are returned unmodified.
    """
    if not resampled_laps:
        return {}

    # Determine target length

    if track_length_m is not None and track_length_m > 0:
        target = track_length_m
        logger.info(
            "Normalising lap distances to known track length: %.1f m",
            target,
        )
    else:
        per_lap = [_lap_total_distance(df) for df in resampled_laps.values()]
        finite = [d for d in per_lap if math.isfinite(d) and d > 0]
        if not finite:
            logger.warning(
                "Cannot normalise: no valid distance data. Returning as-is."
            )
            return dict(resampled_laps)
        target = float(np.median(finite))
        logger.info(
            "Normalising lap distances to median: %.1f m "
            "(range %.1f–%.1f m across %d laps).",
            target, min(finite), max(finite), len(finite),
        )

    result: dict[int, pd.DataFrame] = {}

    for ln, df in sorted(resampled_laps.items()):
        if not _has(df, _COL_DIST):
            result[ln] = df
            continue

        d = pd.to_numeric(df[_COL_DIST], errors="coerce").values.astype(float)
        finite_mask = np.isfinite(d)
        if finite_mask.sum() < 2:
            result[ln] = df
            continue

        d_min = float(np.nanmin(d[finite_mask]))
        d_max = float(np.nanmax(d[finite_mask]))
        d_span = d_max - d_min

        if d_span <= 0:
            result[ln] = df
            continue

        # Affine scaling: shift to zero, scale to target, then restore offset

        scale_factor = target / d_span
        d_new = (d - d_min) * scale_factor

        df_out = df.copy()
        df_out[_COL_DIST] = d_new

        if abs(scale_factor - 1.0) > 0.001:
            logger.debug(
                "Lap %d: distance scaled by %.4f (%.1fm → %.1fm).",
                ln, scale_factor, d_span, target,
            )

        result[ln] = df_out

    return result


# -- -

# Public API — detect_distance_anomalies

# -- -


def detect_distance_anomalies(
    resampled_laps: dict[int, pd.DataFrame],
    *,
    backward_threshold_m: float = _DEFAULT_BACKWARD_THRESH_M,
    stall_dist_m: float = _DEFAULT_STALL_DIST_M,
    min_speed_for_stall_mps: float = _DEFAULT_MIN_SPEED_MPS,
    zero_reset_fraction: float = _DEFAULT_ZERO_RESET_FRAC,
) -> dict[int, list[str]]:
    """
    Per-lap scan for distance channel anomalies.

    Checks performed on each lap:

    1. **Backward jumps** — distance decreases between consecutive samples.
       In resampled data this should never happen; it indicates the upstream
       repair in ``validate_lap_consistency`` missed a glitch.

    2. **Stalled distance** — speed is above *min_speed_for_stall_mps* but
       the distance increment is below *stall_dist_m* for consecutive
       samples.  Indicates a frozen distance channel (sensor dropout).

    3. **Mid-lap zero reset** — distance drops below *zero_reset_fraction*
       of the lap's maximum distance after passing the 20% mark.  This
       typically happens when the GPS logger resets the cumulative counter.

    4. **Large forward jumps** — a single distance step exceeding 10× the
       median step size (a teleportation artefact).

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        Resampled lap DataFrames.

    Returns
    -------
    dict[int, list[str]]
        ``{lap_number: [list of anomaly descriptions]}``.
        Laps with no anomalies have an empty list.
    """
    anomalies: dict[int, list[str]] = {}

    for ln, df in sorted(resampled_laps.items()):
        lap_issues: list[str] = []

        if not _has(df, _COL_DIST):
            lap_issues.append("Missing distance column.")
            anomalies[ln] = lap_issues
            continue

        d = pd.to_numeric(df[_COL_DIST], errors="coerce").values.astype(float)
        n = len(d)
        if n < 2:
            lap_issues.append(f"Too few samples ({n}).")
            anomalies[ln] = lap_issues
            continue

        diffs = np.diff(d)
        finite_diffs = diffs[np.isfinite(diffs)]

        # --- Check 1: Backward jumps -
        backward_mask = diffs < backward_threshold_m
        n_backward = int(backward_mask.sum())
        if n_backward > 0:
            # Find the indices

            back_idxs = np.where(backward_mask)[0]
            worst_jump = float(np.min(diffs[backward_mask]))
            lap_issues.append(
                f"Backward distance jump(s): {n_backward} occurrence(s), "
                f"worst={worst_jump:.3f}m at sample(s) "
                f"{back_idxs[:5].tolist()}{'...' if n_backward > 5 else ''}"
            )

        # --- Check 2: Stalled distance with nonzero speed -
        if _has(df, _COL_SPEED):
            speed = pd.to_numeric(df[_COL_SPEED], errors="coerce").values
            # Check pairs of consecutive samples

            stall_mask = (
                (np.abs(diffs) < stall_dist_m) &
                (speed[:-1] > min_speed_for_stall_mps) &
                np.isfinite(diffs)
            )
            n_stall = int(stall_mask.sum())
            if n_stall > 3:  # occasional single stalls are normal
                stall_frac = n_stall / max(len(diffs), 1) * 100
                lap_issues.append(
                    f"Stalled distance: {n_stall} samples ({stall_frac:.1f}%) "
                    f"where speed > {min_speed_for_stall_mps} m/s but distance "
                    f"unchanged."
                )

        # --- Check 3: Mid-lap zero reset -
        d_max = float(np.nanmax(d))
        if d_max > 0:
            # After the 20% mark, does distance drop below the threshold?

            idx_20pct = int(n * 0.2)
            if idx_20pct < n:
                tail = d[idx_20pct:]
                reset_mask = tail < (d_max * zero_reset_fraction)
                n_reset = int(reset_mask.sum())
                if n_reset > 0:
                    first_reset_idx = idx_20pct + int(np.where(reset_mask)[0][0])
                    lap_issues.append(
                        f"Mid-lap distance reset: distance drops below "
                        f"{zero_reset_fraction * 100:.0f}% of max ({d_max:.1f}m) "
                        f"at sample {first_reset_idx} ({n_reset} samples affected)."
                    )

        # --- Check 4: Large forward jumps -
        if len(finite_diffs) > 5:
            median_step = float(np.median(np.abs(finite_diffs[finite_diffs != 0])))
            if median_step > 0:
                large_mask = diffs > (median_step * 10)
                n_large = int(large_mask.sum())
                if n_large > 0:
                    large_idxs = np.where(large_mask)[0]
                    worst_fwd = float(np.max(diffs[large_mask]))
                    lap_issues.append(
                        f"Large forward jump(s): {n_large} occurrence(s), "
                        f"worst={worst_fwd:.1f}m (median step={median_step:.2f}m) "
                        f"at sample(s) {large_idxs[:5].tolist()}"
                        f"{'...' if n_large > 5 else ''}"
                    )

        anomalies[ln] = lap_issues

    # Summary log

    total_issues = sum(len(v) for v in anomalies.values())
    laps_with_issues = sum(1 for v in anomalies.values() if v)
    if total_issues > 0:
        logger.warning(
            "Distance anomalies: %d issue(s) across %d of %d laps.",
            total_issues, laps_with_issues, len(resampled_laps),
        )
    else:
        logger.info(
            "Distance anomalies: none found across %d laps.",
            len(resampled_laps),
        )

    return anomalies


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

    TRACK_LEN = 660.0
    N_PTS = 500

    def _make_clean_lap(
        lap_num: int = 1,
        total_dist: float = TRACK_LEN,
        n_pts: int = N_PTS,
    ) -> pd.DataFrame:
        dist = np.linspace(0, total_dist, n_pts)
        speed = 20.0 + 5.0 * np.sin(dist / total_dist * 2 * np.pi)
        dt = np.diff(dist) / np.maximum(speed[:-1], 1.0)
        t = np.concatenate([[0.0], np.cumsum(dt)])
        return pd.DataFrame({
            _COL_DIST:  dist,
            _COL_SPEED: speed,
            _COL_TIME:  t,
        })

    def _make_laps(
        n_laps: int = 10,
        dist_range: tuple[float, float] = (658.0, 662.0),
    ) -> dict[int, pd.DataFrame]:
        rng = np.random.default_rng(42)
        laps: dict[int, pd.DataFrame] = {}
        for ln in range(1, n_laps + 1):
            d = rng.uniform(dist_range[0], dist_range[1])
            laps[ln] = _make_clean_lap(ln, d)
        return laps

    # -- -

    # Test 1 — validate: consistent laps → all valid

    # -- -

    def t_validate_consistent() -> None:
        laps = _make_laps(10, (658, 662))
        report = validate_lap_distances(laps, tolerance_pct=5.0)
        assert len(report.flagged_laps) == 0, (
            f"Expected no flagged laps, got {report.flagged_laps}"
        )
        assert len(report.valid_laps) == 10
        assert 658 < report.median_distance_m < 662

    _test("validate_consistent", t_validate_consistent)

    # -- -

    # Test 2 — validate: one outlier flagged

    # -- -

    def t_validate_outlier() -> None:
        laps = _make_laps(8, (658, 662))
        # Add one grossly wrong lap

        laps[9] = _make_clean_lap(9, 750.0)  # +13% over ~660
        report = validate_lap_distances(laps, tolerance_pct=5.0)
        assert 9 in report.flagged_laps, (
            f"Lap 9 (750m) should be flagged, flagged={report.flagged_laps}"
        )
        assert len(report.warnings) > 0

    _test("validate_outlier_flagged", t_validate_outlier)

    # -- -

    # Test 3 — validate: empty laps

    # -- -

    def t_validate_empty() -> None:
        report = validate_lap_distances({})
        assert report.median_distance_m == 0.0
        assert len(report.warnings) > 0

    _test("validate_empty", t_validate_empty)

    # -- -

    # Test 4 — validate: tolerance adjustable

    # -- -

    def t_validate_tolerance() -> None:
        laps = _make_laps(5, (658, 662))
        laps[6] = _make_clean_lap(6, 690.0)  # ~4.5% over
        r_tight = validate_lap_distances(laps, tolerance_pct=3.0)
        r_loose = validate_lap_distances(laps, tolerance_pct=10.0)
        assert 6 in r_tight.flagged_laps
        assert 6 in r_loose.valid_laps

    _test("validate_tolerance_adjustable", t_validate_tolerance)

    # -- -

    # Test 5 — filter_valid_laps: removes flagged

    # -- -

    def t_filter_valid() -> None:
        laps = _make_laps(8, (658, 662))
        laps[9] = _make_clean_lap(9, 750.0)
        report = validate_lap_distances(laps, tolerance_pct=5.0)
        filtered = filter_valid_laps(laps, report)
        assert 9 not in filtered
        assert len(filtered) == 8

    _test("filter_valid_laps", t_filter_valid)

    # -- -

    # Test 6 — filter_valid_laps: keeps all if < 2 would remain

    # -- -

    def t_filter_keeps_all_if_too_few() -> None:
        laps = {
            1: _make_clean_lap(1, 660.0),
            2: _make_clean_lap(2, 750.0),
            3: _make_clean_lap(3, 800.0),
        }
        report = validate_lap_distances(laps, tolerance_pct=3.0)
        filtered = filter_valid_laps(laps, report)
        # Even if 2 and 3 are flagged, shouldn't drop to < 2

        assert len(filtered) >= 2

    _test("filter_keeps_all_if_too_few", t_filter_keeps_all_if_too_few)

    # -- -

    # Test 7 — normalise: known track length → exact match

    # -- -

    def t_normalise_known_length() -> None:
        laps = {
            1: _make_clean_lap(1, 658.0),
            2: _make_clean_lap(2, 665.0),
            3: _make_clean_lap(3, 670.0),
        }
        normed = normalize_lap_distances_robust(laps, track_length_m=660.0)
        for ln, df in normed.items():
            d = df[_COL_DIST].values
            span = d[-1] - d[0]
            assert abs(span - 660.0) < 0.01, (
                f"Lap {ln}: expected span=660.0, got {span:.3f}"
            )

    _test("normalise_known_length", t_normalise_known_length)

    # -- -

    # Test 8 — normalise: no track length → median used

    # -- -

    def t_normalise_median() -> None:
        laps = _make_laps(10, (658, 662))
        normed = normalize_lap_distances_robust(laps)
        spans = []
        for df in normed.values():
            d = df[_COL_DIST].values
            spans.append(d[-1] - d[0])
        # All spans should be identical (the median)

        assert max(spans) - min(spans) < 0.01, (
            f"Normalised spans should be identical, range={max(spans)-min(spans):.3f}"
        )

    _test("normalise_median", t_normalise_median)

    # -- -

    # Test 9 — normalise: preserves proportional positions

    # -- -

    def t_normalise_preserves_proportions() -> None:
        lap = _make_clean_lap(1, 670.0)
        d_orig = lap[_COL_DIST].values
        mid_frac_orig = d_orig[len(d_orig) // 2] / d_orig[-1]

        normed = normalize_lap_distances_robust({1: lap}, track_length_m=660.0)
        d_new = normed[1][_COL_DIST].values
        mid_frac_new = d_new[len(d_new) // 2] / d_new[-1]

        assert abs(mid_frac_orig - mid_frac_new) < 0.001, (
            f"Proportional position shifted: {mid_frac_orig:.4f} → {mid_frac_new:.4f}"
        )

    _test("normalise_preserves_proportions", t_normalise_preserves_proportions)

    # -- -

    # Test 10 — normalise: empty dict

    # -- -

    def t_normalise_empty() -> None:
        assert normalize_lap_distances_robust({}) == {}

    _test("normalise_empty", t_normalise_empty)

    # -- -

    # Test 11 — normalise: doesn't mutate input

    # -- -

    def t_normalise_no_mutation() -> None:
        lap = _make_clean_lap(1, 670.0)
        d_before = lap[_COL_DIST].values.copy()
        _ = normalize_lap_distances_robust({1: lap}, track_length_m=660.0)
        np.testing.assert_array_equal(lap[_COL_DIST].values, d_before)

    _test("normalise_no_mutation", t_normalise_no_mutation)

    # -- -

    # Test 12 — anomalies: clean lap → no anomalies

    # -- -

    def t_anomaly_clean() -> None:
        laps = _make_laps(5)
        anomalies = detect_distance_anomalies(laps)
        for ln, issues in anomalies.items():
            assert len(issues) == 0, (
                f"Clean lap {ln} should have no anomalies, got: {issues}"
            )

    _test("anomaly_clean_no_issues", t_anomaly_clean)

    # -- -

    # Test 13 — anomalies: backward jump detected

    # -- -

    def t_anomaly_backward() -> None:
        lap = _make_clean_lap(1, 660.0)
        d = lap[_COL_DIST].values.copy()
        d[250] = d[249] - 5.0  # inject backward jump
        lap = lap.copy()
        lap[_COL_DIST] = d
        anomalies = detect_distance_anomalies({1: lap})
        assert len(anomalies[1]) > 0
        assert any("ackward" in s for s in anomalies[1])

    _test("anomaly_backward_jump", t_anomaly_backward)

    # -- -

    # Test 14 — anomalies: stalled distance detected

    # -- -

    def t_anomaly_stalled() -> None:
        lap = _make_clean_lap(1, 660.0)
        d = lap[_COL_DIST].values.copy()
        # Freeze distance for 20 samples while speed > 0

        d[200:220] = d[200]
        lap = lap.copy()
        lap[_COL_DIST] = d
        anomalies = detect_distance_anomalies({1: lap})
        assert len(anomalies[1]) > 0
        assert any("talled" in s or "tall" in s for s in anomalies[1])

    _test("anomaly_stalled_distance", t_anomaly_stalled)

    # -- -

    # Test 15 — anomalies: mid-lap zero reset detected

    # -- -

    def t_anomaly_mid_reset() -> None:
        lap = _make_clean_lap(1, 660.0)
        d = lap[_COL_DIST].values.copy()
        # Reset distance to near-zero at 60% of the lap

        reset_idx = int(len(d) * 0.6)
        d[reset_idx:] = d[reset_idx:] - d[reset_idx] + 1.0
        lap = lap.copy()
        lap[_COL_DIST] = d
        anomalies = detect_distance_anomalies({1: lap})
        assert len(anomalies[1]) > 0
        assert any("reset" in s.lower() for s in anomalies[1])

    _test("anomaly_mid_lap_reset", t_anomaly_mid_reset)

    # -- -

    # Test 16 — anomalies: large forward jump

    # -- -

    def t_anomaly_large_jump() -> None:
        lap = _make_clean_lap(1, 660.0)
        d = lap[_COL_DIST].values.copy()
        # Inject a 50m forward jump (normal step ~1.3m)

        d[300:] += 50.0
        lap = lap.copy()
        lap[_COL_DIST] = d
        anomalies = detect_distance_anomalies({1: lap})
        assert len(anomalies[1]) > 0
        assert any("arge" in s or "jump" in s for s in anomalies[1])

    _test("anomaly_large_forward_jump", t_anomaly_large_jump)

    # -- -

    # Test 17 — anomalies: missing distance column

    # -- -

    def t_anomaly_missing_dist() -> None:
        lap = pd.DataFrame({_COL_SPEED: np.full(100, 20.0)})
        anomalies = detect_distance_anomalies({1: lap})
        assert len(anomalies[1]) > 0
        assert any("issing" in s for s in anomalies[1])

    _test("anomaly_missing_distance", t_anomaly_missing_dist)

    # -- -

    # Test 18 — validate: report serialisation

    # -- -

    def t_report_to_dict() -> None:
        laps = _make_laps(5)
        report = validate_lap_distances(laps)
        d = report.to_dict()
        assert "median_distance_m" in d
        assert "flagged_laps" in d
        assert isinstance(d["distances"], dict)

    _test("report_to_dict", t_report_to_dict)

    # -- -

    # Test 19 — normalise: scale factor correctness

    # -- -

    def t_normalise_scale_factor() -> None:
        # Lap at 700m, normalised to 660m → factor = 660/700

        lap = _make_clean_lap(1, 700.0)
        normed = normalize_lap_distances_robust({1: lap}, track_length_m=660.0)
        d_orig = lap[_COL_DIST].values
        d_new = normed[1][_COL_DIST].values
        # Speed values should be unchanged

        np.testing.assert_array_equal(
            lap[_COL_SPEED].values,
            normed[1][_COL_SPEED].values,
        )
        # Distance at every point should be scaled by 660/700

        expected_ratio = 660.0 / 700.0
        with np.errstate(divide="ignore", invalid="ignore"):
            actual_ratios = d_new[1:] / d_orig[1:]
        np.testing.assert_allclose(
            actual_ratios, expected_ratio, rtol=1e-6,
        )

    _test("normalise_scale_factor", t_normalise_scale_factor)

    # -- -

    # Test 20 — end-to-end: validate → normalise → anomaly check

    # -- -

    def t_end_to_end() -> None:
        rng = np.random.default_rng(99)
        laps: dict[int, pd.DataFrame] = {}
        for ln in range(1, 13):
            d = 660.0 + rng.normal(0, 3.0)  # ±3m GPS jitter
            laps[ln] = _make_clean_lap(ln, d)
        # Add one bad lap

        laps[13] = _make_clean_lap(13, 750.0)

        # Step 1: Validate

        report = validate_lap_distances(laps, tolerance_pct=5.0)
        assert 13 in report.flagged_laps

        # Step 2: Filter

        clean = filter_valid_laps(laps, report)
        assert 13 not in clean

        # Step 3: Normalise

        normed = normalize_lap_distances_robust(clean, track_length_m=660.0)
        spans = [df[_COL_DIST].iloc[-1] for df in normed.values()]
        assert max(spans) - min(spans) < 0.01

        # Step 4: Anomaly check

        anomalies = detect_distance_anomalies(normed)
        total_issues = sum(len(v) for v in anomalies.values())
        assert total_issues == 0, (
            f"Clean normalised laps should have no anomalies, got {total_issues}"
        )

    _test("end_to_end_pipeline", t_end_to_end)

    # -- -

    # Summary

    # -- -

    total = len(passed) + len(failed)
    print(f"\nDistance Validation Tests: {len(passed)}/{total} passed")
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
