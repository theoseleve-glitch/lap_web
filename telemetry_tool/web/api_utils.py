"""API response envelope helpers and request-ID middleware.

Every /api/v1/ endpoint uses these helpers to produce a uniform JSON
envelope.  ``init_request_id`` installs a ``before_request`` hook that
generates a UUID4 request ID accessible via ``flask.g.request_id``.

Usage::

    from web.api_utils import api_response, api_error, ErrorCode, init_request_id

    # In app factory
    init_request_id(app)

    # In route handlers
    return api_response({"session": row}, status=200)
    return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
"""
from __future__ import annotations

import functools
import logging
import os
import time
from typing import Any
from uuid import uuid4

from flask import Flask, g, jsonify, request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error codes — stable string constants used across the API surface
# ---------------------------------------------------------------------------

class ErrorCode:
    """Stable string constants for API error codes.

    These are intentionally plain class attributes (not an Enum) so they
    serialise to JSON without ceremony and can be used directly as dict
    values.
    """

    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    FORBIDDEN = "FORBIDDEN"
    INSUFFICIENT_ROLE = "INSUFFICIENT_ROLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    PLAN_REQUIRED = "PLAN_REQUIRED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    API_HTML_RESPONSE = "API_HTML_RESPONSE"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    NOT_READY = "NOT_READY"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    SUPPORT_TIER_REFUSED = "SUPPORT_TIER_REFUSED"


class ReasonCode:
    """Stable reason codes for billing/entitlement errors.

    Used as the ``reason_code`` field inside PLAN_REQUIRED and
    QUOTA_EXCEEDED error envelopes to let the frontend distinguish
    *why* access was denied without parsing the human-readable message.
    """

    FEATURE_LOCKED = "FEATURE_LOCKED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    TRIAL_ENDED = "TRIAL_ENDED"
    PLAN_MISMATCH = "PLAN_MISMATCH"
    SUBSCRIPTION_UNPAID = "SUBSCRIPTION_UNPAID"
    SUBSCRIPTION_CANCELED = "SUBSCRIPTION_CANCELED"
    SUBSCRIPTION_PAUSED = "SUBSCRIPTION_PAUSED"


# ---------------------------------------------------------------------------
# Error catalog — maps each error code to its default HTTP status and
# a terse, user-safe default message.  Callers can override the message
# in api_error(); this catalog ensures consistency when they don't.
# ---------------------------------------------------------------------------

ERROR_CATALOG: dict[str, dict[str, Any]] = {
    ErrorCode.UNAUTHORIZED:         {"status": 401, "message": "Authentication required"},
    ErrorCode.INVALID_CREDENTIALS:  {"status": 401, "message": "Invalid email or password"},
    ErrorCode.TOKEN_EXPIRED:        {"status": 401, "message": "Token has expired"},
    ErrorCode.FORBIDDEN:            {"status": 403, "message": "Access denied"},
    ErrorCode.INSUFFICIENT_ROLE:    {"status": 403, "message": "Insufficient permissions"},
    ErrorCode.PLAN_REQUIRED:        {"status": 403, "message": "Upgrade required for this feature"},
    ErrorCode.VALIDATION_ERROR:     {"status": 422, "message": "Request validation failed"},
    ErrorCode.NOT_FOUND:            {"status": 404, "message": "Resource not found"},
    ErrorCode.CONFLICT:             {"status": 409, "message": "Resource conflict"},
    ErrorCode.IDEMPOTENCY_CONFLICT: {"status": 409, "message": "Duplicate request detected"},
    ErrorCode.QUOTA_EXCEEDED:       {"status": 429, "message": "Usage quota exceeded"},
    ErrorCode.RATE_LIMITED:         {"status": 429, "message": "Too many requests"},
    ErrorCode.FILE_TOO_LARGE:       {"status": 413, "message": "File exceeds size limit"},
    ErrorCode.UNSUPPORTED_FORMAT:   {"status": 415, "message": "Unsupported file format"},
    ErrorCode.ANALYSIS_FAILED:      {"status": 500, "message": "Analysis failed"},
    ErrorCode.INTERNAL_ERROR:       {"status": 500, "message": "Internal server error"},
    ErrorCode.API_HTML_RESPONSE:    {"status": 502, "message": "Upstream returned unexpected format"},
    ErrorCode.SERVICE_UNAVAILABLE:  {"status": 503, "message": "Service temporarily unavailable"},
    ErrorCode.NOT_READY:            {"status": 503, "message": "Service is starting up"},
    ErrorCode.NOT_IMPLEMENTED:      {"status": 501, "message": "Not implemented"},
    ErrorCode.DATA_UNAVAILABLE:     {"status": 404, "message": "Requested data is not available"},
    ErrorCode.SUPPORT_TIER_REFUSED: {"status": 451, "message": "Output unavailable at current support tier"},
}


# ---------------------------------------------------------------------------
# Envelope builders
# ---------------------------------------------------------------------------

def _build_meta(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the ``meta`` section, always including ``request_id`` and ``version``."""
    meta: dict[str, Any] = {
        "request_id": getattr(g, "request_id", None),
        "version": os.environ.get("APP_VERSION", "1.4.0"),
    }
    if extra:
        meta.update(extra)
    return meta


def _filter_fields(data: Any, fields: set[str] | None) -> Any:
    """Filter response data to only include requested fields.

    Supports dicts and lists of dicts. Passes through non-dict types unchanged.
    """
    if fields is None or not fields:
        return data
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in fields}
    if isinstance(data, list):
        return [
            {k: v for k, v in item.items() if k in fields}
            if isinstance(item, dict) else item
            for item in data
        ]
    return data


def _parse_fields_param() -> set[str] | None:
    """Parse ``?fields=id,name,score`` query parameter into a set."""
    raw = request.args.get("fields", "")
    if not raw:
        return None
    return {f.strip() for f in raw.split(",") if f.strip()}


def api_response(
    data: Any = None,
    status: int = 200,
    meta: dict[str, Any] | None = None,
) -> tuple:
    """Return a success envelope.

    Returns a ``(Response, status)`` tuple suitable for Flask route returns.
    Supports ``?fields=a,b,c`` query param for sparse field selection.

    Example response body::

        {"ok": true, "data": {...}, "meta": {"request_id": "..."}}
    """
    fields = _parse_fields_param()
    body = {
        "ok": True,
        "data": _filter_fields(data, fields),
        "meta": _build_meta(meta),
    }
    return jsonify(body), status


def api_error(
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    status: int = 400,
) -> tuple:
    """Return an error envelope.

    Example response body::

        {"ok": false, "error": {"code": "...", "message": "...", "details": [...]},
         "meta": {"request_id": "..."}}
    """
    error_section: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details is not None:
        error_section["details"] = details
    body = {
        "ok": False,
        "error": error_section,
        "meta": _build_meta(),
    }
    return jsonify(body), status


def billing_error(
    reason_code: str,
    message: str,
    *,
    current_plan: str | None = None,
    required_plan: str | None = None,
    upgrade_url: str | None = None,
    error_code: str = ErrorCode.PLAN_REQUIRED,
    status: int = 403,
    extra: dict[str, Any] | None = None,
) -> tuple:
    """Return a standardized billing/entitlement error envelope.

    All plan-gating and quota errors MUST use this builder so the
    frontend receives a predictable schema::

        {
            "ok": false,
            "error": {
                "code": "PLAN_REQUIRED",
                "reason_code": "FEATURE_LOCKED",
                "message": "...",
                "upgrade_url": "/billing?upgrade=true",
                "required_plan": "racer",
                "current_plan": "free"
            },
            "meta": {"request_id": "...", "version": "..."}
        }
    """
    if upgrade_url is None:
        upgrade_url = os.environ.get(
            "BILLING_UPGRADE_URL", "/billing?upgrade=true"
        )

    error_section: dict[str, Any] = {
        "code": error_code,
        "reason_code": reason_code,
        "message": message,
        "upgrade_url": upgrade_url,
        "required_plan": required_plan,
        "current_plan": current_plan,
    }
    if extra:
        error_section.update(extra)

    body = {
        "ok": False,
        "error": error_section,
        "meta": _build_meta(),
    }

    # Observability: count billing errors
    try:
        from web.metrics import incr_counter
        incr_counter("plan_required_error")
    except Exception:
        pass

    return jsonify(body), status


# ---------------------------------------------------------------------------
# Deprecation decorator
# ---------------------------------------------------------------------------

def deprecated(sunset: str, *, alternative: str | None = None):
    """Mark a route as deprecated with standard Deprecation + Sunset headers.

    Usage::

        @bp.route("/old-endpoint")
        @deprecated("2026-06-01", alternative="/api/v1/new-endpoint")
        def old_endpoint():
            ...

    Produces headers::

        Deprecation: true
        Sunset: Sun, 01 Jun 2026 00:00:00 GMT
        Link: </api/v1/new-endpoint>; rel="successor-version"
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)

            # result is (Response, status) or a Response — normalize
            if isinstance(result, tuple):
                response, status = result[0], result[1]
            else:
                response, status = result, 200

            response.headers["Deprecation"] = "true"

            # Convert ISO date to HTTP-date format for Sunset header
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(sunset).replace(tzinfo=timezone.utc)
                response.headers["Sunset"] = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
            except (ValueError, TypeError):
                response.headers["Sunset"] = sunset

            if alternative:
                response.headers["Link"] = f"<{alternative}>; rel=\"successor-version\""

            return (response, status) if isinstance(result, tuple) else response

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------

def init_request_id(app: Flask) -> None:
    """Register before/after hooks for request ID, timing, and correlation header.

    The request ID is a 32-character hex UUID4 string (no dashes), included
    in every response envelope via :func:`_build_meta` and echoed back
    in the ``X-Request-Id`` response header for client-side correlation.

    Request timing is logged on every response at INFO level.
    """

    @app.before_request
    def _set_request_id() -> None:
        g.request_id = uuid4().hex
        g._request_start_time = time.monotonic()

    @app.after_request
    def _add_request_headers(response):
        # Echo request ID for client-side correlation
        req_id = getattr(g, "request_id", None)
        if req_id:
            response.headers["X-Request-Id"] = req_id

        # Log request duration and expose as Server-Timing header
        start = getattr(g, "_request_start_time", None)
        if start is not None:
            duration_ms = (time.monotonic() - start) * 1000
            response.headers["Server-Timing"] = f"total;dur={duration_ms:.1f}"
            logger.info(
                "%s %s %s %.1fms",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
            )

        # Cache-Control headers — policy by method and path
        if "Cache-Control" not in response.headers:
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                # Mutating requests: never cache
                response.headers["Cache-Control"] = "no-store"
            elif request.path.startswith("/api/"):
                if "/healthz" in request.path:
                    response.headers["Cache-Control"] = "no-cache, max-age=0"
                elif any(seg in request.path for seg in (
                    "/speed-trace", "/gps-trace", "/gg-data", "/corners",
                    "/grip-map", "/friction-envelope",
                )):
                    # Chart data: immutable once generated, cache 1 hour
                    response.headers["Cache-Control"] = "private, max-age=3600"
                elif "/sessions" in request.path and request.path.endswith("/scores"):
                    # Scores: cache 5 minutes
                    response.headers["Cache-Control"] = "private, max-age=300"
                else:
                    # Default API: always revalidate (ETag still saves bandwidth
                    # via 304), but never serve stale data after mutations.
                    response.headers["Cache-Control"] = "private, no-cache"

        return response
