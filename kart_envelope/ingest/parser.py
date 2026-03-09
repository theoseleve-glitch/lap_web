"""
parser.py
---------
Thin wrapper around ``telemetry_tool.io_racechrono.read_racechrono_csv``
that adds duplicate-column handling, ``*calc`` preference, and canonical
column normalisation.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

# Ensure the project root is importable so telemetry_tool can be found.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from kart_envelope.ingest.columns import REQUIRED_COLUMNS, normalize_columns  # noqa: E402
from telemetry_tool.io_racechrono import read_racechrono_csv  # noqa: E402

logger = logging.getLogger(__name__)


class ParseError(ValueError):
    """Raised when a RaceChrono CSV cannot be parsed into a valid DataFrame."""


def parse_session_csv_raw(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse a RaceChrono CSV returning both raw and normalised DataFrames.

    This avoids the double-read anti-pattern where the file was read once for
    normalised columns and again for raw column names (needed by
    ``clean_and_derive``).

    Steps
    -----
    1. ``read_racechrono_csv(path)`` — single-pass: encoding detection, header
       discovery, metadata parsing, coercion, monotonicity.
    2. Normalise a copy via :func:`normalize_columns`.
    3. Validate required columns on the normalised version.

    Returns
    -------
    (raw_df, normalised_df)
        raw_df: DataFrame with original RaceChrono column names.
        normalised_df: DataFrame with canonical column names.

    Raises
    ------
    ParseError
        If the file cannot be read or is missing required columns.
    """
    path = Path(path)
    if not path.exists():
        raise ParseError(f"File not found: {path}")

    try:
        raw_df = read_racechrono_csv(str(path))
    except Exception as exc:
        raise ParseError(f"Failed to read {path.name}: {exc}") from exc

    metadata = getattr(raw_df, "attrs", {}).get("racechrono_metadata", {})

    normalised_df = normalize_columns(raw_df)
    normalised_df.attrs["racechrono_metadata"] = metadata

    missing = REQUIRED_COLUMNS - set(normalised_df.columns)
    if missing:
        raise ParseError(
            f"{path.name} is missing required columns after normalisation: "
            f"{sorted(missing)}"
        )

    logger.info(
        "Parsed %s: %d rows, %d columns, laps %s",
        path.name,
        len(normalised_df),
        len(normalised_df.columns),
        sorted(normalised_df["lap_number"].dropna().unique().astype(int))
        if "lap_number" in normalised_df.columns
        else "N/A",
    )
    return raw_df, normalised_df


def parse_session_csv(path: str | Path) -> pd.DataFrame:
    """Parse a RaceChrono CSV with column normalisation.

    Thin wrapper around :func:`parse_session_csv_raw` that returns only the
    normalised DataFrame (backward-compatible public API).

    Parameters
    ----------
    path : str | Path
        Path to a RaceChrono Pro CSV file.

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame with canonical column names.
        RaceChrono metadata is preserved in ``df.attrs["racechrono_metadata"]``.

    Raises
    ------
    ParseError
        If the file cannot be read or is missing required columns.
    """
    _, normalised_df = parse_session_csv_raw(path)
    return normalised_df
