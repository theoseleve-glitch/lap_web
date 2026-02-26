"""Common Pydantic schemas shared across API endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
