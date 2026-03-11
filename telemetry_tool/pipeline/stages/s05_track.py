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

    # Compute fingerprint (needed for upsert_track in the DB)
    fingerprint = track_mod.compute_track_fingerprint(trimmed_df)

    result = track_mod.register_or_match_track(trimmed_df, track_name=track_name)
    # register_or_match_track returns (MatchResult, database_list)
    if isinstance(result, tuple):
        match_result, _db = result
    else:
        match_result = result

    track_id = match_result.track_id if match_result is not None else meta.get("track_id", "unknown_track")
    matched_name = getattr(match_result, "track_name", track_name)

    logger.info("Track detected: %s (id=%s, matched=%s, new=%s)",
                matched_name, track_id,
                getattr(match_result, "matched", None),
                getattr(match_result, "is_new", None))

    # Build a rich dict the orchestrator can pass to upsert_track.
    # MatchResult.to_dict() has {track_id, track_name, ...} but lacks
    # the fingerprint geometry that upsert_track needs for the DB row.
    track_info = match_result.to_dict() if hasattr(match_result, "to_dict") else {}
    track_info["fingerprint"] = fingerprint.to_dict()

    # ── Persist into SessionContext if both handles are available ──
    if context is not None and output_dir is not None:
        _persist_context(context, track_id, output_dir)

    return track_info, track_id


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
