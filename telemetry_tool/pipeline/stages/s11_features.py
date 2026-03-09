"""
Stage 11 — Build Feature Dataset
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Construct a feature DataFrame from lap metrics and delta segments
for downstream ML training and anomaly detection.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


def run_build_features(
    lap_metrics: list[dict[str, Any]],
    delta_segments: Optional[list[dict[str, Any]]],
    track_id: str,
    meta: dict[str, Any],
    *,
    context: Any = None,
    lap_to_phase: Optional[dict[int, int]] = None,
) -> pd.DataFrame:
    """Build feature DataFrame for ML.

    Parameters
    ----------
    lap_metrics : list[dict]
        Per-lap metric dicts from the analysis pipeline.
    delta_segments : list[dict] or None
        Delta-segment dicts (with optional ``cause_details`` sub-dicts).
    track_id : str
        Identifier for the track.
    meta : dict
        Session metadata (driver_name, track_state, session_id, etc.).
    context : SessionContext or None
        Optional session context for phase-aware features.
    lap_to_phase : dict[int, int] or None
        Mapping of lap number to condition-phase index.

    Returns
    -------
    pd.DataFrame
        Feature dataset suitable for ML training / anomaly detection.

    Raises
    ------
    ImportError
        If the ``feature_builder`` module is unavailable.
    """
    fb_mod = lazy_import("feature_builder")
    if fb_mod is None:
        raise ImportError("feature_builder unavailable")

    lap_df = pd.DataFrame(lap_metrics)

    seg_df: Optional[pd.DataFrame] = None
    if delta_segments:
        flat_rows: list[dict[str, Any]] = []
        for seg in delta_segments:
            row = dict(seg)
            cd = seg.get("cause_details")
            if isinstance(cd, dict):
                row.update(cd)
            flat_rows.append(row)
        if flat_rows:
            seg_df = pd.DataFrame(flat_rows)

    metadata = {
        "track_id": track_id,
        "track_state": meta.get("track_state", "dry"),
        "driver_name": meta.get("driver_name", "Unknown"),
        "session_id": meta.get("session_id", ""),
    }

    feature_df = fb_mod.build_feature_dataset(
        lap_df,
        seg_df,
        metadata,
        context=context,
        lap_to_phase=lap_to_phase,
    )
    logger.info("Built feature dataset: %d rows, %d columns", len(feature_df), len(feature_df.columns))
    return feature_df
