"""Device pairing and management endpoints.

POST /api/v1/devices/pair         — generate pairing code (no auth)
GET  /api/v1/devices/pair/<id>/status — poll pairing status (no auth)
POST /api/v1/devices/confirm      — confirm code (JWT auth)
GET  /api/v1/devices              — list linked devices (JWT auth)
DELETE /api/v1/devices/<id>       — revoke a device (JWT auth)
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import string
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, ReasonCode, api_error, api_response, billing_error
from web.db_pg import get_pg_connection
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("devices", __name__, url_prefix="/api/v1")

# Characters that are unambiguous (no 0/O/I/1/L)
_CODE_CHARS = string.ascii_uppercase.replace("O", "").replace("I", "").replace("L", "") + "23456789"
_CODE_TTL_MINUTES = 10
_POLL_AFTER_CONFIRM_TTL_S = 60  # pairing_id remains valid for 60s after confirm


def _generate_code() -> str:
    """Generate a 6-char code like K7X-9M2."""
    part1 = "".join(secrets.choice(_CODE_CHARS) for _ in range(3))
    part2 = "".join(secrets.choice(_CODE_CHARS) for _ in range(3))
    return f"{part1}-{part2}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@bp.route("/devices/pair", methods=["POST"])
@rate_limit("device_pair")
def create_pairing():
    """Generate a pairing code for the logger to display."""
    body = request.get_json(silent=True) or {}
    device_name = str(body.get("device_name", ""))[:100]

    conn = get_pg_connection()
    code = _generate_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)

    # Retry on code collision (extremely unlikely with 6 chars from 33-char alphabet)
    for _ in range(5):
        try:
            cur = conn.execute(
                "INSERT INTO device_pairings (pairing_code, device_name, expires_at) "
                "VALUES (%(code)s, %(name)s, %(exp)s) RETURNING pairing_id",
                {"code": code, "name": device_name, "exp": expires_at.isoformat()},
            )
            row = cur.fetchone()
            r = dict(row) if not isinstance(row, dict) else row
            return api_response({
                "pairing_id": str(r["pairing_id"]),
                "code": code,
                "expires_at": expires_at.isoformat(),
            })
        except Exception:
            code = _generate_code()

    return api_error(ErrorCode.INTERNAL_ERROR, "Failed to generate pairing code", status=500)


@bp.route("/devices/pair/<pairing_id>/status", methods=["GET"])
@rate_limit("device_poll")
def poll_pairing_status(pairing_id: str):
    """Poll the status of a pairing request."""
    conn = get_pg_connection()
    cur = conn.execute(
        "SELECT status, device_token_hash, expires_at FROM device_pairings "
        "WHERE pairing_id = %(pid)s::uuid",
        {"pid": pairing_id},
    )
    row = cur.fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Pairing not found", status=404)

    r = dict(row) if not isinstance(row, dict) else row

    # Check expiry for pending codes
    if r["status"] == "pending":
        expires = r.get("expires_at")
        if expires and isinstance(expires, datetime) and expires < datetime.now(timezone.utc):
            return api_response({"status": "expired"})

    result = {"status": r["status"]}

    # Only reveal token on first poll after confirmation
    if r["status"] == "confirmed" and r.get("device_token_hash"):
        import redis
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r_client = redis.from_url(redis_url)
        token_key = f"device_pair_token:{pairing_id}"
        raw_token = r_client.get(token_key)
        if raw_token:
            result["device_token"] = raw_token.decode("utf-8")
            r_client.delete(token_key)

    return api_response(result)


@bp.route("/devices/confirm", methods=["POST"])
def confirm_pairing():
    """Confirm a pairing code (requires JWT auth)."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    body = request.get_json(silent=True) or {}
    code = str(body.get("code", "")).strip().upper()
    if not code:
        return api_error(ErrorCode.VALIDATION_ERROR, "Pairing code is required", status=400)

    conn = get_pg_connection()

    # Check entitlement: max_linked_devices
    from auth.entitlements import get_plan_entitlements, get_user_plan_tier
    tier = get_user_plan_tier(conn, user_id)
    plan = get_plan_entitlements(tier)
    max_devices = plan.get("max_linked_devices", 0)

    if max_devices == 0:
        return billing_error(
            reason_code=ReasonCode.FEATURE_LOCKED,
            message="Device linking requires Racer plan or higher",
            current_plan=tier,
            required_plan="racer",
            upgrade_url="/billing?plan=RACER",
            status=403,
        )

    # Count existing confirmed devices
    cur = conn.execute(
        "SELECT COUNT(*) AS cnt FROM device_pairings "
        "WHERE user_id = %(uid)s AND status = 'confirmed' AND revoked_at IS NULL",
        {"uid": user_id},
    )
    row = cur.fetchone()
    count = (dict(row) if not isinstance(row, dict) else row).get("cnt", 0)
    if count >= max_devices:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Maximum {max_devices} devices allowed. Unlink a device first.",
            status=400,
        )

    # Find the pairing code
    cur = conn.execute(
        "SELECT id, pairing_id, device_name, expires_at FROM device_pairings "
        "WHERE pairing_code = %(code)s AND status = 'pending'",
        {"code": code},
    )
    row = cur.fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Invalid or expired pairing code", status=404)

    r = dict(row) if not isinstance(row, dict) else row

    # Check expiry
    expires = r.get("expires_at")
    if expires and isinstance(expires, datetime) and expires < datetime.now(timezone.utc):
        return api_error(ErrorCode.NOT_FOUND, "Pairing code has expired", status=410)

    # Generate device token
    device_token = secrets.token_hex(32)  # 64 chars
    token_hash = _hash_token(device_token)

    # Resolve default workspace
    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        from auth.workspace import get_default_workspace_id
        workspace_id = get_default_workspace_id(conn, user_id)

    # Update the pairing row
    conn.execute(
        "UPDATE device_pairings SET "
        "user_id = %(uid)s, workspace_id = %(wsid)s, "
        "device_token_hash = %(hash)s, status = 'confirmed', "
        "confirmed_at = now() "
        "WHERE id = %(pid)s",
        {"uid": user_id, "wsid": workspace_id, "hash": token_hash, "pid": r["id"]},
    )

    # Store plaintext token in Redis for one-time retrieval by logger poll
    import redis
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    r_client = redis.from_url(redis_url)
    r_client.setex(
        f"device_pair_token:{r['pairing_id']}",
        _POLL_AFTER_CONFIRM_TTL_S,
        device_token,
    )

    return api_response({
        "device_id": r["id"],
        "device_name": r.get("device_name"),
    })


@bp.route("/devices", methods=["GET"])
def list_devices():
    """List the user's linked devices."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    conn = get_pg_connection()
    cur = conn.execute(
        "SELECT id, device_name, status, last_seen_at, confirmed_at "
        "FROM device_pairings "
        "WHERE user_id = %(uid)s AND status = 'confirmed' AND revoked_at IS NULL "
        "ORDER BY confirmed_at DESC",
        {"uid": user_id},
    )
    devices = []
    for row in cur.fetchall():
        r = dict(row) if not isinstance(row, dict) else row
        devices.append({
            "id": r["id"],
            "device_name": r.get("device_name"),
            "status": r["status"],
            "last_seen_at": r.get("last_seen_at").isoformat() if r.get("last_seen_at") else None,
            "confirmed_at": r.get("confirmed_at").isoformat() if r.get("confirmed_at") else None,
        })

    return api_response(devices)


@bp.route("/devices/<int:device_id>", methods=["DELETE"])
def revoke_device(device_id: int):
    """Revoke (unlink) a device."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    conn = get_pg_connection()
    cur = conn.execute(
        "UPDATE device_pairings SET status = 'revoked', revoked_at = now(), "
        "device_token_hash = NULL "
        "WHERE id = %(did)s AND user_id = %(uid)s AND status = 'confirmed' "
        "RETURNING id",
        {"did": device_id, "uid": user_id},
    )
    row = cur.fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Device not found", status=404)

    return api_response({"revoked": True})
