"""JWT auth middleware -- extracts user from Bearer token."""
import logging
import re
from functools import wraps

from flask import request, g, current_app, jsonify

logger = logging.getLogger(__name__)


def log_security_event(*args, **kwargs):
    """Lazy proxy to avoid circular imports."""
    try:
        from admin.audit import log_security_event as _log
        _log(*args, **kwargs)
    except Exception:
        logger.debug("Failed to log security event", exc_info=True)

# Matches /auth/oauth/<provider> and /auth/oauth/<provider>/callback only
_OAUTH_PATH_RE = re.compile(r"^/auth/oauth/[a-z]+(/callback)?$")


def auth_middleware():
    """Before-request hook: decode JWT if present.

    When ``AUTH_REQUIRED`` is *False* (legacy / local mode), this is a
    no-op.  Otherwise it enforces a valid ``Authorization: Bearer <jwt>``
    header on all ``/api/v1/`` routes.
    """
    if not current_app.config.get("AUTH_REQUIRED"):
        return  # Legacy mode -- no auth required

    # Let CORS preflight through — browsers never attach auth headers
    # to OPTIONS requests, so rejecting them breaks the CORS handshake.
    if request.method == "OPTIONS":
        return

    # Skip auth for public auth endpoints (explicit allowlist, not prefix,
    # so future /auth/admin/* routes are still protected).
    _AUTH_PUBLIC_PATHS = {
        "/auth/register", "/auth/login", "/auth/logout",
        "/auth/refresh", "/auth/verify-email",
        "/auth/forgot-password", "/auth/reset-password",
        "/auth/2fa/verify",
        "/api/v1/billing/webhook",  # Uses Stripe signature verification
    }
    if request.path in _AUTH_PUBLIC_PATHS or _OAUTH_PATH_RE.match(request.path):
        return

    # Skip for static assets
    if request.path.startswith("/static/"):
        return

    # Skip for legacy HTML routes (backward compat)
    if not request.path.startswith("/api/v1/"):
        return

    token = _extract_token()
    if token is None:
        log_security_event("auth_denied",
                           ip_address=request.remote_addr,
                           details={"path": request.path, "reason": "missing_token"})
        return jsonify({
            "ok": False,
            "error": {"code": "UNAUTHORIZED", "message": "Authentication required"},
            "meta": {},
        }), 401

    from auth.service import decode_access_token, AuthError
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
        return jsonify({
            "ok": False,
            "error": {"code": e.code, "message": str(e)},
            "meta": {},
        }), 401

    # Check account suspension (after successful JWT decode)
    if g.current_user_id is not None:
        try:
            from web.db import get_db_connection
            conn = get_db_connection()
            row = conn.execute(
                "SELECT suspended_at FROM users WHERE id = %(uid)s AND suspended_at IS NOT NULL",
                {"uid": g.current_user_id},
            ).fetchone()
            if row is not None:
                return jsonify({
                    "ok": False,
                    "error": {"code": "ACCOUNT_SUSPENDED", "message": "Account suspended"},
                    "meta": {},
                }), 403
        except Exception:
            pass  # Fail open — don't block if DB check fails


def require_auth(f):
    """Decorator: endpoint requires a valid JWT (g.current_user_id set)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Desktop mode — no auth enforced
        if not current_app.config.get("AUTH_REQUIRED"):
            if not hasattr(g, "current_user_id"):
                g.current_user_id = None
            return f(*args, **kwargs)

        if not hasattr(g, "current_user_id") or g.current_user_id is None:
            from web.api_utils import api_error, ErrorCode
            return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=401)
        return f(*args, **kwargs)
    return decorated


def _extract_token():
    """Extract the Bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None
