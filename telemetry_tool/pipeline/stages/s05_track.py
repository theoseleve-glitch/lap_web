"""
Stage 05 — Track Detection + Context Persistence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Detect the track from GPS coordinates in the trimmed DataFrame,
then optionally persist the result into a SessionContext file.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


def run_track_detection(
    trimmed_df,
    meta: dict[str, Any],
    *,
    context: Any = None,
    output_dir: Optional[str] = None,
    driver_tag: str = "",
) -> tuple[Any, str]:
    """Detect track from GPS data.

    Parameters
    ----------
    trimmed_df : pd.DataFrame
        Session DataFrame after trim (must contain lat/lon columns).
    meta : dict
        Session metadata; checked for ``track_name`` / ``track_id``.
    context : SessionContext or None
        If provided (together with *output_dir*), the detected track_id
        is written back into the context and persisted to disk.
    output_dir : str or None
        Directory used when saving the session context.
    driver_tag : str
        Optional driver identifier (unused here but kept for API parity).

    Returns
    -------
    (track_match, track_id) : tuple
        *track_match* is the match object returned by the track-detection
        module, or ``None`` when the module is unavailable.
        *track_id* is a string identifier for the detected track.
    """
    track_mod = lazy_import("track_detection")
    if track_mod is None:
        track_id = meta.get("track_id", "unknown_track")
        logger.info("track_detection unavailable — using fallback track_id=%s", track_id)
        return None, track_id

    track_name = meta.get("track_name") or meta.get("track_id", "Unknown Track")

    match = track_mod.register_or_match_track(trimmed_df, track_name=track_name)
    track_id = match.track_id if match is not None else meta.get("track_id", "unknown_track")

    logger.info("Track detected: %s (id=%s)", track_name, track_id)

    # ── Persist into SessionContext if both handles are available ──
    if context is not None and output_dir is not None:
        _persist_context(context, track_id, output_dir)

    return match, track_id


def _persist_context(context: Any, track_id: str, output_dir: str) -> None:
    """Set *track_id* on *context* and save to *output_dir*."""
    context.track_id = track_id
    try:
        sc_mod = lazy_import("session_context")
        if sc_mod is not None:
            sc_mod.save_session_context(context, output_dir)
            logger.debug("SessionContext saved with track_id=%s", track_id)
    except Exception:
        logger.warning("Failed to save SessionContext after track detection", exc_info=True)
