"""Admin middleware — superadmin guards and role-based access control.

Provides before_request hook and decorators for admin-only endpoints.
Admin routes bypass workspace RLS (no SET LOCAL) since admins need
cross-workspace visibility.
"""
from __future__ import annotations

import ipaddress
import logging
import os
from functools import wraps

from flask import g, jsonify, request

logger = logging.getLogger(__name__)

ADMIN_ROLES = {
    "root_admin",
    "support_admin",
    "billing_admin",
    "sre_admin",
    "auditor",
}

# Optional IP allowlist for admin endpoints.
# Set ADMIN_ALLOWED_IPS="10.0.0.1,192.168.1.0/24" to restrict access.
# Empty or unset = no IP restriction (auth-only).
_ADMIN_ALLOWED_IPS_RAW = os.environ.get("ADMIN_ALLOWED_IPS", "").strip()

# Optional TOTP exemption for specific admin users.
# Set ADMIN_TOTP_EXEMPT_EMAILS="user@example.com,other@example.com"
# These users skip the totp_enabled + admin_verified checks in
# require_superadmin but still require is_superadmin=True.
_TOTP_EXEMPT_RAW = os.environ.get("ADMIN_TOTP_EXEMPT_EMAILS", "").strip()
_TOTP_EXEMPT_EMAILS: set[str] = {
    e.strip().lower() for e in _TOTP_EXEMPT_RAW.split(",") if e.strip()
}
# Hard-coded admin email allowlist. Only these emails can access admin endpoints,
# regardless of is_superadmin in the DB. This is the outermost gate.
_ADMIN_ALLOWED_EMAILS: set[str] = {
    "theos.eleve@gmail.com",
}

_ADMIN_ALLOWED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []

if _ADMIN_ALLOWED_IPS_RAW:
    for entry in _ADMIN_ALLOWED_IPS_RAW.split(","):
        entry = entry.strip()
        if entry:
            try:
                _ADMIN_ALLOWED_NETWORKS.append(
                    ipaddress.ip_network(entry, strict=False)
                )
            except ValueError:
                logger.warning("Invalid ADMIN_ALLOWED_IPS entry: %s", entry)


def _check_admin_ip() -> bool:
    """Return True if request IP is allowed (or no restriction configured)."""
    if not _ADMIN_ALLOWED_NETWORKS:
        return True
    # Respect Cloudflare / reverse proxy real IP headers
    client_ip_str = (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Real-IP")
        or request.remote_addr
        or ""
    )
    try:
        client_ip = ipaddress.ip_address(client_ip_str)
    except ValueError:
        return False
    return any(client_ip in net for net in _ADMIN_ALLOWED_NETWORKS)


def _get_admin_conn():
    """Get DB connection for admin queries."""
    from flask import current_app

    if current_app.config.get("USE_PG"):
        from web.db_pg import get_pg_connection

        return get_pg_connection()
    from web.db import get_db_connection

    return get_db_connection()


def _get_current_user_id():
    """Get current user ID from Flask g."""
    return getattr(g, "current_user_id", None)


def _get_admin_verified():
    """Check if the current JWT has admin_verified claim."""
    return getattr(g, "admin_verified", False)


def _error_response(code: str, message: str, status: int = 403):
    """Return a standard error response."""
    return (
        jsonify(
            {
                "ok": False,
                "error": {"code": code, "message": message},
                "meta": {},
            }
        ),
        status,
    )


def admin_before_request():
    """before_request hook for admin blueprint.

    Loads admin user info into g.admin_user. Does NOT set RLS context
    (admin sees all workspaces). Optionally enforces IP allowlist.
    """
    if not _check_admin_ip():
        logger.warning(
            "Admin access denied from IP %s",
            request.headers.get("CF-Connecting-IP")
            or request.remote_addr,
        )
        return _error_response("FORBIDDEN", "Access denied", status=403)

    user_id = _get_current_user_id()
    if user_id is None:
        return _error_response("FORBIDDEN", "Authentication required")

    try:
        conn = _get_admin_conn()
        row = conn.execute(
            "SELECT is_superadmin, admin_role, totp_enabled, email "
            "FROM users WHERE id = %(uid)s",
            {"uid": user_id},
        ).fetchone()

        if row is None:
            return _error_response("FORBIDDEN", "User not found")

        user_data = dict(row) if not isinstance(row, dict) else row

        # Hard gate: only emails in _ADMIN_ALLOWED_EMAILS can access admin
        email = (user_data.get("email") or "").lower()
        if email not in _ADMIN_ALLOWED_EMAILS:
            logger.warning("Admin access denied for email %s (user %s)", email, user_id)
            return _error_response("FORBIDDEN", "Access denied")

        g.admin_user = user_data
    except Exception:
        logger.exception("Failed to load admin user info")
        return _error_response("FORBIDDEN", "Admin check failed")


def require_superadmin(f):
    """Decorator: checks is_superadmin=True AND (totp_enabled=True AND
    admin_verified JWT claim) — unless the user's email is in
    ADMIN_TOTP_EXEMPT_EMAILS.

    Must be used AFTER admin_before_request has populated g.admin_user.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        admin_user = getattr(g, "admin_user", None)
        if admin_user is None:
            return _error_response("FORBIDDEN", "Admin access required")

        if not admin_user.get("is_superadmin"):
            return _error_response("FORBIDDEN", "Superadmin access required")

        # Allow TOTP-exempt users to skip 2FA checks
        email = (admin_user.get("email") or "").lower()
        totp_exempt = email in _TOTP_EXEMPT_EMAILS

        if not totp_exempt:
            if not admin_user.get("totp_enabled"):
                return _error_response(
                    "FORBIDDEN", "2FA must be enabled for admin access"
                )

            if not _get_admin_verified():
                return _error_response(
                    "FORBIDDEN", "Admin 2FA verification required"
                )

        return f(*args, **kwargs)

    return decorated


def require_admin_role(*allowed_roles: str):
    """Decorator: checks admin_role is in allowed_roles.

    Used after require_superadmin.
    """

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            admin_user = getattr(g, "admin_user", None)
            if admin_user is None:
                return _error_response("FORBIDDEN", "Admin access required")

            role = admin_user.get("admin_role")
            if role not in allowed_roles:
                return _error_response(
                    "FORBIDDEN",
                    f"Required role: {', '.join(allowed_roles)}",
                )

            return f(*args, **kwargs)

        return decorated

    return decorator


def authorize_admin_metrics():
    """Self-contained admin gate for endpoints OUTSIDE the /api/v1 admin chain.

    ``/admin/metrics`` is registered on its own blueprint at ``/admin`` (not
    ``/api/v1/admin``), so neither ``auth_middleware`` (which only enforces
    ``/api/v1/``) nor ``admin_before_request`` runs for it — leaving it
    unauthenticated. This helper reproduces the admin gate inline: IP allowlist,
    a valid Bearer JWT, ``is_superadmin``, and the hard email allowlist.

    Returns an error response tuple to short-circuit the request, or ``None``
    when the caller is an allowed admin.
    """
    from flask import current_app
    from web.middleware.auth import _extract_token

    if not _check_admin_ip():
        return _error_response("FORBIDDEN", "Access denied", status=403)

    token = _extract_token()
    if not token:
        return _error_response("UNAUTHORIZED", "Authentication required", status=401)

    try:
        from auth.service import decode_access_token
        payload = decode_access_token(token, current_app.config["JWT_SECRET"])
        user_id = payload["user_id"]
    except Exception:
        return _error_response("UNAUTHORIZED", "Invalid or expired token", status=401)

    try:
        conn = _get_admin_conn()
        row = conn.execute(
            "SELECT is_superadmin, email FROM users WHERE id = %(uid)s",
            {"uid": user_id},
        ).fetchone()
    except Exception:
        logger.exception("Admin metrics auth: user lookup failed")
        return _error_response("FORBIDDEN", "Admin check failed", status=403)

    user_data = dict(row) if row and not isinstance(row, dict) else (row or {})
    email = (user_data.get("email") or "").lower()
    if not user_data.get("is_superadmin") or email not in _ADMIN_ALLOWED_EMAILS:
        logger.warning("Admin metrics access denied for user %s (email %s)", user_id, email)
        return _error_response("FORBIDDEN", "Access denied", status=403)

    return None
