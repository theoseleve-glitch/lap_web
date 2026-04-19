"""OptimizerContract — theoretical lap + delta attribution.

Two depth levels:

- TRAJECTORY_ONLY: computed from GPS + accelerations only (real-life).
  Produces a theoretical lap time and corner-level time loss. No driver-
  input traces.

- FULL_FIDELITY: uses param-ID'd physics + solver (sim racing).
  Produces everything above PLUS reconstructed input traces (optimal
  throttle/brake/steer at each distance step), enabling input-level
  delta coaching.

Field names align with ``sim_optimizer/output/summary.py`` where the sim
pipeline already emits a compatible shape.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OptimizerDepth(str, Enum):
    TRAJECTORY_ONLY = "trajectory_only"
    FULL_FIDELITY = "full_fidelity"


class CornerDelta(BaseModel):
    """Per-corner time loss attribution."""
    model_config = ConfigDict(frozen=True)
    corner_id: str
    time_loss_s: float
    root_cause: str
    coaching_text: str = ""
    phase: str | None = None


class TrajectoryDelta(BaseModel):
    """Distance-indexed speed delta between driver and theoretical."""
    model_config = ConfigDict(frozen=True)
    distance_m: list[float]
    speed_delta_ms: list[float]

    @model_validator(mode="after")
    def _equal_lengths(self) -> "TrajectoryDelta":
        if len(self.distance_m) != len(self.speed_delta_ms):
            raise ValueError("distance_m and speed_delta_ms must have equal length")
        return self


class ReconstructedInputs(BaseModel):
    """Theoretical throttle/brake/steer traces (only available in FULL_FIDELITY)."""
    model_config = ConfigDict(frozen=True)
    distance_m: list[float]
    throttle: list[float]
    brake: list[float]
    steer: list[float]

    @model_validator(mode="after")
    def _equal_lengths(self) -> "ReconstructedInputs":
        n = len(self.distance_m)
        if not (len(self.throttle) == len(self.brake) == len(self.steer) == n):
            raise ValueError("all input arrays must have the same length as distance_m")
        return self


class OptimizerContract(BaseModel):
    """Unified optimizer result."""
    model_config = ConfigDict(frozen=True)

    depth: OptimizerDepth
    method: str = Field(..., description="Underlying solver identifier, e.g. 'qss_enhanced' or 'trajectory'")
    theoretical_lap_time_s: float
    confidence: float = Field(..., description="Overall result confidence, 0..1")

    corner_deltas: list[CornerDelta] = Field(default_factory=list)
    total_time_loss_s: float = 0.0

    trajectory_delta: TrajectoryDelta | None = None
    reconstructed_inputs: ReconstructedInputs | None = None

    vehicle_model: dict[str, Any] = Field(default_factory=dict, description="Identified model params, free-form until W5")
    validation: dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def _confidence_in_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be in [0,1], got {v}")
        return v

    @model_validator(mode="after")
    def _full_fidelity_requires_inputs(self) -> "OptimizerContract":
        if self.depth is OptimizerDepth.FULL_FIDELITY and self.reconstructed_inputs is None:
            raise ValueError("FULL_FIDELITY depth requires reconstructed_inputs")
        return self
