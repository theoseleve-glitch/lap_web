"""
io_racechrono.py
----------------
Production-grade reader for RaceChrono CSV exports.

RaceChrono prepends a variable number of metadata/comment rows before the
actual data header.  The header row is identified by its first cell containing
"Time (s)" (after whitespace normalisation).  Every row above it is discarded.

Public API
~~~~~~~~~~
- ``read_racechrono_csv(path)``  -- full pipeline: detect header, load, clean.

Internal helpers
~~~~~~~~~~~~~~~~
- ``_find_header_row(path)``     -- scan for the zero-based row index of the
                                   data header.
- ``_strip_headers(df)``         -- normalise column names in-place.
- ``_coerce_numeric(df)``        -- safely cast parseable columns to float64.

Design principles
~~~~~~~~~~~~~~~~~
- No assumption about the number of metadata rows.
- Encoding errors are handled via a fallback chain (UTF-8 -> latin-1 -> raw bytes).
- No crash on missing optional columns.
- No print statements; structured logging only.
- All mutable state is local; no module-level side effects.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final

import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Constants

# -- -


#: The normalised cell value that identifies the data header row.

_HEADER_SENTINEL: Final[str] = "Time (s)"

#: Encoding fallback chain -- tried in order until one succeeds.

_ENCODINGS: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

#: Columns that must never be coerced to float (identifiers / categoricals).
#: Uses raw RaceChrono header names because _coerce_numeric runs before any
#: schema standardisation (the pipeline's _map_to_internal_names is separate).

_NON_NUMERIC_RAW: Final[frozenset[str]] = frozenset({"Lap #", "lap_number"})

#: Regex that matches any run of leading/trailing/internal extra whitespace.

_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")


# -- -

# Exceptions

# -- -


class RaceChronoParseError(ValueError):
    """Raised when the CSV cannot be parsed into a usable DataFrame."""


# -- -

# Internal helpers

# -- -


def _normalise_cell(value: str) -> str:
    """Collapse whitespace and strip a raw cell string."""
    return _WS_RE.sub(" ", value).strip()


def _open_with_fallback(path: Path) -> tuple[list[str], str]:
    """
    Read *path* as a list of raw text lines using the first encoding in
    ``_ENCODINGS`` that does not raise a ``UnicodeDecodeError``.

    Returns
    -------
    (lines, encoding_used)

    Raises
    ------
    RaceChronoParseError
        If every encoding in the fallback chain fails.
    """
    for enc in _ENCODINGS:
        try:
            lines = path.read_text(encoding=enc).splitlines()
            logger.debug("Opened %s with encoding=%r (%d lines)", path, enc, len(lines))
            return lines, enc
        except UnicodeDecodeError:
            logger.debug("Encoding %r failed for %s -- trying next.", enc, path)

    # Last resort: replace undecodable bytes rather than crashing.

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    logger.warning(
        "All clean encodings failed for %s; loaded with utf-8 + replacement chars.", path
    )
    return lines, "utf-8-replace"


def _find_header_row_from_lines(lines: list[str], source_label: str = "<unknown>") -> int:
    """
    Scan pre-read *lines* and return the **zero-based** index of the row
    whose first CSV field (after whitespace normalisation) equals
    ``_HEADER_SENTINEL`` (``"Time (s)"``).

    Parameters
    ----------
    lines:
        Raw text lines (already read from disk).
    source_label:
        Human-readable name used in log / error messages.

    Returns
    -------
    int
        Zero-based row index of the data header.

    Raises
    ------
    RaceChronoParseError
        If the sentinel column is not found within the lines.
    """
    for idx, line in enumerate(lines):
        # Try comma first, then semicolon -- RaceChrono exports vary by locale.

        stripped = line.strip()
        if not stripped:
            continue
        # Split on whichever delimiter is present in this line

        if ";" in stripped:
            first_cell = _normalise_cell(stripped.split(";")[0])
        else:
            first_cell = _normalise_cell(stripped.split(",")[0])
        if first_cell == _HEADER_SENTINEL:
            logger.debug("Header sentinel found at row %d in %s.", idx, source_label)
            return idx

    raise RaceChronoParseError(
        f"Could not locate the data header row in {source_label}.\n"
        f"Expected first cell to contain {_HEADER_SENTINEL!r} "
        f"(after whitespace normalisation) on some row, "
        f"but no such row was found across {len(lines)} line(s)."
    )


def _find_header_row(path: str | Path) -> int:
    """
    Scan *path* line-by-line and return the **zero-based** index of the row
    whose first CSV field (after whitespace normalisation) equals
    ``_HEADER_SENTINEL`` (``"Time (s)"``).

    Parameters
    ----------
    path:
        Path to a RaceChrono CSV file.

    Returns
    -------
    int
        Zero-based row index of the data header.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    RaceChronoParseError
        If the sentinel column is not found within the file.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    lines, _ = _open_with_fallback(path)
    return _find_header_row_from_lines(lines, source_label=str(path))


def _strip_headers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return *df* with all column names whitespace-normalised.

    Does **not** mutate the original DataFrame.
    """
    rename_map = {col: _normalise_cell(str(col)) for col in df.columns}
    return df.rename(columns=rename_map)


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attempt to cast every column in *df* to ``float64``.

    Columns that cannot be coerced (e.g. string identifiers, all-NaN columns
    produced by a malformed CSV row) are left in their original dtype.
    Columns listed in ``_NON_NUMERIC_RAW`` are never coerced regardless
    of their content.

    Returns a new DataFrame; the original is not mutated.
    """
    result = df.copy()
    for col in result.columns:
        if col in _NON_NUMERIC_RAW:
            continue
        coerced = pd.to_numeric(result[col], errors="coerce")
        # Only adopt the coerced series if it added numeric information.

        # (If every value became NaN the column was purely non-numeric.)

        non_null_before = result[col].notna().sum()
        non_null_after  = coerced.notna().sum()
        if non_null_after > 0 or non_null_before == 0:
            result[col] = coerced
            logger.debug("Column %r coerced to float64 (%d NaN introduced).",
                         col, non_null_before - non_null_after)
        else:
            logger.debug("Column %r left as %s (all values non-numeric).",
                         col, result[col].dtype)
    return result


def _drop_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove rows where *every* value is NaN or empty string.
    These arise when RaceChrono appends a trailing blank line or a footer row.
    """
    mask = df.replace("", pd.NA).isna().all(axis=1)
    dropped = mask.sum()
    if dropped:
        logger.debug("Dropped %d fully-empty row(s).", dropped)
    return df[~mask].reset_index(drop=True)


def _parse_metadata(lines: list[str], header_row_idx: int) -> dict[str, str]:
    """
    Parse RaceChrono metadata rows (everything above the data header) into a
    ``dict``.

    Common metadata patterns found in RaceChrono CSV exports::

        RaceChrono Pro v<version> export
        Session: <session title>
        Track: <track name>
        Driver: <driver name>
        Vehicle: <vehicle name>
        Date: <date>
        <key>: <value>

    Lines that do not match a ``Key: Value`` pattern are stored under
    ``"comment_<N>"`` keys (zero-indexed).  Empty or delimiter-only lines
    are skipped.

    Parameters
    ----------
    lines:
        Full file contents as a list of text lines.
    header_row_idx:
        Zero-based index of the data header row.

    Returns
    -------
    dict[str, str]
        Metadata key-value pairs.
    """
    metadata: dict[str, str] = {}
    comment_idx = 0

    for i in range(header_row_idx):
        raw = lines[i].strip()
        # Skip blank or delimiter-only lines
        if not raw or raw in (",", ";", ",,", ";;"):
            continue
        # Strip leading comment characters
        clean = raw.lstrip("#").strip()
        if not clean:
            continue
        # Try "Key: Value" pattern (first colon splits)
        if ":" in clean:
            key, _, value = clean.partition(":")
            key = key.strip()
            value = value.strip()
            if key:
                metadata[key.lower()] = value
                continue
        # Fallback: store as numbered comment
        metadata[f"comment_{comment_idx}"] = clean
        comment_idx += 1

    return metadata


def _check_time_monotonicity(df: pd.DataFrame, *, sort: bool = True) -> pd.DataFrame:
    """
    Check whether the time column (``_HEADER_SENTINEL`` / ``"Time (s)"``) is
    monotonically non-decreasing.  GPS glitches can produce non-monotonic
    timestamps.

    If non-monotonic timestamps are detected a warning is logged.  When
    *sort* is ``True`` (the default) the DataFrame is sorted by the time
    column in-place and reset-indexed so downstream code always sees ordered
    data.

    Parameters
    ----------
    df:
        DataFrame that should already have normalised column names and
        numeric dtypes.
    sort:
        If ``True`` and non-monotonicity is detected, sort by the time
        column.

    Returns
    -------
    pd.DataFrame
        Possibly re-sorted DataFrame.
    """
    if _HEADER_SENTINEL not in df.columns:
        return df

    time_col = df[_HEADER_SENTINEL]
    if time_col.is_monotonic_increasing:
        return df

    n_violations = int((time_col.diff().dropna() < 0).sum())
    logger.warning(
        "Time column is NOT monotonically increasing "
        "(%d backward jump(s) detected). %s",
        n_violations,
        "Sorting by time." if sort else "No automatic sort requested.",
    )

    if sort:
        df = df.sort_values(_HEADER_SENTINEL).reset_index(drop=True)

    return df


# -- -

# Public API

# -- -


def read_racechrono_csv(path: str | Path, **kwargs) -> pd.DataFrame:
    """
    Load a RaceChrono CSV export into a clean pandas DataFrame.

    When the ``INGEST_V2`` feature flag is enabled (env var
    ``TELEMETRY_INGEST_V2=1``) and the file exceeds 100 MB, this function
    automatically routes to the streaming reader which uses chunked I/O
    and bounded memory.  Otherwise the legacy in-memory path is used.

    Pipeline (legacy path)
    ~~~~~~~~~~~~~~~~~~~~~~
    1. Read the file once (encoding fallback chain).
    2. Detect the data-header row from the buffered lines.
    3. Parse metadata rows above the header into a dict.
    4. Auto-detect field separator (comma vs semicolon).
    5. Read the CSV with ``pandas.read_csv``, skipping rows above the header.
       When semicolons are used as separator, ``decimal=","`` is passed to
       handle European decimal-comma notation.
    6. Strip whitespace from all column names.
    7. Drop fully-empty rows (trailing blank lines, footer text).
    8. Coerce all numeric-compatible columns to ``float64``.
    9. Check time-column monotonicity; sort if needed.

    Parameters
    ----------
    path:
        Path to a RaceChrono ``.csv`` export file.  Accepts ``str`` or
        :class:`pathlib.Path`.
    **kwargs:
        Forwarded to the streaming reader when active.  Accepts
        ``config`` (:class:`~telemetry_tool.ingest.config.IngestionConfig`)
        and ``progress_cb`` (callable).

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame with normalised column names and numeric dtypes
        where applicable.  Optional sensor columns absent from *path* are
        simply not present in the result -- no ``KeyError`` is raised.

        Session metadata parsed from the rows above the data header is
        stored in ``df.attrs["racechrono_metadata"]`` as a ``dict``.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    RaceChronoParseError
        If the header sentinel cannot be located, or if the file is empty
        after skipping metadata rows.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    # ── INGEST_V2 routing ────────────────────────────────────────
    # When the streaming pipeline is enabled (default ON), route ALL files
    # through it regardless of size.  Set TELEMETRY_INGEST_V2=0 to force
    # the legacy path below.
    try:
        from telemetry_tool.ingest.config import INGEST_V2
        if INGEST_V2:
            from telemetry_tool.ingest.streaming import read_racechrono_csv_streamed
            logger.info(
                "INGEST_V2 active: routing %s (%.1f MB) to streaming reader.",
                path.name, path.stat().st_size / 1e6,
            )
            return read_racechrono_csv_streamed(path, **kwargs)
    except ImportError:
        pass  # ingest package not available — fall through to legacy path
    # ── End INGEST_V2 routing ────────────────────────────────────

    logger.info("Reading RaceChrono CSV: %s", path)

    # Step 1 -- read file ONCE (encoding fallback chain).
    # All subsequent steps reuse `lines` and `encoding` -- no redundant reads.

    lines, encoding = _open_with_fallback(path)
    if encoding == "utf-8-replace":
        encoding = "utf-8"   # pandas accepts "utf-8" + errors kwarg separately

    # Step 2 -- locate the header row from the buffered lines.

    header_row_idx = _find_header_row_from_lines(lines, source_label=str(path))

    # Step 3 -- parse metadata rows above the header (Issue 5).

    metadata = _parse_metadata(lines, header_row_idx)
    if metadata:
        logger.debug("Parsed %d metadata entries from %s: %s",
                      len(metadata), path.name, list(metadata.keys()))

    # Step 4 -- auto-detect field separator (comma vs semicolon).

    header_line = lines[header_row_idx] if header_row_idx < len(lines) else ""
    if header_line.count(";") > header_line.count(","):
        sep = ";"
        decimal = ","          # Issue 1: European decimal-comma handling
        logger.info("Detected semicolon separator in %s (decimal=',').", path.name)
    else:
        sep = ","
        decimal = "."

    # Step 5 -- load CSV, skipping all rows above the header.

    try:
        df = pd.read_csv(
            path,
            sep=sep,
            decimal=decimal,           # Issue 1: handle "47,123" as 47.123
            skiprows=header_row_idx,   # skip metadata rows; row at index becomes header
            encoding=encoding,
            encoding_errors="replace",
            on_bad_lines="skip",       # silently skip malformed lines
            # Issue 2: low_memory=False removed -- _coerce_numeric handles
            # type conversion; avoiding 8+ GB RAM usage on large (659 MB) files.
        )
    except pd.errors.EmptyDataError as exc:
        raise RaceChronoParseError(
            f"No data found in {path} after skipping {header_row_idx} "
            f"metadata row(s)."
        ) from exc

    if df.empty:
        raise RaceChronoParseError(
            f"DataFrame is empty after loading {path} "
            f"(skipped {header_row_idx} row(s))."
        )

    # Count skipped lines (ragged rows) -- reuse buffered `lines`.

    expected_data_lines = sum(
        1 for line in lines[header_row_idx + 1:] if line.strip()
    )
    n_skipped = max(0, expected_data_lines - len(df))
    if n_skipped > 0:
        logger.warning(
            "Skipped %d ragged/malformed line(s) in %s "
            "(expected %d data lines, loaded %d).",
            n_skipped, path.name, expected_data_lines, len(df),
        )

    # Step 6 -- normalise column names.

    df = _strip_headers(df)

    # Step 7 -- drop blank trailing rows.

    df = _drop_empty_rows(df)

    # Step 8 -- safe numeric coercion.

    df = _coerce_numeric(df)

    # Step 9 -- time monotonicity check (Issue 4).

    df = _check_time_monotonicity(df)

    # Attach session metadata to DataFrame (Issue 5, backward-compatible).

    df.attrs["racechrono_metadata"] = metadata

    logger.info(
        "Loaded %s  ->  %d rows x %d columns  (header at row %d).",
        path.name, len(df), len(df.columns), header_row_idx,
    )
    return df


# -- -

# Quick self-test / debug entry-point

# -- -


if __name__ == "__main__":  # pragma: no cover
    import sys
    import tempfile
    import textwrap

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

    #
    # Build a synthetic RaceChrono-style CSV with 3 metadata rows.

    #
    SAMPLE_CSV = textwrap.dedent("""\
        RaceChrono export
        Session: Spa 2024
        ,
        Time (s), Lap #, Distance (m), Speed (m/s), Latitude (deg), Longitude (deg), Yaw rate (deg/s)
        0.0,1,0.0,0.0,50.4372,6.0253,0.1
        0.1,1,0.5,18.3,50.4373,6.0254,0.2
        0.2,1,2.3,22.1,50.4374,6.0255,
        0.3,2,5.0,25.0,50.4375,6.0256,0.4
        ,,,,,,,
    """)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(SAMPLE_CSV)
        tmp_path = tmp.name

    print(f"\n-- Synthetic CSV written to {tmp_path} --")

    df = read_racechrono_csv(tmp_path)
    print(f"\nShape : {df.shape}")
    print(f"Columns: {list(df.columns)}")
    print(f"\nDtypes:\n{df.dtypes}")
    print(f"\nData:\n{df.to_string()}")

    # Verify numeric coercion

    assert df["Time (s)"].dtype == "float64",  "Time should be float64"
    assert df["Speed (m/s)"].dtype == "float64", "Speed should be float64"
    assert df["Yaw rate (deg/s)"].isna().sum() == 1, "One NaN expected in yaw rate"
    assert len(df) == 4, f"Expected 4 data rows, got {len(df)}"

    print("\nOK All assertions passed.")

    # Test: header not found

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as bad_tmp:
        bad_tmp.write("no,header,here\n1,2,3\n")
        bad_path = bad_tmp.name

    try:
        read_racechrono_csv(bad_path)
    except RaceChronoParseError as exc:
        print(f"\nOK RaceChronoParseError correctly raised:\n  {exc}")

    # Test: semicolon-separated CSV (European locale / RaceChrono export)

    SAMPLE_SEMICOLON = textwrap.dedent("""\
        RaceChrono export
        Session: MKR 2026
        ;
        Time (s); Lap #; Distance (m); Speed (m/s); Latitude (deg); Longitude (deg)
        0.0;1;0.0;0.0;50.437;6.025
        0.1;1;0.5;18.3;50.438;6.026
        0.2;1;2.3;22.1;50.439;6.027
        0.3;2;5.0;25.0;50.440;6.028
    """)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as semi_tmp:
        semi_tmp.write(SAMPLE_SEMICOLON)
        semi_path = semi_tmp.name

    df_semi = read_racechrono_csv(semi_path)
    assert len(df_semi) == 4, f"Expected 4 rows, got {len(df_semi)}"
    assert "Time (s)" in df_semi.columns, f"Columns: {list(df_semi.columns)}"
    assert "Speed (m/s)" in df_semi.columns
    assert df_semi["Speed (m/s)"].dtype == "float64"
    print(f"\nOK Semicolon-separated CSV: {df_semi.shape[0]} rows x {df_semi.shape[1]} cols")

    # Test: metadata parsing (Issue 5)
    assert "racechrono_metadata" in df.attrs, "Metadata not attached to DataFrame"
    meta = df.attrs["racechrono_metadata"]
    assert "session" in meta, f"Expected 'session' key in metadata, got {list(meta.keys())}"
    print(f"\nOK Metadata parsed: {meta}")

    # Test: semicolon CSV with European decimal-comma notation (Issue 1)
    SAMPLE_EURO = textwrap.dedent("""\
        RaceChrono export
        Session: Euro Test
        ;
        Time (s); Lap #; Distance (m); Speed (m/s); Latitude (deg); Longitude (deg)
        0,0;1;0,0;0,0;50,437;6,025
        0,1;1;0,5;18,3;50,438;6,026
        0,2;1;2,3;22,1;50,439;6,027
        0,3;2;5,0;25,0;50,440;6,028
    """)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as euro_tmp:
        euro_tmp.write(SAMPLE_EURO)
        euro_path = euro_tmp.name

    df_euro = read_racechrono_csv(euro_path)
    assert len(df_euro) == 4, f"Expected 4 rows, got {len(df_euro)}"
    assert df_euro["Speed (m/s)"].dtype == "float64", (
        f"European decimal-comma not parsed: dtype={df_euro['Speed (m/s)'].dtype}"
    )
    assert abs(df_euro["Speed (m/s)"].iloc[1] - 18.3) < 0.01, (
        f"Expected 18.3, got {df_euro['Speed (m/s)'].iloc[1]}"
    )
    print(f"\nOK European decimal-comma CSV: {df_euro.shape[0]} rows x {df_euro.shape[1]} cols")

    # Test: non-monotonic time (Issue 4) -- should warn and sort
    SAMPLE_NONMONO = textwrap.dedent("""\
        RaceChrono export
        Time (s), Lap #, Speed (m/s)
        0.0,1,10.0
        0.2,1,12.0
        0.1,1,11.0
        0.3,1,13.0
    """)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as nm_tmp:
        nm_tmp.write(SAMPLE_NONMONO)
        nm_path = nm_tmp.name

    df_nm = read_racechrono_csv(nm_path)
    times = df_nm["Time (s)"].tolist()
    assert times == sorted(times), f"Time not sorted after monotonicity fix: {times}"
    print(f"\nOK Non-monotonic time sorted correctly: {times}")

    print("\nOK All assertions passed.")