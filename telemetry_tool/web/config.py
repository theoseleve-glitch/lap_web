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

    # Database
    BASE_DIR: Path = _resolve_base_dir()
    DB_PATH: Path = Path(
        os.environ.get("TELEMETRY_DB_PATH", str(BASE_DIR / "telemetry.db"))
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
