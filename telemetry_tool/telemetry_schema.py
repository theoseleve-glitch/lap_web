"""
telemetry_schema.py
-------------------
Canonical column-name contract between raw RaceChrono CSV exports and the
internal telemetry pipeline.

Responsibilities
~~~~~~~~~~~~~~~~
- ``TelemetrySchema``       – dataclass that holds the raw→internal name mapping.
- ``validate_schema(df)``   – assert that every required column is present in *df*
                              (after whitespace normalisation) and raise a
                              descriptive error on the first violation.
- ``standardize_columns(df)`` – rename raw columns to internal names and return
                               a cleaned DataFrame.

Design principles
~~~~~~~~~~~~~~~~~
- Zero side-effects:  no print statements, no global state mutation, no I/O.
- Immutable mapping:  ``TelemetrySchema`` is frozen so callers cannot
  accidentally mutate the production schema at runtime.
- Whitespace-robust:  leading/trailing/internal whitespace in CSV headers is
  silently normalised before any comparison or rename.
- Separation of concerns:  validation and transformation are separate functions
  so callers can validate without transforming (e.g. in a data-contract test).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

import pandas as pd


# -- -

# Exceptions

# -- -


class TelemetrySchemaError(ValueError):
    """
    Raised when a DataFrame does not satisfy the telemetry schema contract.

    Inherits from ``ValueError`` so existing ``except ValueError`` handlers
    still catch it; code that needs precise discrimination can catch this
    subclass directly.
    """


# -- -

# Internal helpers

# -- -


_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")


def _normalise(name: str) -> str:
    """
    Collapse any run of whitespace in *name* to a single space and strip
    leading/trailing whitespace.

    Examples
    --------
    >>> _normalise("  Speed  (m/s) ")
    'Speed (m/s)'
    >>> _normalise("Lap\\tNumber")
    'Lap Number'
    """
    return _WHITESPACE_RE.sub(" ", name).strip()


def _normalise_columns(df: pd.DataFrame) -> dict[str, str]:
    """
    Return a mapping of ``{normalised_name: original_column_name}`` for every
    column in *df*.  When two original names normalise to the same string the
    last one wins (consistent with pandas' own dedup behaviour).
    """
    return {_normalise(col): col for col in df.columns}


# -- -

# Schema dataclass

# -- -


@dataclass(frozen=True)
class TelemetrySchema:
    """
    Bidirectional mapping between raw RaceChrono CSV header names and the
    internal standardised column names used throughout the pipeline.

    The dataclass is **frozen** to prevent accidental mutation.  Create a
    custom schema by instantiating with overriding values rather than patching
    an existing instance.

    Attributes
    ----------
    Raw→internal name pairs are stored as ``raw_<internal_name>`` attributes.
    ``required_internal`` lists the internal names that *must* be present.
    ``optional_internal`` lists names that may or may not be present in a
    given CSV export.

    Notes
    -----
    RaceChrono column names may contain parenthetical units and can vary
    slightly between firmware/export versions.  The defaults here match the
    standard RaceChrono CSV export format; override individual ``raw_*``
    fields when ingesting non-standard exports.
    """

    #
    # Required columns

    #
    raw_time_s:         str = "Time (s)"
    raw_lap_number:     str = "Lap #"
    raw_distance_m:     str = "Distance (m)"
    raw_speed_mps:      str = "Speed (m/s)"

    #
    # Optional columns

    #
    raw_latitude_deg:           str = "Latitude (deg)"
    raw_longitude_deg:          str = "Longitude (deg)"
    raw_x_m:                    str = "X (m)"
    raw_y_m:                    str = "Y (m)"
    raw_longitudinal_accel_mps2: str = "Longitudinal acceleration (m/s²)"
    raw_lateral_accel_mps2:     str = "Lateral acceleration (m/s²)"
    raw_yaw_rate_dps:           str = "Yaw rate (deg/s)"

    #
    # Column-group membership (internal names)

    #
    required_internal: tuple[str, ...] = field(default_factory=lambda: (
        "time_s",
        "lap_number",
        "distance_m",
        "speed_mps",
    ))

    optional_internal: tuple[str, ...] = field(default_factory=lambda: (
        "latitude_deg",
        "longitude_deg",
        "x_m",
        "y_m",
        "longitudinal_accel_mps2",
        "lateral_accel_mps2",
        "yaw_rate_dps",
    ))

    #
    # Derived views (computed from the fields above)

    #

    def raw_to_internal(self) -> dict[str, str]:
        """
        Return ``{normalised_raw_name: internal_name}`` for every column
        (required + optional) defined in this schema.

        The raw names are normalised so they can be matched against normalised
        DataFrame column names regardless of whitespace quirks.
        """
        pairs: list[tuple[str, str]] = [
            (self.raw_time_s,                  "time_s"),
            (self.raw_lap_number,              "lap_number"),
            (self.raw_distance_m,              "distance_m"),
            (self.raw_speed_mps,               "speed_mps"),
            (self.raw_latitude_deg,            "latitude_deg"),
            (self.raw_longitude_deg,           "longitude_deg"),
            (self.raw_x_m,                     "x_m"),
            (self.raw_y_m,                     "y_m"),
            (self.raw_longitudinal_accel_mps2, "longitudinal_accel_mps2"),
            (self.raw_lateral_accel_mps2,      "lateral_accel_mps2"),
            (self.raw_yaw_rate_dps,            "yaw_rate_dps"),
        ]
        return {_normalise(raw): internal for raw, internal in pairs}

    def required_raw(self) -> tuple[str, ...]:
        """Return the raw header names for required columns."""
        internal_to_raw = {v: k for k, v in self.raw_to_internal().items()}
        return tuple(internal_to_raw[name] for name in self.required_internal)


# -- -

# Module-level default schema instance

# -- -


#: Production schema instance.  Import and use this directly unless you need

#: a custom mapping.

DEFAULT_SCHEMA: Final[TelemetrySchema] = TelemetrySchema()


# -- -

# Public API

# -- -


def validate_schema(
    df: pd.DataFrame,
    schema: TelemetrySchema = DEFAULT_SCHEMA,
) -> None:
    """
    Verify that *df* contains all required columns defined in *schema*.

    Column names in *df* are normalised (whitespace collapsed) before
    comparison, so ``"  Time  (s) "`` will match ``"Time (s)"``.

    Parameters
    ----------
    df:
        Raw DataFrame loaded directly from a RaceChrono CSV (or equivalent).
    schema:
        Schema to validate against.  Defaults to ``DEFAULT_SCHEMA``.

    Raises
    ------
    TypeError
        If *df* is not a :class:`pandas.DataFrame`.
    TelemetrySchemaError
        If one or more required columns are absent.  The error message lists
        every missing column (raw name) so the root cause is immediately
        actionable.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"validate_schema() expects a pandas DataFrame, "
            f"got {type(df).__name__!r}."
        )

    normalised_df_cols: set[str] = set(_normalise_columns(df).keys())
    mapping: dict[str, str]      = schema.raw_to_internal()
    required_raw_normalised: set[str] = {
        _normalise(raw)
        for raw, internal in zip(schema.required_raw(), schema.required_internal)
    }

    missing_raw: list[str] = sorted(
        raw
        for raw in required_raw_normalised
        if raw not in normalised_df_cols
    )

    if missing_raw:
        # Surface the *original* (un-normalised) raw names for clarity.

        raw_norm_to_original = {_normalise(r): r for r in schema.required_raw()}
        missing_display = [raw_norm_to_original.get(r, r) for r in missing_raw]
        raise TelemetrySchemaError(
            f"Telemetry DataFrame is missing {len(missing_display)} required "
            f"column(s):\n"
            + "\n".join(f"  • {name!r}" for name in missing_display)
            + f"\n\nColumns present in DataFrame:\n"
            + "\n".join(f"  – {col!r}" for col in df.columns)
        )


def standardize_columns(
    df: pd.DataFrame,
    schema: TelemetrySchema = DEFAULT_SCHEMA,
    *,
    drop_unknown: bool = False,
) -> pd.DataFrame:
    """
    Rename raw RaceChrono column headers to internal standardised names.

    Only columns present in *schema* (required + optional) are renamed.
    Columns not recognised by the schema are preserved by default; set
    ``drop_unknown=True`` to remove them.

    Parameters
    ----------
    df:
        Raw DataFrame to standardise.  ``validate_schema`` is called
        internally, so callers do not need to call it separately.
    schema:
        Schema to apply.  Defaults to ``DEFAULT_SCHEMA``.
    drop_unknown:
        If ``True``, any column not listed in *schema* is dropped from the
        returned DataFrame.

    Returns
    -------
    pd.DataFrame
        A new DataFrame with standardised column names (and optionally with
        unknown columns removed).  The original *df* is never mutated.

    Raises
    ------
    TelemetrySchemaError
        Propagated from :func:`validate_schema` if required columns are absent.
    """
    validate_schema(df, schema)

    # Build normalised_raw → original_column_in_df lookup.

    norm_to_original: dict[str, str] = _normalise_columns(df)

    # Build the rename map: original_col → internal_name.

    rename_map: dict[str, str] = {}
    norm_schema_mapping = schema.raw_to_internal()   # {normalised_raw: internal}

    for norm_raw, internal_name in norm_schema_mapping.items():
        original_col = norm_to_original.get(norm_raw)
        if original_col is not None:
            rename_map[original_col] = internal_name

    result = df.rename(columns=rename_map)

    if drop_unknown:
        known_internal: set[str] = set(schema.required_internal) | set(schema.optional_internal)
        cols_to_keep = [c for c in result.columns if c in known_internal]
        result = result[cols_to_keep]

    return result