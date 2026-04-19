"""
track_surface.prescriptive.types
================================

PUBLISHED LANGUAGE — the stable, frontend-facing schema for a coaching sheet.

Every class in this module is part of the public coaching contract. The
field set mirrors the top-level shape of ``track-surface-ok-data.json``'s
``prescriptive_coaching`` node (version 1.0) so existing viewers
(``lap-studio-live.html``, ``ouest-karting-live.html``) keep working
through the Phase 1 → 3 migration.

Version discipline
------------------
- Adding an optional field with a safe default : additive, no version bump.
- Removing a field, renaming, or changing a type : version bump + ADR.
- Changing semantics of an existing field       : version bump + ADR.
- Changing ``HIGH_SEVERITY_MS`` / ``MEDIUM_SEVERITY_MS``: content contract —
  version bump + ADR (moves prescriptions up/down the focus list).

This module MUST NOT import from ``_internal``. Research types stay behind
the engine boundary; the published language never surfaces them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

# ── Version anchor ──────────────────────────────────────────────

COACHING_SHEET_VERSION: Final[str] = "1.0"


# ── Severity policy (content contract, not physics) ─────────────

HIGH_SEVERITY_MS: Final[float] = 400.0
"""Cost-in-ms threshold above which a weakness is tagged 'high' severity."""

MEDIUM_SEVERITY_MS: Final[float] = 150.0
"""Cost-in-ms threshold above which a weakness is tagged 'medium' severity."""


# ── Enums (Literal types) ──────────────────────────────────────

Severity = Literal["high", "medium", "low"]
"""Matches the values already emitted to ok-data.json; do not silently extend."""

PhaseTag = Literal["entry", "brake_release", "apex", "exit", "straight"]
"""Superset of the three phases currently used by the legacy playbook
('apex', 'entry', 'exit') plus the two phases declared in
``coaching_intelligence.PHASES``. Pinned so pattern authors cannot drift."""

NextRunItemType = Literal[
    "technical_focus", "execution_focus", "validation_metric", "anti_overload"
]


def severity_for(cost_ms: float) -> Severity:
    """Map a time-cost in ms to a ``Severity`` tag.

    Thresholds are part of the published contract (see ``HIGH_SEVERITY_MS``
    and ``MEDIUM_SEVERITY_MS``). Changing them shifts which prescriptions
    appear at the top of the viewer — treat any change as a version bump
    + ADR, not a refactor.
    """
    if cost_ms > HIGH_SEVERITY_MS:
        return "high"
    if cost_ms > MEDIUM_SEVERITY_MS:
        return "medium"
    return "low"


# ── Leaf DTOs ──────────────────────────────────────────────────

@dataclass(frozen=True)
class FocusItem:
    """One entry in ``global_focus`` — the top-3 ranked prescriptions."""
    rank: int
    weakness_key: str
    title: str
    severity: Severity
    estimated_cost_ms: float
    corners: tuple[int, ...]
    phase: PhaseTag
    confidence: float  # clamped to [0.0, 1.0] by the engine


@dataclass(frozen=True)
class PlaybookMatch:
    """Full prescription for one weakness. Serialised under
    ``weakness_playbook_matches``."""
    weakness_key: str
    title: str
    matched_playbook: bool
    corner_ids: tuple[int, ...]
    severity: Severity
    coaching_actions: tuple[str, ...]
    driver_cues: tuple[str, ...]
    measurable_targets: tuple[str, ...]
    likely_causes: tuple[str, ...]
    sensor_note: str
    portability: str
    data_support: str


@dataclass(frozen=True)
class CornerCoaching:
    """Per-corner summary of which prescriptions apply here.
    Serialised under ``corner_coaching``."""
    corner_id: int
    time_delta_ms: float
    s_entry_m: float | None
    s_exit_m: float | None
    applicable_weaknesses: tuple[str, ...]
    primary_cause: str
    confidence: float
    summary: str


@dataclass(frozen=True)
class NextRunItem:
    """One item in the next-run plan. ``rank=0`` + ``type='anti_overload'``
    is the dedicated cognitive-load guard slot."""
    rank: int
    type: NextRunItemType
    title: str
    corners: tuple[int, ...]
    instruction: str
    validation: str


@dataclass(frozen=True)
class ValidationCheck:
    """A measurable check tied to specific corners."""
    weakness_key: str
    metric_name: str
    target_description: str
    corners: tuple[int, ...]
    measurement_method: str
    confidence: float


@dataclass(frozen=True)
class StorylineEntry:
    """Narrative entry. ``type`` is an open tag — viewers MUST tolerate
    unknown values. Known values include at minimum:

        - 'primary_focus'
        - 'progress'
        - 'plateau'
        - 'data_warning'
        - 'insufficient_data'
        - 'unregistered_weakness'   # new in the Phase 1 design
    """
    type: str
    text: str
    confidence: float


@dataclass(frozen=True)
class Limits:
    """Declared bounds on what the coaching sheet can and cannot claim.
    Every field is a short human-readable string or a count; the frontend
    displays this block verbatim as a 'what this data can/cannot tell you' panel."""
    sessions_analyzed: int
    laps_analyzed: int
    brake_data: str
    throttle_data: str
    steering_data: str
    cross_track_portability: str
    weather_conditions: str
    reference_basis: str
    confidence_floor: str


# ── Root DTO ───────────────────────────────────────────────────

@dataclass(frozen=True)
class CoachingSheet:
    """The full published coaching output.

    Serialised under ``data.prescriptive_coaching`` in
    ``track-surface-ok-data.json`` and returned by the Phase 4 API endpoint.
    """
    version: str
    source: str
    global_focus: tuple[FocusItem, ...]
    corner_coaching: tuple[CornerCoaching, ...]
    weakness_playbook_matches: tuple[PlaybookMatch, ...]
    next_run_plan: tuple[NextRunItem, ...]
    validation_checks: tuple[ValidationCheck, ...]
    storyline: tuple[StorylineEntry, ...]
    limits: Limits

    @classmethod
    def empty(cls, limits: Limits) -> "CoachingSheet":
        """Canonical empty sheet emitted when no evidence is available.

        Matches the current legacy behaviour at line 566 of
        ``prescriptive_coaching.py`` — a frontend-safe "we have nothing to say,
        and here is why" payload, never a null or missing key.
        """
        return cls(
            version=COACHING_SHEET_VERSION,
            source="bronze_compare_plus_development_intelligence_only",
            global_focus=(),
            corner_coaching=(),
            weakness_playbook_matches=(),
            next_run_plan=(),
            validation_checks=(),
            storyline=(
                StorylineEntry(
                    type="insufficient_data",
                    text="No compare evidence or weakness patterns available.",
                    confidence=1.0,
                ),
            ),
            limits=limits,
        )
