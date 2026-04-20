"""Build a SessionContract from orchestrator summary + Celery ContextRef.

This module is populated across Tasks 3-6. Task 3: laps + scores.
Task 4 appends metadata builders; Task 6 adds `build_session_contract`.
"""
from __future__ import annotations

import logging
import math
from typing import Any

from telemetry_tool.web.schemas.contracts import LapSummary, Scores

logger = logging.getLogger(__name__)


def build_laps(summary: dict[str, Any]) -> list[LapSummary]:
    lap_times: list[Any] = summary.get("lap_times") or []
    best_key = summary.get("best_lap_key")
    invalid_set = set((summary.get("invalid_lap_analysis") or {}).get("invalid_laps") or [])
    incomplete_set = set((summary.get("incomplete_lap_analysis") or {}).get("incomplete_laps") or [])

    laps: list[LapSummary] = []
    for idx, t in enumerate(lap_times, start=1):
        flags: list[str] = []
        if t is None or not isinstance(t, (int, float)) or not math.isfinite(t) or t <= 0:
            flags.append("incomplete")
            is_valid = False
            lap_time: float | None = None
        else:
            is_valid = idx not in invalid_set
            lap_time = float(t)
        if idx in invalid_set:
            flags.append("invalid")
        if idx in incomplete_set and "incomplete" not in flags:
            flags.append("incomplete")
        laps.append(LapSummary(
            lap_number=idx,
            lap_time_s=lap_time,
            is_valid=is_valid,
            is_best=(best_key is not None and idx == int(best_key)),
            flags=flags,
        ))
    return laps


def build_scores(score_result: dict[str, Any] | None) -> Scores | None:
    if not score_result:
        return None
    sub = score_result.get("scores") or {}
    try:
        return Scores(
            pace=float(sub.get("pace") or 0.0),
            consistency=float(sub.get("consistency") or 0.0),
            execution=float(sub.get("execution") or 0.0),
            robustness=float(sub.get("robustness") or 0.0),
            overall=float(score_result.get("total_score") or 0.0),
        )
    except Exception:
        logger.exception("scores mapping failed; returning None for safety")
        return None
