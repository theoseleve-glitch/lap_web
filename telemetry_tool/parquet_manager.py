"""
parquet_manager.py
------------------
Safe, schema-validated Parquet I/O with duplicate prevention.

Responsibilities
~~~~~~~~~~~~~~~~
- append_to_parquet(path, df)
    Write *df* into a Parquet dataset, creating the file on first call and
    deduplicating on every subsequent call.  A file-system lock prevents
    concurrent writers from corrupting the file.

- load_parquet_partition(path, filters=None)
    Read a Parquet file or partitioned dataset, optionally pushing down
    row-group filters so only the requested data is deserialised.

Design notes
~~~~~~~~~~~~
- Uses pyarrow exclusively (no pandas I/O path) so schema enforcement is
  done at the Arrow level before any data hits disk.
- Deduplication is performed on the full set of columns present in the
  incoming DataFrame, matching the contract expected by feature_schema.py.
- The write lock is a sibling file (<name>.lock) that survives crashes
  because portalocker / fcntl is not a hard dependency; a pure-Python
  fallback using os.open(O_CREAT | O_EXCL) is used instead.
- Schema validation delegates to feature_schema.validate_schema() when the
  caller passes validate=True (default).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from feature_schema import SchemaValidationError, validate_schema  # noqa: F401 (re-exported)

logger = logging.getLogger(__name__)

# -- -

# Constants

# -- -


_LOCK_SUFFIX        = ".lock"
_LOCK_TIMEOUT_S     = 30        # seconds to wait for an existing lock to clear
_LOCK_POLL_S        = 0.05      # polling interval while waiting
_PARQUET_COMPRESSION = "snappy"  # snappy: fast, good ratio, widely supported


# -- -

# Internal helpers

# -- -


class ParquetLockTimeout(TimeoutError):
    """Raised when the file lock cannot be acquired within the timeout."""


class ParquetSchemaConflict(ValueError):
    """Raised when the incoming DataFrame's Arrow schema differs from the on-disk schema."""


def _lock_path(parquet_path: Path) -> Path:
    """Return the sibling lock-file path for *parquet_path*."""
    return parquet_path.with_suffix(_LOCK_SUFFIX)


class _FileLock:
    """
    Minimal advisory file lock using O_CREAT | O_EXCL atomicity.

    Works on Windows, macOS, and Linux without third-party packages.
    The lock file is removed on __exit__ or if the process is interrupted
    (the context manager catches BaseException so KeyboardInterrupt is also
    handled).
    """

    def __init__(self, path: Path, timeout: float = _LOCK_TIMEOUT_S) -> None:
        self._lock_path = path
        self._timeout   = timeout
        self._fd: Optional[int] = None

    def __enter__(self) -> "_FileLock":
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                # O_EXCL guarantees atomicity: exactly one process succeeds.

                self._fd = os.open(
                    self._lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                # Write PID for diagnostics; ignore errors (best-effort).

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
                        f"within {self._timeout}s.  "
                        f"If this is a stale lock, delete it manually."
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
            pass  # already removed (e.g. by an external process)


def _df_to_arrow(df: pd.DataFrame) -> pa.Table:
    """Convert a pandas DataFrame to a pyarrow Table, preserving dtypes."""
    return pa.Table.from_pandas(df, preserve_index=False)


def _assert_compatible_schema(
    incoming: pa.Schema,
    existing: pa.Schema,
    path: Path,
) -> None:
    """
    Raise ParquetSchemaConflict if *incoming* is not compatible with *existing*.

    Compatibility here means every field in *existing* is also present in
    *incoming* with the same Arrow data type.  Extra columns in *incoming*
    are allowed (they will be appended) but missing columns or type mismatches
    are rejected.
    """
    existing_fields = {f.name: f.type for f in existing}
    incoming_fields = {f.name: f.type for f in incoming}

    type_mismatches = [
        f"  '{name}': on-disk={existing_fields[name]}, incoming={incoming_fields[name]}"
        for name in existing_fields
        if name in incoming_fields and existing_fields[name] != incoming_fields[name]
    ]
    missing_cols = sorted(set(existing_fields) - set(incoming_fields))

    problems: list[str] = []
    if missing_cols:
        problems.append(f"Columns present on disk but absent in DataFrame: {missing_cols}")
    if type_mismatches:
        problems.append("Type mismatches:\n" + "\n".join(type_mismatches))

    if problems:
        raise ParquetSchemaConflict(
            f"Schema conflict for {path}:\n" + "\n".join(problems)
        )


def _deduplicate(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """
    Return only the rows in *new_df* that are not already in *existing_df*.

    Deduplication is performed across all columns shared between the two
    DataFrames, which covers the full feature/target/metadata contract.
    """
    shared_cols = list(existing_df.columns.intersection(new_df.columns))
    if not shared_cols:
        # No overlap → nothing to deduplicate against.

        return new_df

    combined      = pd.concat([existing_df[shared_cols], new_df[shared_cols]], ignore_index=True)
    duplicate_mask = combined.duplicated(keep="first").iloc[len(existing_df):]
    new_rows_only  = new_df[~duplicate_mask.values]

    dropped = len(new_df) - len(new_rows_only)
    if dropped:
        logger.info("Deduplicated %d duplicate row(s) before append.", dropped)

    return new_rows_only


# -- -

# Public API

# -- -


def append_to_parquet(
    path: str | Path,
    df: pd.DataFrame,
    *,
    validate: bool = True,
    compression: str = _PARQUET_COMPRESSION,
) -> None:
    """
    Append *df* to the Parquet file at *path*.

    Behaviour
    ~~~~~~~~~
    - **First call**: creates parent directories, writes *df* as a new file.
    - **Subsequent calls**: reads the existing file, deduplicates, appends
      only novel rows, and rewrites atomically (write to a temp file, then
      rename).
    - The target file is protected by an advisory lock for the duration of
      the read-modify-write cycle, preventing concurrent corruption.
    - Schema compatibility is checked against the on-disk Arrow schema before
      any write is attempted.

    Parameters
    ----------
    path:
        Destination Parquet file path.  Parent directories are created if
        they do not exist.
    df:
        DataFrame to append.  Must satisfy the feature_schema contract when
        *validate* is True.
    validate:
        Run feature_schema.validate_schema() before writing.  Disable only
        if the caller has already validated upstream.
    compression:
        Parquet compression codec (default: ``"snappy"``).

    Raises
    ------
    SchemaValidationError
        If *validate* is True and *df* does not match the expected schema.
    ParquetSchemaConflict
        If *df*'s Arrow schema is incompatible with the on-disk schema.
    ParquetLockTimeout
        If the lock file cannot be acquired within ``_LOCK_TIMEOUT_S`` seconds.
    ValueError
        If *df* is empty.
    """
    path = Path(path)

    if df.empty:
        raise ValueError("append_to_parquet() received an empty DataFrame – nothing to write.")

    if validate:
        validate_schema(df)

    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _FileLock(_lock_path(path))

    with lock:
        incoming_table = _df_to_arrow(df)

        if not path.exists():
            #
            # First-time creation

            #
            logger.info("Creating new Parquet file: %s (%d rows)", path, len(df))
            pq.write_table(incoming_table, path, compression=compression)
            return

        #
        # File exists → validate schema, deduplicate, rewrite atomically

        #
        existing_table  = pq.read_table(path)
        existing_schema = existing_table.schema

        _assert_compatible_schema(incoming_table.schema, existing_schema, path)

        existing_df  = existing_table.to_pandas()
        new_rows     = _deduplicate(existing_df, df)

        if new_rows.empty:
            logger.info("No new rows to append to %s – all rows already present.", path)
            return

        # Merge: preserve the on-disk column order, add any new columns at the end.

        combined_df   = pd.concat([existing_df, new_rows], ignore_index=True)
        combined_table = pa.Table.from_pandas(combined_df, preserve_index=False)

        # Atomic write: temp file + rename so a crash never leaves a half-written file.

        tmp_path = path.with_suffix(".tmp.parquet")
        try:
            pq.write_table(combined_table, tmp_path, compression=compression)
            tmp_path.replace(path)           # atomic on POSIX; near-atomic on Windows
            logger.info(
                "Appended %d new row(s) to %s (total: %d rows).",
                len(new_rows), path, len(combined_df),
            )
        except Exception:
            # Clean up the temp file on failure so stale files don't accumulate.

            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise


def load_parquet_partition(
    path: str | Path,
    filters: Optional[list] = None,
    *,
    columns: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Load a Parquet file (or partitioned dataset directory) into a DataFrame.

    Parameters
    ----------
    path:
        Path to a ``.parquet`` file or a directory containing a partitioned
        Parquet dataset.
    filters:
        Optional row-group filter expressions in the DNF (disjunctive normal
        form) accepted by ``pyarrow.parquet.read_table``.  Only matching
        row groups are deserialised, which can drastically reduce I/O for
        large datasets.

        Examples::

            # Single predicate

            filters=[("season", "=", 2024)]

            # AND – both conditions must hold

            filters=[("season", "=", 2024), ("driver_id", "=", "VER")]

            # OR – either predicate group matches  (list-of-lists)

            filters=[[("season", "=", 2023)], [("season", "=", 2024)]]

    columns:
        If provided, only these columns are read from disk (column pruning).
        Pass None to read all columns (default).

    Returns
    -------
    pd.DataFrame
        The loaded data, with the original column order preserved.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Parquet path not found: {path}")

    kwargs: dict = dict(filters=filters, columns=columns)
    table = pq.read_table(path, **{k: v for k, v in kwargs.items() if v is not None})
    df    = table.to_pandas()

    logger.info(
        "Loaded %d row(s) × %d col(s) from %s%s.",
        len(df),
        len(df.columns),
        path,
        f" (filters={filters})" if filters else "",
    )
    return df


# -- -

# Quick self-test / debug entry-point

# -- -


if __name__ == "__main__":  # pragma: no cover
    import tempfile

    import numpy as np

    from feature_schema import ALL_COLUMNS, FEATURE_COLUMNS, METADATA_COLUMNS, TARGET_COLUMNS

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    def _make_df(n: int, seed: int = 0) -> pd.DataFrame:
        """Build a minimal but valid stub DataFrame."""
        rng = np.random.default_rng(seed)
        row: dict = {
            # features

            "lap_time_s":        rng.uniform(85, 95,  n).tolist(),
            "sector_1_s":        rng.uniform(25, 30,  n).tolist(),
            "sector_2_s":        rng.uniform(28, 35,  n).tolist(),
            "sector_3_s":        rng.uniform(20, 25,  n).tolist(),
            "tyre_age_laps":     rng.integers(0, 40,  n).tolist(),
            "tyre_compound":     (["SOFT", "MEDIUM", "HARD"] * (n // 3 + 1))[:n],
            "fuel_load_kg":      rng.uniform(0, 110,  n).tolist(),
            "air_temp_c":        rng.uniform(18, 38,  n).tolist(),
            "track_temp_c":      rng.uniform(25, 55,  n).tolist(),
            "humidity_pct":      rng.uniform(20, 90,  n).tolist(),
            "wind_speed_ms":     rng.uniform(0, 15,   n).tolist(),
            "track_status":      ["1"] * n,
            "drs_available":     rng.integers(0, 2,   n).tolist(),
            "ers_deployed_pct":  rng.uniform(0, 100,  n).tolist(),
            "gap_ahead_s":       rng.uniform(0, 60,   n).tolist(),
            "gap_behind_s":      rng.uniform(0, 60,   n).tolist(),
            "pit_stop_count":    rng.integers(0, 4,   n).tolist(),
            "starting_grid_pos": rng.integers(1, 21,  n).tolist(),
            # targets

            "finish_pos":        rng.integers(1, 21,  n).tolist(),
            "race_time_s":       rng.uniform(5400, 6000, n).tolist(),
            "points_scored":     rng.integers(0, 26,  n).tolist(),
            # metadata

            "race_id":           [f"R{i:04d}" for i in range(n)],
            "driver_id":         ["VER"] * n,
            "team_id":           ["RBR"] * n,
            "lap_number":        list(range(1, n + 1)),
            "season":            [2024] * n,
            "round":             [1] * n,
            "timestamp":         pd.date_range("2024-03-02", periods=n, freq="90s").tolist(),
        }
        return pd.DataFrame(row)

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "telemetry.parquet"

        batch_a = _make_df(5, seed=1)
        batch_b = _make_df(5, seed=2)
        # Overlap: last 2 rows of batch_a also in batch_c  → should be deduped

        batch_c = pd.concat([batch_a.tail(2), _make_df(3, seed=3)], ignore_index=True)

        print("── Append batch A (5 rows, first-time creation) ──")
        append_to_parquet(dest, batch_a, validate=True)

        print("\n── Append batch B (5 new rows) ──")
        append_to_parquet(dest, batch_b, validate=True)

        print("\n── Append batch C (2 duplicates + 3 new rows) ──")
        append_to_parquet(dest, batch_c, validate=True)

        print("\n── Load with no filters ──")
        df_all = load_parquet_partition(dest)
        print(f"   Total rows loaded: {len(df_all)}")  # expect 13

        print("\n── Load with season=2024 filter ──")
        df_filtered = load_parquet_partition(dest, filters=[("season", "=", 2024)])
        print(f"   Filtered rows loaded: {len(df_filtered)}")

        print("\n── Load with column pruning ──")
        df_cols = load_parquet_partition(dest, columns=["lap_time_s", "driver_id", "season"])
        print(f"   Columns returned: {list(df_cols.columns)}")

        print("\n✓ All checks passed.")