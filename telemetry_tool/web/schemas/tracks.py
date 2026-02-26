"""Pydantic schemas for track endpoints."""
from __future__ import annotations

from web.schemas.common import PaginationParams


class TrackListParams(PaginationParams):
    """Query parameters for GET /api/v1/tracks."""

    pass
