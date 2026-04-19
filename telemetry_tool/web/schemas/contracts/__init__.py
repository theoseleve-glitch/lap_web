"""Unified contracts for the W1 workstream."""
from __future__ import annotations

from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)
from telemetry_tool.web.schemas.contracts.coaching import (
    COACHING_SHEET_VERSION,
    CoachingContract,
    CornerCoachingItem,
    CornerCueItem,
    FocusItem,
    NextRunItem,
    PhaseTag,
    Severity,
    StorylineItem,
    StorylineState,
    ValidationCheck,
)
from telemetry_tool.web.schemas.contracts.common import (
    DriverRef,
    Event,
    LapSummary,
    Scores,
    SidecarRef,
    SourceLiteral,
    TrackRef,
    TrajectorySample,
    VehicleRef,
)
from telemetry_tool.web.schemas.contracts.session import (
    SessionContract,
    CONTRACT_VERSION,
)

__all__ = [
    "ChannelTag",
    "SessionCapabilities",
    "COACHING_SHEET_VERSION",
    "CoachingContract",
    "CornerCoachingItem",
    "CornerCueItem",
    "FocusItem",
    "NextRunItem",
    "PhaseTag",
    "Severity",
    "StorylineItem",
    "StorylineState",
    "ValidationCheck",
    "DriverRef",
    "Event",
    "LapSummary",
    "Scores",
    "SidecarRef",
    "SourceLiteral",
    "TrackRef",
    "TrajectorySample",
    "VehicleRef",
    "SessionContract",
    "CONTRACT_VERSION",
]
