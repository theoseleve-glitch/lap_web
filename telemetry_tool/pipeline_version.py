"""Pipeline processing version tracking.

Tracks the current pipeline version so sessions processed with an older
version can be identified and re-processed when the pipeline evolves.
"""

from __future__ import annotations

from typing import Optional

PIPELINE_VERSION: int = 1


def is_stale(session_version: Optional[int]) -> bool:
    """Return True if a session was processed with an older pipeline version.

    Treats None as version 0 (never processed / legacy session).
    """
    return (session_version or 0) < PIPELINE_VERSION
