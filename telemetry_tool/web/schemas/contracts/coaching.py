"""CoachingContract — harmonized with track_surface.prescriptive.types.

Field names mirror the existing ``prescriptive_coaching`` node in
``track-surface-ok-data.json`` so viewers that already consume that shape
keep working when they switch to the contract-typed API.

Version anchor mirrors ``track_surface.prescriptive.types.COACHING_SHEET_VERSION``.
If that anchor changes, bump the one here in the same commit + ADR.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

COACHING_SHEET_VERSION = "1.0"

Severity = Literal["high", "medium", "low"]
PhaseTag = Literal["entry", "brake_release", "apex", "exit", "straight"]
StorylineState = Literal["Detected", "NotTriggered", "Insufficient", "Unregistered"]
NextRunItemType = Literal[
    "technical_focus", "execution_focus", "validation_metric", "anti_overload"
]


class FocusItem(BaseModel):
    """One entry in ``global_focus`` — the top-3 ranked prescriptions."""
    model_config = ConfigDict(frozen=True)
    rank: int
    weakness_key: str
    title: str
    severity: Severity
    corner_ids: list[str] = Field(default_factory=list)
    cost_ms: float | None = None


class StorylineItem(BaseModel):
    """One narrative line in the coaching storyline."""
    model_config = ConfigDict(frozen=True)
    weakness_key: str
    state: StorylineState
    headline: str
    detail: str | None = None


class CornerCueItem(BaseModel):
    """A single cue attached to a corner within ``corner_coaching``."""
    model_config = ConfigDict(frozen=True)
    weakness_key: str
    phase: PhaseTag
    severity: Severity
    cue_text: str
    cost_ms: float | None = None


class CornerCoachingItem(BaseModel):
    """All cues that apply to one corner."""
    model_config = ConfigDict(frozen=True)
    corner_id: str
    items: list[CornerCueItem] = Field(default_factory=list)


class ValidationCheck(BaseModel):
    """A measurable target the driver can validate on the next run."""
    model_config = ConfigDict(frozen=True)
    check_id: str
    description: str
    measurable_target: str | None = None
    corner_id: str | None = None


class NextRunItem(BaseModel):
    """A structured next-run item (focus / metric / anti-overload)."""
    model_config = ConfigDict(frozen=True)
    item_type: NextRunItemType
    title: str
    body: str
    weakness_key: str | None = None


class CoachingContract(BaseModel):
    """Published, frontend-facing coaching sheet.

    Shape mirrors track_surface.prescriptive's ``prescriptive_coaching``
    node — see module docstring.
    """
    model_config = ConfigDict(frozen=True)

    version: str = Field(default=COACHING_SHEET_VERSION)

    storyline: list[StorylineItem]
    global_focus: list[FocusItem]
    corner_coaching: dict[str, CornerCoachingItem]
    not_evaluable_corners: list[str]
    validation_checks: list[ValidationCheck]
    next_run: list[NextRunItem]
