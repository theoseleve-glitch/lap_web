"""Device token authentication for logger sync endpoints."""
from __future__ import annotations

import hashlib
import logging
from functools import wraps

from flask import g, request

logger = logging.getLogger(__name__)


def _extract_device_token() -> str | None:
    """Extract token from 'Authorization: DeviceToken <token>' header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("DeviceToken "):
        return None
    return auth[len("DeviceToken "):].strip() or None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_device_token(conn, token: str) -> dict | None:
    """Validate a device token against the DB.

    Returns dict with user_id, workspace_id, device_id if valid, else None.
    """
    token_hash = _hash_token(token)
    cur = conn.execute(
        "SELECT id, user_id, workspace_id FROM device_pairings "
        "WHERE device_token_hash = %(hash)s "
        "AND status = 'confirmed' AND revoked_at IS NULL",
        {"hash": token_hash},
    )
    row = cur.fetchone()
    if row is None:
        return None
    r = dict(row) if not isinstance(row, dict) else row
    return {
        "device_id": r["id"],
        "user_id": r["user_id"],
        "workspace_id": r["workspace_id"],
    }


def require_device_token(fn):
    """Decorator: require a valid device token. Sets g.current_user_id, g.workspace_id, g.device_id."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        from web.api_utils import ErrorCode, api_error
        from web.db_pg import get_pg_connection

        token = _extract_device_token()
        if token is None:
            return api_error(ErrorCode.UNAUTHORIZED, "Device token required", status=401)

        conn = get_pg_connection()
        result = validate_device_token(conn, token)
        if result is None:
            return api_error(ErrorCode.UNAUTHORIZED, "Invalid or revoked device token", status=401)

        g.current_user_id = result["user_id"]
        g.user_id = result["user_id"]
        g.workspace_id = result["workspace_id"]
        g.device_id = result["device_id"]

        # Update last_seen_at
        try:
            conn.execute(
                "UPDATE device_pairings SET last_seen_at = now() WHERE id = %(did)s",
                {"did": result["device_id"]},
            )
        except Exception:
            logger.warning("Failed to update device last_seen_at", exc_info=True)

        return fn(*args, **kwargs)
    return wrapper
