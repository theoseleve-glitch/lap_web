"""JWT auth middleware -- extracts user from Bearer token."""
from functools import wraps

from flask import request, g, current_app, jsonify


def auth_middleware():
    """Before-request hook: decode JWT if present.

    When ``AUTH_REQUIRED`` is *False* (legacy / local mode), this is a
    no-op.  Otherwise it enforces a valid ``Authorization: Bearer <jwt>``
    header on all ``/api/v1/`` routes.
    """
    if not current_app.config.get("AUTH_REQUIRED"):
        return  # Legacy mode -- no auth required

    # Skip auth for public auth endpoints (explicit allowlist, not prefix,
    # so future /auth/admin/* routes are still protected).
    _AUTH_PUBLIC_PATHS = {
        "/auth/register", "/auth/login", "/auth/logout",
        "/auth/refresh", "/auth/verify-email",
    }
    if request.path in _AUTH_PUBLIC_PATHS or request.path.startswith("/auth/oauth/"):
        return

    # Skip for static assets
    if request.path.startswith("/static/"):
        return

    # Skip for legacy HTML routes (backward compat)
    if not request.path.startswith("/api/v1/"):
        return

    token = _extract_token()
    if token is None:
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
    except AuthError as e:
        return jsonify({
            "ok": False,
            "error": {"code": e.code, "message": str(e)},
            "meta": {},
        }), 401


def require_auth(f):
    """Decorator: endpoint requires a valid JWT (``g.current_user_id`` set)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, "current_user_id") or g.current_user_id is None:
            return jsonify({
                "ok": False,
                "error": {"code": "UNAUTHORIZED", "message": "Authentication required"},
                "meta": {},
            }), 401
        return f(*args, **kwargs)
    return decorated


def _extract_token():
    """Extract the Bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None
