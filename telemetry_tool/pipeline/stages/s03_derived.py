"""
Stage 03 -- Derived Channels (longitudinal/lateral accel, yaw rate, elevation).

Computes additional physical channels from the filtered GPS/IMU data:
grade (elevation) profile with quality assessment, longitudinal
acceleration (optionally slope-corrected), lateral acceleration from
XY coordinates, and yaw rate from heading.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


def run_derived_channels(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, Optional[str]]:
    """Compute derived channels.

    Parameters
    ----------
    df:
        Filtered DataFrame (output of stage 02).

    Returns
    -------
    (enriched_df, grade_status)
        *enriched_df* has additional columns for longitudinal/lateral
        acceleration and yaw rate.  *grade_status* is one of
        ``"grade_used"``, ``"grade_low_confidence"``,
        ``"grade_unavailable"``, or ``None`` if the module is absent.
    """
    dc_mod = lazy_import("derived_channels")
    if dc_mod is None:
        dc_mod = lazy_import("telemetry_tool.derived_channels")
    if dc_mod is None:
        logger.info("Derived channels skipped (module absent).")
        return df, None

    # ── Grade quality check + elevation profile ──────────────────
    grade_status: str = "grade_unavailable"
    do_slope_correct = False

    if hasattr(dc_mod, "compute_elevation_profile_with_quality"):
        try:
            grade_series, grade_status = (
                dc_mod.compute_elevation_profile_with_quality(df)
            )
            if grade_status == "grade_used":
                df = df.copy()
                df[dc_mod.OUT_GRADE_PCT] = grade_series.values
                do_slope_correct = True
            elif grade_status == "grade_low_confidence":
                df = df.copy()
                df[dc_mod.OUT_GRADE_PCT] = grade_series.values
                # Still compute grade column but don't use for correction
        except Exception as exc:
            logger.warning("Grade estimation failed: %s", exc)

    # ── Longitudinal acceleration (with optional slope correction) ─
    try:
        df = dc_mod.compute_longitudinal_accel(
            df, correct_for_slope=do_slope_correct,
        )
    except Exception as exc:
        logger.warning("Longitudinal accel computation failed: %s", exc)

    # ── Lateral acceleration from XY ─────────────────────────────
    try:
        df = dc_mod.compute_lateral_accel_from_xy(df)
    except Exception as exc:
        logger.warning("Lateral accel computation failed: %s", exc)

    # ── Yaw rate from heading ────────────────────────────────────
    try:
        df = dc_mod.compute_yaw_rate_from_heading(df)
    except Exception as exc:
        logger.warning("Yaw rate computation failed: %s", exc)

    return df, grade_status
