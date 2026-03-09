"""Common Pydantic schemas shared across API endpoints."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictSchema(BaseModel):
    """Base schema that forbids extra fields (prevents silent typos)."""

    model_config = ConfigDict(extra="forbid")


class LenientSchema(BaseModel):
    """Base schema that ignores extra fields (for external/user input)."""

    model_config = ConfigDict(extra="ignore")


class PaginationParams(BaseModel):
    """Query parameters for cursor-paginated list endpoints.

    Usage::

        @bp.route("/sessions")
        @validate_params(PaginationParams)
        def list_sessions():
            p = g.params
            # p.limit, p.cursor, p.sort, p.order
    """

    limit: int = Field(default=25, ge=1, le=100)
    cursor: str | None = None
    sort: str | None = None
    order: Literal["asc", "desc"] = "desc"

    @field_validator("sort")
    @classmethod
    def sort_must_be_identifier(cls, v: str | None) -> str | None:
        """Reject sort values that aren't simple column identifiers."""
        if v is not None and not re.fullmatch(r"[a-z_][a-z0-9_.]*", v):
            raise ValueError("sort must be a simple field name")
        return v
