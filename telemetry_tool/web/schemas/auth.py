"""Pydantic schemas for authentication endpoints."""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterSchema(BaseModel):
    """POST /auth/register request body."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=1024)
    display_name: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address format")
        return v


class LoginSchema(BaseModel):
    """POST /auth/login request body."""

    model_config = ConfigDict(populate_by_name=True)

    email: str = Field(min_length=1)
    password: str = Field(min_length=1, max_length=1024)
    # Cloudflare Turnstile step-up challenge token (see auth/turnstile.py).
    # Optional -- only checked when auth.lockout.challenge_required() flags
    # this login attempt. Accepts the widget's native field name.
    turnstile_token: str | None = Field(default=None, alias="cf-turnstile-response")


class RefreshSchema(BaseModel):
    """POST /auth/refresh request body."""

    refresh_token: str = Field(min_length=1)


class VerifyEmailSchema(BaseModel):
    """POST /auth/verify-email request body."""

    token: str = Field(min_length=1)
