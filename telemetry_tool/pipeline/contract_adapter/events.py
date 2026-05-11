"""Translate real-life pipeline quality/analysis artefacts into contract Events.

Events surface in the session view as a neutral timeline of detections --
invalid laps, joker laps, data-quality warnings, unexpected channels,
line-deviation outliers. Kept intentionally shallow: the rich analysis
object stays in the pipeline's analysis_json blob.
"""
from __future__ import annotations

from typing import Any

from telemetry_tool.web.schemas.contracts import Event

# Channels that must never appear for a real-life session (see F5).
_FORBIDDEN_NEEDLES: tuple[str, ...] = (
    "throttle", "brake", "steer", "wheel speed", "shock defl",
)


def _invalid(summary: dict[str, Any]) -> list[Event]:
    data = summary.get("invalid_lap_analysis") or {}
    reasons = data.get("reasons") or {}
    return [
        Event(
            event_type="lap.invalid",
            lap_number=int(lap),
            severity="medium",
            detector="invalid_lap_analyzer",
            payload={"reason": reasons.get(str(lap), "unspecified")},
        )
        for lap in (data.get("invalid_laps") or [])
    ]


def _incomplete(summary: dict[str, Any]) -> list[Event]:
    data = summary.get("incomplete_lap_analysis") or {}
    return [
        Event(
            event_type="lap.incomplete",
            lap_number=int(lap),
            severity="low",
            detector="incomplete_lap_analyzer",
            payload={},
        )
        for lap in (data.get("incomplete_laps") or [])
    ]


def _anomalous(summary: dict[str, Any]) -> list[Event]:
    data = summary.get("anomalous_lap_analysis") or {}
    return [
        Event(
            event_type="lap.anomalous",
            lap_number=int(lap),
            severity="low",
            detector="anomaly_detector",
            payload={},
        )
        for lap in (data.get("anomalous_laps") or [])
    ]


def _joker(summary: dict[str, Any]) -> list[Event]:
    data = summary.get("joker_detection_result") or {}
    lap = data.get("joker_lap")
    if lap is None:
        return []
    return [Event(
        event_type="lap.joker",
        lap_number=int(lap),
        severity="low",
        detector="joker_detector",
        payload={k: v for k, v in data.items() if k != "joker_lap"},
    )]


def _unexpected_channels(summary: dict[str, Any]) -> list[Event]:
    headers = summary.get("available_channels") or []
    out: list[Event] = []
    for h in headers:
        low = str(h).lower()
        if any(n in low for n in _FORBIDDEN_NEEDLES):
            out.append(Event(
                event_type="capability.unexpected_channel",
                severity="low",
                detector="contract_adapter",
                payload={"channel": str(h)},
            ))
    return out


def extract_events(summary: dict[str, Any]) -> list[Event]:
    return (
        _invalid(summary)
        + _incomplete(summary)
        + _anomalous(summary)
        + _joker(summary)
        + _unexpected_channels(summary)
    )
