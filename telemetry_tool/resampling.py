"""
resampling.py
-------------
Resamples telemetry data onto a uniform distance grid so that laps can be
compared sample-by-sample regardless of variations in GPS sampling rate,
car speed profile, or absolute lap time.

Why distance-based resampling?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Raw GPS data is time-uniform (10 Hz, 25 Hz, etc.) which means slow corners
are densely sampled and straights are sparsely sampled.  Distance-uniform
grids give each part of the circuit equal representation and make lap-to-lap
overlays meaningful.

Public API
~~~~~~~~~~
``resample_lap_by_distance(lap_df, n_points=1000)``
    Interpolate all numeric channels of a single lap onto a uniform distance
    grid of *n_points* samples.

``resample_all_laps(lap_dict, n_points=1000)``
    Apply ``resample_lap_by_distance`` to every lap in a dict and return a
    new dict of the same shape.

Interpolation strategy
~~~~~~~~~~~~~~~~~~~~~~
- Distance column is required; all other numeric columns are optional.
- NaN values are removed from each channel independently before interpolation
  so a broken sensor on one channel does not corrupt others.
- Interpolation uses ``numpy.interp`` (piecewise linear) which guarantees
  no extrapolation: values outside the original distance range are clamped
  to the boundary values.
- Lap-time accuracy is preserved because ``Time (s)`` is interpolated on the
  same distance grid as every other channel; the final value of the
  interpolated time series equals the original lap duration to floating-point
  precision.
"""

from __future__ import annotations

import logging
from typing import Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants

# -- -


_COL_DIST:  Final[str] = "Distance (m)"
_COL_TIME:  Final[str] = "Time (s)"
_COL_SPEED: Final[str] = "Speed (m/s)"
_COL_LAP:   Final[str] = "Lap #"

# Synthetic output column added to every resampled DataFrame.

_COL_DIST_NORM: Final[str] = "distance_norm"   # 0.0 – 1.0 fractional position


# -- -

# Exceptions

# -- -


class ResamplingError(ValueError):
    """Raised when a lap cannot be resampled due to missing or invalid data."""


# -- -

# Internal helpers

# -- -


def _drop_nan_pair(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Remove elements where either *x* or *y* is NaN, then return the cleaned
    pair sorted by *x*.

    Sorting is required because ``numpy.interp`` assumes a monotone x-axis.
    If distance values are not monotone (e.g. a GPS glitch) they are also
    removed by de-duplicating after sorting.
    """
    mask  = np.isfinite(x) & np.isfinite(y)
    x_c, y_c = x[mask], y[mask]
    order = np.argsort(x_c, kind="stable")
    x_c, y_c = x_c[order], y_c[order]
    # Remove duplicate x values to avoid interp artefacts

    _, unique = np.unique(x_c, return_index=True)
    return x_c[unique], y_c[unique]


def _validate_distance(dist: np.ndarray) -> None:
    """
    Raise ResamplingError if the distance array has too few valid points or
    no meaningful span.
    """
    finite = dist[np.isfinite(dist)]
    if len(finite) < 2:
        raise ResamplingError(
            f"Need at least 2 finite distance values; got {len(finite)}."
        )
    span = float(finite.max() - finite.min())
    if span <= 0.0:
        raise ResamplingError(
            f"Distance span is {span:.3f} m; cannot build a distance grid."
        )


def _interp_channel(
    dist_raw: np.ndarray,
    values: np.ndarray,
    dist_grid: np.ndarray,
) -> np.ndarray:
    """
    Interpolate *values* (sampled at *dist_raw*) onto *dist_grid*.

    NaN-cleans both arrays independently so a gap in *values* does not affect
    other channels.  Uses ``numpy.interp`` which clamps at boundaries (no
    extrapolation).
    """
    x, y = _drop_nan_pair(dist_raw, values)
    if len(x) < 2:
        # Channel has fewer than 2 valid points → fill with NaN

        logger.debug("Channel has <2 valid points; filling with NaN.")
        return np.full(len(dist_grid), np.nan)
    return np.interp(dist_grid, x, y)


# -- -

# Public API

# -- -


def resample_lap_by_distance(
    lap_df: pd.DataFrame,
    n_points: int = 1000,
) -> pd.DataFrame:
    """
    Interpolate all numeric channels of *lap_df* onto a uniform distance grid.

    The output DataFrame has exactly *n_points* rows, one per equally-spaced
    distance step from ``lap_df[Distance (m)].min()`` to
    ``lap_df[Distance (m)].max()``.

    Parameters
    ----------
    lap_df:
        Single-lap telemetry DataFrame.  Must contain ``Distance (m)``.
        All other columns are optional; non-numeric columns are preserved
        as their first valid value (broadcasted to *n_points* rows).
    n_points:
        Number of output samples.  Default: 1000.

    Returns
    -------
    pd.DataFrame
        Resampled DataFrame with *n_points* rows and the same columns as
        *lap_df* plus ``distance_norm`` (0.0 – 1.0 fractional position).
        Index is reset to 0-based integers.

    Raises
    ------
    TypeError
        If *lap_df* is not a pandas DataFrame.
    ResamplingError
        If ``Distance (m)`` is absent, has fewer than 2 finite values, or has
        zero span.
    ValueError
        If *n_points* < 2.
    """
    if not isinstance(lap_df, pd.DataFrame):
        raise TypeError(
            f"resample_lap_by_distance() expects a pandas DataFrame, "
            f"got {type(lap_df).__name__!r}."
        )
    if n_points < 2:
        raise ValueError(f"n_points must be ≥ 2, got {n_points}.")
    if _COL_DIST not in lap_df.columns:
        raise ResamplingError(
            f"Required column {_COL_DIST!r} not found. "
            f"Available: {list(lap_df.columns)}"
        )

    dist_raw = pd.to_numeric(lap_df[_COL_DIST], errors="coerce").values
    _validate_distance(dist_raw)

    d_min = float(np.nanmin(dist_raw))
    d_max = float(np.nanmax(dist_raw))

    dist_grid = np.linspace(d_min, d_max, n_points)
    dist_norm = (dist_grid - d_min) / (d_max - d_min)   # 0.0 – 1.0

    out: dict[str, np.ndarray] = {
        _COL_DIST:      dist_grid,
        _COL_DIST_NORM: dist_norm,
    }

    numeric_cols    = lap_df.select_dtypes(include=[np.number]).columns.tolist()
    non_numeric_cols = [c for c in lap_df.columns if c not in numeric_cols and c != _COL_DIST]

    # Interpolate each numeric channel (except Distance itself, already set)

    for col in numeric_cols:
        if col == _COL_DIST:
            continue
        values = pd.to_numeric(lap_df[col], errors="coerce").values
        out[col] = _interp_channel(dist_raw, values, dist_grid)

    # Broadcast non-numeric columns (e.g. lap number, compound) as first valid value

    for col in non_numeric_cols:
        first_valid = lap_df[col].dropna().iloc[0] if lap_df[col].notna().any() else None
        out[col] = np.full(n_points, first_valid, dtype=object)

    result = pd.DataFrame(out)

    # Restore column order: Distance, distance_norm, then original columns

    original_cols = [c for c in lap_df.columns if c != _COL_DIST]
    ordered = [_COL_DIST, _COL_DIST_NORM] + [c for c in original_cols if c in result.columns]
    # Add any extra columns not in original (shouldn't happen, but be safe)

    ordered += [c for c in result.columns if c not in ordered]
    result = result[ordered].reset_index(drop=True)

    logger.debug(
        "Resampled lap: %d raw → %d uniform samples  d=%.1f–%.1f m",
        len(lap_df), n_points, d_min, d_max,
    )
    return result


def resample_all_laps(
    lap_dict: dict[int, pd.DataFrame],
    n_points: int = 1000,
) -> dict[int, pd.DataFrame]:
    """
    Apply :func:`resample_lap_by_distance` to every lap in *lap_dict*.

    Laps that fail resampling (e.g. missing distance data) are skipped with a
    warning rather than aborting the entire batch.

    Parameters
    ----------
    lap_dict:
        Mapping of ``{lap_number: single_lap_DataFrame}``.
    n_points:
        Number of output samples per lap.  Default: 1000.

    Returns
    -------
    dict[int, pd.DataFrame]
        Mapping of ``{lap_number: resampled_DataFrame}`` for all successfully
        resampled laps.  Laps that could not be resampled are absent from the
        output.
    """
    if not lap_dict:
        logger.warning("resample_all_laps() received an empty dict.")
        return {}

    results: dict[int, pd.DataFrame] = {}
    skipped: list[int] = []

    for lap_num, lap_df in lap_dict.items():
        try:
            results[lap_num] = resample_lap_by_distance(lap_df, n_points=n_points)
        except (ResamplingError, TypeError, ValueError) as exc:
            logger.warning(
                "Skipping lap %s during resampling: %s", lap_num, exc
            )
            skipped.append(lap_num)

    logger.info(
        "resample_all_laps: %d/%d laps resampled successfully%s.",
        len(results),
        len(lap_dict),
        f"; skipped laps: {skipped}" if skipped else "",
    )
    return results


# -- -

# Unit tests

# -- -


def _run_tests() -> None:
    import traceback

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:   # type: ignore[type-arg]
        try:
            fn()
            passed.append(name)
        except Exception:   # noqa: BLE001
            failed.append((name, traceback.format_exc()))

    rng = np.random.default_rng(42)

    #
    # Fixture factory

    #

    def _lap(
        n: int = 200,
        lap_length_m: float = 4500.0,
        irregular: bool = False,
        nan_frac: float = 0.0,
        lap_num: int = 1,
    ) -> pd.DataFrame:
        """
        Synthetic lap DataFrame.

        Parameters
        ----------
        n:           Number of raw samples.
        lap_length_m: Lap distance in metres.
        irregular:   Use non-uniform time spacing if True.
        nan_frac:    Fraction of speed samples to replace with NaN.
        """
        if irregular:
            # Random spacing with occasional large gaps

            gaps = np.abs(rng.exponential(0.1, n))
            t    = np.cumsum(gaps)
        else:
            t = np.linspace(0.0, 90.0, n)

        # Monotone distance proportional to time (constant speed approximation)

        dist = lap_length_m * (t / t[-1])

        speed = 30.0 + 20.0 * np.sin(2 * np.pi * dist / lap_length_m)

        if nan_frac > 0:
            nan_idx = rng.choice(n, size=int(n * nan_frac), replace=False)
            speed[nan_idx] = np.nan

        return pd.DataFrame({
            _COL_TIME:  t,
            _COL_DIST:  dist,
            _COL_SPEED: speed,
            _COL_LAP:   lap_num,
        })

    #
    # Test 1 – output has exactly n_points rows

    #
    def t_output_length() -> None:
        df  = _lap(n=300)
        out = resample_lap_by_distance(df, n_points=500)
        assert len(out) == 500, f"Expected 500 rows, got {len(out)}"

    _test("output_length", t_output_length)

    #
    # Test 2 – distance grid is strictly uniform

    #
    def t_uniform_distance_grid() -> None:
        df  = _lap(n=200)
        out = resample_lap_by_distance(df, n_points=1000)
        diffs = np.diff(out[_COL_DIST].values)
        assert diffs.min() > 0, "Distance grid must be strictly increasing"
        np.testing.assert_allclose(
            diffs, diffs[0], rtol=1e-6,
            err_msg="Distance steps must be equal"
        )

    _test("uniform_distance_grid", t_uniform_distance_grid)

    #
    # Test 3 – no extrapolation beyond original limits

    #
    def t_no_extrapolation() -> None:
        df   = _lap(n=150)
        d_min = df[_COL_DIST].min()
        d_max = df[_COL_DIST].max()
        out  = resample_lap_by_distance(df, n_points=1000)
        assert out[_COL_DIST].min() >= d_min - 1e-9
        assert out[_COL_DIST].max() <= d_max + 1e-9

    _test("no_extrapolation", t_no_extrapolation)

    #
    # Test 4 – lap time preserved at boundaries

    #
    def t_lap_time_preserved() -> None:
        df       = _lap(n=200)
        t_start  = float(df[_COL_TIME].iloc[0])
        t_end    = float(df[_COL_TIME].iloc[-1])
        out      = resample_lap_by_distance(df, n_points=1000)
        np.testing.assert_allclose(
            float(out[_COL_TIME].iloc[-1]), t_end, rtol=1e-6,
            err_msg="Final (max) time must match original"
        )
        np.testing.assert_allclose(
            float(out[_COL_TIME].iloc[0]), t_start, rtol=1e-6,
            err_msg="First (min) time must match original"
        )

    _test("lap_time_preserved", t_lap_time_preserved)

    #
    # Test 5 – NaN values in speed handled without poisoning other channels

    #
    def t_nan_handling() -> None:
        df  = _lap(n=200, nan_frac=0.15)
        out = resample_lap_by_distance(df, n_points=500)
        # Time channel should be fully valid despite NaNs in speed

        assert out[_COL_TIME].isna().sum() == 0, (
            "Time column should have no NaN after interpolation"
        )
        # Speed may have NaN only if the entire channel is NaN (it isn't here)

        assert out[_COL_SPEED].isna().sum() == 0, (
            "Speed should interpolate over its NaN gaps"
        )

    _test("nan_handling", t_nan_handling)

    #
    # Test 6 – irregular sampling frequency works correctly

    #
    def t_irregular_sampling() -> None:
        df  = _lap(n=300, irregular=True)
        out = resample_lap_by_distance(df, n_points=1000)
        assert len(out) == 1000
        diffs = np.diff(out[_COL_DIST].values)
        np.testing.assert_allclose(diffs, diffs[0], rtol=1e-6)

    _test("irregular_sampling", t_irregular_sampling)

    #
    # Test 7 – distance_norm is exactly 0 → 1

    #
    def t_distance_norm() -> None:
        df  = _lap(n=150)
        out = resample_lap_by_distance(df, n_points=500)
        assert _COL_DIST_NORM in out.columns
        np.testing.assert_allclose(
            float(out[_COL_DIST_NORM].iloc[0]),  0.0, atol=1e-9
        )
        np.testing.assert_allclose(
            float(out[_COL_DIST_NORM].iloc[-1]), 1.0, atol=1e-9
        )

    _test("distance_norm_bounds", t_distance_norm)

    #
    # Test 8 – resample_all_laps processes multiple laps

    #
    def t_all_laps_dict() -> None:
        lap_dict = {1: _lap(n=200, lap_num=1),
                    2: _lap(n=250, lap_num=2),
                    3: _lap(n=180, lap_num=3)}
        out_dict = resample_all_laps(lap_dict, n_points=500)
        assert set(out_dict.keys()) == {1, 2, 3}
        for k, v in out_dict.items():
            assert len(v) == 500, f"Lap {k}: expected 500 rows, got {len(v)}"

    _test("all_laps_dict", t_all_laps_dict)

    #
    # Test 9 – bad lap in dict is skipped, others succeed

    #
    def t_bad_lap_skipped() -> None:
        bad_df = pd.DataFrame({"Speed (m/s)": [10.0, 20.0]})   # no Distance
        lap_dict = {
            1: _lap(n=200, lap_num=1),
            2: bad_df,
            3: _lap(n=200, lap_num=3),
        }
        out_dict = resample_all_laps(lap_dict, n_points=500)
        assert 1 in out_dict
        assert 3 in out_dict
        assert 2 not in out_dict, "Bad lap should have been skipped"

    _test("bad_lap_skipped", t_bad_lap_skipped)

    #
    # Test 10 – missing distance column raises ResamplingError

    #
    def t_missing_distance_raises() -> None:
        df = pd.DataFrame({_COL_TIME: [0.0, 1.0], _COL_SPEED: [10.0, 20.0]})
        try:
            resample_lap_by_distance(df)
            raise AssertionError("Should have raised ResamplingError")
        except ResamplingError:
            pass

    _test("missing_distance_raises", t_missing_distance_raises)

    #
    # Test 11 – all-NaN distance raises ResamplingError

    #
    def t_all_nan_distance_raises() -> None:
        df = pd.DataFrame({
            _COL_DIST:  [np.nan, np.nan, np.nan],
            _COL_SPEED: [10.0,   20.0,   30.0],
        })
        try:
            resample_lap_by_distance(df)
            raise AssertionError("Should have raised ResamplingError")
        except ResamplingError:
            pass

    _test("all_nan_distance_raises", t_all_nan_distance_raises)

    #
    # Test 12 – speed channel with only NaN fills with NaN (no crash)

    #
    def t_all_nan_channel_fills_nan() -> None:
        df = pd.DataFrame({
            _COL_DIST:  np.linspace(0, 4500, 100),
            _COL_TIME:  np.linspace(0, 90,   100),
            _COL_SPEED: [np.nan] * 100,
        })
        out = resample_lap_by_distance(df, n_points=200)
        assert out[_COL_SPEED].isna().all(), (
            "All-NaN speed channel should remain NaN after interpolation"
        )
        assert out[_COL_TIME].isna().sum() == 0, (
            "Time channel should still be valid"
        )

    _test("all_nan_channel_fills_nan", t_all_nan_channel_fills_nan)

    #
    # Test 13 – n_points=2 edge case

    #
    def t_n_points_minimum() -> None:
        df  = _lap(n=100)
        out = resample_lap_by_distance(df, n_points=2)
        assert len(out) == 2

    _test("n_points_minimum", t_n_points_minimum)

    #
    # Test 14 – non-numeric (lap #) column preserved

    #
    def t_non_numeric_column_preserved() -> None:
        df = _lap(n=200, lap_num=7)
        # Add a string column

        df["compound"] = "SOFT"
        out = resample_lap_by_distance(df, n_points=500)
        assert "compound" in out.columns
        assert (out["compound"] == "SOFT").all()
        assert int(out[_COL_LAP].iloc[0]) == 7

    _test("non_numeric_column_preserved", t_non_numeric_column_preserved)

    #
    # Test 15 – interpolated speed is within original min/max (no overshoot)

    #
    def t_no_overshoot() -> None:
        df       = _lap(n=200)
        spd_min  = df[_COL_SPEED].min()
        spd_max  = df[_COL_SPEED].max()
        out      = resample_lap_by_distance(df, n_points=1000)
        assert out[_COL_SPEED].min() >= spd_min - 1e-6, (
            "Interpolated speed below original minimum"
        )
        assert out[_COL_SPEED].max() <= spd_max + 1e-6, (
            "Interpolated speed above original maximum (overshoot)"
        )

    _test("no_overshoot", t_no_overshoot)

    #
    # Test 16 – equal-length arrays in all_laps output (lap comparison ready)

    #
    def t_equal_length_for_comparison() -> None:
        lap_dict = {
            i: _lap(n=rng.integers(100, 400), lap_num=i)
            for i in range(1, 6)
        }
        out_dict = resample_all_laps(lap_dict, n_points=750)
        lengths  = [len(v) for v in out_dict.values()]
        assert len(set(lengths)) == 1, (
            f"All laps must have equal length; got {set(lengths)}"
        )

    _test("equal_length_for_comparison", t_equal_length_for_comparison)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    print(f"\nResampling Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  ✓ {name}")
    for name, tb in failed:
        print(f"  ✗ {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


def build_master_grid(resampled_laps: dict, n_points: int = 1000) -> np.ndarray:
    """Canonical distance grid from median of all lap distance ranges."""
    if not resampled_laps:
        return np.linspace(0, 1000, n_points)
    maxes = []
    for lap_df in resampled_laps.values():
        if lap_df is not None and not lap_df.empty and _COL_DIST in lap_df.columns:
            maxes.append(float(lap_df[_COL_DIST].max()))
    if not maxes:
        return np.linspace(0, 1000, n_points)
    median_max = float(np.median(maxes))
    return np.linspace(0, median_max, n_points)


def align_to_grid(data: np.ndarray, data_dist: np.ndarray, master_grid: np.ndarray) -> np.ndarray:
    """Align any distance-indexed array to master grid via np.interp."""
    return np.interp(master_grid, data_dist, data)


def event_to_grid_index(s_position: float, master_grid: np.ndarray) -> int:
    """Convert s_position to nearest grid index via searchsorted."""
    idx = int(np.searchsorted(master_grid, s_position))
    idx = max(0, min(idx, len(master_grid) - 1))
    if idx > 0 and abs(master_grid[idx - 1] - s_position) < abs(master_grid[idx] - s_position):
        idx -= 1
    return idx


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()