"""JWT auth middleware -- extracts user from Bearer token."""
from __future__ import annotations

import logging
import re
from functools import wraps
from typing import Any, Callable

from flask import current_app, g, jsonify, request
from flask.wrappers import Response

logger = logging.getLogger(__name__)


def log_security_event(*args: Any, **kwargs: Any) -> None:
    """Lazy proxy to avoid circular imports."""
    try:
        from admin.audit import log_security_event as _log
        _log(*args, **kwargs)
    except Exception:
        logger.debug("Failed to log security event", exc_info=True)

# Matches /auth/oauth/<provider> and /auth/oauth/<provider>/callback only
_OAUTH_PATH_RE = re.compile(r"^/auth/oauth/[a-z]+(/callback)?$")
# Matches /api/v1/devices/pair/<uuid>/status for unauthenticated poll
_DEVICE_PAIR_STATUS_RE = re.compile(r"^/api/v1/devices/pair/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/status$")


def auth_middleware() -> Response | tuple | None:
    """Before-request hook: decode JWT if present.

    When ``AUTH_REQUIRED`` is *False* (legacy / local mode), this is a
    no-op.  Otherwise it enforces a valid ``Authorization: Bearer <jwt>``
    header on all ``/api/v1/`` routes.
    """
    if not current_app.config.get("AUTH_REQUIRED"):
        return None  # Legacy mode -- no auth required

    # Let CORS preflight through — browsers never attach auth headers
    # to OPTIONS requests, so rejecting them breaks the CORS handshake.
    if request.method == "OPTIONS":
        return None

    # Skip auth for public auth endpoints (explicit allowlist, not prefix,
    # so future /auth/admin/* routes are still protected).
    _AUTH_PUBLIC_PATHS = {
        "/auth/register", "/auth/login", "/auth/logout",
        "/auth/refresh", "/auth/verify-email",
        "/auth/forgot-password", "/auth/reset-password",
        "/auth/2fa/verify",
        "/api/v1/billing/webhook",  # Uses Stripe signature verification
        "/api/v1/billing/checkout",  # Guest checkout (pre-signup); Stripe collects email + creates customer
        "/api/v1/devices/pair",        # Device pairing (no auth)
        "/api/v1/sessions/sync-upload",  # Uses DeviceToken auth
        "/api/v1/marketing-events",    # Public anonymous marketing collector
        "/api/v1/onboarding/draft",     # Track-onboarding loop: signed-token auth only
        "/api/v1/onboarding/save",      # Track-onboarding loop: signed-token auth only
    }
    if request.path in _AUTH_PUBLIC_PATHS or _OAUTH_PATH_RE.match(request.path) or _DEVICE_PAIR_STATUS_RE.match(request.path):
        return None

    # Skip for static assets
    if request.path.startswith("/static/"):
        return None

    # Skip for endurance status/report polling (job_id acts as access token)
    if request.path.startswith("/api/v1/endurance/status/") or request.path.startswith("/api/v1/endurance/report/"):
        return None

    # Skip for legacy HTML routes (backward compat)
    if not request.path.startswith("/api/v1/"):
        return None

    token = _extract_token()
    if token is None:
        log_security_event("auth_denied",
                           ip_address=request.remote_addr,
                           details={"path": request.path, "reason": "missing_token"})
        from web.api_utils import ErrorCode, api_error
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    from auth.service import AuthError, decode_access_token
    secret = current_app.config["JWT_SECRET"]
    try:
        payload = decode_access_token(token, secret)
        g.current_user_id = payload["user_id"]
        g.user_id = payload["user_id"]  # Transitional alias for migration
        g.email_verified = payload.get("email_verified", True)
        g.admin_verified = payload.get("admin_verified", False)
    except AuthError as e:
        event_type = "token_expired" if e.code == "TOKEN_EXPIRED" else "auth_denied"
        log_security_event(event_type,
                           ip_address=request.remote_addr,
                           details={"path": request.path, "error_code": e.code})
        from web.api_utils import api_error
        return api_error(e.code, str(e), status=401)

    # Check account suspension (after successful JWT decode).
    # Only applies when AUTH_REQUIRED is set (multi-tenant SaaS mode).
    # In desktop/local mode (no auth), skip the suspension check entirely.
    if g.current_user_id is not None and current_app.config.get("AUTH_REQUIRED"):
        conn = None
        try:
            from web.db import get_db_connection
            conn = get_db_connection()
        except Exception:
            # DB not configured (desktop/test mode) — skip suspension check
            pass

        if conn is not None:
            try:
                row = conn.execute(
                    "SELECT suspended_at FROM users WHERE id = %(uid)s AND suspended_at IS NOT NULL",
                    {"uid": g.current_user_id},
                ).fetchone()
                if row is not None:
                    from web.api_utils import ErrorCode, api_error
                    return api_error(ErrorCode.FORBIDDEN, "Account suspended", status=403)
            except Exception:
                # Fail closed: DB is available but query failed — deny rather
                # than letting a potentially suspended user through.
                logger.warning("Suspended-account check failed — denying request", exc_info=True)
                from web.api_utils import api_error
                return api_error("SERVICE_UNAVAILABLE", "Unable to verify account status", status=503)

    return None


def require_auth(f: Callable) -> Callable:
    """Decorator: endpoint requires a valid JWT (g.current_user_id set)."""
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Response | tuple:
        # Desktop mode — no auth enforced
        if not current_app.config.get("AUTH_REQUIRED"):
            if not hasattr(g, "current_user_id"):
                g.current_user_id = None
            return f(*args, **kwargs)

        if not hasattr(g, "current_user_id") or g.current_user_id is None:
            from web.api_utils import ErrorCode, api_error
            return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)
        return f(*args, **kwargs)
    return decorated


def _extract_token() -> str | None:
    """Extract the Bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None
