"""
Stage 06 — Lap Segmentation + Distance Integrity
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Split the trimmed session DataFrame into per-lap DataFrames and
run distance-integrity preflight checks on the result.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from pipeline.helpers import _COL_LAP, PipelineError, lazy_import

logger = logging.getLogger(__name__)

# Possible column names for the lap number, in priority order.
_LAP_COL_CANDIDATES = (_COL_LAP, "lap_number")


# ── Lap segmentation ────────────────────────────────────────────────


def run_segment_laps(
    trimmed_df: pd.DataFrame,
    *,
    lap_range: Optional[tuple[int, int]] = None,
) -> dict[int, pd.DataFrame]:
    """Segment *trimmed_df* into per-lap DataFrames.

    Parameters
    ----------
    trimmed_df : pd.DataFrame
        Session data that has already been trimmed/cleaned.
    lap_range : (start, end) or None
        If given, only laps whose number falls in
        ``start <= lap_num <= end`` are kept.

    Returns
    -------
    dict[int, pd.DataFrame]
        Mapping of ``{lap_number: DataFrame}``.  Each DataFrame is
        reset-indexed.

    Raises
    ------
    PipelineError
        If the lap column is missing or no laps remain after filtering.
    """
    # Resolve lap column name
    lap_col_name: Optional[str] = None
    for candidate in _LAP_COL_CANDIDATES:
        if candidate in trimmed_df.columns:
            lap_col_name = candidate
            break

    if lap_col_name is None:
        raise PipelineError(f"Column '{_COL_LAP}' missing.")

    lap_col = pd.to_numeric(trimmed_df[lap_col_name], errors="coerce")

    # Group by lap number
    lap_dict: dict[int, pd.DataFrame] = {}
    for lap_num, grp in trimmed_df.groupby(lap_col, sort=True):
        if pd.isna(lap_num):
            continue
        lap_num_int = int(lap_num)

        # Apply optional range filter
        if lap_range is not None:
            lo, hi = lap_range
            if lap_num_int < lo or lap_num_int > hi:
                continue

        lap_dict[lap_num_int] = grp.reset_index(drop=True)

    if not lap_dict:
        raise PipelineError("No laps remain after segmentation.")

    logger.info("Segmented %d laps (range=%s)", len(lap_dict), lap_range)
    return lap_dict


# ── Distance integrity preflight ────────────────────────────────────


def run_distance_integrity(
    lap_dict: dict[int, pd.DataFrame],
) -> tuple[dict[int, pd.DataFrame], Any]:
    """Run distance-integrity preflight on *lap_dict*.

    Parameters
    ----------
    lap_dict : dict[int, pd.DataFrame]
        Per-lap DataFrames produced by :func:`run_segment_laps`.

    Returns
    -------
    (lap_dict, distance_quality) : tuple
        The (possibly repaired) lap dict and a quality report object.
        If the ``distance_integrity`` module is unavailable,
        *distance_quality* is ``None``.
    """
    di_mod = lazy_import("distance_integrity")
    if di_mod is None:
        logger.info("distance_integrity unavailable — skipping preflight")
        return lap_dict, None

    result = di_mod.run_distance_integrity(lap_dict)
    logger.info("Distance integrity check complete")
    return result
