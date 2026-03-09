"""
Stage 02 -- GPS Quality Filtering + Sensor Fusion (EKF).

Applies GPS quality filtering to remove noisy or low-satellite samples,
then optionally runs an Extended Kalman Filter for sensor fusion when
the ``fusion_ekf`` module is available.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


def run_filter(
    df: pd.DataFrame,
    *,
    filter_profile: Any = None,
) -> pd.DataFrame:
    """Filter GPS quality.

    Parameters
    ----------
    df:
        Raw (or column-discovered) DataFrame from the ingest stage.
    filter_profile:
        Optional filter profile forwarded to ``gps_filtering.filter_gps_quality``.

    Returns
    -------
    pd.DataFrame
        Filtered DataFrame.  Returns *df* unchanged if the module is
        absent or filtering fails.
    """
    gps_mod = lazy_import("gps_filtering")
    if gps_mod is None:
        gps_mod = lazy_import("telemetry_tool.gps_filtering")
    if gps_mod is None:
        logger.info("GPS filtering skipped (module absent).")
        return df

    try:
        return gps_mod.filter_gps_quality(df, filter_profile=filter_profile)
    except Exception as exc:
        logger.warning("GPS filtering failed: %s — returning unfiltered data", exc)
        return df


def run_sensor_fusion(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, Optional[Any]]:
    """Run EKF sensor fusion if available.

    Parameters
    ----------
    df:
        Filtered DataFrame from ``run_filter``.

    Returns
    -------
    (fused_df, fusion_meta)
        *fused_df* is the DataFrame after sensor fusion (or original *df*
        if fusion is unavailable).  *fusion_meta* is a metadata object
        from the fusion module, or ``None``.
    """
    fusion_mod = lazy_import("fusion_ekf")
    if fusion_mod is None:
        fusion_mod = lazy_import("telemetry_tool.fusion_ekf")
    if fusion_mod is None:
        logger.info("fusion_ekf module absent; skipping sensor fusion.")
        return df, None

    try:
        fused_df, fusion_meta = fusion_mod.run_sensor_fusion(df)
        return fused_df, fusion_meta
    except Exception as exc:
        logger.warning("Sensor fusion failed: %s — returning unmodified data", exc)
        return df, None
