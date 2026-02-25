"""
gps_filtering.py
----------------
GPS quality filtering for RaceChrono telemetry data.

Removes rows that fail any of four independent quality gates:

1. **Satellite count**     – rows where the number of visible satellites is
   below *min_satellites* indicate a weak fix and are dropped.
2. **Accuracy**            – rows where the reported horizontal accuracy exceeds
   *max_accuracy_m* metres are dropped.
3. **Speed spike**         – rows where the instantaneous speed is negative or
   exceeds *max_speed_mps* are dropped.  This catches GPS multipath artefacts
   and momentary fix losses that produce physically impossible velocities.
4. **Acceleration spike**  – rows where the speed change per time step exceeds
   *max_accel_mps2* are dropped.  This catches GPS multipath spikes that
   produce implausible acceleration even when absolute speed is in range.

All gate masks are computed on a single defensive copy and combined before
filtering, minimising DataFrame copies.

Each gate is applied independently; a row is kept only if it passes all
gates that are applicable (i.e. whose corresponding column is present in
the DataFrame).

After filtering, time gaps exceeding 2x the median time step are detected
and logged as warnings so downstream interpolation can be handled carefully.

Design principles
~~~~~~~~~~~~~~~~~
- Columns for any gate that is absent from the DataFrame are silently skipped
  rather than raising an error.
- Time ordering is preserved; the returned index is reset to 0-based integers.
- All filtering decisions are logged at INFO level with row counts.
- No mutation of the input DataFrame.
- No print statements; structured logging only.
- If all rows are filtered out, a descriptive GPSFilterError is raised.
- If more than 50% of rows are removed, a warning is logged.
"""

from __future__ import annotations

import logging
from typing import Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants  (single source of truth)

# -- -


_COL_SATELLITES: Final[str] = "Satellites"
_COL_ACCURACY:   Final[str] = "Accuracy (m)"
_COL_SPEED:      Final[str] = "Speed (m/s)"
_COL_TIME:       Final[str] = "Time (s)"


# -- -

# Exceptions

# -- -


class GPSFilterError(ValueError):
    """Raised when filter parameters are invalid."""


# -- -

# Internal helpers

# -- -


def _validate_params(
    min_satellites: int,
    max_accuracy_m: float,
    max_speed_mps: float,
    max_accel_mps2: float,
) -> None:
    """Raise GPSFilterError if any threshold is out of a sensible range."""
    errors: list[str] = []
    if min_satellites < 0:
        errors.append(f"min_satellites must be ≥ 0, got {min_satellites}")
    if max_accuracy_m <= 0:
        errors.append(f"max_accuracy_m must be > 0, got {max_accuracy_m}")
    if max_speed_mps <= 0:
        errors.append(f"max_speed_mps must be > 0, got {max_speed_mps}")
    if max_accel_mps2 <= 0:
        errors.append(f"max_accel_mps2 must be > 0, got {max_accel_mps2}")
    if errors:
        raise GPSFilterError("Invalid filter parameter(s):\n  " + "\n  ".join(errors))


def _log_gate(
    mask: pd.Series,
    gate_name: str,
    initial_len: int,
) -> int:
    """
    Log the number of rows that would be removed by *mask* and return the
    count.  Does **not** copy or filter the DataFrame -- callers combine
    masks externally and apply once.

    Parameters
    ----------
    mask:
        Boolean Series; True = keep the row.
    gate_name:
        Human-readable name used in log messages.
    initial_len:
        Row count before any filtering started, for percentage calculation.

    Returns
    -------
    int
        Number of rows rejected by this gate.
    """
    removed = int((~mask).sum())
    if removed:
        pct = 100.0 * removed / initial_len
        logger.info(
            "GPS filter [%s]: removed %d row(s) (%.1f %% of input).",
            gate_name, removed, pct,
        )
    else:
        logger.debug("GPS filter [%s]: no rows removed.", gate_name)
    return removed


def _detect_time_gaps(df: pd.DataFrame) -> None:
    """
    Scan *df* for time gaps exceeding 2x the median time step and log
    warnings with gap timestamps.  This alerts downstream code that
    interpolation across these gaps would be unreliable.

    Does nothing if the Time column is absent or there are fewer than 2 rows.
    """
    if _COL_TIME not in df.columns or len(df) < 2:
        return

    times = pd.to_numeric(df[_COL_TIME], errors="coerce")
    dt = times.diff().iloc[1:]               # first diff is NaN, skip it
    dt = dt.dropna()

    if dt.empty:
        return

    median_dt = dt.median()
    if median_dt <= 0:
        return

    threshold = 2.0 * median_dt
    gap_mask = dt > threshold
    if not gap_mask.any():
        return

    gap_indices = dt.index[gap_mask]
    n_gaps = len(gap_indices)
    max_gap = float(dt.loc[gap_indices].max()) if n_gaps else 0.0

    # Log summary instead of per-gap spam
    if n_gaps <= 5:
        for idx in gap_indices:
            t_before = times.loc[idx - 1] if (idx - 1) in times.index else float("nan")
            t_after  = times.loc[idx]
            gap_size = dt.loc[idx]
            logger.warning(
                "Time gap detected after filtering: %.4f s gap between "
                "t=%.4f s and t=%.4f s (threshold=%.4f s = 2x median dt).",
                gap_size, t_before, t_after, threshold,
            )
    else:
        logger.warning(
            "Time gap detected after filtering: %d gaps found "
            "(max=%.4f s, threshold=%.4f s = 2x median dt). "
            "First 3 shown below.",
            n_gaps, max_gap, threshold,
        )
        for idx in gap_indices[:3]:
            t_before = times.loc[idx - 1] if (idx - 1) in times.index else float("nan")
            t_after  = times.loc[idx]
            gap_size = dt.loc[idx]
            logger.warning(
                "  gap: %.4f s at t=%.4f s -> t=%.4f s",
                gap_size, t_before, t_after,
            )


# -- -

# Public API

# -- -


def filter_gps_quality(
    df: pd.DataFrame,
    *,
    min_satellites: int    = 5,
    max_accuracy_m: float  = 3.0,
    max_speed_mps:  float  = 80.0,
    max_accel_mps2: float  = 50.0,
) -> pd.DataFrame:
    """
    Remove low-quality GPS rows from *df* and return a cleaned DataFrame.

    Gates applied (in order)
    ~~~~~~~~~~~~~~~~~~~~~~~~
    1. ``Satellites``   < *min_satellites*       → dropped
    2. ``Accuracy (m)`` > *max_accuracy_m*       → dropped
    3. ``Speed (m/s)``  < 0 or > *max_speed_mps* → dropped
    4. Acceleration     > *max_accel_mps2*       → dropped
       (requires both ``Speed (m/s)`` and ``Time (s)`` columns)

    Any gate whose required column(s) are absent from *df* is silently
    skipped.

    Parameters
    ----------
    df:
        Input telemetry DataFrame.  Column names must match the RaceChrono
        export format (or the standardised internal names from
        ``telemetry_schema.py``).
    min_satellites:
        Minimum number of visible satellites required to keep a row.
        Default: 5.
    max_accuracy_m:
        Maximum acceptable horizontal accuracy in metres.  Default: 3.0.
    max_speed_mps:
        Maximum physically plausible speed in m/s.  Default: 80.0
        (approximately 288 km/h -- suitable for most circuit categories; increase for
        GT/F1 data).
    max_accel_mps2:
        Maximum plausible acceleration in m/s**2.  Default: 50.0
        (roughly 5 g -- catches GPS multipath spikes).

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame with reset integer index.  Time ordering is
        preserved (no rows are reordered).

    Raises
    ------
    TypeError
        If *df* is not a :class:`pandas.DataFrame`.
    GPSFilterError
        If any threshold value is outside a sensible range, or if all rows
        are removed by the filters (indicating wholly unusable GPS data).
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"filter_gps_quality() expects a pandas DataFrame, "
            f"got {type(df).__name__!r}."
        )

    _validate_params(min_satellites, max_accuracy_m, max_speed_mps, max_accel_mps2)

    if df.empty:
        logger.warning("filter_gps_quality() received an empty DataFrame; returning as-is.")
        return df.copy()

    initial_len = len(df)

    # -- Single defensive copy; all masks computed against this copy --------
    work = df.copy()

    # Combined keep-mask: starts as all-True, AND-ed with each gate.
    combined_mask = pd.Series(True, index=work.index)

    #
    # Gate 1 -- Satellite count
    #
    if _COL_SATELLITES in work.columns:
        sats = pd.to_numeric(work[_COL_SATELLITES], errors="coerce")
        gate_mask = sats.ge(min_satellites).fillna(False)   # NaN -> fail
        _log_gate(gate_mask, f"satellites >= {min_satellites}", initial_len)
        combined_mask = combined_mask & gate_mask
    else:
        logger.debug("Column %r not found; satellite gate skipped.", _COL_SATELLITES)

    #
    # Gate 2 -- Horizontal accuracy
    #
    if _COL_ACCURACY in work.columns:
        acc = pd.to_numeric(work[_COL_ACCURACY], errors="coerce")
        gate_mask = acc.le(max_accuracy_m).fillna(False)    # NaN -> fail
        _log_gate(gate_mask, f"accuracy <= {max_accuracy_m} m", initial_len)
        combined_mask = combined_mask & gate_mask
    else:
        logger.debug("Column %r not found; accuracy gate skipped.", _COL_ACCURACY)

    #
    # Gate 3 -- Speed spike  (BUG 1 FIX: also reject negative speeds)
    #
    if _COL_SPEED in work.columns:
        spd = pd.to_numeric(work[_COL_SPEED], errors="coerce")
        gate_mask = spd.ge(0) & spd.le(max_speed_mps)
        gate_mask = gate_mask.fillna(False)                 # NaN -> fail
        _log_gate(gate_mask, f"0 <= speed <= {max_speed_mps} m/s", initial_len)
        combined_mask = combined_mask & gate_mask
    else:
        logger.debug("Column %r not found; speed gate skipped.", _COL_SPEED)

    #
    # Gate 4 -- Acceleration plausibility  (BUG 3: new gate)
    #
    if _COL_SPEED in work.columns and _COL_TIME in work.columns:
        spd_vals  = pd.to_numeric(work[_COL_SPEED], errors="coerce")
        time_vals = pd.to_numeric(work[_COL_TIME],  errors="coerce")
        d_speed = spd_vals.diff().abs()
        d_time  = time_vals.diff()
        # Avoid division by zero: where dt <= 0 treat acceleration as NaN
        with np.errstate(divide="ignore", invalid="ignore"):
            accel = (d_speed / d_time.replace(0, np.nan)).abs()
        # First row has NaN diff -> pass by default.
        # Note: NaN.le(x) returns False (not NaN), so fillna won't help;
        # use explicit isna() to let NaN-accel rows pass.
        gate_mask = accel.le(max_accel_mps2) | accel.isna()
        _log_gate(gate_mask, f"accel <= {max_accel_mps2} m/s^2", initial_len)
        combined_mask = combined_mask & gate_mask
    else:
        logger.debug(
            "Column(s) %r / %r not found; acceleration gate skipped.",
            _COL_SPEED, _COL_TIME,
        )

    #
    # Apply combined mask once  (BUG 4: single filter application)
    #
    result = work[combined_mask]
    total_removed = initial_len - len(result)

    #
    # BUG 2: Protection when all rows are filtered out
    #
    kept = len(result)
    if kept == 0:
        raise GPSFilterError(
            f"All {initial_len} GPS row(s) were removed by quality filters. "
            "The GPS data is wholly unusable.  Check sensor hardware, signal "
            "environment, or relax filter thresholds."
        )

    if kept < 0.5 * initial_len:
        logger.warning(
            "GPS filtering removed more than 50%% of data: kept %d / %d row(s) "
            "(%.1f %% removed). Consider reviewing filter thresholds or data quality.",
            kept, initial_len, 100.0 * total_removed / initial_len,
        )

    #
    # Summary log
    #
    logger.info(
        "GPS filtering complete: kept %d / %d row(s) (removed %d total, %.1f %%).",
        kept, initial_len, total_removed, 100.0 * total_removed / initial_len,
    )

    result = result.reset_index(drop=True)

    #
    # BUG 5: Detect time gaps created by row deletion
    #
    _detect_time_gaps(result)

    return result


# -- -

# Unit tests

# -- -


def _run_tests() -> None:
    """
    Self-contained unit tests using synthetic data.
    Raises AssertionError on any failure; prints a summary on success.
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

    #
    # Fixtures

    #

    def _base_df(n: int = 10) -> pd.DataFrame:
        """Return a clean, all-passing synthetic DataFrame."""
        return pd.DataFrame({
            _COL_TIME:       np.linspace(0, 9, n),
            _COL_SATELLITES: np.full(n, 8),
            _COL_ACCURACY:   np.full(n, 1.5),
            _COL_SPEED:      np.linspace(10, 40, n),
        })

    #
    # Test 1 – clean input passes through unchanged

    #
    def t_clean_passthrough() -> None:
        df = _base_df()
        out = filter_gps_quality(df)
        assert len(out) == len(df), f"Expected {len(df)}, got {len(out)}"
        assert list(out.index) == list(range(len(df))), "Index should be reset"

    _test("clean_passthrough", t_clean_passthrough)

    #
    # Test 2 – low satellite count rows removed

    #
    def t_satellite_filter() -> None:
        df = _base_df(10)
        df.loc[2, _COL_SATELLITES] = 3   # below default threshold of 5
        df.loc[7, _COL_SATELLITES] = 1
        out = filter_gps_quality(df, min_satellites=5)
        assert len(out) == 8, f"Expected 8 rows, got {len(out)}"
        assert (out[_COL_SATELLITES] >= 5).all(), "All remaining rows should pass satellite gate"

    _test("satellite_filter", t_satellite_filter)

    #
    # Test 3 – high accuracy (poor fix) rows removed

    #
    def t_accuracy_filter() -> None:
        df = _base_df(10)
        df.loc[0, _COL_ACCURACY] = 5.0   # exceeds default 3.0 m
        df.loc[9, _COL_ACCURACY] = 10.0
        out = filter_gps_quality(df, max_accuracy_m=3.0)
        assert len(out) == 8, f"Expected 8 rows, got {len(out)}"
        assert (out[_COL_ACCURACY] <= 3.0).all()

    _test("accuracy_filter", t_accuracy_filter)

    #
    # Test 4 – speed spike rows removed

    #
    def t_speed_filter() -> None:
        df = _base_df(10)
        df.loc[5, _COL_SPEED] = 150.0    # GPS multipath spike > 80 m/s default
        out = filter_gps_quality(df, max_speed_mps=80.0)
        # Row 5 removed by speed gate; row 6 also removed by accel gate
        # (speed drops from 150 back to ~26.67 in 1 s = 123 m/s^2 >> 50)
        assert len(out) == 8, f"Expected 8 rows, got {len(out)}"
        assert (out[_COL_SPEED] <= 80.0).all()

    _test("speed_filter", t_speed_filter)

    #
    # Test 5 – all three gates fire simultaneously

    #
    def t_all_gates() -> None:
        df = _base_df(12)
        df.loc[1,  _COL_SATELLITES] = 2    # fail sat
        df.loc[4,  _COL_ACCURACY]   = 8.0  # fail acc
        df.loc[9,  _COL_SPEED]      = 200.0 # fail spd
        # Row 10 will also fail accel gate (speed jumps back from 200 to ~37)
        out = filter_gps_quality(df)
        assert len(out) == 8, f"Expected 8 rows, got {len(out)}"

    _test("all_gates", t_all_gates)

    #
    # Test 6 – missing columns are skipped (no KeyError)

    #
    def t_missing_columns() -> None:
        df = pd.DataFrame({
            _COL_TIME:  [0.0, 1.0, 2.0],
            _COL_SPEED: [10.0, 20.0, 999.0],   # spike present
            # no Satellites or Accuracy columns

        })
        out = filter_gps_quality(df, max_speed_mps=80.0)
        assert len(out) == 2, f"Expected 2 rows after speed gate, got {len(out)}"

    _test("missing_columns", t_missing_columns)

    #
    # Test 7 – NaN values in gate columns fail the gate

    #
    def t_nan_in_gate_columns() -> None:
        df = _base_df(6)
        df.loc[2, _COL_SATELLITES] = np.nan
        df.loc[4, _COL_ACCURACY]   = np.nan
        out = filter_gps_quality(df)
        # Rows 2 and 4 should be dropped (NaN → fail)

        assert len(out) == 4, f"Expected 4 rows, got {len(out)}"

    _test("nan_in_gate_columns", t_nan_in_gate_columns)

    #
    # Test 8 – time ordering preserved

    #
    def t_time_ordering() -> None:
        df = _base_df(8)
        df.loc[3, _COL_SPEED] = 500.0    # will be removed
        out = filter_gps_quality(df, max_speed_mps=80.0)
        times = out[_COL_TIME].tolist()
        assert times == sorted(times), "Time ordering was not preserved"

    _test("time_ordering", t_time_ordering)

    #
    # Test 9 – empty DataFrame returns empty without error

    #
    def t_empty_dataframe() -> None:
        df = pd.DataFrame(columns=[_COL_TIME, _COL_SATELLITES, _COL_ACCURACY, _COL_SPEED])
        out = filter_gps_quality(df)
        assert out.empty

    _test("empty_dataframe", t_empty_dataframe)

    #
    # Test 10 – invalid parameters raise GPSFilterError

    #
    def t_invalid_params() -> None:
        df = _base_df(4)
        try:
            filter_gps_quality(df, min_satellites=-1)
            raise AssertionError("Should have raised GPSFilterError")
        except GPSFilterError:
            pass
        try:
            filter_gps_quality(df, max_accuracy_m=0.0)
            raise AssertionError("Should have raised GPSFilterError")
        except GPSFilterError:
            pass
        try:
            filter_gps_quality(df, max_speed_mps=-10.0)
            raise AssertionError("Should have raised GPSFilterError")
        except GPSFilterError:
            pass
        try:
            filter_gps_quality(df, max_accel_mps2=0.0)
            raise AssertionError("Should have raised GPSFilterError")
        except GPSFilterError:
            pass

    _test("invalid_params", t_invalid_params)

    #
    # Test 11 – TypeError on non-DataFrame input

    #
    def t_type_error() -> None:
        try:
            filter_gps_quality([1, 2, 3])  # type: ignore[arg-type]
            raise AssertionError("Should have raised TypeError")
        except TypeError:
            pass

    _test("type_error", t_type_error)

    #
    # Test 12 – custom thresholds respected

    #
    def t_custom_thresholds() -> None:
        df = _base_df(10)
        # Baseline accuracy is 1.5 m — set it to 0.8 m so rows pass strict ≤1.0 m gate.

        df[_COL_ACCURACY] = 0.8
        df.loc[5, _COL_SATELLITES] = 6    # passes default (≥5) but fails strict (≥8)
        df.loc[6, _COL_ACCURACY]   = 2.0  # passes default (≤3.0) but fails strict (≤1.0)
        out = filter_gps_quality(df, min_satellites=8, max_accuracy_m=1.0)
        assert len(out) == 8, f"Expected 8 rows, got {len(out)}"

    _test("custom_thresholds", t_custom_thresholds)

    #
    # Test 13 -- negative speed is rejected (BUG 1)

    #
    def t_negative_speed_rejected() -> None:
        df = _base_df(6)
        df.loc[1, _COL_SPEED] = -5.0    # negative speed -> should be dropped
        df.loc[3, _COL_SPEED] = -0.001  # tiny negative   -> should be dropped
        out = filter_gps_quality(df)
        assert len(out) == 4, f"Expected 4 rows, got {len(out)}"
        assert (out[_COL_SPEED] >= 0).all(), "Negative speeds should be removed"

    _test("negative_speed_rejected", t_negative_speed_rejected)

    #
    # Test 14 -- all rows filtered raises GPSFilterError (BUG 2)

    #
    def t_all_rows_filtered_raises() -> None:
        df = _base_df(5)
        df[_COL_SPEED] = 999.0          # all rows fail speed gate
        try:
            filter_gps_quality(df, max_speed_mps=80.0)
            raise AssertionError("Should have raised GPSFilterError")
        except GPSFilterError:
            pass

    _test("all_rows_filtered_raises", t_all_rows_filtered_raises)

    #
    # Test 15 -- acceleration gate removes implausible acceleration (BUG 3)

    #
    def t_accel_gate() -> None:
        n = 10
        dt = 0.1
        df = pd.DataFrame({
            _COL_TIME:       np.arange(n) * dt,
            _COL_SATELLITES: np.full(n, 8),
            _COL_ACCURACY:   np.full(n, 1.0),
            _COL_SPEED:      np.full(n, 20.0),
        })
        # Insert a speed that changes by 100 m/s in 0.1 s = 1000 m/s^2
        df.loc[5, _COL_SPEED] = 120.0  # also exceeds 80 m/s default, so row 5 fails speed+accel
        # Row 6 returns to 20: accel = |20-120|/0.1 = 1000 m/s^2 -> fails accel
        out = filter_gps_quality(df, max_speed_mps=200.0, max_accel_mps2=50.0)
        # Row 5: accel = |120-20|/0.1 = 1000 -> removed
        # Row 6: accel = |20-120|/0.1 = 1000 -> removed
        assert len(out) == 8, f"Expected 8 rows, got {len(out)}"

    _test("accel_gate", t_accel_gate)

    #
    # Test 16 -- accel gate skipped when columns missing (BUG 3 edge case)

    #
    def t_accel_gate_no_time_col() -> None:
        df = pd.DataFrame({
            _COL_SATELLITES: [8, 8, 8],
            _COL_ACCURACY:   [1.0, 1.0, 1.0],
            _COL_SPEED:      [10.0, 20.0, 30.0],
            # no Time column -> accel gate should be silently skipped
        })
        out = filter_gps_quality(df)
        assert len(out) == 3, f"Expected 3 rows (accel gate skipped), got {len(out)}"

    _test("accel_gate_no_time_col", t_accel_gate_no_time_col)

    #
    # Test 17 -- input DataFrame not mutated (single-copy design, BUG 4)

    #
    def t_input_not_mutated() -> None:
        df = _base_df(6)
        original_values = df.values.copy()
        df.loc[2, _COL_SPEED] = 999.0   # will be filtered
        df_before = df.copy()
        _ = filter_gps_quality(df, max_speed_mps=80.0)
        pd.testing.assert_frame_equal(df, df_before)

    _test("input_not_mutated", t_input_not_mutated)

    #
    # Test 18 -- gap detection logs warnings (BUG 5)

    #
    def t_gap_detection() -> None:
        import io

        handler = logging.StreamHandler(io.StringIO())
        handler.setLevel(logging.WARNING)
        # Use the module-level logger directly (name may differ between
        # module import and __main__ execution contexts).
        logger.addHandler(handler)
        try:
            # Create data where removing middle rows creates a time gap.
            # Times: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9
            df = pd.DataFrame({
                _COL_TIME:       np.arange(10, dtype=float),
                _COL_SATELLITES: np.full(10, 8),
                _COL_ACCURACY:   np.full(10, 1.0),
                _COL_SPEED:      np.full(10, 20.0),
            })
            # Make rows 3, 4, 5 fail -> creates gap from t=2 to t=6
            df.loc[3, _COL_SPEED] = -1.0
            df.loc[4, _COL_SPEED] = -1.0
            df.loc[5, _COL_SPEED] = -1.0
            _ = filter_gps_quality(df)
            log_output = handler.stream.getvalue()
            assert "Time gap detected" in log_output, (
                "Expected gap warning in log output"
            )
        finally:
            logger.removeHandler(handler)

    _test("gap_detection", t_gap_detection)

    #
    # Test 19 -- max_accel_mps2 param validation

    #
    def t_invalid_accel_param() -> None:
        df = _base_df(4)
        try:
            filter_gps_quality(df, max_accel_mps2=-5.0)
            raise AssertionError("Should have raised GPSFilterError")
        except GPSFilterError:
            pass

    _test("invalid_accel_param", t_invalid_accel_param)

    #
    # Results

    #
    total = len(passed) + len(failed)
    print(f"\nGPS Filtering Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  PASS {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()