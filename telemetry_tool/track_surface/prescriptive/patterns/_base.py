"""
track_surface.prescriptive.patterns._base
=========================================

Base class for all built-in coaching patterns.

Responsibilities of ``BasePattern.evaluate``
--------------------------------------------

1. Partition incoming ``Evidence`` items by the pattern's ``required_fields``
   into:
       - evaluable      : every required field is non-None
       - not_evaluable  : at least one required field is None
2. If ``evaluable`` is empty → return ``Insufficient`` with the missing fields.
   Per Phase-1 policy (Option B), this is the ONLY case that blocks emission.
3. Otherwise, call subclass hooks to compute:
       - parameters    (dict[str,str]) — filled into action/cue templates
       - measurable_targets (tuple[str,...]) — pattern-specific metric lines
4. Build and return a ``Detected``. Both the evaluable-corner set AND the
   not-evaluable-corner set are reported, so the engine (Phase 3) can
   surface "corner 6 was skipped: missing brake_point_delta_m" honestly.

Subclass contract
-----------------

Override class attributes:
    - ``key``                         : str
    - ``title``                       : str
    - ``phase``                       : PhaseTag
    - ``required_fields``             : tuple[str, ...]
    - ``likely_causes``               : tuple[str, ...]
    - ``coaching_action_templates``   : tuple[str, ...]
    - ``driver_cues``                 : tuple[str, ...]
    - ``sensor_note``                 : str

Override methods (both take ``(context, evaluable)``):
    - ``_compute_parameters``         → dict[str, str]
    - ``_compute_measurable_targets`` → tuple[str, ...]

Subclasses must NOT override ``evaluate`` itself — the partition and
Detected-construction logic is the contract and must stay identical across
every pattern so that the four-way result semantics are uniform.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np

from track_surface.prescriptive._internal import (
    Detected,
    Evidence,
    Insufficient,
    PatternResult,
    WeaknessContext,
    portability_for,
)
from track_surface.prescriptive.types import PhaseTag, severity_for


class BasePattern:
    """Default ``Pattern`` implementation. Concrete patterns inherit and
    override the class attributes + two compute hooks."""

    # ── subclass overrides ──────────────────────────────────
    key: str = ""
    title: str = ""
    phase: PhaseTag = "apex"
    required_fields: tuple[str, ...] = ()
    likely_causes: tuple[str, ...] = ()
    coaching_action_templates: tuple[str, ...] = ()
    driver_cues: tuple[str, ...] = ()
    sensor_note: str = ""

    # ── Pattern.evaluate — locked, do not override ─────────

    def evaluate(
        self,
        context: WeaknessContext,
        evidence: Iterable[Evidence],
    ) -> PatternResult:
        evaluable, not_evaluable = self._partition(evidence)

        if not evaluable:
            return Insufficient(
                weakness_key=self.key,
                missing_fields=self.required_fields,
                reason=(
                    f"none of {len(not_evaluable)} corner(s) have all of "
                    f"{list(self.required_fields)}"
                ),
            )

        params = self._compute_parameters(context, evaluable)
        return Detected(
            weakness_key=self.key,
            title=self.title,
            phase=self.phase,
            affected_corners=tuple(ev.corner_id for ev in evaluable),
            not_evaluable_corners=tuple(ev.corner_id for ev in not_evaluable),
            cost_ms=context.estimated_time_cost_ms,
            severity=severity_for(context.estimated_time_cost_ms),
            confidence=context.confidence,
            likely_causes=self.likely_causes,
            coaching_actions=tuple(
                self._apply_template(t, params)
                for t in self.coaching_action_templates
            ),
            driver_cues=tuple(
                self._apply_template(c, params) for c in self.driver_cues
            ),
            measurable_targets=self._compute_measurable_targets(context, evaluable),
            sensor_note=self.sensor_note,
            portability=portability_for(
                context.archetypes_observed, context.sessions_analyzed,
            ),
            data_support=self._build_data_support(context),
        )

    # ── subclass hooks ──────────────────────────────────────

    def _compute_parameters(
        self,
        context: WeaknessContext,
        evaluable: list[Evidence],
    ) -> dict[str, str]:
        """Return the ``{var}`` → value map used to parameterise templates.
        Default: empty dict (used by patterns whose templates have no variables,
        e.g. ``line_deviation``)."""
        return {}

    def _compute_measurable_targets(
        self,
        context: WeaknessContext,
        evaluable: list[Evidence],
    ) -> tuple[str, ...]:
        """Return the measurable-target lines for this pattern.

        Default fallback preserves legacy behaviour — a generic
        time-delta target derived from ``cost_ms`` when the pattern cannot
        compute a more specific one.
        """
        fallback_ms = context.estimated_time_cost_ms * 0.2
        return (
            f"Time delta at affected corners reduces by {fallback_ms:.0f}+ ms",
        )

    # ── helpers ────────────────────────────────────────────

    def _partition(
        self,
        evidence: Iterable[Evidence],
    ) -> tuple[list[Evidence], list[Evidence]]:
        evaluable: list[Evidence] = []
        not_evaluable: list[Evidence] = []
        for ev in evidence:
            if all(
                getattr(ev, f, None) is not None for f in self.required_fields
            ):
                evaluable.append(ev)
            else:
                not_evaluable.append(ev)
        return evaluable, not_evaluable

    @staticmethod
    def _apply_template(template: str, params: dict[str, str]) -> str:
        """Parameterise one template. Matches legacy fallback: on
        ``KeyError``/``IndexError`` return the raw template rather than raising."""
        try:
            return template.format(**params)
        except (KeyError, IndexError):
            return template

    @staticmethod
    def _build_data_support(context: WeaknessContext) -> str:
        return (
            f"{context.occurrence_count} occurrences across "
            f"{len(context.corners_observed)} corners in "
            f"{context.sessions_analyzed} sessions. "
            f"Trend: {context.trend}. "
            f"Evidence confidence: {context.confidence:.0%}."
        )

    @staticmethod
    def _median_abs(values: list[float]) -> float:
        """Median of absolute values; 0.0 for an empty list. Matches the
        legacy ``np.median(abs-values)`` pattern at
        ``prescriptive_coaching.py:265-269``."""
        if not values:
            return 0.0
        return float(np.median([abs(v) for v in values]))
