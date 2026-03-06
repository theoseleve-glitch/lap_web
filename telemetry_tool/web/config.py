"""
Flask application configuration.

Reads settings from environment variables with sensible defaults
for local single-user operation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _is_strong_secret(value: str, *, min_len: int = 32) -> bool:
    """Return True when a secret looks production-safe."""
    if not value or len(value) < min_len:
        return False
    lowered = value.lower()
    weak_markers = (
        "change-me",
        "dev",
        "default",
        "example",
        "local",
        "test",
        "secret",
    )
    return not any(marker in lowered for marker in weak_markers)


def _resolve_base_dir() -> Path:
    """Return the project base directory (same logic as path_manager).

    Frozen (PyInstaller) → folder containing the .exe (writable).
    Normal Python run    → folder containing this file's parent.
    """
    # When frozen, always use exe directory (writable, has data/, telemetry.db)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    try:
        from path_manager import get_base_dir
        return get_base_dir()
    except ImportError:
        return Path(__file__).resolve().parent.parent


class Config:
    """Default configuration for the Flask app."""

    SECRET_KEY: str = os.environ.get("TELEMETRY_SECRET_KEY", "")

    # Database — SQLite (legacy / single-user)
    BASE_DIR: Path = _resolve_base_dir()
    DB_PATH: Path = Path(
        os.environ.get("TELEMETRY_DB_PATH", str(BASE_DIR / "telemetry.db"))
    )

    # Database — PostgreSQL (SaaS / multi-user)
    USE_PG: bool = os.environ.get("USE_PG", "0") == "1"
    PG_URL: str = os.environ.get(
        "TELEMETRY_PG_URL",
        "postgresql://telemetry:telemetry@localhost:5432/telemetry",
    )

    # Redis (Celery broker + result backend + pipeline context)
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Celery
    CELERY_BROKER_URL: str = os.environ.get(
        "CELERY_BROKER_URL", os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    CELERY_RESULT_BACKEND: str = os.environ.get(
        "CELERY_RESULT_BACKEND", os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

    # Authentication
    AUTH_REQUIRED: bool = os.environ.get("AUTH_REQUIRED", "0") == "1"
    JWT_SECRET: str = os.environ.get("TELEMETRY_JWT_SECRET", "")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRY_MINUTES: int = 15
    JWT_REFRESH_EXPIRY_DAYS: int = 30

    # OAuth
    GOOGLE_CLIENT_ID: str = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GITHUB_CLIENT_ID: str = os.environ.get("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.environ.get("GITHUB_CLIENT_SECRET", "")
    OAUTH_REDIRECT_BASE: str = os.environ.get(
        "OAUTH_REDIRECT_BASE", "http://localhost:5000"
    )
    FRONTEND_URL: str = os.environ.get(
        "FRONTEND_URL", "http://localhost:3000"
    )

    @property
    def _oauth_google_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @property
    def _oauth_github_configured(self) -> bool:
        return bool(self.GITHUB_CLIENT_ID and self.GITHUB_CLIENT_SECRET)

    def hardening_summary(self) -> dict:
        """Return startup hardening diagnostics without exposing secret values."""
        oauth_providers = []
        if self._oauth_google_configured:
            oauth_providers.append("google")
        if self._oauth_github_configured:
            oauth_providers.append("github")

        return {
            "env": self.ENV,
            "use_pg": self.USE_PG,
            "auth_required": self.AUTH_REQUIRED,
            "auth_required_explicit": os.environ.get("AUTH_REQUIRED") == "1",
            "secret_key_strong": _is_strong_secret(self.SECRET_KEY),
            "jwt_secret_strong": _is_strong_secret(self.JWT_SECRET),
            "oauth_google_configured": self._oauth_google_configured,
            "oauth_github_configured": self._oauth_github_configured,
            "oauth_provider_count": len(oauth_providers),
            "oauth_providers": oauth_providers,
            "oauth_redirect_base_set": bool(self.OAUTH_REDIRECT_BASE),
            "frontend_url_set": bool(self.FRONTEND_URL),
        }

    def validate(self) -> None:
        """Raise if configuration is unsafe for production."""
        if self.ENV == "production":
            if os.environ.get("AUTH_REQUIRED") != "1":
                raise ValueError("ENV=production requires explicit AUTH_REQUIRED=1")
            # CORS: reject localhost/127.0.0.1 in production allowlist.
            for origin in self.CORS_ALLOWED_ORIGINS.split(","):
                origin = origin.strip().lower()
                if not origin:
                    continue
                if "localhost" in origin or "127.0.0.1" in origin:
                    raise ValueError(
                        f"CORS_ALLOWED_ORIGINS contains localhost origin "
                        f"'{origin}' — forbidden in production"
                    )

        if self.AUTH_REQUIRED or self.ENV == "production" or self.USE_PG:
            if not _is_strong_secret(self.JWT_SECRET):
                raise ValueError(
                    "TELEMETRY_JWT_SECRET must be set to a strong secret"
                )
            if not _is_strong_secret(self.SECRET_KEY):
                raise ValueError(
                    "TELEMETRY_SECRET_KEY must be set to a strong secret"
                )

        if self.USE_PG:
            if not self.AUTH_REQUIRED:
                raise ValueError("USE_PG=1 requires AUTH_REQUIRED=1")

            google_partial = bool(self.GOOGLE_CLIENT_ID) ^ bool(self.GOOGLE_CLIENT_SECRET)
            github_partial = bool(self.GITHUB_CLIENT_ID) ^ bool(self.GITHUB_CLIENT_SECRET)
            if google_partial:
                raise ValueError(
                    "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must both be set"
                )
            if github_partial:
                raise ValueError(
                    "GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET must both be set"
                )

            has_oauth_provider = self._oauth_google_configured or self._oauth_github_configured
            if not has_oauth_provider:
                raise ValueError(
                    "USE_PG=1 requires at least one OAuth provider configuration"
                )
            if not self.OAUTH_REDIRECT_BASE:
                raise ValueError("USE_PG=1 requires OAUTH_REDIRECT_BASE")
            if not self.FRONTEND_URL:
                raise ValueError("USE_PG=1 requires FRONTEND_URL")

    # Directories
    DATA_RAW_DIR: Path = BASE_DIR / "data" / "raw"
    RESULTS_DIR: Path = BASE_DIR / "results"
    UPLOAD_DIR: Path = BASE_DIR / "data" / "raw"

    # Server
    HOST: str = os.environ.get("TELEMETRY_HOST", "127.0.0.1")
    PORT: int = int(os.environ.get("TELEMETRY_PORT", "5000"))
    DEBUG: bool = os.environ.get("TELEMETRY_DEBUG", "0") == "1"

    # Pagination
    SESSIONS_PER_PAGE: int = 25

    # Upload — must accommodate large telemetry CSVs (endurance sessions).
    MAX_CONTENT_LENGTH: int = 12 * 1024 * 1024 * 1024  # 12 GB max upload

    # Logging
    LOG_FORMAT: str = os.environ.get("TELEMETRY_LOG_FORMAT", "text")

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = os.environ.get("RATE_LIMIT_ENABLED", "1") == "1"

    # CORS — no default in production; explicit allowlist required.
    CORS_ALLOWED_ORIGINS: str = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    ENV: str = os.environ.get("ENV", "development").lower()
