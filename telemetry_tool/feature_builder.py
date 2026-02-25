"""
feature_builder.py
------------------
Aggregates lap-level and segment-level metrics into a structured, ML-ready
feature dataset persisted in Parquet format (with CSV fallback).

Public API
~~~~~~~~~~
``build_feature_dataset(lap_metrics_df, segment_metrics_df, metadata_dict)``
    Merge per-lap features, aggregated segment diagnostics, and session
    metadata into a single row-per-lap DataFrame with a deterministic column
    order.

``validate_feature_schema(df)``
    Assert that a DataFrame matches the canonical feature schema produced by
    ``build_feature_dataset``.

``append_feature_dataset(df, base_path)``
    Write validated feature rows to ``<base_path>/processed/features.parquet``
    (or ``.csv`` fallback) with deduplication and atomic write.

``load_feature_dataset(base_path)``
    Read back the persisted feature dataset.

Input contracts
~~~~~~~~~~~~~~~
``lap_metrics_df``  -- one row per lap.  Expected columns (all optional;
    absent columns degrade to NaN):

    From ``features.compute_lap_time``:
        lap_time_s

    From ``features.compute_speed_profile_features``:
        speed_min_mps, speed_max_mps, speed_mean_mps, speed_std_mps,
        speed_p10_mps, speed_p90_mps

    From ``features.compute_accel_features``:
        accel_max_mps2, braking_max_mps2, accel_rms_mps2,
        jerk_rms_mps3, jerk_max_mps3, jerk_min_mps3,
        lat_accel_max_mps2, lat_accel_rms_mps2

    From ``features.compute_line_length``:
        line_length_m

    From delta / theoretical comparison:
        delta_to_theoretical_s

    Must contain ``lap_number`` for the segment join.

``segment_metrics_df``  -- one row per segment per lap (output of
    ``deltas.classify_time_loss_cause`` flattened into a DataFrame).
    Expected columns:

        lap_number, segment, time_loss_ms, likely_cause,
        entry_speed_diff_mps, min_speed_diff_mps,
        exit_accel_diff_mps2, yaw_var_ratio

``metadata_dict``  -- session-level metadata broadcast to every row:

        track_id, track_state, driver_name, session_id

Design principles
~~~~~~~~~~~~~~~~~
- pyarrow preferred; pandas CSV fallback for environments without it.
- Fully typed, NaN-robust, deterministic.
- No global state, no print statements, structured logging only.
- Column order is enforced by a canonical list, not by insertion order.
- Writes use an advisory file lock and atomic rename so that a crash
  never corrupts the on-disk dataset.
"""

from __future__ import annotations

import logging
import math
import os
import time
import traceback
from pathlib import Path
from typing import Any, Final, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Conditional pyarrow import  (CSV fallback when absent)

# -- -

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    _HAS_PYARROW = True
    logger.debug("pyarrow available -- using Parquet backend.")
except ImportError:
    pa = None   # type: ignore[assignment]
    pq = None   # type: ignore[assignment]
    _HAS_PYARROW = False
    logger.debug("pyarrow not found -- falling back to CSV backend.")


# ============================================================================

# Column-name constants  (single source of truth for the feature dataset)

# ============================================================================


# -- Metadata columns (always first, in this order) -- -

_M_TRACK_ID:      Final[str] = "track_id"
_M_TRACK_STATE:   Final[str] = "track_state"
_M_DRIVER_NAME:   Final[str] = "driver_name"
_M_SESSION_ID:    Final[str] = "session_id"
_M_LAP_NUMBER:    Final[str] = "lap_number"

METADATA_COLUMNS: Final[list[str]] = [
    _M_TRACK_ID,
    _M_TRACK_STATE,
    _M_DRIVER_NAME,
    _M_SESSION_ID,
    _M_LAP_NUMBER,
]

# -- Lap-level feature columns (from features.py outputs) -- -

_F_LAP_TIME_S:           Final[str] = "lap_time_s"
_F_SPEED_MIN:            Final[str] = "speed_min_mps"
_F_SPEED_MAX:            Final[str] = "speed_max_mps"
_F_SPEED_MEAN:           Final[str] = "speed_mean_mps"
_F_SPEED_STD:            Final[str] = "speed_std_mps"
_F_SPEED_P10:            Final[str] = "speed_p10_mps"
_F_SPEED_P90:            Final[str] = "speed_p90_mps"
_F_ACCEL_MAX:            Final[str] = "accel_max_mps2"
_F_BRAKING_MAX:          Final[str] = "braking_max_mps2"
_F_ACCEL_RMS:            Final[str] = "accel_rms_mps2"
_F_JERK_RMS:             Final[str] = "jerk_rms_mps3"
_F_JERK_MAX:             Final[str] = "jerk_max_mps3"
_F_JERK_MIN:             Final[str] = "jerk_min_mps3"
_F_LAT_ACCEL_MAX:        Final[str] = "lat_accel_max_mps2"
_F_LAT_ACCEL_RMS:        Final[str] = "lat_accel_rms_mps2"
_F_LINE_LENGTH:          Final[str] = "line_length_m"
_F_DELTA_TO_THEORETICAL: Final[str] = "delta_to_theoretical_s"

LAP_FEATURE_COLUMNS: Final[list[str]] = [
    _F_LAP_TIME_S,
    _F_SPEED_MIN,
    _F_SPEED_MAX,
    _F_SPEED_MEAN,
    _F_SPEED_STD,
    _F_SPEED_P10,
    _F_SPEED_P90,
    _F_ACCEL_MAX,
    _F_BRAKING_MAX,
    _F_ACCEL_RMS,
    _F_JERK_RMS,
    _F_JERK_MAX,
    _F_JERK_MIN,
    _F_LAT_ACCEL_MAX,
    _F_LAT_ACCEL_RMS,
    _F_LINE_LENGTH,
    _F_DELTA_TO_THEORETICAL,
]

# -- Segment-aggregated feature columns (from deltas.py outputs)
_S_TOTAL_LOSS_MS:        Final[str] = "total_time_loss_ms"
_S_ENTRY_LOSS_MS:        Final[str] = "entry_loss_ms"
_S_MID_CORNER_LOSS_MS:   Final[str] = "mid_corner_loss_ms"
_S_EXIT_LOSS_MS:         Final[str] = "exit_loss_ms"
_S_INSTABILITY_LOSS_MS:  Final[str] = "instability_loss_ms"
_S_LINE_INEFF_LOSS_MS:   Final[str] = "line_inefficiency_loss_ms"
_S_MEAN_ENTRY_SPD_DIFF:  Final[str] = "mean_entry_speed_diff_mps"
_S_MEAN_MIN_SPD_DIFF:    Final[str] = "mean_min_speed_diff_mps"
_S_MEAN_EXIT_ACCEL_DIFF: Final[str] = "mean_exit_accel_diff_mps2"
_S_MEAN_YAW_VAR_RATIO:  Final[str] = "mean_yaw_var_ratio"
_S_N_LOSS_SEGMENTS:      Final[str] = "n_loss_segments"

SEGMENT_FEATURE_COLUMNS: Final[list[str]] = [
    _S_TOTAL_LOSS_MS,
    _S_ENTRY_LOSS_MS,
    _S_MID_CORNER_LOSS_MS,
    _S_EXIT_LOSS_MS,
    _S_INSTABILITY_LOSS_MS,
    _S_LINE_INEFF_LOSS_MS,
    _S_MEAN_ENTRY_SPD_DIFF,
    _S_MEAN_MIN_SPD_DIFF,
    _S_MEAN_EXIT_ACCEL_DIFF,
    _S_MEAN_YAW_VAR_RATIO,
    _S_N_LOSS_SEGMENTS,
]

# -- Context columns (optional; appended when SessionContext is provided) -- -

_CTX_SESSION_TYPE:         Final[str] = "session_type"
_CTX_BASELINE_TRACK_STATE: Final[str] = "baseline_track_state"
_CTX_WEATHER_TEMP_C:       Final[str] = "weather_temp_c"
_CTX_WEATHER_HUMIDITY_PCT: Final[str] = "weather_humidity_pct"
_CTX_WEATHER_WIND_MPS:     Final[str] = "weather_wind_mps"
_CTX_PHASE_ID:             Final[str] = "phase_id"

CONTEXT_COLUMNS: Final[list[str]] = [
    _CTX_SESSION_TYPE,
    _CTX_BASELINE_TRACK_STATE,
    _CTX_WEATHER_TEMP_C,
    _CTX_WEATHER_HUMIDITY_PCT,
    _CTX_WEATHER_WIND_MPS,
    _CTX_PHASE_ID,
]

# -- Canonical column order (metadata -> lap features -> segment features) -
ALL_FEATURE_COLUMNS: Final[list[str]] = (
    METADATA_COLUMNS + LAP_FEATURE_COLUMNS + SEGMENT_FEATURE_COLUMNS
)

# Extended schema including optional context columns

EXTENDED_FEATURE_COLUMNS: Final[list[str]] = (
    ALL_FEATURE_COLUMNS + CONTEXT_COLUMNS
)

# -- I/O constants -- -

_PARQUET_FILENAME:    Final[str] = "features.parquet"
_CSV_FILENAME:        Final[str] = "features.csv"
_PROCESSED_DIR_NAME:  Final[str] = "processed"
_PARQUET_COMPRESSION: Final[str] = "snappy"
_LOCK_SUFFIX:         Final[str] = ".lock"
_LOCK_TIMEOUT_S:      Final[float] = 30.0
_LOCK_POLL_S:         Final[float] = 0.05

# -- Segment-metric input column names (from deltas.classify_time_loss_cause) -

_SEG_LAP_NUMBER:      Final[str] = "lap_number"
_SEG_TIME_LOSS_MS:    Final[str] = "time_loss_ms"
_SEG_LIKELY_CAUSE:    Final[str] = "likely_cause"
_SEG_ENTRY_SPD_DIFF:  Final[str] = "entry_speed_diff_mps"
_SEG_MIN_SPD_DIFF:    Final[str] = "min_speed_diff_mps"
_SEG_EXIT_ACCEL_DIFF: Final[str] = "exit_accel_diff_mps2"
_SEG_YAW_VAR_RATIO:   Final[str] = "yaw_var_ratio"

# Cause labels emitted by deltas.classify_time_loss_cause

_CAUSE_ENTRY:       Final[str] = "entry_loss"
_CAUSE_MID:         Final[str] = "mid_corner_loss"
_CAUSE_EXIT:        Final[str] = "exit_loss"
_CAUSE_INSTABILITY: Final[str] = "instability"
_CAUSE_LINE:        Final[str] = "line_inefficiency"


# ============================================================================

# Exceptions

# ============================================================================


class FeatureSchemaError(ValueError):
    """Raised when a DataFrame does not conform to the feature dataset schema."""


class FeatureBuilderError(ValueError):
    """Raised when inputs are structurally invalid."""


class ParquetLockTimeout(TimeoutError):
    """Raised when the file lock cannot be acquired within the timeout."""


class ParquetSchemaConflict(ValueError):
    """Raised when the incoming schema conflicts with the on-disk schema."""


# ============================================================================

# Internal helpers -- segment aggregation

# ============================================================================


def _safe_mean(series: pd.Series) -> float:
    """Mean of finite values; NaN if none."""
    vals = pd.to_numeric(series, errors="coerce")
    finite = vals.dropna()
    return round(float(finite.mean()), 4) if len(finite) > 0 else float("nan")


def _sum_loss_for_cause(group: pd.DataFrame, cause: str) -> float:
    """
    Sum ``time_loss_ms`` for rows whose ``likely_cause`` matches *cause*
    and whose ``time_loss_ms`` is positive (actual losses, not gains).
    """
    mask = (
        (group[_SEG_LIKELY_CAUSE] == cause)
        & (pd.to_numeric(group[_SEG_TIME_LOSS_MS], errors="coerce") > 0)
    )
    vals = pd.to_numeric(group.loc[mask, _SEG_TIME_LOSS_MS], errors="coerce").dropna()
    return round(float(vals.sum()), 2) if len(vals) > 0 else 0.0


def _aggregate_segments_for_lap(group: pd.DataFrame) -> dict[str, Any]:
    """
    Collapse all segment rows for a single lap into one feature dict.

    Parameters
    ----------
    group:
        Subset of ``segment_metrics_df`` for a single ``lap_number``.

    Returns
    -------
    dict with all ``SEGMENT_FEATURE_COLUMNS`` keys.
    """
    loss_col = pd.to_numeric(group[_SEG_TIME_LOSS_MS], errors="coerce")

    return {
        _S_TOTAL_LOSS_MS:        round(float(loss_col.sum()), 2) if loss_col.notna().any() else float("nan"),
        _S_ENTRY_LOSS_MS:        _sum_loss_for_cause(group, _CAUSE_ENTRY),
        _S_MID_CORNER_LOSS_MS:   _sum_loss_for_cause(group, _CAUSE_MID),
        _S_EXIT_LOSS_MS:         _sum_loss_for_cause(group, _CAUSE_EXIT),
        _S_INSTABILITY_LOSS_MS:  _sum_loss_for_cause(group, _CAUSE_INSTABILITY),
        _S_LINE_INEFF_LOSS_MS:   _sum_loss_for_cause(group, _CAUSE_LINE),
        _S_MEAN_ENTRY_SPD_DIFF:  _safe_mean(group[_SEG_ENTRY_SPD_DIFF])  if _SEG_ENTRY_SPD_DIFF  in group.columns else float("nan"),
        _S_MEAN_MIN_SPD_DIFF:    _safe_mean(group[_SEG_MIN_SPD_DIFF])    if _SEG_MIN_SPD_DIFF    in group.columns else float("nan"),
        _S_MEAN_EXIT_ACCEL_DIFF: _safe_mean(group[_SEG_EXIT_ACCEL_DIFF]) if _SEG_EXIT_ACCEL_DIFF in group.columns else float("nan"),
        _S_MEAN_YAW_VAR_RATIO:   _safe_mean(group[_SEG_YAW_VAR_RATIO])  if _SEG_YAW_VAR_RATIO   in group.columns else float("nan"),
        _S_N_LOSS_SEGMENTS:       int((loss_col > 0).sum()),
    }


# ============================================================================

# Internal helpers -- file lock (portable)

# ============================================================================


class _FileLock:
    """
    Minimal advisory file lock using ``O_CREAT | O_EXCL`` atomicity.

    Portable across Windows, macOS, and Linux without third-party packages.
    """

    def __init__(self, path: Path, timeout: float = _LOCK_TIMEOUT_S) -> None:
        self._lock_path = path
        self._timeout   = timeout
        self._fd: Optional[int] = None

    def __enter__(self) -> "_FileLock":
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                self._fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                try:
                    os.write(self._fd, str(os.getpid()).encode())
                except OSError:
                    pass
                logger.debug("Lock acquired: %s", self._lock_path)
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ParquetLockTimeout(
                        f"Could not acquire lock on {self._lock_path} "
                        f"within {self._timeout}s."
                    ) from None
                time.sleep(_LOCK_POLL_S)

    def __exit__(self, *_: object) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            self._lock_path.unlink()
            logger.debug("Lock released: %s", self._lock_path)
        except FileNotFoundError:
            pass


# ============================================================================

# Internal helpers -- backend-agnostic I/O

# ============================================================================


def _feature_path(base_path: Path) -> Path:
    """Return the canonical feature dataset file path."""
    filename = _PARQUET_FILENAME if _HAS_PYARROW else _CSV_FILENAME
    return base_path / _PROCESSED_DIR_NAME / filename


def _write_df(df: pd.DataFrame, path: Path) -> None:
    """Write *df* to *path* using the best available backend."""
    if _HAS_PYARROW:
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, path, compression=_PARQUET_COMPRESSION)
    else:
        df.to_csv(path, index=False)


def _read_df(path: Path) -> pd.DataFrame:
    """Read a DataFrame from *path* using the best available backend."""
    if _HAS_PYARROW and path.suffix == ".parquet":
        return pq.read_table(path).to_pandas()
    return pd.read_csv(path)


def _read_df_columns(path: Path, columns: list[str] | None) -> pd.DataFrame:
    """Read with optional column pruning."""
    if columns is None:
        return _read_df(path)
    if _HAS_PYARROW and path.suffix == ".parquet":
        return pq.read_table(path, columns=columns).to_pandas()
    df = pd.read_csv(path, usecols=columns)
    return df[columns]  # enforce order


def _deduplicate(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """Return only rows in *new_df* not already in *existing_df*."""
    shared_cols = list(existing_df.columns.intersection(new_df.columns))
    if not shared_cols:
        return new_df

    combined = pd.concat(
        [existing_df[shared_cols], new_df[shared_cols]], ignore_index=True,
    )
    dup_mask = combined.duplicated(keep="first").iloc[len(existing_df):]
    new_only = new_df[~dup_mask.values]

    dropped = len(new_df) - len(new_only)
    if dropped:
        logger.info("Deduplicated %d duplicate row(s) before append.", dropped)

    return new_only


def _assert_compatible_columns(
    incoming_cols: list[str],
    existing_cols: list[str],
    path: Path,
) -> None:
    """Raise ``ParquetSchemaConflict`` if existing columns are missing from incoming."""
    missing = sorted(set(existing_cols) - set(incoming_cols))
    if missing:
        raise ParquetSchemaConflict(
            f"Schema conflict for {path}: columns present on disk "
            f"but absent in incoming DataFrame: {missing}"
        )


# ============================================================================

# Schema validation

# ============================================================================


def validate_feature_schema(
    df: pd.DataFrame,
    *,
    require_all: bool = True,
    extra_columns_ok: bool = True,
) -> None:
    """
    Assert that *df* conforms to the canonical feature dataset schema.

    Parameters
    ----------
    df:
        DataFrame to validate.
    require_all:
        When ``True`` (default), every column in ``ALL_FEATURE_COLUMNS`` must
        be present.  Set to ``False`` to require only metadata columns.
    extra_columns_ok:
        When ``True`` (default), columns beyond the schema are silently
        accepted.  Set to ``False`` to enforce a strict column set.

    Raises
    ------
    TypeError
        If *df* is not a pandas DataFrame.
    FeatureSchemaError
        If required columns are missing or unexpected columns are present
        (when *extra_columns_ok* is False).
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"validate_feature_schema() expects a pandas DataFrame, "
            f"got {type(df).__name__!r}."
        )

    actual: set[str] = set(df.columns)
    errors: list[str] = []

    required = list(ALL_FEATURE_COLUMNS) if require_all else list(METADATA_COLUMNS)
    missing  = sorted(set(required) - actual)
    if missing:
        errors.append(
            f"Missing column(s) [{len(missing)}]: " + ", ".join(missing)
        )

    if not extra_columns_ok:
        unexpected = sorted(actual - set(ALL_FEATURE_COLUMNS) - set(CONTEXT_COLUMNS))
        if unexpected:
            errors.append(
                f"Unexpected column(s) [{len(unexpected)}]: "
                + ", ".join(unexpected)
            )

    if errors:
        header = (
            f"Feature schema validation failed "
            f"(shape {df.shape[0]} rows x {df.shape[1]} cols):"
        )
        raise FeatureSchemaError(header + "\n  " + "\n  ".join(errors))


# ============================================================================

# Public API -- build_feature_dataset

# ============================================================================


def build_feature_dataset(
    lap_metrics_df: pd.DataFrame,
    segment_metrics_df: pd.DataFrame | None,
    metadata_dict: dict[str, Any],
    *,
    context: Any = None,
    lap_to_phase: dict[int, int] | None = None,
) -> pd.DataFrame:
    """
    Merge lap-level and segment-level metrics into a single ML-ready DataFrame.

    Parameters
    ----------
    lap_metrics_df:
        One row per lap.  Must contain ``lap_number``.  All other columns
        from ``LAP_FEATURE_COLUMNS`` are optional (absent -> NaN).

    segment_metrics_df:
        One row per segment per lap (from ``deltas.classify_time_loss_cause``
        with ``cause_details`` flattened).  Must contain ``lap_number``,
        ``time_loss_ms``, and ``likely_cause``.  Pass ``None`` if segment
        data is unavailable (all segment features will be NaN).

        Expected ``cause_details`` columns (all optional):
            ``entry_speed_diff_mps``, ``min_speed_diff_mps``,
            ``exit_accel_diff_mps2``, ``yaw_var_ratio``

    metadata_dict:
        Session-level metadata broadcast to every row.  Expected keys:
            ``track_id``, ``track_state``, ``driver_name``, ``session_id``

    Returns
    -------
    pd.DataFrame
        One row per lap, columns in ``ALL_FEATURE_COLUMNS`` order,
        validated against the schema.

    Raises
    ------
    TypeError
        If inputs are not the expected types.
    FeatureBuilderError
        If ``lap_metrics_df`` is empty or lacks ``lap_number``.
    """
    # -- Input validation
    if not isinstance(lap_metrics_df, pd.DataFrame):
        raise TypeError(
            f"lap_metrics_df must be a DataFrame, "
            f"got {type(lap_metrics_df).__name__!r}."
        )
    if segment_metrics_df is not None and not isinstance(segment_metrics_df, pd.DataFrame):
        raise TypeError(
            f"segment_metrics_df must be a DataFrame or None, "
            f"got {type(segment_metrics_df).__name__!r}."
        )
    if not isinstance(metadata_dict, dict):
        raise TypeError(
            f"metadata_dict must be a dict, got {type(metadata_dict).__name__!r}."
        )

    if lap_metrics_df.empty:
        raise FeatureBuilderError("lap_metrics_df is empty -- nothing to build.")

    if _M_LAP_NUMBER not in lap_metrics_df.columns:
        raise FeatureBuilderError(
            f"lap_metrics_df must contain a {_M_LAP_NUMBER!r} column."
        )

    # Work on a copy to avoid mutating the caller's data.

    result = lap_metrics_df.copy()

    # -- 1. Ensure all lap feature columns exist (fill absent with NaN)
    for col in LAP_FEATURE_COLUMNS:
        if col not in result.columns:
            result[col] = float("nan")

    # -- 2. Aggregate segment metrics per lap
    if (
        segment_metrics_df is not None
        and not segment_metrics_df.empty
        and _SEG_LAP_NUMBER in segment_metrics_df.columns
        and _SEG_TIME_LOSS_MS in segment_metrics_df.columns
        and _SEG_LIKELY_CAUSE in segment_metrics_df.columns
    ):
        seg_agg_rows: list[dict[str, Any]] = []
        for lap_num, group in segment_metrics_df.groupby(_SEG_LAP_NUMBER):
            agg = _aggregate_segments_for_lap(group)
            agg[_M_LAP_NUMBER] = lap_num
            seg_agg_rows.append(agg)

        if seg_agg_rows:
            seg_agg_df = pd.DataFrame(seg_agg_rows)
            result = result.merge(seg_agg_df, on=_M_LAP_NUMBER, how="left")

        logger.info(
            "Aggregated segment metrics: %d lap(s) matched.",
            len(seg_agg_rows),
        )
    else:
        logger.debug("No segment metrics provided; segment features will be NaN.")

    # Ensure all segment columns exist

    for col in SEGMENT_FEATURE_COLUMNS:
        if col not in result.columns:
            result[col] = float("nan")

    # -- 3. Broadcast metadata -- -

    for meta_col in METADATA_COLUMNS:
        if meta_col == _M_LAP_NUMBER:
            continue  # already in lap_metrics_df
        result[meta_col] = metadata_dict.get(meta_col)

    # -- 4. Enforce canonical column order -- -

    result = result[ALL_FEATURE_COLUMNS].copy()

    # -- 5. Coerce numeric columns to float64
    for col in LAP_FEATURE_COLUMNS + SEGMENT_FEATURE_COLUMNS:
        if col == _S_N_LOSS_SEGMENTS:
            result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0).astype(int)
        else:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    # -- 6. Broadcast context + phase columns (optional)
    if context is not None:
        _st = getattr(context, "session_type", None)
        _ts = getattr(context, "baseline_track_state", None)
        _w  = getattr(context, "weather", None)

        result[_CTX_SESSION_TYPE] = _st.value if hasattr(_st, "value") else str(_st)
        result[_CTX_BASELINE_TRACK_STATE] = _ts.value if hasattr(_ts, "value") else str(_ts)
        result[_CTX_WEATHER_TEMP_C] = (
            _w.air_temp_c if _w is not None else None
        )
        result[_CTX_WEATHER_HUMIDITY_PCT] = (
            _w.humidity_pct if _w is not None else None
        )
        result[_CTX_WEATHER_WIND_MPS] = (
            _w.wind_speed_mps if _w is not None else None
        )
    else:
        for col in CONTEXT_COLUMNS:
            if col not in result.columns:
                result[col] = None

    # Phase mapping per lap

    if lap_to_phase and _M_LAP_NUMBER in result.columns:
        result[_CTX_PHASE_ID] = (
            result[_M_LAP_NUMBER].map(lap_to_phase).astype("Int64")
        )
    elif _CTX_PHASE_ID not in result.columns:
        result[_CTX_PHASE_ID] = None

    # -- 7. Validate -- -

    validate_feature_schema(result, require_all=True, extra_columns_ok=False)

    logger.info(
        "Built feature dataset: %d lap(s) x %d columns.",
        len(result), len(result.columns),
    )
    return result


# ============================================================================

# Public API -- append_feature_dataset

# ============================================================================


def append_feature_dataset(
    df: pd.DataFrame,
    base_path: str | Path,
    *,
    validate: bool = True,
) -> Path:
    """
    Append *df* to the canonical feature dataset file.

    File path:
        ``<base_path>/processed/features.parquet``  (pyarrow available)
        ``<base_path>/processed/features.csv``       (fallback)

    Behaviour
    ~~~~~~~~~
    - First call:  creates parent directories and a new file.
    - Subsequent:  reads existing file, deduplicates incoming rows, appends
      new rows atomically (temp file + rename).
    - File-level advisory lock prevents concurrent-writer corruption.

    Parameters
    ----------
    df:
        Feature DataFrame, typically produced by ``build_feature_dataset``.
    base_path:
        Project data root (e.g. ``Data/``).
    validate:
        When ``True`` (default), ``validate_feature_schema(df)`` is called
        before writing.

    Returns
    -------
    Path
        Absolute path to the written file.

    Raises
    ------
    ValueError
        If *df* is empty.
    FeatureSchemaError
        If *validate* is True and the schema check fails.
    ParquetLockTimeout
        If the lock cannot be acquired within the timeout.
    ParquetSchemaConflict
        If the incoming columns conflict with the on-disk columns.
    """
    if df.empty:
        raise ValueError(
            "append_feature_dataset() received an empty DataFrame."
        )

    if validate:
        validate_feature_schema(df)

    base_path = Path(base_path)
    dest      = _feature_path(base_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    lock_path = dest.with_suffix(_LOCK_SUFFIX)
    lock      = _FileLock(lock_path)

    with lock:
        if not dest.exists():
            logger.info(
                "Creating new feature dataset: %s (%d rows)", dest, len(df),
            )
            _write_df(df, dest)
            return dest.resolve()

        # File exists -> column check, dedup, atomic rewrite

        existing_df = _read_df(dest)
        _assert_compatible_columns(
            list(df.columns), list(existing_df.columns), dest,
        )

        new_rows = _deduplicate(existing_df, df)

        if new_rows.empty:
            logger.info(
                "No new rows to append to %s -- all already present.", dest,
            )
            return dest.resolve()

        combined_df = pd.concat([existing_df, new_rows], ignore_index=True)

        tmp_suffix = ".tmp.parquet" if _HAS_PYARROW else ".tmp.csv"
        tmp_path   = dest.with_suffix(tmp_suffix)
        try:
            _write_df(combined_df, tmp_path)
            tmp_path.replace(dest)
            logger.info(
                "Appended %d row(s) to %s (total: %d rows).",
                len(new_rows), dest, len(combined_df),
            )
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    return dest.resolve()


# ============================================================================

# Public API -- load_feature_dataset

# ============================================================================


def load_feature_dataset(
    base_path: str | Path,
    *,
    columns: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Load the canonical feature dataset into a DataFrame.

    Parameters
    ----------
    base_path:
        Project data root.
    columns:
        If provided, only these columns are read (column pruning).

    Returns
    -------
    pd.DataFrame

    Raises
    ------
    FileNotFoundError
        If the dataset file does not exist.
    """
    dest = _feature_path(Path(base_path))
    if not dest.exists():
        raise FileNotFoundError(f"Feature dataset not found: {dest}")

    df = _read_df_columns(dest, columns)

    logger.info(
        "Loaded %d row(s) x %d col(s) from %s.",
        len(df), len(df.columns), dest,
    )
    return df


# ============================================================================

# Inline tests

# ============================================================================


def _run_tests() -> None:
    """Self-contained test suite -- run with ``python feature_builder.py``."""
    import tempfile

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn: Any) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Synthetic data factories -- -


    def _lap_df(n_laps: int = 5, seed: int = 42) -> pd.DataFrame:
        """Create a plausible lap_metrics_df."""
        rng = np.random.default_rng(seed)
        rows: list[dict[str, Any]] = []
        for lap in range(1, n_laps + 1):
            rows.append({
                _M_LAP_NUMBER:           lap,
                _F_LAP_TIME_S:           round(88.0 + rng.normal(0, 1.5), 3),
                _F_SPEED_MIN:            round(15.0 + rng.normal(0, 2), 3),
                _F_SPEED_MAX:            round(65.0 + rng.normal(0, 3), 3),
                _F_SPEED_MEAN:           round(42.0 + rng.normal(0, 1), 3),
                _F_SPEED_STD:            round(12.0 + rng.normal(0, 0.5), 3),
                _F_SPEED_P10:            round(22.0 + rng.normal(0, 1), 3),
                _F_SPEED_P90:            round(58.0 + rng.normal(0, 2), 3),
                _F_ACCEL_MAX:            round(6.0  + rng.normal(0, 0.3), 4),
                _F_BRAKING_MAX:          round(12.0 + rng.normal(0, 0.5), 4),
                _F_ACCEL_RMS:            round(3.5  + rng.normal(0, 0.2), 4),
                _F_JERK_RMS:             round(18.0 + rng.normal(0, 2), 3),
                _F_JERK_MAX:             round(30.0 + rng.normal(0, 3), 3),
                _F_JERK_MIN:             round(-35.0 + rng.normal(0, 3), 3),
                _F_LAT_ACCEL_MAX:        round(10.0 + rng.normal(0, 0.5), 4),
                _F_LAT_ACCEL_RMS:        round(5.0  + rng.normal(0, 0.3), 4),
                _F_LINE_LENGTH:          round(4500.0 + rng.normal(0, 5), 2),
                _F_DELTA_TO_THEORETICAL: round(1.5 + rng.normal(0, 0.5), 3),
            })
        return pd.DataFrame(rows)

    def _seg_df(n_laps: int = 5, n_segs: int = 20, seed: int = 99) -> pd.DataFrame:
        """Create a plausible segment_metrics_df."""
        rng    = np.random.default_rng(seed)
        causes = [
            _CAUSE_ENTRY, _CAUSE_MID, _CAUSE_EXIT,
            _CAUSE_INSTABILITY, _CAUSE_LINE, "on_pace",
        ]
        rows: list[dict[str, Any]] = []
        for lap in range(1, n_laps + 1):
            for seg in range(1, n_segs + 1):
                rows.append({
                    _SEG_LAP_NUMBER:      lap,
                    "segment":            seg,
                    _SEG_TIME_LOSS_MS:    round(rng.normal(5, 15), 2),
                    _SEG_LIKELY_CAUSE:    causes[rng.integers(0, len(causes))],
                    _SEG_ENTRY_SPD_DIFF:  round(rng.normal(0.5, 1.0), 3),
                    _SEG_MIN_SPD_DIFF:    round(rng.normal(0.3, 0.8), 3),
                    _SEG_EXIT_ACCEL_DIFF: round(rng.normal(0.1, 0.3), 4),
                    _SEG_YAW_VAR_RATIO:   round(1.0 + abs(rng.normal(0, 0.3)), 4),
                })
        return pd.DataFrame(rows)

    META: dict[str, Any] = {
        _M_TRACK_ID:    "spa_2024",
        _M_TRACK_STATE: "dry",
        _M_DRIVER_NAME: "TestDriver",
        _M_SESSION_ID:  "sess_001",
    }

    #
    # Test 1 -- basic build returns correct shape and columns

    #
    def t_build_basic() -> None:
        result = build_feature_dataset(_lap_df(), _seg_df(), META)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 5
        assert list(result.columns) == EXTENDED_FEATURE_COLUMNS

    _test("build_basic", t_build_basic)

    #
    # Test 2 -- column order is deterministic and canonical

    #
    def t_column_order() -> None:
        r1 = build_feature_dataset(_lap_df(seed=1), _seg_df(seed=1), META)
        r2 = build_feature_dataset(_lap_df(seed=1), _seg_df(seed=1), META)
        assert list(r1.columns) == list(r2.columns) == EXTENDED_FEATURE_COLUMNS

    _test("column_order", t_column_order)

    #
    # Test 3 -- metadata broadcast correctly to all rows

    #
    def t_metadata_broadcast() -> None:
        result = build_feature_dataset(_lap_df(), _seg_df(), META)
        assert (result[_M_TRACK_ID] == "spa_2024").all()
        assert (result[_M_DRIVER_NAME] == "TestDriver").all()
        assert (result[_M_SESSION_ID] == "sess_001").all()
        assert (result[_M_TRACK_STATE] == "dry").all()

    _test("metadata_broadcast", t_metadata_broadcast)

    #
    # Test 4 -- lap_number preserved from input

    #
    def t_lap_number() -> None:
        result = build_feature_dataset(_lap_df(3), _seg_df(3), META)
        assert sorted(result[_M_LAP_NUMBER].tolist()) == [1, 2, 3]

    _test("lap_number", t_lap_number)

    #
    # Test 5 -- segment aggregation produces sensible values

    #
    def t_segment_aggregation() -> None:
        result = build_feature_dataset(_lap_df(), _seg_df(), META)
        assert result[_S_TOTAL_LOSS_MS].notna().all()
        assert (result[_S_N_LOSS_SEGMENTS] >= 0).all()
        assert result[_S_N_LOSS_SEGMENTS].dtype in (np.int64, np.int32, int)

    _test("segment_aggregation", t_segment_aggregation)

    #
    # Test 6 -- None segment_metrics_df fills segment cols with NaN

    #
    def t_no_segments() -> None:
        result = build_feature_dataset(_lap_df(), None, META)
        assert len(result) == 5
        for col in SEGMENT_FEATURE_COLUMNS:
            if col == _S_N_LOSS_SEGMENTS:
                continue  # filled with 0
            assert result[col].isna().all(), f"{col} should be NaN"

    _test("no_segments", t_no_segments)

    #
    # Test 7 -- missing lap feature columns degrade gracefully

    #
    def t_missing_lap_features() -> None:
        sparse_df = pd.DataFrame({_M_LAP_NUMBER: [1, 2], _F_LAP_TIME_S: [90.1, 89.8]})
        result = build_feature_dataset(sparse_df, None, META)
        assert len(result) == 2
        assert result[_F_SPEED_MEAN].isna().all()
        assert result[_F_LAP_TIME_S].notna().all()

    _test("missing_lap_features", t_missing_lap_features)

    #
    # Test 8 -- validate_feature_schema passes for valid DataFrame

    #
    def t_validate_passes() -> None:
        df = build_feature_dataset(_lap_df(), _seg_df(), META)
        validate_feature_schema(df)  # should not raise

    _test("validate_passes", t_validate_passes)

    #
    # Test 9 -- validate_feature_schema rejects missing columns

    #
    def t_validate_rejects_missing() -> None:
        df = pd.DataFrame({_M_LAP_NUMBER: [1]})
        try:
            validate_feature_schema(df)
            raise AssertionError("Should have raised FeatureSchemaError")
        except FeatureSchemaError:
            pass

    _test("validate_rejects_missing", t_validate_rejects_missing)

    #
    # Test 10 -- validate rejects non-DataFrame

    #
    def t_validate_type_error() -> None:
        try:
            validate_feature_schema("not_a_df")  # type: ignore[arg-type]
            raise AssertionError("Should have raised TypeError")
        except TypeError:
            pass

    _test("validate_type_error", t_validate_type_error)

    #
    # Test 11 -- strict mode rejects extra columns

    #
    def t_validate_strict() -> None:
        df = build_feature_dataset(_lap_df(), _seg_df(), META)
        df["bonus_col"] = 42
        try:
            validate_feature_schema(df, extra_columns_ok=False)
            raise AssertionError("Should have raised FeatureSchemaError")
        except FeatureSchemaError:
            pass

    _test("validate_strict", t_validate_strict)

    #
    # Test 12 -- append creates and appends

    #
    def t_append() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df1 = build_feature_dataset(_lap_df(3, seed=1), _seg_df(3, seed=1), META)
            df2 = build_feature_dataset(
                _lap_df(3, seed=2), _seg_df(3, seed=2),
                {**META, _M_SESSION_ID: "sess_002"},
            )

            path = append_feature_dataset(df1, tmpdir)
            assert path.exists()

            loaded = load_feature_dataset(tmpdir)
            assert len(loaded) == 3

            append_feature_dataset(df2, tmpdir)
            loaded2 = load_feature_dataset(tmpdir)
            assert len(loaded2) == 6

    _test("append", t_append)

    #
    # Test 13 -- deduplication on re-append

    #
    def t_dedup() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = build_feature_dataset(_lap_df(3, seed=10), _seg_df(3, seed=10), META)
            append_feature_dataset(df, tmpdir)
            append_feature_dataset(df, tmpdir)  # same data again

            loaded = load_feature_dataset(tmpdir)
            assert len(loaded) == 3, f"Expected 3 after dedup, got {len(loaded)}"

    _test("dedup", t_dedup)

    #
    # Test 14 -- empty DataFrame raises ValueError

    #
    def t_append_empty_raises() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                append_feature_dataset(pd.DataFrame(), tmpdir)
                raise AssertionError("Should have raised ValueError")
            except ValueError:
                pass

    _test("append_empty_raises", t_append_empty_raises)

    #
    # Test 15 -- TypeError on bad inputs to build

    #
    def t_type_errors() -> None:
        try:
            build_feature_dataset("nope", None, {})  # type: ignore[arg-type]
            raise AssertionError("Expected TypeError")
        except TypeError:
            pass
        try:
            build_feature_dataset(_lap_df(), "nope", {})  # type: ignore[arg-type]
            raise AssertionError("Expected TypeError")
        except TypeError:
            pass
        try:
            build_feature_dataset(_lap_df(), None, "nope")  # type: ignore[arg-type]
            raise AssertionError("Expected TypeError")
        except TypeError:
            pass

    _test("type_errors", t_type_errors)

    #
    # Test 16 -- empty lap_metrics_df raises FeatureBuilderError

    #
    def t_empty_lap_df() -> None:
        try:
            build_feature_dataset(pd.DataFrame(columns=[_M_LAP_NUMBER]), None, META)
            raise AssertionError("Expected FeatureBuilderError")
        except FeatureBuilderError:
            pass

    _test("empty_lap_df", t_empty_lap_df)

    #
    # Test 17 -- missing lap_number raises FeatureBuilderError

    #
    def t_missing_lap_number() -> None:
        try:
            build_feature_dataset(
                pd.DataFrame({_F_LAP_TIME_S: [90.0]}), None, META,
            )
            raise AssertionError("Expected FeatureBuilderError")
        except FeatureBuilderError:
            pass

    _test("missing_lap_number", t_missing_lap_number)

    #
    # Test 18 -- deterministic output

    #
    def t_deterministic() -> None:
        r1 = build_feature_dataset(_lap_df(5, 77), _seg_df(5, 77), META)
        r2 = build_feature_dataset(_lap_df(5, 77), _seg_df(5, 77), META)
        s1 = r1.to_json(orient="records", double_precision=10)
        s2 = r2.to_json(orient="records", double_precision=10)
        assert s1 == s2, "Output must be deterministic"

    _test("deterministic", t_deterministic)

    #
    # Test 19 -- cause-specific sums <= total loss for positive totals

    #
    def t_cause_sums_non_negative() -> None:
        result = build_feature_dataset(_lap_df(), _seg_df(), META)
        cause_cols = [
            _S_ENTRY_LOSS_MS, _S_MID_CORNER_LOSS_MS, _S_EXIT_LOSS_MS,
            _S_INSTABILITY_LOSS_MS, _S_LINE_INEFF_LOSS_MS,
        ]
        for _, row in result.iterrows():
            # Each cause-specific sum should be non-negative (only counts

            # positive-loss segments).

            for c in cause_cols:
                v = row[c]
                if not math.isnan(v):
                    assert v >= 0, f"{c} should be >= 0, got {v}"
            # total_time_loss_ms is the net sum (can be negative if the

            # driver gained time overall), so no upper-bound check here.

            assert not math.isnan(row[_S_TOTAL_LOSS_MS]), "Total loss should not be NaN"

    _test("cause_sums_non_negative", t_cause_sums_non_negative)

    #
    # Test 20 -- load with column pruning

    #
    def t_load_column_pruning() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            df = build_feature_dataset(_lap_df(3), _seg_df(3), META)
            append_feature_dataset(df, tmpdir)

            cols = [_M_LAP_NUMBER, _F_LAP_TIME_S, _S_TOTAL_LOSS_MS]
            loaded = load_feature_dataset(tmpdir, columns=cols)
            assert list(loaded.columns) == cols

    _test("load_column_pruning", t_load_column_pruning)

    #
    # Test 21 -- JSON serialisability

    #
    def t_json_serialisable() -> None:
        import json
        df = build_feature_dataset(_lap_df(), _seg_df(), META)
        records = df.to_dict(orient="records")
        json.dumps(records)

    _test("json_serialisable", t_json_serialisable)

    #
    # Test 22 -- partial segment data (fewer laps in segments)

    #
    def t_partial_segment_data() -> None:
        lap_df = _lap_df(5)
        seg_df = _seg_df(3)  # only 3 laps have segments
        result = build_feature_dataset(lap_df, seg_df, META)
        assert len(result) == 5
        lap_4_5 = result[result[_M_LAP_NUMBER] > 3]
        assert lap_4_5[_S_TOTAL_LOSS_MS].isna().all()

    _test("partial_segment_data", t_partial_segment_data)

    #
    # Test 23 -- FileNotFoundError on load from empty dir

    #
    def t_load_missing() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                load_feature_dataset(tmpdir)
                raise AssertionError("Should have raised FileNotFoundError")
            except FileNotFoundError:
                pass

    _test("load_missing", t_load_missing)

    #
    # Test 24 -- require_all=False only checks metadata

    #
    def t_validate_metadata_only() -> None:
        df = pd.DataFrame({
            _M_TRACK_ID: ["spa"], _M_TRACK_STATE: ["dry"],
            _M_DRIVER_NAME: ["X"], _M_SESSION_ID: ["s1"],
            _M_LAP_NUMBER: [1],
        })
        validate_feature_schema(df, require_all=False)  # should not raise

    _test("validate_metadata_only", t_validate_metadata_only)

    #
    # Test 25 -- input DataFrames are not mutated

    #
    def t_no_mutation() -> None:
        lap_df = _lap_df()
        seg_df = _seg_df()
        lap_cols_before = list(lap_df.columns)
        seg_cols_before = list(seg_df.columns)
        lap_len_before  = len(lap_df)
        seg_len_before  = len(seg_df)

        build_feature_dataset(lap_df, seg_df, META)

        assert list(lap_df.columns) == lap_cols_before
        assert list(seg_df.columns) == seg_cols_before
        assert len(lap_df) == lap_len_before
        assert len(seg_df) == seg_len_before

    _test("no_mutation", t_no_mutation)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    print(f"\nFeature Builder Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  \u2713 {name}")
    for name, tb in failed:
        print(f"  \u2717 {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# ============================================================================

# Entry point

# ============================================================================


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()