"""
session_trimming.py -- -
Identifies and removes low-quality session segments from telemetry data.

Three complementary trimming operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. ``identify_outlaps(lap_times)``
   Labels laps as outlaps/inlaps when their duration exceeds
   ``outlap_ratio × median(representative_laps)``.

2. ``identify_waiting_periods(df)``
   Detects continuous blocks where speed < *speed_threshold* for longer than
   *min_duration_s* seconds (pit-lane queuing, formation laps, red flags).

3. ``trim_session(df)``
   Orchestrates both analyses, removes lap 0 (out-lap before first timed lap),
   strips waiting periods, and returns a cleaned DataFrame plus a structured
   report dict describing every removal decision.

Design principles
~~~~~~~~~~~~~~~~~
- All thresholds are keyword arguments with documented defaults; no magic
  numbers in the logic paths.
- The report dict is machine-readable so downstream code can log, persist, or
  surface it in a UI without string parsing.
- Input DataFrames are never mutated.
- Structured logging only; zero print statements.
- Edge cases (empty DataFrame, single lap, all outlaps) are handled
  explicitly with early returns and clear log messages.
"""

from __future__ import annotations

import logging
from typing import Any, Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants

# -- -


_COL_LAP:   Final[str] = "Lap #"
_COL_TIME:  Final[str] = "Time (s)"
_COL_SPEED: Final[str] = "Speed (m/s)"
_COL_DIST:  Final[str] = "Distance (m)"

# -- -

# Default thresholds (all overridable via keyword arguments)

# -- -


_DEFAULT_OUTLAP_RATIO:   Final[float] = 1.5    #  × median representative lap
_DEFAULT_SPEED_THRESH:   Final[float] = 2.0    # m/s below which car is "waiting"
_DEFAULT_MIN_WAIT_S:     Final[float] = 5.0    # seconds of continuous low speed
_MIN_REPRESENTATIVE_LAPS: Final[int]  = 2      # need at least this many laps to
                                               # compute a meaningful median


# ── Per-session-type trim strategies ────────────────────────────
# Each strategy overrides defaults for specific session types.
#   keep_only_fast:   if True, discard warm-up/slow laps (e.g., qualifying)
#   keep_all:         if True, don't remove laps beyond outlap detection
#   preserve_pit_laps: if True, flag but don't remove pit-type laps
#   outlap_ratio:     multiplier threshold for outlap detection

_TRIM_STRATEGIES: dict[str, dict[str, Any]] = {
    "qualifying": {
        "keep_only_fast": True,
        "keep_all": False,
        "preserve_pit_laps": False,
        "outlap_ratio": 1.3,
    },
    "race": {
        "keep_only_fast": False,
        "keep_all": True,
        "preserve_pit_laps": False,
        "outlap_ratio": 2.0,
    },
    "sprint_race": {
        "keep_only_fast": False,
        "keep_all": True,
        "preserve_pit_laps": False,
        "outlap_ratio": 2.0,
    },
    "feature_race": {
        "keep_only_fast": False,
        "keep_all": True,
        "preserve_pit_laps": False,
        "outlap_ratio": 2.0,
    },
    "endurance": {
        "keep_only_fast": False,
        "keep_all": True,
        "preserve_pit_laps": True,
        "outlap_ratio": 2.5,
    },
    "endurance_stint": {
        "keep_only_fast": False,
        "keep_all": True,
        "preserve_pit_laps": True,
        "outlap_ratio": 2.5,
    },
    "endurance_race": {
        "keep_only_fast": False,
        "keep_all": True,
        "preserve_pit_laps": True,
        "outlap_ratio": 2.5,
    },
    "warmup": {
        "keep_only_fast": False,
        "keep_all": False,
        "preserve_pit_laps": False,
        "outlap_ratio": 2.0,
    },
    "test": {
        "keep_only_fast": False,
        "keep_all": False,
        "preserve_pit_laps": False,
        "outlap_ratio": 2.0,
    },
    "heat": {
        "keep_only_fast": True,
        "keep_all": False,
        "preserve_pit_laps": False,
        "outlap_ratio": 1.5,
    },
    "final": {
        "keep_only_fast": True,
        "keep_all": False,
        "preserve_pit_laps": False,
        "outlap_ratio": 1.5,
    },
    "sprint": {
        "keep_only_fast": False,
        "keep_all": True,
        "preserve_pit_laps": False,
        "outlap_ratio": 1.8,
    },
    "practice": {
        "keep_only_fast": False,
        "keep_all": False,
        "preserve_pit_laps": False,
        "outlap_ratio": 1.5,
    },
}


# -- -

# Exceptions

# -- -


class SessionTrimmingError(ValueError):
    """Raised when required columns are absent or data is structurally invalid."""


# -- -

# Internal helpers

# -- -


def _require_column(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        raise SessionTrimmingError(
            f"Required column {col!r} not found in DataFrame. "
            f"Available columns: {list(df.columns)}"
        )


def _lap_durations(df: pd.DataFrame) -> pd.Series:
    """
    Compute per-lap duration (seconds) from the time column.

    Returns a Series indexed by lap number.  Uses the span of ``Time (s)``
    within each lap group, which is robust to variable sample rates.
    """
    def _duration(group: pd.DataFrame) -> float:
        t = pd.to_numeric(group[_COL_TIME], errors="coerce").dropna()
        return float(t.max() - t.min()) if len(t) >= 2 else np.nan

    return (
        df.groupby(_COL_LAP, sort=True)
        .apply(_duration, include_groups=False)
        .rename("lap_duration_s")
    )


# -- -

# Public API  --  analysis functions

# -- -


def identify_outlaps(
    lap_times: pd.Series,
    *,
    outlap_ratio: float = _DEFAULT_OUTLAP_RATIO,
    flag_last_lap: bool = True,
    session_type: str = "practice",
) -> dict[str, Any]:
    """
    Classify laps as representative or outlaps/inlaps based on duration.

    A lap is considered an outlap (or inlap) when its duration exceeds
    ``outlap_ratio × median(representative_laps)``.  Lap 0 is always treated
    as an outlap regardless of duration.

    When ``flag_last_lap`` is True (default), the last lap is also checked
    against the threshold to catch end-of-race inlaps.

    For endurance sessions (``session_type="endurance"``), slow laps mid-session
    are flagged but returned separately in ``flagged_only`` so they can be
    displayed with a badge rather than fully removed.

    The algorithm is iterative:
      1. Start with all laps as candidates.
      2. Compute median of current candidate set.
      3. Remove candidates that exceed ``outlap_ratio × median``.
      4. Repeat until the candidate set stabilises.
    This converges in O(n) iterations and handles sessions where multiple
    early/late laps are slow without distorting the reference median.

    Parameters -- lap_times:
        Series mapping lap number (index) to lap duration in seconds.
        Must not be empty.
    outlap_ratio:
        Threshold multiplier above the median that marks a lap as slow.
        Default: 1.5.
    flag_last_lap:
        If True, also check the last lap against threshold (inlap detection).
    session_type:
        Session type string. For "endurance", mid-session slow laps are
        flagged only (pit laps), not treated as hard outlaps.

    Returns -- -
    dict with keys:
        ``outlap_numbers``    --  list[int]    --  laps classified as outlaps/inlaps
        ``representative``    --  list[int]    --  laps used for the reference median
        ``median_lap_s``      --  float        --  median of representative laps
        ``threshold_s``       --  float        --  absolute duration threshold used
        ``reason``            --  dict[int, str]  --  human-readable reason per outlap
        ``flagged_only``      --  list[int]    --  endurance pit laps (flagged, not removed)
        ``inlap_numbers``     --  list[int]    --  laps detected as end-of-session inlaps

    Raises -- ValueError
        If *outlap_ratio*  ≤ 1.0.
    SessionTrimmingError
        If *lap_times* is empty.
    """
    if outlap_ratio <= 1.0:
        raise ValueError(
            f"outlap_ratio must be > 1.0 to be meaningful, got {outlap_ratio}"
        )
    if lap_times.empty:
        raise SessionTrimmingError("lap_times is empty; cannot identify outlaps.")

    lap_times = pd.to_numeric(lap_times, errors="coerce").dropna()
    all_laps  = set(lap_times.index.tolist())

    reasons: dict[int, str] = {}
    flagged_only: list[int] = []
    inlap_numbers: list[int] = []

    # Lap 0 always removed  --  data before the first timed lap.

    if 0 in all_laps:
        reasons[0] = "lap_number == 0 (pre-session)"
        all_laps.discard(0)

    # Iterative outlap detection on remaining laps.

    candidates = {lap for lap in all_laps if lap_times[lap] == lap_times[lap]}  # non-NaN

    if len(candidates) < _MIN_REPRESENTATIVE_LAPS:
        logger.warning(
            "Only %d candidate lap(s) after removing lap 0; "
            "outlap detection skipped.",
            len(candidates),
        )
        median_s    = float(lap_times[list(candidates)].median()) if candidates else np.nan
        threshold_s = median_s * outlap_ratio if not np.isnan(median_s) else np.nan
        return {
            "outlap_numbers": list(reasons.keys()),
            "representative": sorted(candidates),
            "median_lap_s":   median_s,
            "threshold_s":    threshold_s,
            "reason":         reasons,
            "flagged_only":   flagged_only,
            "inlap_numbers":  inlap_numbers,
        }

    prev_size = -1
    while len(candidates) != prev_size:
        prev_size   = len(candidates)
        median_s    = float(lap_times[list(candidates)].median())
        threshold_s = median_s * outlap_ratio
        slow_laps   = {
            lap for lap in candidates
            if lap_times[lap] > threshold_s
        }
        for lap in slow_laps:
            reasons[lap] = (
                f"lap_time={lap_times[lap]:.1f}s > "
                f"threshold={threshold_s:.1f}s "
                f"({outlap_ratio}xmedian={median_s:.1f}s)"
            )
        candidates -= slow_laps

    # Final median is computed on the stabilised representative set.

    final_median    = float(lap_times[list(candidates)].median()) if candidates else np.nan
    final_threshold = final_median * outlap_ratio if not np.isnan(final_median) else np.nan

    # Check the last lap for inlap (end-of-session/race) if flag_last_lap.
    if flag_last_lap and candidates and not np.isnan(final_threshold):
        sorted_all = sorted(all_laps)
        if sorted_all:
            last_lap = sorted_all[-1]
            if last_lap in candidates and lap_times[last_lap] > final_threshold:
                reasons[last_lap] = (
                    f"inlap (end of session): lap_time={lap_times[last_lap]:.1f}s > "
                    f"threshold={final_threshold:.1f}s"
                )
                candidates.discard(last_lap)
                inlap_numbers.append(last_lap)

    # For endurance sessions, separate mid-session outlaps as "flagged only"
    # (pit laps) rather than full outlaps to be removed.
    is_endurance = str(session_type).lower() == "endurance"
    outlap_keys = sorted(reasons.keys())

    if is_endurance:
        # In endurance: lap 0 and inlaps are still removed.
        # Mid-session slow laps are moved to flagged_only.
        sorted_laps = sorted(all_laps)
        first_lap = sorted_laps[0] if sorted_laps else None
        last_lap_num = sorted_laps[-1] if sorted_laps else None

        new_outlap_keys = []
        for lk in outlap_keys:
            if lk == 0:
                new_outlap_keys.append(lk)  # always remove lap 0
            elif lk == first_lap or lk == last_lap_num:
                new_outlap_keys.append(lk)  # remove first/last outlaps
            elif lk in inlap_numbers:
                new_outlap_keys.append(lk)  # remove detected inlaps
            else:
                flagged_only.append(lk)  # flag mid-session pit laps
                reasons[lk] = "pit lap (endurance): " + reasons.get(lk, "slow lap")
        outlap_keys = new_outlap_keys

    result = {
        "outlap_numbers": outlap_keys,
        "representative": sorted(candidates),
        "median_lap_s":   round(final_median, 3),
        "threshold_s":    round(final_threshold, 3),
        "reason":         reasons,
        "flagged_only":   flagged_only,
        "inlap_numbers":  inlap_numbers,
    }

    logger.info(
        "Outlap detection: %d outlap(s) %s, %d representative lap(s), "
        "%d flagged-only, median=%.2f s, threshold=%.2f s.",
        len(result["outlap_numbers"]),
        result["outlap_numbers"],
        len(result["representative"]),
        len(flagged_only),
        final_median,
        final_threshold,
    )
    return result


def identify_waiting_periods(
    df: pd.DataFrame,
    *,
    speed_threshold_mps: float = _DEFAULT_SPEED_THRESH,
    min_duration_s:      float = _DEFAULT_MIN_WAIT_S,
) -> list[dict[str, Any]]:
    """
    Detect continuous time windows where the car is stationary or crawling.

    A waiting period is any unbroken run of samples with
    ``Speed (m/s) < speed_threshold_mps`` whose total duration (last sample
    time -- first sample time) exceeds *min_duration_s*.

    Parameters -- df:
        Telemetry DataFrame containing at minimum ``Time (s)`` and
        ``Speed (m/s)``.
    speed_threshold_mps:
        Speed below which a sample is considered "waiting".  Default: 2.0 m/s.
    min_duration_s:
        Minimum continuous duration (seconds) to qualify as a waiting period.
        Default: 5.0 s.

    Returns -- -
    list of dicts, each with keys:
        ``start_time_s``   --  float  --  session time at which the period begins
        ``end_time_s``     --  float  --  session time at which the period ends
        ``duration_s``     --  float  --  duration of the waiting period
        ``row_start``      --  int    --  DataFrame index of first row
        ``row_end``        --  int    --  DataFrame index of last row (inclusive)
        ``sample_count``   --  int    --  number of samples in the period

    Raises -- SessionTrimmingError
        If ``Time (s)`` or ``Speed (m/s)`` columns are absent.
    """
    _require_column(df, _COL_TIME)
    _require_column(df, _COL_SPEED)

    if df.empty:
        return []

    time  = pd.to_numeric(df[_COL_TIME],  errors="coerce").reset_index(drop=True)
    speed = pd.to_numeric(df[_COL_SPEED], errors="coerce").reset_index(drop=True)

    # Boolean mask: True = this sample is "slow"

    slow = speed.lt(speed_threshold_mps).fillna(True)   # NaN speed  --  treat as waiting

    # Label contiguous blocks using cumsum trick on transition edges

    # Label each contiguous run (slow or fast) with a unique ID using the

    # shift-based trick: a new group starts every time the boolean changes.

    run_id    = (slow != slow.shift()).cumsum()
    slow_runs = slow.groupby(run_id)

    periods: list[dict[str, Any]] = []

    for _, run in slow_runs:
        # Skip fast runs

        if not bool(run.iloc[0]):
            continue

        idx_start = int(run.index[0])
        idx_end   = int(run.index[-1])

        t_start = float(time.iloc[idx_start])
        t_end   = float(time.iloc[idx_end])
        duration = t_end - t_start

        if duration >= min_duration_s:
            periods.append({
                "start_time_s": round(t_start, 3),
                "end_time_s":   round(t_end,   3),
                "duration_s":   round(duration, 3),
                "row_start":    idx_start,
                "row_end":      idx_end,
                "sample_count": idx_end - idx_start + 1,
            })

    logger.info(
        "Waiting periods detected: %d period(s) "
        "(threshold=%.1f m/s, min_duration=%.1f s).",
        len(periods), speed_threshold_mps, min_duration_s,
    )
    return periods


def trim_session(
    df: pd.DataFrame,
    *,
    outlap_ratio:        float = _DEFAULT_OUTLAP_RATIO,
    speed_threshold_mps: float = _DEFAULT_SPEED_THRESH,
    min_wait_s:          float = _DEFAULT_MIN_WAIT_S,
    session_type:        str = "practice",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Remove low-quality segments from a telemetry session DataFrame.

    Trimming steps (applied in order)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    1. Remove all rows where ``Lap # == 0``.
    2. Identify outlaps/inlaps via :func:`identify_outlaps` and remove their rows.
    3. Identify waiting periods via :func:`identify_waiting_periods` and remove
       their rows.

    Parameters -- df:
        Input telemetry DataFrame with at minimum ``Lap #``, ``Time (s)``,
        and ``Speed (m/s)`` columns.
    outlap_ratio:
        Passed to :func:`identify_outlaps`.  Default: 1.5.
    speed_threshold_mps:
        Passed to :func:`identify_waiting_periods`.  Default: 2.0 m/s.
    min_wait_s:
        Minimum waiting period duration.  Default: 5.0 s.

    Returns -- -
    (trimmed_df, report) : tuple
        ``trimmed_df``
            Cleaned DataFrame with reset integer index.  Column order and
            dtypes are preserved.
        ``report``
            Dict with keys:
              ``rows_input``            --  int
              ``rows_output``           --  int
              ``rows_removed_total``    --  int
              ``rows_removed_lap0``     --  int
              ``rows_removed_outlaps``  --  int
              ``rows_removed_waiting``  --  int
              ``outlap_analysis``       --  dict from :func:`identify_outlaps`
              ``waiting_periods``       --  list from :func:`identify_waiting_periods`
              ``laps_removed``          --  list[int]
              ``laps_retained``         --  list[int]

    Raises -- TypeError
        If *df* is not a pandas DataFrame.
    SessionTrimmingError
        If required columns are missing.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"trim_session() expects a pandas DataFrame, got {type(df).__name__!r}."
        )

    for col in (_COL_LAP, _COL_TIME, _COL_SPEED):
        _require_column(df, col)

    rows_input = len(df)

    if df.empty:
        logger.warning("trim_session() received an empty DataFrame; returning as-is.")
        return df.copy(), _empty_report(rows_input)

    result = df.copy().reset_index(drop=True)

    # Look up session-type-specific trimming strategy
    _stype = str(session_type).lower().replace("-", "_") if session_type else "practice"
    strategy = _TRIM_STRATEGIES.get(_stype, _TRIM_STRATEGIES["practice"])

    # Override outlap_ratio from strategy if not explicitly passed
    effective_outlap_ratio = strategy["outlap_ratio"]

    report_details: dict[str, Any] = {}

    # Step 1  --  Remove lap 0

    #

    lap_col = pd.to_numeric(result[_COL_LAP], errors="coerce")
    mask_lap0    = lap_col.eq(0) | lap_col.isna()
    rows_lap0    = int(mask_lap0.sum())
    result       = result[~mask_lap0].reset_index(drop=True)

    logger.info("Lap 0 removal: dropped %d row(s).", rows_lap0)

    # Step 2  --  Outlap / inlap removal

    outlap_analysis: dict[str, Any] = {}
    rows_outlaps = 0

    if not result.empty:
        durations       = _lap_durations(result)
        outlap_analysis = identify_outlaps(
            durations,
            outlap_ratio=effective_outlap_ratio,
            flag_last_lap=True,
            session_type=session_type,
        )
        bad_laps        = set(outlap_analysis["outlap_numbers"])
        flagged_only    = set(outlap_analysis.get("flagged_only", []))

        # -- Strategy: keep_only_fast (qualifying / heat / final) --
        # Discard warm-up / slow laps that aren't already outlaps.
        if strategy.get("keep_only_fast") and len(durations) >= 3:
            valid_lap_nums = [
                ln for ln in durations.index
                if ln not in bad_laps and np.isfinite(durations[ln])
            ]
            valid_times = [float(durations[ln]) for ln in valid_lap_nums]
            if len(valid_times) >= 3:
                median_time = float(np.median(valid_times))
                fast_threshold = median_time * 1.02  # within 2% of median
                slow_laps = [
                    lap_num for lap_num, t in zip(valid_lap_nums, valid_times)
                    if t > fast_threshold
                ]
                for lap_num in slow_laps:
                    if lap_num not in bad_laps:
                        bad_laps.add(lap_num)
                        report_details.setdefault("qualifying_trimmed", []).append(lap_num)
                logger.info(
                    "keep_only_fast: trimmed %d slow lap(s) %s (threshold=%.2fs).",
                    len(report_details.get("qualifying_trimmed", [])),
                    report_details.get("qualifying_trimmed", []),
                    fast_threshold if valid_times else 0.0,
                )

        # -- Strategy: preserve_pit_laps (endurance) --
        # Move pit-type laps from bad_laps into flagged_only instead of removing.
        if strategy.get("preserve_pit_laps") and flagged_only:
            # Laps already in flagged_only from identify_outlaps are kept;
            # ensure they are NOT in bad_laps so they won't be removed.
            for lap_num in list(flagged_only):
                bad_laps.discard(lap_num)
            report_details["flagged_pit_laps"] = sorted(flagged_only)
            logger.info(
                "preserve_pit_laps: %d pit lap(s) flagged but retained %s.",
                len(flagged_only), sorted(flagged_only),
            )

        # -- Strategy: keep_all (race / endurance / sprint) --
        # Don't remove laps beyond lap-0 and outlap detection; only flag them.
        if strategy.get("keep_all") and bad_laps:
            # Still remove lap 0 (handled in Step 1) and genuine first/last
            # outlaps, but keep mid-session laps that were flagged as slow.
            keep_anyway: set[int] = set()
            sorted_all_laps = sorted(durations.index.tolist())
            first_real = sorted_all_laps[0] if sorted_all_laps else None
            last_real = sorted_all_laps[-1] if sorted_all_laps else None
            inlap_set = set(outlap_analysis.get("inlap_numbers", []))

            for lap_num in list(bad_laps):
                # Always remove genuine first/last outlaps and detected inlaps
                if lap_num == first_real or lap_num == last_real:
                    continue
                if lap_num in inlap_set:
                    continue
                # Mid-session slow laps: flag only, don't remove
                keep_anyway.add(lap_num)

            if keep_anyway:
                for lap_num in keep_anyway:
                    bad_laps.discard(lap_num)
                report_details["keep_all_retained"] = sorted(keep_anyway)
                logger.info(
                    "keep_all: retained %d mid-session lap(s) %s (flagged only).",
                    len(keep_anyway), sorted(keep_anyway),
                )

        if bad_laps:
            lap_col_r    = pd.to_numeric(result[_COL_LAP], errors="coerce")
            mask_outlaps = lap_col_r.isin(bad_laps)
            rows_outlaps = int(mask_outlaps.sum())
            result       = result[~mask_outlaps].reset_index(drop=True)
            logger.info(
                "Outlap removal: dropped %d row(s) from laps %s.",
                rows_outlaps, sorted(bad_laps),
            )

    # Step 3  --  Waiting period removal

    waiting_periods: list[dict[str, Any]] = []
    rows_waiting = 0

    if not result.empty:
        waiting_periods = identify_waiting_periods(
            result,
            speed_threshold_mps=speed_threshold_mps,
            min_duration_s=min_wait_s,
        )

        if waiting_periods:
            # Build a boolean keep-mask; mark all rows inside waiting windows

            # as False.  Windows are expressed as row indices in the *current*

            # (post-outlap) result, so index lookups are direct.

            keep = pd.Series(True, index=result.index)
            for period in waiting_periods:
                keep.iloc[period["row_start"] : period["row_end"] + 1] = False
            rows_waiting = int((~keep).sum())
            result       = result[keep].reset_index(drop=True)
            logger.info(
                "Waiting period removal: dropped %d row(s) across %d period(s).",
                rows_waiting, len(waiting_periods),
            )

    # Final report

    #

    rows_output       = len(result)
    rows_removed      = rows_input - rows_output
    retained_laps     = sorted(
        pd.to_numeric(result[_COL_LAP], errors="coerce").dropna().unique().astype(int).tolist()
    )
    removed_laps      = sorted(
        set(
            pd.to_numeric(df[_COL_LAP], errors="coerce").dropna().unique().astype(int).tolist()
        ) - set(retained_laps)
    )

    report: dict[str, Any] = {
        "rows_input":            rows_input,
        "rows_output":           rows_output,
        "rows_removed_total":    rows_removed,
        "rows_removed_lap0":     rows_lap0,
        "rows_removed_outlaps":  rows_outlaps,
        "rows_removed_waiting":  rows_waiting,
        "outlap_analysis":       outlap_analysis,
        "waiting_periods":       waiting_periods,
        "laps_removed":          removed_laps,
        "laps_retained":         retained_laps,
        "trim_strategy":         strategy,
        "trim_strategy_details": report_details,
    }

    logger.info(
        "Session trimming complete: %d  --  %d rows (removed %d total). "
        "Laps retained: %s  Laps removed: %s",
        rows_input, rows_output, rows_removed,
        retained_laps, removed_laps,
    )
    return result, report


def _empty_report(rows_input: int) -> dict[str, Any]:
    return {
        "rows_input":            rows_input,
        "rows_output":           rows_input,
        "rows_removed_total":    0,
        "rows_removed_lap0":     0,
        "rows_removed_outlaps":  0,
        "rows_removed_waiting":  0,
        "outlap_analysis":       {},
        "waiting_periods":       [],
        "laps_removed":          [],
        "laps_retained":         [],
    }


# -- -

# 3b. Incomplete-lap & session-pause detection (distance-based)

# -- -


_DEFAULT_MIN_LAP_DIST_RATIO: Final[float] = 0.925  # lap must cover >= 92.5% of median distance
_DEFAULT_MAX_LAP_DIST_RATIO: Final[float] = 1.075  # lap must cover <= 107.5% of median distance
_DEFAULT_MIN_LAP_TIME_RATIO: Final[float] = 0.90   # lap time must be > 90% of median time
_DEFAULT_MAX_LAP_TIME_RATIO: Final[float] = 1.10   # lap time must be <= 110% of median time
_DEFAULT_MIN_LAP_DURATION_S: Final[float] = 10.0   # laps shorter than this are always invalid
_DEFAULT_PAUSE_TIME_GAP_S:   Final[float] = 30.0   # time gap between samples that signals a pause


def identify_incomplete_laps(
    df: pd.DataFrame,
    *,
    min_lap_dist_ratio: float = _DEFAULT_MIN_LAP_DIST_RATIO,
    min_lap_duration_s: float = _DEFAULT_MIN_LAP_DURATION_S,
    pause_time_gap_s:   float = _DEFAULT_PAUSE_TIME_GAP_S,
) -> dict[str, Any]:
    """
    Detect incomplete laps (pit-in, session stops, pauses) using distance
    and time-gap analysis.

    A lap is "incomplete" if:
      1. Its covered distance is less than ``min_lap_dist_ratio x median_lap_distance``.
         This catches pit-in laps, short inlaps at end-of-session, and partial laps
         from pauses.
      2. Its total duration is less than ``min_lap_duration_s`` seconds.
      3. It contains a large time gap (> ``pause_time_gap_s``) between consecutive
         samples, indicating the session was paused/stopped mid-lap.

    Parameters -- df:
        Telemetry DataFrame with ``Lap #``, ``Time (s)``, and optionally
        ``Distance (m)`` columns.
    min_lap_dist_ratio:
        Fraction of the median lap distance below which a lap is incomplete.
    min_lap_duration_s:
        Absolute floor; laps shorter than this are always flagged.
    pause_time_gap_s:
        If any two consecutive samples within a lap have a time gap greater
        than this, the lap is flagged as containing a session pause.

    Returns -- -
    dict with keys:
        ``incomplete_laps``  -- set of lap numbers flagged as incomplete
        ``short_distance``   -- set flagged for short distance
        ``short_duration``   -- set flagged for very short duration
        ``paused_laps``      -- set flagged for mid-lap pauses
        ``median_distance_m``-- median distance of representative laps
        ``reason``           -- dict mapping lap number to reason string
    """
    _require_column(df, _COL_LAP)
    _require_column(df, _COL_TIME)

    short_distance: set[int] = set()
    short_duration: set[int] = set()
    paused_laps:    set[int] = set()
    reason: dict[int, str] = {}

    if df.empty:
        return {
            "incomplete_laps": set(),
            "short_distance":  set(),
            "short_duration":  set(),
            "paused_laps":     set(),
            "median_distance_m": float("nan"),
            "reason":          {},
        }

    lap_col = pd.to_numeric(df[_COL_LAP], errors="coerce")
    time_col = pd.to_numeric(df[_COL_TIME], errors="coerce")

    # Group by lap

    groups = df.groupby(lap_col.values)

    # Compute per-lap distance and duration

    lap_distances: dict[int, float] = {}
    lap_durations: dict[int, float] = {}

    has_dist = _COL_DIST in df.columns

    for lap_num, grp in groups:
        if np.isnan(lap_num):
            continue
        lap_num = int(lap_num)

        t = pd.to_numeric(grp[_COL_TIME], errors="coerce").dropna()
        if len(t) < 2:
            lap_durations[lap_num] = 0.0
            lap_distances[lap_num] = 0.0
            continue

        dur = float(t.max() - t.min())
        lap_durations[lap_num] = dur

        # Compute distance covered

        if has_dist:
            d = pd.to_numeric(grp[_COL_DIST], errors="coerce").dropna()
            if len(d) >= 2:
                lap_distances[lap_num] = float(d.max() - d.min())
            else:
                lap_distances[lap_num] = 0.0
        else:
            # Estimate from speed x time

            spd = pd.to_numeric(grp[_COL_SPEED], errors="coerce").dropna() if _COL_SPEED in grp.columns else pd.Series(dtype=float)
            if len(spd) >= 2 and len(t) >= 2:
                lap_distances[lap_num] = float(spd.mean()) * dur
            else:
                lap_distances[lap_num] = 0.0

        # Check for mid-lap time gaps (session pauses)

        t_arr = t.sort_values().values
        if len(t_arr) >= 2:
            diffs = np.diff(t_arr)
            max_gap = float(diffs.max())
            if max_gap > pause_time_gap_s:
                paused_laps.add(lap_num)
                reason[lap_num] = (
                    f"session pause: {max_gap:.1f}s gap between samples "
                    f"(threshold: {pause_time_gap_s:.1f}s)"
                )

    if not lap_distances:
        return {
            "incomplete_laps": set(),
            "short_distance":  set(),
            "short_duration":  set(),
            "paused_laps":     paused_laps,
            "median_distance_m": float("nan"),
            "reason":          reason,
        }

    # Compute median distance from all laps (will iteratively refine)

    all_dists = np.array(list(lap_distances.values()))
    valid_dists = all_dists[np.isfinite(all_dists) & (all_dists > 0)]

    if len(valid_dists) < 2:
        median_dist = float(valid_dists[0]) if len(valid_dists) == 1 else float("nan")
    else:
        # Iterative: start with all, remove outliers, recompute

        candidates = valid_dists.copy()
        for _ in range(3):
            med = float(np.median(candidates))
            # Keep only laps within 50% - 150% of median distance

            mask = (candidates >= med * 0.5) & (candidates <= med * 1.5)
            if mask.sum() >= 2:
                candidates = candidates[mask]
            else:
                break
        median_dist = float(np.median(candidates))

    dist_threshold = median_dist * min_lap_dist_ratio

    for lap_num, dist in lap_distances.items():
        # Short duration check

        dur = lap_durations.get(lap_num, 0.0)
        if dur < min_lap_duration_s:
            short_duration.add(lap_num)
            reason.setdefault(lap_num, (
                f"very short lap: duration={dur:.1f}s < "
                f"min={min_lap_duration_s:.1f}s"
            ))

        # Short distance check (only if we have a valid median)

        if np.isfinite(median_dist) and median_dist > 0:
            if dist < dist_threshold:
                short_distance.add(lap_num)
                reason.setdefault(lap_num, (
                    f"incomplete lap: distance={dist:.0f}m < "
                    f"threshold={dist_threshold:.0f}m "
                    f"({min_lap_dist_ratio:.1%} of median={median_dist:.0f}m)"
                ))

    all_incomplete = short_distance | short_duration | paused_laps

    logger.info(
        "Incomplete lap detection: %d flagged "
        "(short_dist=%d, short_dur=%d, paused=%d), "
        "median_distance=%.0f m, threshold=%.0f m.",
        len(all_incomplete), len(short_distance),
        len(short_duration), len(paused_laps),
        median_dist, dist_threshold if np.isfinite(dist_threshold) else 0.0,
    )

    return {
        "incomplete_laps":   all_incomplete,
        "short_distance":    short_distance,
        "short_duration":    short_duration,
        "paused_laps":       paused_laps,
        "median_distance_m": round(median_dist, 1) if np.isfinite(median_dist) else float("nan"),
        "reason":            reason,
    }


# -- -

# 3c. Validate lap bounds — strict (80,120%] time and [92.5,107.5%] distance

# -- -


def validate_lap_bounds(
    df: pd.DataFrame,
    *,
    min_time_ratio: float = _DEFAULT_MIN_LAP_TIME_RATIO,
    max_time_ratio: float = _DEFAULT_MAX_LAP_TIME_RATIO,
    min_dist_ratio: float = _DEFAULT_MIN_LAP_DIST_RATIO,
    max_dist_ratio: float = _DEFAULT_MAX_LAP_DIST_RATIO,
) -> dict[str, Any]:
    """
    Validate that every lap falls within strict time and distance bounds
    relative to the median of representative laps.

    A valid lap must satisfy **both** of the following:

    * **Time bound**: ``min_time_ratio * median_time < lap_time <= max_time_ratio * median_time``
      Default: (80%, 120%] — laps outside this window are anomalous.
    * **Distance bound**: ``min_dist_ratio * median_dist <= lap_dist <= max_dist_ratio * median_dist``
      Default: [92.5%, 107.5%] — laps covering significantly more or fewer
      metres than the median indicate missed/extra sector crossings, GPS drift,
      or track-cut shortcuts.

    The median is computed iteratively from laps that already pass a coarse
    filter (within 50–150% of the initial median) to resist skewing by
    extreme outliers.

    Parameters
    ----------
    df :
        Telemetry DataFrame with ``Lap #``, ``Time (s)``, and optionally
        ``Distance (m)`` columns.
    min_time_ratio :
        Lower bound for lap time as a fraction of median.  Laps faster than
        ``min_time_ratio × median`` are flagged (possible track cuts).
    max_time_ratio :
        Upper bound for lap time as a fraction of median.  Laps slower than
        ``max_time_ratio × median`` are flagged (slow / interrupted laps).
    min_dist_ratio :
        Lower bound for lap distance as a fraction of median.
    max_dist_ratio :
        Upper bound for lap distance as a fraction of median.

    Returns
    -------
    dict with keys:
        ``invalid_laps``      — set of lap numbers that violate bounds
        ``time_too_fast``     — set of laps below time lower bound
        ``time_too_slow``     — set of laps above time upper bound
        ``dist_too_short``    — set of laps below distance lower bound
        ``dist_too_long``     — set of laps above distance upper bound
        ``median_time_s``     — median lap time used as reference
        ``median_distance_m`` — median lap distance used as reference
        ``reason``            — dict mapping lap number → reason string
    """
    _require_column(df, _COL_LAP)
    _require_column(df, _COL_TIME)

    time_too_fast:  set[int] = set()
    time_too_slow:  set[int] = set()
    dist_too_short: set[int] = set()
    dist_too_long:  set[int] = set()
    reason: dict[int, str] = {}

    if df.empty:
        return {
            "invalid_laps":     set(),
            "time_too_fast":    set(),
            "time_too_slow":    set(),
            "dist_too_short":   set(),
            "dist_too_long":    set(),
            "median_time_s":    float("nan"),
            "median_distance_m": float("nan"),
            "reason":           {},
        }

    lap_col = pd.to_numeric(df[_COL_LAP], errors="coerce")
    groups = df.groupby(lap_col.values)

    # Compute per-lap time and distance
    lap_times: dict[int, float] = {}
    lap_dists: dict[int, float] = {}
    has_dist = _COL_DIST in df.columns

    for lap_num, grp in groups:
        if np.isnan(lap_num):
            continue
        lap_num = int(lap_num)

        t = pd.to_numeric(grp[_COL_TIME], errors="coerce").dropna()
        if len(t) < 2:
            continue
        lap_times[lap_num] = float(t.max() - t.min())

        if has_dist:
            d = pd.to_numeric(grp[_COL_DIST], errors="coerce").dropna()
            if len(d) >= 2:
                lap_dists[lap_num] = float(d.max() - d.min())

    if len(lap_times) < 3:
        logger.debug("validate_lap_bounds: fewer than 3 laps; skipping.")
        return {
            "invalid_laps":     set(),
            "time_too_fast":    set(),
            "time_too_slow":    set(),
            "dist_too_short":   set(),
            "dist_too_long":    set(),
            "median_time_s":    float("nan"),
            "median_distance_m": float("nan"),
            "reason":           {},
        }

    # --- Iterative robust median for times ---
    time_arr = np.array(list(lap_times.values()))
    time_arr = time_arr[np.isfinite(time_arr) & (time_arr > 0)]
    candidates_t = time_arr.copy()
    for _ in range(3):
        med_t = float(np.median(candidates_t))
        mask = (candidates_t >= med_t * 0.5) & (candidates_t <= med_t * 1.5)
        if mask.sum() >= 2:
            candidates_t = candidates_t[mask]
        else:
            break
    median_time = float(np.median(candidates_t))

    # --- Iterative robust median for distances ---
    median_dist = float("nan")
    if lap_dists:
        dist_arr = np.array(list(lap_dists.values()))
        dist_arr = dist_arr[np.isfinite(dist_arr) & (dist_arr > 0)]
        if len(dist_arr) >= 2:
            candidates_d = dist_arr.copy()
            for _ in range(3):
                med_d = float(np.median(candidates_d))
                mask_d = (candidates_d >= med_d * 0.5) & (candidates_d <= med_d * 1.5)
                if mask_d.sum() >= 2:
                    candidates_d = candidates_d[mask_d]
                else:
                    break
            median_dist = float(np.median(candidates_d))

    # --- Validate each lap ---
    lo_time = median_time * min_time_ratio
    hi_time = median_time * max_time_ratio

    for lap_num, t in lap_times.items():
        # Time: valid if min_time_ratio * median < t <= max_time_ratio * median
        if t <= lo_time:
            time_too_fast.add(lap_num)
            reason[lap_num] = (
                f"time too fast: {t:.3f}s <= {lo_time:.3f}s "
                f"({min_time_ratio:.0%} of median={median_time:.3f}s)"
            )
        elif t > hi_time:
            time_too_slow.add(lap_num)
            reason[lap_num] = (
                f"time too slow: {t:.3f}s > {hi_time:.3f}s "
                f"({max_time_ratio:.0%} of median={median_time:.3f}s)"
            )

    if np.isfinite(median_dist) and median_dist > 0:
        lo_dist = median_dist * min_dist_ratio
        hi_dist = median_dist * max_dist_ratio

        for lap_num, d in lap_dists.items():
            if d < lo_dist:
                dist_too_short.add(lap_num)
                reason.setdefault(lap_num, (
                    f"distance too short: {d:.0f}m < {lo_dist:.0f}m "
                    f"({min_dist_ratio:.1%} of median={median_dist:.0f}m)"
                ))
            elif d > hi_dist:
                dist_too_long.add(lap_num)
                reason.setdefault(lap_num, (
                    f"distance too long: {d:.0f}m > {hi_dist:.0f}m "
                    f"({max_dist_ratio:.1%} of median={median_dist:.0f}m)"
                ))

    all_invalid = time_too_fast | time_too_slow | dist_too_short | dist_too_long

    logger.info(
        "Lap bounds validation: %d invalid of %d total "
        "(fast=%d, slow=%d, short_dist=%d, long_dist=%d). "
        "Median: time=%.3fs, dist=%.0fm.",
        len(all_invalid), len(lap_times),
        len(time_too_fast), len(time_too_slow),
        len(dist_too_short), len(dist_too_long),
        median_time,
        median_dist if np.isfinite(median_dist) else 0.0,
    )

    return {
        "invalid_laps":     all_invalid,
        "time_too_fast":    time_too_fast,
        "time_too_slow":    time_too_slow,
        "dist_too_short":   dist_too_short,
        "dist_too_long":    dist_too_long,
        "median_time_s":    round(median_time, 3),
        "median_distance_m": round(median_dist, 1) if np.isfinite(median_dist) else float("nan"),
        "reason":           reason,
    }


# -- -

# 4. Advanced invalid-lap detection (track cuts + incidents)

# -- -


_DEFAULT_TRACK_CUT_PCT:  Final[float] = 7.0    # lap > 7% faster than local best (raised from 5% to reduce false flags)
_DEFAULT_INCIDENT_PCT:   Final[float] = 30.0   # lap > 30% slower than neighbours
_DEFAULT_ROLLING_WINDOW: Final[int]   = 5


def identify_invalid_laps(
    lap_times: list[float] | pd.Series | np.ndarray,
    *,
    lap_keys: list[int] | None = None,
    track_cut_pct: float = _DEFAULT_TRACK_CUT_PCT,
    incident_pct: float = _DEFAULT_INCIDENT_PCT,
    rolling_window: int = _DEFAULT_ROLLING_WINDOW,
    exclude_laps: list[int] | None = None,
) -> dict[str, Any]:
    """
    Detect laps that are anomalously fast (track cut) or slow (incident).

    Also supports manual exclusion via *exclude_laps*.

    Parameters -- lap_times:
        Ordered list/array of lap times in seconds.
    lap_keys:
        Lap identifiers corresponding to each element of *lap_times*.
        Defaults to ``[0, 1, 2, ...]``.
    track_cut_pct:
        Threshold for track-cut detection.  If a lap is more than this
        percentage faster than the local rolling-window best, flag it.
    incident_pct:
        Threshold for incident detection.  If a lap is more than this
        percentage slower than the average of its neighbours (excluding
        session start), flag it.
    rolling_window:
        Size of the rolling window for local-best comparison.
    exclude_laps:
        Manual list of lap keys to exclude (from JSON config).

    Returns -- -
    dict with keys:
        ``invalid_laps`` -- set of lap keys flagged as invalid
        ``track_cuts``   -- set of lap keys flagged as track cuts
        ``incidents``    -- set of lap keys flagged as incidents
        ``manual``       -- set of lap keys from manual exclude_laps
        ``reason``       -- dict mapping lap key to human-readable reason
    """
    arr = np.asarray(lap_times, dtype=float)
    n = len(arr)

    if lap_keys is None:
        lap_keys = list(range(n))

    if n != len(lap_keys):
        raise SessionTrimmingError(
            f"lap_times length ({n}) != lap_keys length ({len(lap_keys)})"
        )

    track_cuts: set[int] = set()
    incidents:  set[int] = set()
    manual_set: set[int] = set()
    reason: dict[int, str] = {}

    # -- Manual exclusions -- -

    if exclude_laps:
        for lk in exclude_laps:
            if lk in lap_keys:
                manual_set.add(lk)
                reason[lk] = "manual exclusion via config"

    # -- Track-cut detection -- -

    # A lap is flagged if it's more than track_cut_pct% faster than the local

    # best (rolling window of surrounding laps, excluding the lap itself).

    if n >= 3:
        half_w = rolling_window // 2
        for i in range(n):
            if not np.isfinite(arr[i]):
                continue

            # Build local window (excluding self)

            start = max(0, i - half_w)
            end   = min(n, i + half_w + 1)
            window = np.concatenate([arr[start:i], arr[i+1:end]])
            window = window[np.isfinite(window)]

            if len(window) < 2:
                continue

            local_best = float(window.min())
            if local_best <= 0:
                continue

            # If this lap is much faster than local best

            pct_faster = (local_best - arr[i]) / local_best * 100.0
            if pct_faster > track_cut_pct:
                lk = lap_keys[i]
                track_cuts.add(lk)
                reason[lk] = (
                    f"track cut: lap {arr[i]:.3f}s is {pct_faster:.1f}% "
                    f"faster than local best {local_best:.3f}s "
                    f"(threshold: {track_cut_pct}%)"
                )

    # -- Incident lap detection --
    # A lap is flagged if it's more than incident_pct% slower than the
    # median of its direct neighbours.  Uses median (not mean) so a single
    # outlier neighbour cannot poison the comparison.
    # Laps in the first 2 positions are exempt (warm-up, not incident).

    if n >= 3:
        for i in range(2, n):  # skip first 2 laps
            if not np.isfinite(arr[i]):
                continue
            # Already flagged as track cut — don't double-flag as incident
            if lap_keys[i] in track_cuts:
                continue

            # Gather up to 2 neighbours on each side (excluding self).
            # Skip neighbours that are:
            #   - already flagged as track cuts or incidents (cascade guard)
            #   - more than 30% faster than current lap (fragments/shortcuts)
            #   - more than 30% slower than current lap (other incidents)
            neighbours = []
            lo_bound = arr[i] * 0.85
            hi_bound = arr[i] * 1.15
            for j in (i - 2, i - 1, i + 1, i + 2):
                if 0 <= j < n and j != i and np.isfinite(arr[j]):
                    if lap_keys[j] in track_cuts:
                        continue
                    if lap_keys[j] in incidents:
                        continue
                    if arr[j] < lo_bound or arr[j] > hi_bound:
                        continue
                    neighbours.append(arr[j])

            if len(neighbours) < 1:
                continue

            med_neighbour = float(np.median(neighbours))
            if med_neighbour <= 0:
                continue

            pct_slower = (arr[i] - med_neighbour) / med_neighbour * 100.0
            if pct_slower > incident_pct:
                lk = lap_keys[i]
                incidents.add(lk)
                reason[lk] = (
                    f"incident: lap {arr[i]:.3f}s is {pct_slower:.1f}% "
                    f"slower than neighbours median {med_neighbour:.3f}s "
                    f"(threshold: {incident_pct}%)"
                )

    all_invalid = track_cuts | incidents | manual_set

    logger.info(
        "Invalid lap detection: %d flagged "
        "(track_cuts=%d, incidents=%d, manual=%d).",
        len(all_invalid), len(track_cuts), len(incidents), len(manual_set),
    )

    return {
        "invalid_laps": all_invalid,
        "track_cuts":   track_cuts,
        "incidents":    incidents,
        "manual":       manual_set,
        "reason":       reason,
    }


# -- -

# 5. Best-N% lap selection for theoretical building

# -- -


def select_best_n_percent_laps(
    lap_times: list[float] | pd.Series | np.ndarray,
    *,
    lap_keys: list[int] | None = None,
    best_pct: float = 30.0,
    min_laps: int = 3,
) -> list[int]:
    """
    Select the fastest N% of laps for theoretical envelope building.

    Parameters -- lap_times:
        Ordered list/array of lap times in seconds.
    lap_keys:
        Lap identifiers corresponding to each element of *lap_times*.
    best_pct:
        Percentage of laps to select (default 30%).
    min_laps:
        Minimum number of laps to return regardless of percentage.

    Returns -- -
    list of lap keys for the selected best laps.
    """
    arr = np.asarray(lap_times, dtype=float)
    n = len(arr)

    if lap_keys is None:
        lap_keys = list(range(n))

    # Filter NaN

    valid = [(lap_keys[i], arr[i]) for i in range(n) if np.isfinite(arr[i])]
    if not valid:
        return []

    # Sort by time (fastest first)

    valid.sort(key=lambda x: x[1])

    # Select top N%

    n_select = max(min_laps, int(np.ceil(len(valid) * best_pct / 100.0)))
    n_select = min(n_select, len(valid))

    selected = [key for key, _ in valid[:n_select]]
    logger.info(
        "Best-N%% selection: %d/%d laps (%.0f%% requested, min=%d).",
        len(selected), len(valid), best_pct, min_laps,
    )
    return selected


# -- -

# 6. Stint-based distance + time filtering (mean of 5 median laps)

# -- -

_DEFAULT_DIST_BAND_LOW:   Final[float] = 0.90   # keep if distance >= 90% of stint ref
_DEFAULT_DIST_BAND_HIGH:  Final[float] = 1.10   # keep if distance <= 110% of stint ref
_DEFAULT_TIME_BAND_LOW:   Final[float] = 0.90   # keep if time >= 90% of stint ref
_DEFAULT_TIME_BAND_HIGH:  Final[float] = 1.10   # keep if time <= 110% of stint ref
_DEFAULT_ROLLING_MEAN_WIN: Final[int]  = 10     # kept for backward compat (unused)


def identify_anomalous_laps(
    df: pd.DataFrame,
    *,
    dist_band_low:    float = _DEFAULT_DIST_BAND_LOW,
    dist_band_high:   float = _DEFAULT_DIST_BAND_HIGH,
    time_band_low:    float = _DEFAULT_TIME_BAND_LOW,
    time_band_high:   float = _DEFAULT_TIME_BAND_HIGH,
    rolling_window:   int   = _DEFAULT_ROLLING_MEAN_WIN,
    excluded_laps:    set[int] | None = None,
) -> dict[str, Any]:
    """
    Flag laps whose distance or time deviates from the stint reference.

    Reference computation
    ~~~~~~~~~~~~~~~~~~~~~
    Laps are grouped into **stints** (runs of consecutive lap numbers;
    a gap > 1 in numbering indicates a pit stop).  Within each stint the
    **5 median laps** (the 5 centrally-ranked laps when sorted by time)
    are selected and their mean time and mean distance become the stint
    reference.  Any lap whose time OR distance falls outside
    ``[band_low, band_high] × stint_reference`` is flagged.

    Parameters
    ----------
    df : pd.DataFrame
        Trimmed telemetry DataFrame (must contain ``Lap #``, ``Time (s)``,
        and ideally ``Distance (m)``).
    dist_band_low / dist_band_high : float
        Fraction of the stint reference distance defining the keep range.
    time_band_low / time_band_high : float
        Fraction of the stint reference time defining the keep range.
    rolling_window : int
        Kept for backward compatibility (unused).
    excluded_laps : set[int] | None
        Laps already excluded (outlaps etc.) — skip these.

    Returns
    -------
    dict with keys:
        ``flagged_laps``      -- set of lap numbers flagged
        ``dist_flagged``      -- set flagged by distance check
        ``time_flagged``      -- set flagged by time check
        ``reason``            -- dict[int, str]
        ``median_distance_m`` -- float (overall, for logging)
        ``lap_distances``     -- dict[int, float]
        ``lap_times``         -- dict[int, float]
        ``stint_refs``        -- dict[int, dict] per-stint reference info
    """
    _require_column(df, _COL_LAP)
    _require_column(df, _COL_TIME)

    excluded_laps = excluded_laps or set()
    dist_flagged: set[int] = set()
    time_flagged: set[int] = set()
    reason: dict[int, str] = {}

    if df.empty:
        return {
            "flagged_laps": set(), "dist_flagged": set(),
            "time_flagged": set(), "reason": {},
            "median_distance_m": float("nan"),
            "lap_distances": {}, "lap_times": {},
        }

    has_dist = _COL_DIST in df.columns
    lap_col = pd.to_numeric(df[_COL_LAP], errors="coerce")
    groups = df.groupby(lap_col.values)

    lap_distances: dict[int, float] = {}
    lap_durations: dict[int, float] = {}

    for lap_num, grp in groups:
        if np.isnan(lap_num):
            continue
        lap_num = int(lap_num)
        if lap_num in excluded_laps:
            continue

        t = pd.to_numeric(grp[_COL_TIME], errors="coerce").dropna()
        if len(t) < 2:
            lap_durations[lap_num] = 0.0
            lap_distances[lap_num] = 0.0
            continue

        lap_durations[lap_num] = float(t.max() - t.min())

        if has_dist:
            d = pd.to_numeric(grp[_COL_DIST], errors="coerce").dropna()
            if len(d) >= 2:
                lap_distances[lap_num] = float(d.max() - d.min())
            else:
                lap_distances[lap_num] = 0.0
        else:
            spd = (pd.to_numeric(grp[_COL_SPEED], errors="coerce").dropna()
                   if _COL_SPEED in grp.columns else pd.Series(dtype=float))
            if len(spd) >= 2:
                lap_distances[lap_num] = float(spd.mean()) * lap_durations[lap_num]
            else:
                lap_distances[lap_num] = 0.0

    if not lap_distances:
        return {
            "flagged_laps": set(), "dist_flagged": set(),
            "time_flagged": set(), "reason": {},
            "median_distance_m": float("nan"),
            "lap_distances": lap_distances, "lap_times": lap_durations,
        }

    # ── Detect stints from lap numbering gaps ──
    # A gap > 1 in consecutive lap numbers indicates a pit stop / stint break.
    sorted_laps = sorted(lap_durations.keys())
    stints: list[list[int]] = []
    if sorted_laps:
        current_stint: list[int] = [sorted_laps[0]]
        for i in range(1, len(sorted_laps)):
            if sorted_laps[i] - sorted_laps[i - 1] > 1:
                stints.append(current_stint)
                current_stint = [sorted_laps[i]]
            else:
                current_stint.append(sorted_laps[i])
        stints.append(current_stint)

    # ── Per-stint reference: mean of the 5 median laps ──
    stint_ref_time: dict[int, float] = {}
    stint_ref_dist: dict[int, float | None] = {}
    stint_refs_info: dict[int, dict] = {}  # stint_idx -> {ref_time, ref_dist, ...}

    for stint_idx, stint_laps in enumerate(stints):
        # Gather valid (non-excluded, positive, finite) lap times in this stint
        valid_in_stint = [
            (ln, lap_durations[ln])
            for ln in stint_laps
            if ln not in excluded_laps
            and lap_durations.get(ln, 0) > 0
            and np.isfinite(lap_durations.get(ln, 0))
        ]
        if len(valid_in_stint) < 3:
            continue  # Not enough laps for a meaningful reference

        # Sort by time, select up to 5 central (median) laps
        valid_in_stint.sort(key=lambda x: x[1])
        n = len(valid_in_stint)
        n_select = min(5, n)
        start_idx = (n - n_select) // 2
        median_entries = valid_in_stint[start_idx : start_idx + n_select]

        ref_time = float(np.mean([t for _, t in median_entries]))

        # Reference distance from the same median laps
        median_dists = [
            lap_distances[ln]
            for ln, _ in median_entries
            if lap_distances.get(ln, 0) > 0
        ]
        ref_dist = float(np.mean(median_dists)) if median_dists else None

        stint_refs_info[stint_idx] = {
            "laps": stint_laps,
            "median_lap_nums": [ln for ln, _ in median_entries],
            "ref_time_s": round(ref_time, 3),
            "ref_distance_m": round(ref_dist, 1) if ref_dist is not None else None,
            "n_valid": len(valid_in_stint),
        }

        for ln in stint_laps:
            stint_ref_time[ln] = ref_time
            stint_ref_dist[ln] = ref_dist

    # Overall median distance for logging
    all_dists = np.array([d for d in lap_distances.values() if d > 0])
    median_dist = float(np.median(all_dists)) if len(all_dists) > 0 else float("nan")

    # ── Flag laps outside [90%, 110%] of stint reference ──
    for lap_num in sorted_laps:
        if lap_num in excluded_laps:
            continue
        if lap_num not in stint_ref_time:
            continue
        ref_t = stint_ref_time[lap_num]
        ref_d = stint_ref_dist[lap_num]
        dur = lap_durations.get(lap_num, 0)
        dist = lap_distances.get(lap_num, 0)

        # Time check
        if dur > 0 and np.isfinite(dur):
            low_t = ref_t * time_band_low
            high_t = ref_t * time_band_high
            if dur < low_t:
                time_flagged.add(lap_num)
                reason.setdefault(lap_num, (
                    f"fast anomaly: {dur:.2f}s < {low_t:.2f}s "
                    f"({time_band_low:.0%} of stint ref {ref_t:.2f}s)"
                ))
            elif dur > high_t:
                time_flagged.add(lap_num)
                reason.setdefault(lap_num, (
                    f"slow anomaly: {dur:.2f}s > {high_t:.2f}s "
                    f"({time_band_high:.0%} of stint ref {ref_t:.2f}s)"
                ))

        # Distance check
        if ref_d is not None and dist > 0:
            low_d = ref_d * dist_band_low
            high_d = ref_d * dist_band_high
            if dist < low_d:
                dist_flagged.add(lap_num)
                reason.setdefault(lap_num, (
                    f"short distance: {dist:.0f}m < {low_d:.0f}m "
                    f"({dist_band_low:.0%} of stint ref {ref_d:.0f}m)"
                ))
            elif dist > high_d:
                dist_flagged.add(lap_num)
                reason.setdefault(lap_num, (
                    f"long distance: {dist:.0f}m > {high_d:.0f}m "
                    f"({dist_band_high:.0%} of stint ref {ref_d:.0f}m)"
                ))

    flagged = dist_flagged | time_flagged

    logger.info(
        "Anomalous lap filter: %d flagged "
        "(dist=%d, time=%d), %d stint(s), median_dist=%.0f m.",
        len(flagged), len(dist_flagged), len(time_flagged),
        len(stints),
        median_dist if np.isfinite(median_dist) else 0.0,
    )

    return {
        "flagged_laps":     flagged,
        "dist_flagged":     dist_flagged,
        "time_flagged":     time_flagged,
        "reason":           reason,
        "median_distance_m": round(median_dist, 1) if np.isfinite(median_dist) else float("nan"),
        "lap_distances":    lap_distances,
        "lap_times":        lap_durations,
        "stint_refs":       stint_refs_info,
    }


# -- -

# 7. Line deviation detection (track cuts via reference line comparison)

# -- -

_DEFAULT_LINE_DEVIATION_THRESHOLD_M: Final[float] = 8.0  # metres (relaxed to reduce GPS false positives)


def identify_line_deviations(
    resampled_laps: dict[int, pd.DataFrame],
    reference_line: pd.DataFrame | None,
    *,
    deviation_threshold_m: float = _DEFAULT_LINE_DEVIATION_THRESHOLD_M,
    excluded_laps: set[int] | None = None,
) -> dict[str, Any]:
    """
    Flag laps whose racing line deviates > *deviation_threshold_m* from the
    reference line, indicating potential track cuts or off-tracks.

    For each lap, the maximum perpendicular distance to the reference line
    is computed.  If it exceeds the threshold the lap is flagged.

    Parameters
    ----------
    resampled_laps : dict[int, DataFrame]
        Mapping of lap number → resampled lap DataFrame (must have
        lat/lon columns).
    reference_line : DataFrame | None
        Reference line with lat_ref_deg, lon_ref_deg columns.
    deviation_threshold_m : float
        Maximum allowed deviation in metres.
    excluded_laps : set[int] | None
        Laps already excluded.

    Returns
    -------
    dict with keys:
        ``deviated_laps``        -- set of flagged lap numbers
        ``max_deviations``       -- dict[int, float] (metres per lap)
        ``reason``               -- dict[int, str]
    """
    excluded_laps = excluded_laps or set()
    deviated: set[int] = set()
    max_devs: dict[int, float] = {}
    reason: dict[int, str] = {}

    if reference_line is None or not hasattr(reference_line, "columns"):
        return {"deviated_laps": deviated, "max_deviations": max_devs, "reason": reason}

    # Find reference line lat/lon columns
    ref_lat_col = ref_lon_col = None
    for c in reference_line.columns:
        cl = c.lower()
        if "lat_ref" in cl:
            ref_lat_col = c
        elif "lon_ref" in cl:
            ref_lon_col = c
    if ref_lat_col is None or ref_lon_col is None:
        return {"deviated_laps": deviated, "max_deviations": max_devs, "reason": reason}

    ref_lats = reference_line[ref_lat_col].values
    ref_lons = reference_line[ref_lon_col].values

    # Pre-compute reference as XY offsets (for fast distance calc)
    ref_lat0 = float(np.nanmean(ref_lats))
    # Approximate metres per degree
    m_per_lat = 111_320.0
    m_per_lon = 111_320.0 * np.cos(np.radians(ref_lat0))

    ref_x = (ref_lons - np.nanmean(ref_lons)) * m_per_lon
    ref_y = (ref_lats - ref_lat0) * m_per_lat
    ref_xy = np.column_stack([ref_x, ref_y])  # shape (N, 2)

    for lap_num, lap_df in resampled_laps.items():
        if lap_num in excluded_laps:
            continue
        if lap_df is None or len(lap_df) < 2:
            continue

        # Find lat/lon columns in lap data
        lat_col = lon_col = None
        for c in lap_df.columns:
            cl = c.lower()
            if "latitude" in cl and "deg" in cl:
                lat_col = c
            elif "longitude" in cl and "deg" in cl:
                lon_col = c
        if lat_col is None or lon_col is None:
            continue

        lats = pd.to_numeric(lap_df[lat_col], errors="coerce").values
        lons = pd.to_numeric(lap_df[lon_col], errors="coerce").values

        lap_x = (lons - np.nanmean(ref_lons)) * m_per_lon
        lap_y = (lats - ref_lat0) * m_per_lat

        # For each point in the lap, find min distance to any ref point
        # Use vectorised approach: for each lap point compute distance to
        # a subset of nearest ref points (chunked for memory efficiency)
        max_dev = 0.0
        chunk = 200  # process in chunks for large traces
        for start in range(0, len(lap_x), chunk):
            end = min(start + chunk, len(lap_x))
            lx = lap_x[start:end]
            ly = lap_y[start:end]
            valid = np.isfinite(lx) & np.isfinite(ly)
            if not valid.any():
                continue
            lx = lx[valid]
            ly = ly[valid]
            # Distance from each lap point to each ref point
            dx = lx[:, None] - ref_x[None, :]  # (M, N)
            dy = ly[:, None] - ref_y[None, :]
            dists = np.sqrt(dx * dx + dy * dy)
            min_dists = dists.min(axis=1)  # min distance to ref for each lap point
            chunk_max = float(min_dists.max())
            if chunk_max > max_dev:
                max_dev = chunk_max

        max_devs[lap_num] = round(max_dev, 2)
        if max_dev > deviation_threshold_m:
            deviated.add(lap_num)
            reason[lap_num] = (
                f"line deviation: {max_dev:.1f}m > "
                f"threshold {deviation_threshold_m:.1f}m"
            )

    logger.info(
        "Line deviation detection: %d deviated lap(s) out of %d checked "
        "(threshold=%.1fm).",
        len(deviated), len(max_devs), deviation_threshold_m,
    )

    return {
        "deviated_laps":   deviated,
        "max_deviations":  max_devs,
        "reason":          reason,
    }


# -- -

# Unit tests

# -- -


def _run_tests() -> None:
    import traceback

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:  # type: ignore[type-arg]
        try:
            fn()
            passed.append(name)
        except Exception:   # noqa: BLE001
            failed.append((name, traceback.format_exc()))

    # Helpers

    #

    def _make_session(
        lap_pattern: list[tuple[int, float, float]],
        hz: float = 10.0,
    ) -> pd.DataFrame:
        """
        Build a synthetic telemetry DataFrame.

        Parameters -- lap_pattern:
            List of (lap_number, lap_duration_s, avg_speed_mps).
        hz:
            Sample rate in Hz.
        """
        rows: list[dict] = []
        t = 0.0
        for lap_num, duration, avg_speed in lap_pattern:
            n_samples = max(2, int(duration * hz))
            for i in range(n_samples):
                rows.append({
                    _COL_LAP:   lap_num,
                    _COL_TIME:  round(t, 3),
                    _COL_SPEED: avg_speed + np.sin(i) * 0.5,
                })
                t += 1.0 / hz
        return pd.DataFrame(rows)

    # Test 1  --  lap 0 rows are always removed

    #

    def t_lap0_removed() -> None:
        df = _make_session([
            (0, 30.0, 20.0),   # pre-session
            (1, 90.0, 40.0),
            (2, 88.0, 41.0),
        ])
        out, report = trim_session(df)
        assert 0 not in pd.to_numeric(out[_COL_LAP]).unique(), "Lap 0 still present"
        assert report["rows_removed_lap0"] > 0
        assert 0 in report["laps_removed"]

    _test("lap0_always_removed", t_lap0_removed)

    # Test 2  --  outlap detected by 1.5× rule

    #

    def t_outlap_detected() -> None:
        # Laps 1-5 are representative ~90 s; lap 6 is a slow inlap at 160 s

        lap_times = pd.Series({1: 90.0, 2: 89.5, 3: 91.0, 4: 88.0, 5: 90.5, 6: 160.0})
        result = identify_outlaps(lap_times, outlap_ratio=1.5)
        assert 6 in result["outlap_numbers"], f"Lap 6 should be outlap: {result}"
        assert 6 not in result["representative"]

    _test("outlap_detected", t_outlap_detected)

    # Test 3  --  representative laps not misclassified

    #

    def t_representative_laps_kept() -> None:
        lap_times = pd.Series({1: 92.0, 2: 91.5, 3: 90.0, 4: 92.5, 5: 91.0})
        result = identify_outlaps(lap_times)
        assert result["outlap_numbers"] == [], (
            f"No outlaps expected, got {result['outlap_numbers']}"
        )
        assert sorted(result["representative"]) == [1, 2, 3, 4, 5]

    _test("representative_laps_kept", t_representative_laps_kept)

    # Test 4  --  multiple consecutive outlaps (opening + closing)

    #

    def t_multiple_outlaps() -> None:
        lap_times = pd.Series({
            1: 145.0,   # outlap
            2: 91.0, 3: 90.0, 4: 89.5, 5: 91.5,
            6: 155.0,   # inlap
        })
        result = identify_outlaps(lap_times)
        assert 1 in result["outlap_numbers"]
        assert 6 in result["outlap_numbers"]
        for rep in [2, 3, 4, 5]:
            assert rep in result["representative"]

    _test("multiple_outlaps", t_multiple_outlaps)

    # Test 5  --  waiting period detected (low speed > 5 s)

    #

    def t_waiting_period_detected() -> None:
        t = np.linspace(0, 30, 300)
        speed = np.full(300, 30.0)
        # Rows 100-160 = ~6 s of near-zero speed

        speed[100:160] = 0.5
        df = pd.DataFrame({_COL_TIME: t, _COL_SPEED: speed, _COL_LAP: 1})
        periods = identify_waiting_periods(df, speed_threshold_mps=2.0, min_duration_s=5.0)
        assert len(periods) >= 1, "Expected at least one waiting period"
        assert periods[0]["duration_s"] >= 5.0

    _test("waiting_period_detected", t_waiting_period_detected)

    # Test 6  --  short low-speed blip NOT flagged as waiting period

    #

    def t_short_blip_not_flagged() -> None:
        t = np.linspace(0, 20, 200)
        speed = np.full(200, 30.0)
        speed[90:95] = 1.0   # only ~0.5 s  — below 5 s threshold
        df = pd.DataFrame({_COL_TIME: t, _COL_SPEED: speed, _COL_LAP: 1})
        periods = identify_waiting_periods(df, speed_threshold_mps=2.0, min_duration_s=5.0)
        assert len(periods) == 0, f"Short blip should not be flagged: {periods}"

    _test("short_blip_not_flagged", t_short_blip_not_flagged)

    # Test 7  --  trim_session removes waiting periods from result

    #

    def t_trim_removes_waiting() -> None:
        n = 500
        t = np.linspace(0, 50, n)
        speed = np.full(n, 30.0)
        speed[200:270] = 0.3   # ~7 s waiting block
        df = pd.DataFrame({
            _COL_TIME:  t,
            _COL_SPEED: speed,
            _COL_LAP:   1,
        })
        out, report = trim_session(df, outlap_ratio=1.5)
        assert report["rows_removed_waiting"] > 0
        remaining_speed = out[_COL_SPEED].values
        # No remaining sample should be in the waiting block

        # (some edge samples may remain, so check the bulk)

        assert (remaining_speed > 2.0).mean() > 0.85

    _test("trim_removes_waiting", t_trim_removes_waiting)

    # Test 8  --  report dict contains expected keys

    #

    def t_report_keys() -> None:
        df = _make_session([(1, 90.0, 40.0), (2, 91.0, 41.0)])
        _, report = trim_session(df)
        expected_keys = {
            "rows_input", "rows_output", "rows_removed_total",
            "rows_removed_lap0", "rows_removed_outlaps", "rows_removed_waiting",
            "outlap_analysis", "waiting_periods", "laps_removed", "laps_retained",
            "trim_strategy", "trim_strategy_details",
        }
        assert expected_keys == set(report.keys()), (
            f"Missing keys: {expected_keys - set(report.keys())}"
        )

    _test("report_keys_complete", t_report_keys)

    # Test 9  --  input DataFrame is not mutated

    #

    def t_no_mutation() -> None:
        df = _make_session([(0, 20.0, 5.0), (1, 90.0, 40.0), (2, 88.0, 41.0)])
        n_before = len(df)
        cols_before = set(df.columns)
        trim_session(df)
        assert len(df) == n_before, "Input DataFrame was mutated (row count changed)"
        assert set(df.columns) == cols_before, "Input DataFrame was mutated (columns changed)"

    _test("no_input_mutation", t_no_mutation)

    # Test 10  --  outlap_ratio  ≤ 1.0 raises ValueError

    #

    def t_invalid_outlap_ratio() -> None:
        lap_times = pd.Series({1: 90.0, 2: 91.0})
        try:
            identify_outlaps(lap_times, outlap_ratio=0.9)
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    _test("invalid_ratio_raises", t_invalid_outlap_ratio)

    # Test 11  --  empty DataFrame returns empty with full report

    #

    def t_empty_df() -> None:
        df = pd.DataFrame(columns=[_COL_LAP, _COL_TIME, _COL_SPEED])
        out, report = trim_session(df)
        assert out.empty
        assert report["rows_removed_total"] == 0

    _test("empty_df_handled", t_empty_df)

    # Test 12  --  single representative lap session

    #

    def t_single_lap() -> None:
        df = _make_session([(1, 90.0, 40.0)])
        out, report = trim_session(df)
        assert 1 in report["laps_retained"]
        assert len(out) > 0

    _test("single_lap_session", t_single_lap)

    # Test 13  --  report row counts are self-consistent

    #

    def t_row_count_consistency() -> None:
        df = _make_session([
            (0, 25.0, 5.0),
            (1, 140.0, 15.0),  # outlap
            (2, 90.0, 40.0),
            (3, 89.0, 41.0),
            (4, 91.0, 40.5),
        ])
        out, report = trim_session(df)
        total_removed = (
            report["rows_removed_lap0"]
            + report["rows_removed_outlaps"]
            + report["rows_removed_waiting"]
        )
        assert report["rows_removed_total"] == total_removed, (
            f"Row count mismatch: total={report['rows_removed_total']} "
            f"vs sum={total_removed}"
        )
        assert report["rows_input"] == report["rows_output"] + report["rows_removed_total"]

    _test("row_counts_consistent", t_row_count_consistency)

    # Test 14 -- track cut detection

    #

    def t_track_cut_detected() -> None:
        # Normal laps ~90s, one suspiciously fast lap at 82s (> 5% faster)

        lt = [90.0, 91.0, 89.5, 82.0, 90.5, 91.0, 89.0]
        result = identify_invalid_laps(lt, track_cut_pct=5.0)
        assert 3 in result["track_cuts"], f"Lap 3 should be track cut: {result}"
        assert 3 in result["invalid_laps"]

    _test("track_cut_detected", t_track_cut_detected)

    # Test 15 -- legitimate fast lap NOT flagged as track cut

    #

    def t_no_false_track_cut() -> None:
        # All laps within normal range (< 5% variation)

        lt = [90.0, 89.5, 88.0, 89.0, 90.5]
        result = identify_invalid_laps(lt, track_cut_pct=5.0)
        assert len(result["track_cuts"]) == 0, f"False track cut: {result}"

    _test("no_false_track_cut", t_no_false_track_cut)

    # Test 16 -- incident lap detection (big spin/off)

    #

    def t_incident_detected() -> None:
        # Normal laps ~90s, one incident at lap 5 = 130s (> 30% slower)

        lt = [90.0, 91.0, 89.5, 90.5, 130.0, 89.0, 90.0]
        result = identify_invalid_laps(lt, incident_pct=30.0)
        assert 4 in result["incidents"], f"Lap 4 should be incident: {result}"
        assert 4 in result["invalid_laps"]

    _test("incident_detected", t_incident_detected)

    # Test 17 -- slow early laps NOT flagged as incident

    #

    def t_early_slow_not_incident() -> None:
        # First 2 laps slow (warm-up), should NOT be incidents

        lt = [130.0, 120.0, 90.0, 91.0, 89.5, 90.0]
        result = identify_invalid_laps(lt, incident_pct=30.0)
        assert 0 not in result["incidents"], "Lap 0 should be exempt"
        assert 1 not in result["incidents"], "Lap 1 should be exempt"

    _test("early_slow_not_incident", t_early_slow_not_incident)

    # Test 18 -- manual exclusion via config

    #

    def t_manual_exclusion() -> None:
        lt = [90.0, 91.0, 89.5, 90.0, 90.5]
        keys = [1, 2, 3, 4, 5]
        result = identify_invalid_laps(lt, lap_keys=keys, exclude_laps=[2, 4])
        assert 2 in result["manual"]
        assert 4 in result["manual"]
        assert 2 in result["invalid_laps"]
        assert 4 in result["invalid_laps"]

    _test("manual_exclusion", t_manual_exclusion)

    # Test 19 -- best-N% selection

    #

    def t_best_n_percent() -> None:
        lt = [90.0, 95.0, 88.0, 92.0, 87.0, 91.0, 89.0, 93.0, 88.5, 90.5]
        keys = list(range(10))
        selected = select_best_n_percent_laps(lt, lap_keys=keys, best_pct=30.0, min_laps=3)
        assert len(selected) == 3  # 30% of 10 = 3
        # Should be the 3 fastest: keys 4 (87s), 2 (88s), 8 (88.5s)

        assert 4 in selected
        assert 2 in selected

    _test("best_n_percent", t_best_n_percent)

    # Test 20 -- best-N% with min_laps floor

    #

    def t_best_n_min_floor() -> None:
        lt = [90.0, 91.0, 89.0, 92.0]
        selected = select_best_n_percent_laps(lt, best_pct=10.0, min_laps=3)
        assert len(selected) >= 3  # min_laps=3 overrides 10% of 4 = 0.4

    _test("best_n_min_floor", t_best_n_min_floor)

    # Test 21  --  anomalous_laps: short-distance lap flagged

    def t_anomalous_short_dist() -> None:
        # Build session with distance column: 5 laps ~1000m, 1 lap ~600m
        rows = []
        t = 0.0
        for lap_num in range(1, 7):
            dist_total = 600.0 if lap_num == 3 else 1000.0
            dur = 90.0
            n = 100
            for i in range(n):
                rows.append({
                    _COL_LAP: lap_num,
                    _COL_TIME: round(t, 3),
                    _COL_SPEED: 30.0,
                    _COL_DIST: dist_total * i / (n - 1),
                })
                t += dur / n
        df = pd.DataFrame(rows)
        result = identify_anomalous_laps(df, dist_band_low=0.90, dist_band_high=1.10)
        assert 3 in result["dist_flagged"], f"Lap 3 should be distance-flagged: {result}"

    _test("anomalous_short_dist", t_anomalous_short_dist)

    # Test 22  --  anomalous_laps: slow lap flagged by rolling-mean time

    def t_anomalous_slow_time() -> None:
        # 10 normal laps ~90s, then 1 lap at 130s
        rows = []
        t = 0.0
        for lap_num in range(1, 12):
            dur = 130.0 if lap_num == 11 else 90.0
            n = 50
            for i in range(n):
                rows.append({
                    _COL_LAP: lap_num,
                    _COL_TIME: round(t, 3),
                    _COL_SPEED: 30.0,
                    _COL_DIST: 1000.0 * i / (n - 1),
                })
                t += dur / n
        df = pd.DataFrame(rows)
        result = identify_anomalous_laps(df, time_band_low=0.85, time_band_high=1.15)
        assert 11 in result["time_flagged"], f"Lap 11 should be time-flagged: {result}"

    _test("anomalous_slow_time", t_anomalous_slow_time)

    # Test 23  --  anomalous_laps: normal laps not flagged

    def t_anomalous_normal_ok() -> None:
        rows = []
        t = 0.0
        for lap_num in range(1, 8):
            dur = 90.0 + (lap_num % 3)  # 90-92s range
            n = 50
            for i in range(n):
                rows.append({
                    _COL_LAP: lap_num,
                    _COL_TIME: round(t, 3),
                    _COL_SPEED: 30.0,
                    _COL_DIST: 1000.0 * i / (n - 1),
                })
                t += dur / n
        df = pd.DataFrame(rows)
        result = identify_anomalous_laps(df)
        assert len(result["flagged_laps"]) == 0, (
            f"No laps should be flagged: {result['flagged_laps']}"
        )

    _test("anomalous_normal_ok", t_anomalous_normal_ok)

    # Test 24  --  line deviation: deviated lap detected

    def t_line_deviation() -> None:
        # Reference line: straight line along latitude 51.0, lon 0.0 to 0.01
        # Use 500 points so spacing (~1.4m) is well below the 5m threshold.
        n_ref = 500
        ref = pd.DataFrame({
            "lat_ref_deg": [51.0] * n_ref,
            "lon_ref_deg": np.linspace(0.0, 0.01, n_ref),
            "distance_m": np.linspace(0, 800, n_ref),
        })
        # Good lap: follows ref line closely (offset ~1.1 m in latitude)
        good_df = pd.DataFrame({
            "Latitude (deg)": [51.00001] * 30,
            "Longitude (deg)": np.linspace(0.0, 0.01, 30),
        })
        # Bad lap: deviates 0.001 deg in lat (~111 m)
        bad_df = pd.DataFrame({
            "Latitude (deg)": [51.001] * 30,
            "Longitude (deg)": np.linspace(0.0, 0.01, 30),
        })
        laps = {1: good_df, 2: bad_df}
        result = identify_line_deviations(laps, ref, deviation_threshold_m=5.0)
        assert 2 in result["deviated_laps"], f"Lap 2 should deviate: {result}"
        assert 1 not in result["deviated_laps"], f"Lap 1 should NOT deviate: {result}"

    _test("line_deviation", t_line_deviation)

    # Summary

    total = len(passed) + len(failed)
    print(f"\nSession Trimming Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"   --  {name}")
    for name, tb in failed:
        print(f"  x{name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()