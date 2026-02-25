"""
feature_schema.py
-----------------
Single source of truth for all feature, target, and metadata column
definitions used across feature_builder.py, ml_engine.py, and scoring.py.

Centralising column names here means:
  - Renaming a column requires one edit, not three.
  - Schema drift is caught at the boundary where data enters each module,
    not silently downstream when a KeyError surfaces mid-training.
  - Callers can import the lists directly to build pipelines without
    duplicating magic strings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

# -- -

# Column-name constants  (one definition per name – no magic strings)

# -- -


# -- Features
# Numerical / categorical inputs consumed by the model.

# Keep grouped by semantic category for readability; order is preserved and

# used by ml_engine.py when constructing the design matrix.


_F_LAP_TIME_S           = "lap_time_s"
_F_SECTOR_1_S           = "sector_1_s"
_F_SECTOR_2_S           = "sector_2_s"
_F_SECTOR_3_S           = "sector_3_s"
_F_TYRE_AGE_LAPS        = "tyre_age_laps"
_F_TYRE_COMPOUND        = "tyre_compound"          # categorical
_F_FUEL_LOAD_KG         = "fuel_load_kg"
_F_AIR_TEMP_C           = "air_temp_c"
_F_TRACK_TEMP_C         = "track_temp_c"
_F_HUMIDITY_PCT         = "humidity_pct"
_F_WIND_SPEED_MS        = "wind_speed_ms"
_F_TRACK_STATUS         = "track_status"           # categorical
_F_DRS_AVAILABLE        = "drs_available"          # bool / int flag
_F_ERS_DEPLOYED_PCT     = "ers_deployed_pct"
_F_GAP_AHEAD_S          = "gap_ahead_s"
_F_GAP_BEHIND_S         = "gap_behind_s"
_F_PIT_STOP_COUNT       = "pit_stop_count"
_F_STARTING_GRID_POS    = "starting_grid_pos"

# -- Targets -- -

# Labels / regression targets that the model predicts or that scoring

# computes post-race.  Not passed as features.


_T_FINISH_POS           = "finish_pos"
_T_RACE_TIME_S          = "race_time_s"
_T_POINTS_SCORED        = "points_scored"

# -- Metadata
# Identifiers and context columns carried through pipelines for traceability.

# Never used as model inputs or targets.


_M_RACE_ID              = "race_id"
_M_DRIVER_ID            = "driver_id"
_M_TEAM_ID              = "team_id"
_M_LAP_NUMBER           = "lap_number"
_M_SEASON               = "season"
_M_ROUND                = "round"
_M_TIMESTAMP            = "timestamp"

# -- -

# Public column lists

# -- -


FEATURE_COLUMNS: list[str] = [
    _F_LAP_TIME_S,
    _F_SECTOR_1_S,
    _F_SECTOR_2_S,
    _F_SECTOR_3_S,
    _F_TYRE_AGE_LAPS,
    _F_TYRE_COMPOUND,
    _F_FUEL_LOAD_KG,
    _F_AIR_TEMP_C,
    _F_TRACK_TEMP_C,
    _F_HUMIDITY_PCT,
    _F_WIND_SPEED_MS,
    _F_TRACK_STATUS,
    _F_DRS_AVAILABLE,
    _F_ERS_DEPLOYED_PCT,
    _F_GAP_AHEAD_S,
    _F_GAP_BEHIND_S,
    _F_PIT_STOP_COUNT,
    _F_STARTING_GRID_POS,
]

TARGET_COLUMNS: list[str] = [
    _T_FINISH_POS,
    _T_RACE_TIME_S,
    _T_POINTS_SCORED,
]

METADATA_COLUMNS: list[str] = [
    _M_RACE_ID,
    _M_DRIVER_ID,
    _M_TEAM_ID,
    _M_LAP_NUMBER,
    _M_SEASON,
    _M_ROUND,
    _M_TIMESTAMP,
]

# Convenience: every column the schema knows about.

ALL_COLUMNS: list[str] = FEATURE_COLUMNS + TARGET_COLUMNS + METADATA_COLUMNS


# -- -

# Schema validation

# -- -


class SchemaValidationError(ValueError):
    """
    Raised when a DataFrame does not satisfy the expected schema.

    Inherits from ValueError so callers that catch ValueError will still
    handle it, while code that needs to distinguish schema errors from other
    ValueErrors can catch this subclass specifically.
    """


def validate_schema(
    df: "pd.DataFrame",
    *,
    require_features: bool = True,
    require_targets: bool = False,
    require_metadata: bool = False,
    extra_columns_ok: bool = True,
) -> None:
    """
    Assert that *df* contains the expected columns.

    Parameters
    ----------
    df:
        The DataFrame to validate.
    require_features:
        When True (default), all FEATURE_COLUMNS must be present.
    require_targets:
        When True, all TARGET_COLUMNS must be present.
        False by default because targets are absent from inference DataFrames.
    require_metadata:
        When True, all METADATA_COLUMNS must be present.
        False by default to keep validation lightweight for intermediate frames.
    extra_columns_ok:
        When True (default), columns beyond the known schema are silently
        accepted.  Set to False to enforce a strict schema (e.g. during
        testing or data-contract checks).

    Raises
    ------
    TypeError
        If *df* is not a pandas DataFrame.
    SchemaValidationError
        If any required columns are missing, or if unexpected columns are
        present when *extra_columns_ok* is False.  The error message lists
        every offending column so the caller can fix the root cause without
        running the check a second time.
    """
    # -- Type guard
    # Import here to keep the module importable without pandas installed

    # (e.g. in environments that only need the column-name constants).

    try:
        import pandas as pd  # noqa: PLC0415
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ImportError(
            "pandas is required to call validate_schema()."
        ) from exc

    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"validate_schema() expects a pandas DataFrame, "
            f"got {type(df).__name__!r}."
        )

    actual: set[str] = set(df.columns)
    errors: list[str] = []

    # -- Missing-column checks -- -

    def _check_missing(required: list[str], label: str) -> None:
        missing = sorted(set(required) - actual)
        if missing:
            errors.append(
                f"Missing {label} column(s) [{len(missing)}]: "
                + ", ".join(missing)
            )

    if require_features:
        _check_missing(FEATURE_COLUMNS, "feature")
    if require_targets:
        _check_missing(TARGET_COLUMNS, "target")
    if require_metadata:
        _check_missing(METADATA_COLUMNS, "metadata")

    # -- Unexpected-column check -- -

    if not extra_columns_ok:
        unexpected = sorted(actual - set(ALL_COLUMNS))
        if unexpected:
            errors.append(
                f"Unexpected column(s) not in schema [{len(unexpected)}]: "
                + ", ".join(unexpected)
            )

    # -- Raise once with a consolidated message
    if errors:
        header = (
            f"Schema validation failed for DataFrame "
            f"(shape {df.shape[0]} rows × {df.shape[1]} cols):"
        )
        full_message = header + "\n  " + "\n  ".join(errors)
        raise SchemaValidationError(full_message)


# -- -

# Convenience accessors

# -- -


def feature_columns() -> list[str]:
    """Return a copy of FEATURE_COLUMNS (safe to mutate)."""
    return list(FEATURE_COLUMNS)


def target_columns() -> list[str]:
    """Return a copy of TARGET_COLUMNS (safe to mutate)."""
    return list(TARGET_COLUMNS)


def metadata_columns() -> list[str]:
    """Return a copy of METADATA_COLUMNS (safe to mutate)."""
    return list(METADATA_COLUMNS)


# -- -

# Quick self-test / debug entry-point

# -- -


if __name__ == "__main__":  # pragma: no cover
    import pandas as pd

    print(f"Feature columns  ({len(FEATURE_COLUMNS)}): {FEATURE_COLUMNS}")
    print(f"Target columns   ({len(TARGET_COLUMNS)}):  {TARGET_COLUMNS}")
    print(f"Metadata columns ({len(METADATA_COLUMNS)}): {METADATA_COLUMNS}")

    # Happy path – a DataFrame with all required columns passes silently.

    good_df = pd.DataFrame(columns=ALL_COLUMNS)
    validate_schema(good_df, require_features=True, require_targets=True, require_metadata=True)
    print("\n✓ Full-schema validation passed.")

    # Demonstrate the error message on a bad DataFrame.

    bad_df = pd.DataFrame(columns=["lap_time_s", "unknown_col"])
    try:
        validate_schema(bad_df, require_features=True, extra_columns_ok=False)
    except SchemaValidationError as exc:
        print(f"\n✗ Caught expected SchemaValidationError:\n{exc}")