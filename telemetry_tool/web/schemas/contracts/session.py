"""SessionContract — the source-agnostic descriptor of a driven session."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)
from telemetry_tool.web.schemas.contracts.common import (
    DriverRef,
    Event,
    LapSummary,
    Scores,
    SidecarRef,
    SourceLiteral,
    TrackRef,
    VehicleRef,
)

CONTRACT_VERSION = "1.0"

# Channels that CAN NOT be directly measured on real-life hardware today.
# If a real_life session claims one of these, the profile detector is wrong.
_REAL_LIFE_FORBIDDEN: frozenset[ChannelTag] = frozenset({
    ChannelTag.THROTTLE,
    ChannelTag.BRAKE,
    ChannelTag.STEER,
    ChannelTag.WHEEL_SPD,
    ChannelTag.SHOCK_DEFL,
})


class SessionContract(BaseModel):
    """Unified, source-agnostic descriptor of one driven session."""
    model_config = ConfigDict(frozen=True)

    contract_version: str = Field(default=CONTRACT_VERSION)

    session_id: str
    workspace_id: str
    source: SourceLiteral
    capabilities: SessionCapabilities
    data_profile: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form dict describing how the file was detected + parsed. "
                    "Shape defined by W2 (profiler).",
    )

    driver: DriverRef
    track: TrackRef
    vehicle: VehicleRef

    session_start: datetime
    duration_s: float

    laps: list[LapSummary] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    scores: Scores | None = None

    sidecar: SidecarRef | None = Field(
        None,
        description="Pointer to raw-channel Parquet sidecar. Absent until W9 storage lands.",
    )

    @model_validator(mode="after")
    def _check_real_life_capabilities(self) -> "SessionContract":
        if self.source is SourceLiteral.REAL_LIFE:
            illegal = self.capabilities.channels & _REAL_LIFE_FORBIDDEN
            if illegal:
                raise ValueError(
                    f"source=real_life may not claim capabilities {illegal} — "
                    "these are inferred, not measured, on real-life hardware"
                )
        return self
