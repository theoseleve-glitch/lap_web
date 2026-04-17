"""
track_surface.prescriptive.registry
===================================

Pattern protocol + PatternRegistry.

Design choices locked by the brief
----------------------------------
1. Refuse silent overwrite. Duplicate registration raises ``ValueError``
   rather than replacing the existing pattern — that is a behavioural
   change and must be explicit.
2. Refuse non-Pattern objects. Registration validates against the
   ``Pattern`` protocol at runtime via ``isinstance`` (``@runtime_checkable``).
3. Unknown key lookup returns ``None``. Callers MUST then emit an
   ``Unregistered`` result, not fall back to a default pattern.
4. Iteration order is insertion order. Pattern ordering in output is
   predictable and reproducible.

Concrete patterns live in ``prescriptive/patterns/``; the convenience
factory ``build_default_registry()`` there populates a registry with the
five built-in patterns in a fixed order.
"""
from __future__ import annotations

from typing import Iterable, Iterator, Optional, Protocol, runtime_checkable

from track_surface.prescriptive._internal import (
    Evidence,
    PatternResult,
    WeaknessContext,
)
from track_surface.prescriptive.types import PhaseTag


@runtime_checkable
class Pattern(Protocol):
    """Contract every coaching pattern must satisfy.

    Concrete patterns (see ``prescriptive/patterns/``) are plain classes with
    these class attributes and the ``evaluate`` method. A pattern must be a
    pure function of ``(context, evidence)`` — no module-level state, no file
    I/O, no randomness.
    """

    key: str
    """Canonical weakness identifier, e.g. 'low_minimum_speed'. MUST match
    the ``behavior_id`` values emitted by ``driver_development``."""

    title: str
    """Human label for the weakness."""

    phase: PhaseTag
    """Driving phase most affected — used for UI grouping."""

    required_fields: tuple[str, ...]
    """Attribute names on ``Evidence`` that must be non-None for a given
    corner to be evaluable by this pattern. Per the Phase-1 policy choice
    (Option B), a pattern fires on the subset of corners where all required
    fields are present, and returns ``Insufficient`` only when no corner is
    evaluable."""

    def evaluate(
        self,
        context: WeaknessContext,
        evidence: Iterable[Evidence],
    ) -> PatternResult:
        """Evaluate the pattern for one weakness.

        Arguments:
            context  : per-weakness metadata (count, trend, archetypes, …).
            evidence : per-corner snapshots, already filtered to the corners
                       listed in ``context.corners_observed``.

        Implementations MUST return exactly one of:
            - Detected     (one or more corners triggered)
            - NotTriggered (no corner triggered, evidence was sufficient)
            - Insufficient (required fields absent across all corners)

        ``Unregistered`` is emitted by the engine, not by any pattern — a
        pattern that exists in the registry cannot be unregistered.
        """
        ...


class PatternRegistry:
    """An insertion-ordered, overwrite-refusing collection of ``Pattern``.

    Empty by default. Populate via ``register(pattern)``; enumerate via
    iteration or ``.keys()``.
    """

    def __init__(self) -> None:
        self._patterns: dict[str, Pattern] = {}

    # ── Mutation ──────────────────────────────────────────────

    def register(self, pattern: Pattern) -> None:
        """Add a pattern. Raises:
            - ``TypeError`` if ``pattern`` does not satisfy the ``Pattern`` protocol.
            - ``ValueError`` on duplicate ``pattern.key`` — use ``remove()`` first
              if intentional replacement is needed.
        """
        if not isinstance(pattern, Pattern):
            raise TypeError(
                f"Expected object satisfying the Pattern protocol, got "
                f"{type(pattern).__name__} (missing key/title/phase/"
                f"required_fields/evaluate)"
            )
        key = pattern.key
        if key in self._patterns:
            raise ValueError(
                f"Pattern key already registered: {key!r}. Refusing silent "
                f"overwrite — call remove({key!r}) first if replacement is "
                f"intentional."
            )
        self._patterns[key] = pattern

    def remove(self, key: str) -> None:
        """Remove a pattern by key. Raises ``KeyError`` if absent."""
        del self._patterns[key]

    # ── Query ────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Pattern]:
        """Return the pattern for ``key``, or ``None`` if absent.

        Callers MUST handle ``None`` by emitting an ``Unregistered`` result.
        Do NOT substitute a default pattern — silent defaulting is the
        behaviour the brief explicitly forbids.
        """
        return self._patterns.get(key)

    def keys(self) -> tuple[str, ...]:
        """Registered keys in insertion order."""
        return tuple(self._patterns.keys())

    # ── Container protocol ───────────────────────────────────

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self._patterns

    def __iter__(self) -> Iterator[Pattern]:
        return iter(self._patterns.values())

    def __len__(self) -> int:
        return len(self._patterns)
