"""
Flask application configuration.

Reads settings from environment variables with sensible defaults
for local single-user operation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


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

    SECRET_KEY: str = os.environ.get(
        "TELEMETRY_SECRET_KEY", "telemetry-local-dev-key"
    )

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

    # Authentication
    AUTH_REQUIRED: bool = os.environ.get("AUTH_REQUIRED", "0") == "1"
    JWT_SECRET: str = os.environ.get(
        "TELEMETRY_JWT_SECRET", "jwt-dev-secret-change-me"
    )
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

    def validate(self) -> None:
        """Raise if configuration is unsafe for production."""
        if self.AUTH_REQUIRED and self.JWT_SECRET == "jwt-dev-secret-change-me":
            raise ValueError(
                "TELEMETRY_JWT_SECRET must be set to a strong secret "
                "when AUTH_REQUIRED=1. Set the TELEMETRY_JWT_SECRET "
                "environment variable."
            )

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
