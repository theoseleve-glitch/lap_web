"""Pipeline processing version tracking.

Tracks the current pipeline version so sessions processed with an older
version can be identified and re-processed when the pipeline evolves.

Bump PIPELINE_VERSION whenever the pipeline produces materially different
results (new scoring formula, changed step order, etc.).  The structural
hash in pipeline_status.py changes automatically when steps are
added/removed/renamed.
"""

from __future__ import annotations

from typing import Optional

# 3: distance frame rebased to 0-based per-lap metres in
#    resampling.resample_lap_by_distance. All prior sessions carry corner
#    spans, grip maps and reference lines built in the old absolute frame
#    and must be reprocessed.
PIPELINE_VERSION: int = 3


def is_stale(session_version: Optional[int]) -> bool:
    """Return True if a session was processed with an older pipeline version.

    Treats None as version 0 (never processed / legacy session).
    """
    return (session_version or 0) < PIPELINE_VERSION


def full_version_string() -> str:
    """Return the full version string (e.g. ``v2-a3f8b2c1``)."""
    from pipeline_status import compute_pipeline_version_string
    return compute_pipeline_version_string()
