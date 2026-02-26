"""Pydantic schemas for session endpoints."""
from __future__ import annotations

from pydantic import Field

from web.schemas.common import PaginationParams


class SessionListParams(PaginationParams):
    """Query parameters for GET /api/v1/sessions."""

    track_id: int | None = None
    driver_id: int | None = None
    status: str | None = None
