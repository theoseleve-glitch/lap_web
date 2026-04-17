"""
track_surface.prescriptive.adapters
===================================

Adapters from upstream data shapes into internal research types.

This is the ONLY layer that touches the leaky upstream dict keys
(``behavior_id``, ``corners_observed``, ``evidence.min_speed_delta_kph`` …).
A rename upstream fails HERE — the rest of the engine stays type-safe.

Upstream sources
----------------
- ``session_compare.CornerPacket`` (dataclass), serialised to dicts by
  ``scripts/build_ok_raw.py`` before reaching us.
- ``driver_development.DevelopmentIntelligence.recurring_weaknesses`` — list
  of dicts emitted by ``driver_development._pat`` (``behavior_id``, ``label``,
  ``occurrence_count``, ``trend``, ``estimated_time_cost_ms``, ``confidence``,
  ``corners_observed``, ``archetypes_observed``, ``sessions_observed``).

Missing or malformed fields degrade to ``None`` (for Optional fields) or safe
defaults (for required fields). They never silently become 0 for a required
field — required fields always have a safe non-zero interpretation (e.g.,
``confidence = 0.0`` means "explicitly no confidence", not "unset").
"""
from __future__ import annotations

from typing import Any, Iterable

from track_surface.prescriptive._internal import Evidence, WeaknessContext


# ── Corner packet → Evidence ────────────────────────────────────

def evidence_from_corner_packet_dict(pkt: dict[str, Any]) -> Evidence:
    """Build an ``Evidence`` from a corner-packet dict.

    Required dict keys: ``corner_id``. All others default to safe values.
    Evidence-nested optional fields become ``None`` when missing so
    patterns can distinguish absence from zero.
    """
    ev = pkt.get("evidence") or {}
    return Evidence(
        corner_id=int(pkt["corner_id"]),
        time_delta_ms=float(pkt.get("time_delta_ms", 0.0) or 0.0),
        primary_cause=str(pkt.get("primary_cause", "unknown")),
        confidence=float(pkt.get("confidence", 0.0) or 0.0),
        s_entry_m=_float_or_none(pkt.get("s_entry_m")),
        s_apex_m=_float_or_none(pkt.get("s_apex_m")),
        s_exit_m=_float_or_none(pkt.get("s_exit_m")),
        min_speed_delta_kph=_float_or_none(ev.get("min_speed_delta_kph")),
        brake_point_delta_m=_float_or_none(ev.get("brake_point_delta_m")),
        throttle_pickup_delta_m=_float_or_none(ev.get("throttle_pickup_delta_m")),
        exit_speed_delta_kph=_float_or_none(ev.get("exit_speed_delta_kph")),
        line_deviation_rms_m=_float_or_none(ev.get("line_deviation_rms_m")),
    )


def evidence_list_from_packets(packets: Iterable[dict[str, Any]]) -> list[Evidence]:
    return [evidence_from_corner_packet_dict(p) for p in packets]


# ── Weakness dict → WeaknessContext ─────────────────────────────

def weakness_context_from_dict(
    w: dict[str, Any], *, sessions_analyzed: int,
) -> WeaknessContext:
    """Build a ``WeaknessContext`` from an upstream weakness dict.

    Required key: ``behavior_id``. All other fields have safe defaults;
    this matches legacy ``_build_prescriptions`` tolerance so the Phase-3
    swap does not change which weaknesses flow through.

    ``sessions_analyzed`` is an engine-level count and MUST be supplied
    explicitly — defaulting it would hide a degraded state.
    """
    return WeaknessContext(
        key=str(w["behavior_id"]),
        label=str(w.get("label", "")),
        occurrence_count=int(w.get("occurrence_count", 0) or 0),
        trend=str(w.get("trend", "unknown")),
        estimated_time_cost_ms=float(w.get("estimated_time_cost_ms", 0.0) or 0.0),
        confidence=float(w.get("confidence", 0.0) or 0.0),
        corners_observed=tuple(int(c) for c in (w.get("corners_observed") or ())),
        archetypes_observed=tuple(str(a) for a in (w.get("archetypes_observed") or ())),
        sessions_observed=tuple(str(s) for s in (w.get("sessions_observed") or ())),
        sessions_analyzed=int(sessions_analyzed),
    )


def context_list_from_weaknesses(
    weaknesses: Iterable[dict[str, Any]],
    *,
    sessions_analyzed: int,
) -> list[WeaknessContext]:
    return [
        weakness_context_from_dict(w, sessions_analyzed=sessions_analyzed)
        for w in weaknesses
    ]


# ── helpers ─────────────────────────────────────────────────────

def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
