"""
track_surface.prescriptive.patterns
===================================

Built-in coaching patterns.

Each pattern is a small class inheriting from ``BasePattern``:
    - class attributes: ``key``, ``title``, ``phase``, ``required_fields``,
      ``likely_causes``, ``coaching_action_templates``, ``driver_cues``,
      ``sensor_note``
    - hooks: ``_compute_parameters`` and ``_compute_measurable_targets``

``BasePattern`` handles the evidence-partition policy (Option B from the
Phase-1 design):
    - split evidence into evaluable (all ``required_fields`` present) and
      not-evaluable corners
    - if NO corner is evaluable → return ``Insufficient``
    - otherwise compute parameters and measurable targets from the
      evaluable subset, and return ``Detected`` with both sets reported

Pattern classes are exported from this package for external customisation
(e.g., tests, custom engines). ``build_default_registry()`` is the one-call
factory that installs the five built-ins in a fixed, deterministic order.
"""
from track_surface.prescriptive.patterns._base import BasePattern
from track_surface.prescriptive.patterns.early_braking import EarlyBraking
from track_surface.prescriptive.patterns.late_throttle_pickup import LateThrottlePickup
from track_surface.prescriptive.patterns.line_deviation import LineDeviation
from track_surface.prescriptive.patterns.low_minimum_speed import LowMinimumSpeed
from track_surface.prescriptive.patterns.weak_exit_build import WeakExitBuild
from track_surface.prescriptive.registry import PatternRegistry


def build_default_registry() -> PatternRegistry:
    """Return a fresh ``PatternRegistry`` populated with the five built-in
    patterns.

    Order matters: ``PatternRegistry`` preserves insertion order, and that
    order influences tie-breaking in output listings. The order here matches
    the legacy ``WEAKNESS_PLAYBOOK`` dict key order in
    ``prescriptive_coaching.py`` so that migrated output is byte-identical
    on tie-broken paths.
    """
    reg = PatternRegistry()
    reg.register(LowMinimumSpeed())
    reg.register(EarlyBraking())
    reg.register(LateThrottlePickup())
    reg.register(WeakExitBuild())
    reg.register(LineDeviation())
    return reg


__all__ = [
    "BasePattern",
    "EarlyBraking",
    "LateThrottlePickup",
    "LineDeviation",
    "LowMinimumSpeed",
    "WeakExitBuild",
    "build_default_registry",
]
