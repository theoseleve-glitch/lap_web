"""
track_surface.prescriptive
==========================

Coaching prescription package (Phase 3: domain + registry + built-in
patterns + engine + serializer).

Public API (stable, frontend-facing). Any change to a symbol in this list
requires a version bump of ``COACHING_SHEET_VERSION`` and an ADR:

    - CoachingSheet, FocusItem, PlaybookMatch, CornerCoaching,
      NextRunItem, ValidationCheck, StorylineEntry, Limits
    - Severity, PhaseTag, COACHING_SHEET_VERSION
    - HIGH_SEVERITY_MS, MEDIUM_SEVERITY_MS, severity_for
    - Pattern, PatternRegistry
    - build_default_registry
    - generate_coaching_sheet, run, to_json_dict

Research-layer types (Evidence, WeaknessContext, PatternResult and its
variants, portability_for) live in ``track_surface.prescriptive._internal``
and MUST NOT be re-exported from this module.
"""
from track_surface.prescriptive.engine import generate_coaching_sheet, run
from track_surface.prescriptive.patterns import build_default_registry
from track_surface.prescriptive.registry import Pattern, PatternRegistry
from track_surface.prescriptive.serialization import to_json_dict
from track_surface.prescriptive.types import (
    COACHING_SHEET_VERSION,
    HIGH_SEVERITY_MS,
    MEDIUM_SEVERITY_MS,
    CoachingSheet,
    CornerCoaching,
    FocusItem,
    Limits,
    NextRunItem,
    PhaseTag,
    PlaybookMatch,
    Severity,
    StorylineEntry,
    ValidationCheck,
    severity_for,
)

__all__ = [
    "COACHING_SHEET_VERSION",
    "CoachingSheet",
    "CornerCoaching",
    "FocusItem",
    "HIGH_SEVERITY_MS",
    "Limits",
    "MEDIUM_SEVERITY_MS",
    "NextRunItem",
    "Pattern",
    "PatternRegistry",
    "PhaseTag",
    "PlaybookMatch",
    "Severity",
    "StorylineEntry",
    "ValidationCheck",
    "build_default_registry",
    "generate_coaching_sheet",
    "run",
    "severity_for",
    "to_json_dict",
]
