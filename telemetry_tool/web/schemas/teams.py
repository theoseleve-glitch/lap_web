"""Pydantic schemas for team management endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateTeamSchema(BaseModel):
    """POST /api/v1/teams request body."""

    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", min_length=2, max_length=50)


class InviteMemberSchema(BaseModel):
    """POST /api/v1/teams/:id/members request body."""

    user_id: int
    role: Literal["viewer", "member", "admin"] = "member"
