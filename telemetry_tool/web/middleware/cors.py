"""CORS middleware — single source of truth for all cross-origin headers.

Replaces flask_cors with a minimal after_request handler that:
- Validates Origin against an explicit allowlist (from CORS_ALLOWED_ORIGINS env)
- Sets identical headers on OPTIONS preflight, normal responses, AND error responses
- Never returns ACAO for unrecognised origins
- Always sets Vary: Origin to prevent cache poisoning
"""

from __future__ import annotations

import logging
from typing import Set

from flask import Flask, request

logger = logging.getLogger(__name__)

_ALLOWED_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
_ALLOWED_HEADERS = (
    "Authorization, Content-Type, X-Workspace-Id, "
    "Idempotency-Key, X-CSRF-Token, X-Request-Id"
)
_EXPOSE_HEADERS = "X-Request-Id, Retry-After"
_MAX_AGE = "86400"


def _parse_origins(raw: str) -> Set[str]:
    """Parse comma-separated origins, strip whitespace, drop empties."""
    return {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}


def init_cors(app: Flask) -> None:
    """Register CORS after_request handler on *app*."""
    raw = app.config.get("CORS_ALLOWED_ORIGINS", "")
    if isinstance(raw, str):
        origins = _parse_origins(raw)
    else:
        origins = set(raw)

    if not origins:
        logger.warning("CORS_ALLOWED_ORIGINS is empty — no cross-origin requests will be allowed")

    logger.info("CORS allowlist: %s", origins)

    @app.after_request
    def _set_cors_headers(response):
        # Always set Vary: Origin to prevent CDN/proxy cache poisoning.
        _append_vary(response, "Origin")

        origin = request.headers.get("Origin")
        if not origin:
            return response

        # Normalise: strip trailing slash for comparison.
        origin_normalised = origin.rstrip("/")
        if origin_normalised not in origins:
            # Unrecognised origin — return response WITHOUT ACAO.
            return response

        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"

        if request.method == "OPTIONS":
            response.headers["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
            response.headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
            response.headers["Access-Control-Max-Age"] = _MAX_AGE

        response.headers["Access-Control-Expose-Headers"] = _EXPOSE_HEADERS
        return response


def _append_vary(response, value: str) -> None:
    """Append *value* to the Vary header without duplicating."""
    existing = response.headers.get("Vary", "")
    if value.lower() in existing.lower():
        return
    if existing:
        response.headers["Vary"] = f"{existing}, {value}"
    else:
        response.headers["Vary"] = value
