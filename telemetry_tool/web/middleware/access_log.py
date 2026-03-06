"""Access logging middleware with secret redaction.

Logs every HTTP request with method, path, status, latency, bytes,
IP, and user-agent.  Sensitive headers (Authorization, cookies,
Stripe-Signature) are redacted before logging.

Usage::

    from web.middleware.access_log import init_access_log
    init_access_log(app)
"""
from __future__ import annotations

import logging
import re
import time

from flask import Flask, g, request

logger = logging.getLogger("telemetry_tool.access")

# Headers that must never appear in logs
_REDACT_HEADERS = frozenset({
    "authorization",
    "cookie",
    "set-cookie",
    "stripe-signature",
    "x-api-key",
    "idempotency-key",
})

# Regex for secrets in query strings or form data
_SECRET_PATTERN = re.compile(
    r"(password|token|secret|api_key|apikey|access_token|refresh_token)"
    r"\s*[=:]\s*\S+",
    re.IGNORECASE,
)


def _safe_ip() -> str:
    """Return the client IP, preferring X-Forwarded-For (Caddy sets it)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "-"


def _redact_path(path: str) -> str:
    """Remove tokens/secrets from the URL path and query string."""
    return _SECRET_PATTERN.sub(r"\1=***", path)


def init_access_log(app: Flask) -> None:
    """Register before/after hooks for access logging."""

    @app.before_request
    def _access_log_start():
        g._access_start = time.monotonic()

    @app.after_request
    def _access_log_record(response):
        latency_ms = 0.0
        if hasattr(g, "_access_start"):
            latency_ms = (time.monotonic() - g._access_start) * 1000

        content_length = response.content_length or 0
        req_id = getattr(g, "request_id", "-")
        user_id = getattr(g, "current_user_id", "-")

        logger.info(
            "%s %s %d %.1fms %d %s %s %s %s",
            request.method,
            _redact_path(request.full_path.rstrip("?")),
            response.status_code,
            latency_ms,
            content_length,
            _safe_ip(),
            request.headers.get("User-Agent", "-")[:200],
            req_id,
            user_id,
        )
        return response
