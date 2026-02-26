"""Pydantic schemas for account / GDPR endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProfileUpdateSchema(BaseModel):
    """PATCH /api/v1/account/profile request body."""

    display_name: str | None = None
    email: str | None = None


class ExportRequestSchema(BaseModel):
    """POST /api/v1/account/export request body."""

    format: Literal["zip", "json"] = "zip"
