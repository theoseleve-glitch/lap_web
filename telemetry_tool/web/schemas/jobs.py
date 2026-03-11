"""Pydantic schemas for job management endpoints."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from web.schemas.common import PaginationParams


class CustomCorner(BaseModel):
    """A user-defined corner zone with entry/apex/exit distances."""

    s_start: float = Field(..., description="Entry distance along track (m)")
    s_apex: float = Field(..., description="Apex distance along track (m)")
    s_end: float = Field(..., description="Exit distance along track (m)")

    @model_validator(mode="after")
    def _check_ordering(self):
        if self.s_start > self.s_end:
            raise ValueError(f"s_start ({self.s_start}) must be <= s_end ({self.s_end})")
        if self.s_apex < self.s_start or self.s_apex > self.s_end:
            raise ValueError(f"s_apex ({self.s_apex}) must be between s_start and s_end")
        return self


class ResumeJobSchema(BaseModel):
    """POST /api/v1/jobs/:id/resume request body.

    Accepts one of:
    - joker_decision: for paused (joker) jobs
    - selected_corner_ids: legacy corner selection (filter auto-detected)
    - corners: custom corner geometry (entry/apex/exit distances)
    """

    joker_decision: Optional[Literal["accept", "reject"]] = None
    selected_corner_ids: Optional[list[int]] = None
    corners: Optional[list[CustomCorner]] = None

    @model_validator(mode="after")
    def _check_at_least_one(self):
        if (self.joker_decision is None
                and self.selected_corner_ids is None
                and self.corners is None):
            raise ValueError(
                "One of joker_decision, selected_corner_ids, or corners must be provided"
            )
        return self


class JobListParams(PaginationParams):
    """Query parameters for GET /api/v1/jobs."""

    limit: int = Field(default=50, ge=1, le=100)
    status: str | None = None
