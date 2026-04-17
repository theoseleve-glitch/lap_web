"""
track_surface.prescriptive._internal
====================================

RESEARCH LAYER — internal-only types.

These classes live behind the engine boundary. They:
    - describe what upstream emits per-weakness (``WeaknessContext``)
    - describe what patterns see per-corner (``Evidence``)
    - describe what patterns return (``PatternResult`` sum type)

They MUST NOT appear in:
    - the public namespace of ``track_surface.prescriptive`` (enforced by test)
    - any serialised output (published DTOs in ``types.py``)
    - any frontend package

Design invariant — FOUR distinct states per pattern evaluation
--------------------------------------------------------------
The brief explicitly calls for separating "pattern detected" from
"data insufficient". This module models the full four-way split so the
engine cannot silently collapse any state into another:

    Detected        : pattern registered AND evidence triggered
    NotTriggered    : pattern registered AND evidence sufficient AND nothing fired
    Insufficient    : pattern registered BUT required evidence fields missing
    Unregistered    : upstream emitted a weakness_key the registry does not know
                      (emitted by the engine, not by any pattern)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from track_surface.prescriptive.types import PhaseTag, Severity


# ── Weakness context (upstream-per-weakness) ────────────────────

@dataclass(frozen=True)
class WeaknessContext:
    """Per-weakness metadata passed to every ``Pattern.evaluate()`` call.

    Constructed by the engine (Phase 3) from upstream's
    ``DevelopmentIntelligence.recurring_weaknesses``. Every field is populated
    — no Optionals — because the adapter is responsible for flagging malformed
    upstream data as ``Unregistered`` or ``Insufficient`` at the engine layer,
    not for passing half-built contexts to patterns.
    """
    key: str
    label: str
    occurrence_count: int
    trend: str
    estimated_time_cost_ms: float
    confidence: float  # [0.0, 1.0]
    corners_observed: tuple[int, ...]
    archetypes_observed: tuple[str, ...]
    sessions_observed: tuple[str, ...]
    sessions_analyzed: int  # engine-level total; stamped by the engine


# ── Evidence primitive (upstream-per-corner) ───────────────────

@dataclass(frozen=True)
class Evidence:
    """Normalised per-corner evidence snapshot passed to every pattern.

    Fields are ``Optional`` where the upstream signal can legitimately be
    absent (e.g., no brake pressure sensor → ``brake_point_delta_m = None``).
    Absent fields must surface as ``Insufficient`` results from the matching
    pattern, never as silent zeros.

    This type replaces the ``dict`` shape the legacy module consumes
    (``corner_packets[i]['evidence']``) — adapters (Phase 3) are the only code
    that constructs ``Evidence`` instances.
    """
    corner_id: int
    time_delta_ms: float
    primary_cause: str
    confidence: float  # [0.0, 1.0]
    s_entry_m: Optional[float]
    s_apex_m: Optional[float]
    s_exit_m: Optional[float]
    min_speed_delta_kph: Optional[float]
    brake_point_delta_m: Optional[float]
    throttle_pickup_delta_m: Optional[float]
    exit_speed_delta_kph: Optional[float]
    line_deviation_rms_m: Optional[float]


# ── Pattern result sum type (tagged union) ─────────────────────

@dataclass(frozen=True)
class Detected:
    """Pattern is registered AND evidence triggered it.

    Carries the full prescription content the engine lifts into
    ``PlaybookMatch`` + ``FocusItem`` DTOs. Rich payload (rather than a
    minimal summary) so that patterns own their own coaching content and
    the engine never synthesises templated text.
    """
    weakness_key: str
    title: str
    phase: PhaseTag
    affected_corners: tuple[int, ...]
    not_evaluable_corners: tuple[int, ...]
    cost_ms: float
    severity: Severity
    confidence: float
    likely_causes: tuple[str, ...]
    coaching_actions: tuple[str, ...]
    driver_cues: tuple[str, ...]
    measurable_targets: tuple[str, ...]
    sensor_note: str
    portability: str
    data_support: str


@dataclass(frozen=True)
class NotTriggered:
    """Pattern is registered AND evidence is sufficient AND nothing fired.

    This is a POSITIVE "no issue detected" — distinct from Insufficient and
    Unregistered. It is typically silent in the published output, but is
    counted internally for telemetry/observability.
    """
    weakness_key: str
    reason: str


@dataclass(frozen=True)
class Insufficient:
    """Pattern is registered BUT required evidence fields are missing.

    Emit visibly in the sheet (``storyline[type='insufficient_data']``).
    Do NOT silently skip — silent skips are exactly the failure mode the
    brief forbids.
    """
    weakness_key: str
    missing_fields: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Unregistered:
    """Upstream emitted a ``weakness_key`` that this registry does not know.

    Emit visibly (``storyline[type='unregistered_weakness']``). The current
    legacy module drops these at line 231 with a bare ``continue`` — that
    masks schema drift in ``driver_development.py``.
    """
    weakness_key: str


PatternResult = Union[Detected, NotTriggered, Insufficient, Unregistered]
"""Tagged union over the four distinct states a pattern evaluation can land in.

Consumers MUST handle all four variants explicitly. Do not collapse them
behind ``if result: ...`` — truthiness loses the state distinction."""


# ── Shared heuristics used by patterns + engine ─────────────────

def portability_for(
    archetypes: tuple[str, ...] | list[str],
    sessions_analyzed: int,
) -> str:
    """Human-readable portability label based on archetype diversity and
    session count. Matches legacy behaviour at
    ``prescriptive_coaching.py:210-217`` exactly (kept for schema parity)."""
    unique = len(set(archetypes))
    if sessions_analyzed < 3:
        return "unknown (too few sessions)"
    if unique >= 3:
        return "likely portable (seen across multiple corner types)"
    if unique >= 2:
        return "possibly portable"
    return "may be track-specific (single corner type)"
