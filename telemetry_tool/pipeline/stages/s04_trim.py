"""
Stage 04 -- Session Trimming (remove outlaps, waiting periods).

Removes non-representative portions of the session such as outlaps,
inlaps, and idle/waiting periods so that downstream analysis operates
only on meaningful driving data.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


def run_trim(
    df: pd.DataFrame,
    *,
    session_type: str = "practice",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Trim session.

    Parameters
    ----------
    df:
        Enriched DataFrame (output of stage 03).
    session_type:
        Session type hint forwarded to ``session_trimming.trim_session``
        (e.g. ``"practice"``, ``"qualifying"``, ``"race"``).

    Returns
    -------
    (trimmed_df, trim_report)
        *trimmed_df* is the trimmed DataFrame.  *trim_report* is a dict
        with trimming details from the module, or a note if the module
        is absent.
    """
    trim_mod = lazy_import("session_trimming")
    if trim_mod is None:
        trim_mod = lazy_import("telemetry_tool.session_trimming")
    if trim_mod is None:
        logger.info("Session trimming skipped (module absent).")
        return df, {"note": "session_trimming absent"}

    try:
        return trim_mod.trim_session(df, session_type=session_type)
    except Exception as exc:
        logger.warning("Session trimming failed: %s — returning untrimmed data", exc)
        return df, {"error": str(exc)}
