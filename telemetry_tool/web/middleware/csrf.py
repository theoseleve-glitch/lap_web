"""CSRF protection via double-submit cookie pattern.

On login/refresh, the auth routes set a ``csrf_token`` cookie (readable by JS).
This middleware validates that the ``X-CSRF-Token`` header matches the cookie
value on every state-changing request to ``/api/v1/*``.
"""
import logging
import secrets

from flask import current_app, request

logger = logging.getLogger(__name__)

_CSRF_COOKIE = "csrf_token"
_CSRF_HEADER = "X-CSRF-Token"
# Public, anonymous, cross-origin POST endpoints with no session/cookie to
# protect — CSRF (double-submit cookie) does not apply.
_EXEMPT_PATHS = {
    "/api/v1/billing/webhook",
    "/api/v1/marketing-events",
    # Guest Founding-50 checkout: public, no auth/session/cookie (the authed
    # in-app upgrade lives at /checkout/upgrade and stays CSRF-protected).
    "/api/v1/billing/checkout",
}
_MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


def csrf_middleware():
    """Before-request: validate CSRF token on state-changing requests."""
    if not current_app.config.get("AUTH_REQUIRED"):
        return

    if request.method not in _MUTATING_METHODS:
        return

    if not request.path.startswith("/api/v1/"):
        return

    if request.path in _EXEMPT_PATHS:
        return

    # Bearer tokens are CSRF-immune: they are set manually by JS and
    # cannot be attached automatically by a cross-site attacker's page.
    # Skip CSRF check when a Bearer token is present (cross-domain setup:
    # frontend on www.lap-coach.racing cannot read csrf_token cookie set
    # by api.lap-coach.racing).
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return

    cookie_token = request.cookies.get(_CSRF_COOKIE)
    header_token = request.headers.get(_CSRF_HEADER)

    if not cookie_token or not header_token:
        from web.api_utils import ErrorCode, api_error
        return api_error(ErrorCode.FORBIDDEN, "CSRF token missing", status=403)

    if not secrets.compare_digest(cookie_token, header_token):
        from web.api_utils import ErrorCode, api_error
        return api_error(ErrorCode.FORBIDDEN, "CSRF token mismatch", status=403)


def generate_csrf_token() -> str:
    """Generate a new CSRF token (64 URL-safe bytes)."""
    return secrets.token_urlsafe(48)


def set_csrf_cookie(response, token: str):
    """Set the CSRF cookie on a response object."""
    response.set_cookie(
        _CSRF_COOKIE,
        value=token,
        httponly=False,  # JS must read this to set header
        secure=True,
        samesite="Lax",
        max_age=30 * 24 * 3600,  # 30 days
        path="/",
    )
    return response
