"""
Stage 07 — Resampling + Corner Detection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Resample all laps to a uniform distance grid and detect / classify
corners from the resampled data.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


# ── Resampling ───────────────────────────────────────────────────────


def run_resample(
    lap_dict: dict[int, pd.DataFrame],
    *,
    n_points: int = 1000,
) -> dict[int, pd.DataFrame]:
    """Resample all laps to a uniform distance grid.

    Parameters
    ----------
    lap_dict : dict[int, pd.DataFrame]
        Per-lap DataFrames (from segmentation).
    n_points : int
        Number of equi-spaced points per lap.

    Returns
    -------
    dict[int, pd.DataFrame]
        Resampled per-lap DataFrames.

    Raises
    ------
    ImportError
        If the ``resampling`` module is not available.
    """
    resamp_mod = lazy_import("resampling")
    if resamp_mod is None:
        raise ImportError("resampling unavailable")

    resampled = resamp_mod.resample_all_laps(lap_dict, n_points=n_points)
    logger.info("Resampled %d laps to %d points each", len(resampled), n_points)
    return resampled


# ── Corner detection ─────────────────────────────────────────────────


def run_corner_detection(
    resampled_laps: dict[int, pd.DataFrame],
) -> list[dict[str, Any]]:
    """Detect corners from the first resampled lap.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        Resampled per-lap DataFrames.

    Returns
    -------
    list[dict]
        Detected corner descriptors, or ``[]`` if the module is
        unavailable or the input is empty.
    """
    corner_mod = lazy_import("corner_detection")
    if corner_mod is None:
        logger.info("corner_detection unavailable — returning empty corners")
        return []

    if not resampled_laps:
        return []

    first_key = sorted(resampled_laps.keys())[0]
    corners = corner_mod.detect_corners(resampled_laps[first_key])
    logger.info("Detected %d corners from lap %s", len(corners), first_key)
    return corners


# ── Corner classification ────────────────────────────────────────────


def classify_corners(
    corners: list[dict[str, Any]],
    resampled_laps: dict[int, pd.DataFrame],
    corner_mod: Any,
) -> Optional[list[dict[str, Any]]]:
    """Classify corner types, detect compound corners, identify setup corners.

    Modifies *corners* in-place (adds type/compound/setup flags).

    Parameters
    ----------
    corners : list[dict]
        Corner descriptors from :func:`run_corner_detection`.
    resampled_laps : dict[int, pd.DataFrame]
        Resampled per-lap DataFrames.
    corner_mod : module
        The ``corner_detection`` module (already imported by caller).

    Returns
    -------
    list[dict] or None
        Compound corner groups from ``detect_compound_corners``,
        or ``None`` if classification is unavailable or fails.
    """
    if not corners or not resampled_laps:
        return None

    first_key = sorted(resampled_laps.keys())[0]
    first_lap = resampled_laps[first_key]

    # 1. Classify corner types (hairpin, chicane, sweeper, etc.)
    try:
        if hasattr(corner_mod, "classify_corner_types"):
            corner_mod.classify_corner_types(corners, first_lap)
            logger.debug("Corner types classified")
    except Exception:
        logger.warning("classify_corner_types failed", exc_info=True)

    # 2. Detect compound corners (linked sequences)
    compound_groups: Optional[list[dict[str, Any]]] = None
    try:
        if hasattr(corner_mod, "detect_compound_corners"):
            compound_groups = corner_mod.detect_compound_corners(corners, first_lap)
            logger.debug(
                "Compound corners: %d groups",
                len(compound_groups) if compound_groups else 0,
            )
    except Exception:
        logger.warning("detect_compound_corners failed", exc_info=True)

    # 3. Identify setup corners (corners where entry determines exit speed)
    try:
        if hasattr(corner_mod, "identify_setup_corners"):
            corner_mod.identify_setup_corners(corners, first_lap)
            logger.debug("Setup corners identified")
    except Exception:
        logger.warning("identify_setup_corners failed", exc_info=True)

    return compound_groups
