"""Pydantic schemas for job management endpoints."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from web.schemas.common import PaginationParams


class ResumeJobSchema(BaseModel):
    """POST /api/v1/jobs/:id/resume request body.

    Accepts either a joker decision (for paused jobs) or a corner
    selection (for awaiting_corner_selection jobs). At least one of
    the two fields must be provided.
    """

    joker_decision: Optional[Literal["accept", "reject"]] = None
    selected_corner_ids: Optional[list[int]] = None

    @model_validator(mode="after")
    def _check_at_least_one(self):
        if self.joker_decision is None and self.selected_corner_ids is None:
            raise ValueError("Either joker_decision or selected_corner_ids must be provided")
        return self


class JobListParams(PaginationParams):
    """Query parameters for GET /api/v1/jobs."""

    limit: int = Field(default=50, ge=1, le=100)
    status: str | None = None
