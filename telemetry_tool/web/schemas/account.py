"""Pydantic schemas for account / GDPR endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class NotificationPreferences(BaseModel):
    """Notification preference toggles."""

    report_ready: bool = True
    billing_alerts: bool = True
    product_updates: bool = False
    weekly_digest: bool = True


class UserPreferences(BaseModel):
    """User-level preferences stored as JSONB in the users table."""

    language: str | None = Field(default=None, max_length=5)
    timezone: str | None = Field(default=None, max_length=50)
    units: Literal["metric", "imperial"] | None = None
    notifications: NotificationPreferences | None = None


class ProfileUpdateSchema(BaseModel):
    """PATCH /api/v1/account/profile request body."""

    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    avatar_url: str | None = Field(default=None, max_length=2048)
    preferences: UserPreferences | None = None


class ExportRequestSchema(BaseModel):
    """POST /api/v1/account/export request body."""

    format: Literal["zip", "json"] = "zip"
