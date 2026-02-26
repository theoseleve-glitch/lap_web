"""Pydantic schemas for batch reprocessing endpoints."""
from __future__ import annotations

from pydantic import BaseModel


class BatchReanalyzeSchema(BaseModel):
    """POST /api/v1/batch-reanalyze request body."""

    filter_criteria: dict | None = None
