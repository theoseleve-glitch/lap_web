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


def api_response(
    data: Any = None,
    status: int = 200,
    meta: dict[str, Any] | None = None,
) -> tuple:
    """Return a success envelope.

    Returns a ``(Response, status)`` tuple suitable for Flask route returns.

    Example response body::

        {"ok": true, "data": {...}, "meta": {"request_id": "..."}}
    """
    body = {
        "ok": True,
        "data": data,
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

        # Log request duration
        start = getattr(g, "_request_start_time", None)
        if start is not None:
            duration_ms = (time.monotonic() - start) * 1000
            logger.info(
                "%s %s %s %.1fms",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
            )

        return response
