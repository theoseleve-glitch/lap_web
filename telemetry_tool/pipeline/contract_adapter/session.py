"""Build a SessionContract from orchestrator summary + Celery ContextRef.

This module is populated across Tasks 3-6. Task 3: laps + scores.
Task 4 appends metadata builders; Task 6 adds `build_session_contract`.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from telemetry_tool.pipeline.contract_adapter._types import ContextRef
from telemetry_tool.pipeline.contract_adapter.events import extract_events
from telemetry_tool.web.schemas.contracts import (
    DriverRef,
    LapSummary,
    Scores,
    SessionCapabilities,
    SessionContract,
    TrackRef,
    VehicleRef,
)
from telemetry_tool.web.schemas.contracts.common import SourceLiteral

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


# --- SessionContract composition ------------------------------------------


def _build_data_profile(summary: dict[str, Any]) -> dict[str, Any]:
    """Free-form profiler-style dict describing how the session was parsed.

    Keep the shape narrow and additive — W2's profiler is the formal owner
    of this field. For real-life this is a best-effort reflection of the
    adapter layer so downstream consumers have *something* to display
    before the W2 profiler lands.
    """
    prof: dict[str, Any] = {
        "parser": "real_life_pipeline",
        "source_format": summary.get("source_format"),
        "data_tier": summary.get("data_tier"),
        "channels_detected": len(summary.get("available_channels") or []),
    }
    dq = summary.get("data_quality")
    if isinstance(dq, dict):
        prof["quality_overall"] = dq.get("overall_confidence")
    elif dq is not None and hasattr(dq, "overall_confidence"):
        prof["quality_overall"] = dq.overall_confidence
    return {k: v for k, v in prof.items() if v is not None}


def build_session_contract(
    summary: dict[str, Any],
    ctx: ContextRef,
    capabilities: SessionCapabilities,
) -> SessionContract:
    meta = dict(summary.get("session_meta") or {})
    return SessionContract(
        session_id=ctx.session_id,
        workspace_id=ctx.workspace_id,
        source=SourceLiteral.REAL_LIFE,
        capabilities=capabilities,
        data_profile=_build_data_profile(summary),
        driver=build_driver(meta),
        track=build_track(summary),
        vehicle=build_vehicle(meta),
        session_start=resolve_session_start(meta),
        duration_s=resolve_duration_s(summary.get("lap_times")),
        laps=build_laps(summary),
        events=extract_events(summary),
        scores=build_scores(summary.get("score_result")),
        sidecar=None,
    )
