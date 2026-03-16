"""Stage 14: Detect pit stops and create stint boundaries."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def run_endurance_detection(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Detect pit laps from lap metrics, store stint boundaries.

    Uses the default pit threshold (120s). User can reconfigure later
    via the /stints/configure API endpoint.
    """
    lap_metrics = summary.get("lap_metrics") or []
    if not lap_metrics or len(lap_metrics) < 3:
        return None

    lap_times: dict[int, float] = {}
    for lm in lap_metrics:
        ln = lm.get("lap_number")
        lt = lm.get("lap_time_s")
        if ln is not None and lt is not None and lt > 0:
            lap_times[ln] = lt

    if len(lap_times) < 3:
        return None

    from web.repos.endurance_repo import detect_and_store_stints, DEFAULT_PIT_THRESHOLD_S
    from web.db import get_db_connection

    conn = get_db_connection()
    session_id = summary.get("session_id")
    if not session_id:
        return None

    stints = detect_and_store_stints(conn, session_id, lap_times, DEFAULT_PIT_THRESHOLD_S)

    if len(stints) <= 1:
        logger.info("No pit stops detected for session %s", session_id)
        return None

    logger.info("Detected %d stints for session %s", len(stints), session_id)
    return {"n_stints": len(stints), "stints": stints}
