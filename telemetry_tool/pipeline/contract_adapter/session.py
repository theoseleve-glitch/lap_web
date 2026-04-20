"""Build a SessionContract from orchestrator summary + Celery ContextRef.

This module is populated across Tasks 3-6. Task 3: laps + scores.
Task 4 appends metadata builders; Task 6 adds `build_session_contract`.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from telemetry_tool.web.schemas.contracts import (
    DriverRef,
    LapSummary,
    Scores,
    TrackRef,
    VehicleRef,
)

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


# --- metadata builders -----------------------------------------------------


def build_driver(meta: dict[str, Any]) -> DriverRef:
    return DriverRef(
        driver_id=int(meta.get("driver_id") or 0),
        name=str(meta.get("driver_name") or "Unknown")[:100],
    )


def build_track(summary: dict[str, Any]) -> TrackRef:
    tm = summary.get("track_match")
    if isinstance(tm, dict) and tm:
        return TrackRef(
            track_id=int(tm.get("track_row_id") or 0),
            name=str(tm.get("track_name") or summary.get("track_id") or "unknown")[:200],
            layout=(tm.get("layout") or None),
        )
    return TrackRef(
        track_id=0,
        name=str(summary.get("track_id") or "unknown")[:200],
        layout=None,
    )


def build_vehicle(meta: dict[str, Any]) -> VehicleRef:
    kart_id = meta.get("kart_id")
    if kart_id is not None:
        return VehicleRef(
            vehicle_id=int(kart_id),
            vehicle_class="kart",
            model=(str(meta.get("kart_name"))[:100] if meta.get("kart_name") else None),
        )
    v_id = meta.get("vehicle_id")
    return VehicleRef(
        vehicle_id=(int(v_id) if v_id is not None else None),
        vehicle_class=(meta.get("vehicle_class") or None),
        model=(meta.get("vehicle_model") or None),
    )


def resolve_session_start(meta: dict[str, Any]) -> datetime:
    raw = meta.get("session_datetime") or meta.get("date")
    if isinstance(raw, str) and raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def resolve_duration_s(lap_times: list[Any] | None) -> float:
    if not lap_times:
        return 0.0
    total = 0.0
    for t in lap_times:
        if isinstance(t, (int, float)) and math.isfinite(t) and t > 0:
            total += float(t)
    return total
