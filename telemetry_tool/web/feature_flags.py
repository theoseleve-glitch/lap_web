"""Lightweight feature flag system.

Checks flags in order: environment variable → Redis override → default.

Usage::

    from web.feature_flags import is_enabled, flags

    if is_enabled("experimental_charts"):
        return render_new_charts()

    # Or use as a decorator
    @flags.require("beta_export")
    def export_beta():
        ...
"""
from __future__ import annotations

import functools
import logging
import os
from typing import Any, Callable

from flask import g

logger = logging.getLogger(__name__)


# Default flags with their default state
_DEFAULTS: dict[str, bool] = {
    "ingest_v2": True,
    "use_pg": False,
    "auth_required": False,
    "streaming_upload": True,
    "experimental_charts": False,
    "beta_export": False,
    "advanced_coaching": False,
    "ai_suggestions": False,
}

# Map from flag name to env var name (for env-based overrides)
_ENV_MAP: dict[str, str] = {
    "ingest_v2": "TELEMETRY_INGEST_V2",
    "use_pg": "USE_PG",
    "auth_required": "AUTH_REQUIRED",
}


def _env_bool(key: str) -> bool | None:
    """Read an env var as a boolean. Returns None if not set."""
    val = os.environ.get(key)
    if val is None:
        return None
    return val.lower() in ("1", "true", "yes", "on")


def _redis_flag(name: str) -> bool | None:
    """Check Redis for a flag override. Returns None if Redis unavailable or flag not set."""
    try:
        from flask import current_app
        r = current_app.extensions.get("redis")
        if r is None:
            return None
        val = r.get(f"feature_flag:{name}")
        if val is None:
            return None
        return val.lower() in (b"1", b"true", "1", "true")
    except Exception:
        return None


def is_enabled(name: str, default: bool | None = None) -> bool:
    """Check if a feature flag is enabled.

    Resolution order:
    1. Environment variable (if mapped in _ENV_MAP)
    2. Redis override (``feature_flag:{name}``)
    3. Per-request override (``g.feature_flags``)
    4. Default from _DEFAULTS dict
    5. Provided default parameter
    """
    # 1. Env var
    env_key = _ENV_MAP.get(name)
    if env_key:
        env_val = _env_bool(env_key)
        if env_val is not None:
            return env_val

    # 2. Redis override
    redis_val = _redis_flag(name)
    if redis_val is not None:
        return redis_val

    # 3. Per-request override
    try:
        request_flags = getattr(g, "feature_flags", None)
        if request_flags and name in request_flags:
            return bool(request_flags[name])
    except RuntimeError:
        pass  # Outside request context

    # 4. Default registry
    if name in _DEFAULTS:
        return _DEFAULTS[name]

    # 5. Caller default
    if default is not None:
        return default

    return False


def register_flag(name: str, default: bool = False) -> None:
    """Register a new feature flag with a default value."""
    _DEFAULTS[name] = default


def get_all_flags() -> dict[str, bool]:
    """Return all registered flags with their current resolved values."""
    return {name: is_enabled(name) for name in sorted(_DEFAULTS)}


class _FlagNamespace:
    """Convenience namespace for flag operations."""

    def require(self, flag_name: str) -> Callable:
        """Decorator that returns 404 if the flag is not enabled."""
        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if not is_enabled(flag_name):
                    from web.api_utils import ErrorCode, api_error
                    return api_error(ErrorCode.NOT_FOUND, "Not found", status=404)
                return fn(*args, **kwargs)
            return wrapper
        return decorator


flags = _FlagNamespace()
