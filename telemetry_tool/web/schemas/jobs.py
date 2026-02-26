"""Pydantic schemas for job management endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from web.schemas.common import PaginationParams


class ResumeJobSchema(BaseModel):
    """POST /api/v1/jobs/:id/resume request body."""

    joker_decision: Literal["accept", "reject"]


class JobListParams(PaginationParams):
    """Query parameters for GET /api/v1/jobs."""

    limit: int = Field(default=50, ge=1, le=100)
    status: str | None = None
