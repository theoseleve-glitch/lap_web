"""Pydantic schemas for security endpoints (password, 2FA)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PasswordChangeSchema(BaseModel):
    """POST /api/v1/account/password — change password."""

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=1024)


class ForgotPasswordSchema(BaseModel):
    """POST /auth/forgot-password — request reset link."""

    email: str = Field(min_length=3, max_length=320)


class ResetPasswordSchema(BaseModel):
    """POST /auth/reset-password — set new password with token."""

    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=1024)


class TotpSetupVerifySchema(BaseModel):
    """POST /api/v1/account/2fa/confirm — verify TOTP code."""

    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TotpDisableSchema(BaseModel):
    """POST /api/v1/account/2fa/disable — disable 2FA."""

    password: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=8)


class TotpLoginSchema(BaseModel):
    """POST /auth/login/2fa — complete 2FA login."""

    temp_token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=8)
