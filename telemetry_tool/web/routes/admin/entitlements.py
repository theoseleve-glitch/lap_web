"""Admin entitlements routes — plans, usage, anomalies, overrides.

Endpoints:
- GET  /admin/entitlements/plans — plan definitions
- GET  /admin/entitlements/usage/:workspace_id — workspace usage
- GET  /admin/entitlements/anomalies — detected anomalies
- POST /admin/entitlements/overrides — create override
- POST /admin/entitlements/refresh/:user_id — refresh tier from Stripe
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, request

from web.api_utils import api_response, api_error, ErrorCode
from admin.entitlements import (
    get_workspace_usage_summary,
    create_override as create_override_service,
    detect_anomalies,
    refresh_user_tier,
)
from .middleware import require_superadmin, require_admin_role

logger = logging.getLogger(__name__)

bp = Blueprint("admin_entitlements", __name__)


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _serialize_row(row):
    r = dict(row) if not isinstance(row, dict) else row
    result = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


@bp.route("/entitlements/plans", methods=["GET"])
@require_superadmin
def list_plans():
    """List plan definitions."""
    conn = _get_conn()

    rows = conn.execute(
        "SELECT * FROM plan_definitions ORDER BY tier"
    ).fetchall()

    return api_response([_serialize_row(r) for r in rows])


@bp.route("/entitlements/usage/<int:workspace_id>", methods=["GET"])
@require_superadmin
def get_usage(workspace_id: int):
    """Get usage summary for a workspace."""
    conn = _get_conn()
    period = request.args.get("period")

    usage = get_workspace_usage_summary(conn, workspace_id, period)
    return api_response({"workspace_id": workspace_id, "usage": usage})


@bp.route("/entitlements/anomalies", methods=["GET"])
@require_superadmin
def list_anomalies():
    """Detect entitlement anomalies across all users."""
    conn = _get_conn()
    anomalies = detect_anomalies(conn)

    result = []
    for a in anomalies:
        result.append({
            "anomaly_type": a.anomaly_type,
            "severity": a.severity,
            "user_id": a.user_id,
            "workspace_id": a.workspace_id,
            "details": a.details,
        })

    return api_response(result)


@bp.route("/entitlements/overrides", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin", "billing_admin")
def create_override_route():
    """Create an entitlement override. Audited."""
    conn = _get_conn()
    body = request.get_json(silent=True) or {}

    override_key = body.get("override_key")
    override_value = body.get("override_value")
    reason = body.get("reason")

    if not override_key or not override_value or not reason:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "override_key, override_value, and reason are required",
            status=400,
        )

    user_id = body.get("user_id")
    workspace_id = body.get("workspace_id")

    if not user_id and not workspace_id:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "At least one of user_id or workspace_id required",
            status=400,
        )

    try:
        override_id = create_override_service(
            conn,
            override_key=override_key,
            override_value=override_value,
            reason=reason,
            user_id=user_id,
            workspace_id=workspace_id,
            created_by=getattr(g, "current_user_id", 0),
        )
    except ValueError as e:
        return api_error(ErrorCode.VALIDATION_ERROR, str(e), status=400)

    return api_response({"override_id": override_id})


@bp.route("/entitlements/refresh/<int:user_id>", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin", "billing_admin")
def refresh_tier(user_id: int):
    """Re-derive plan_tier from Stripe subscription. Audited."""
    conn = _get_conn()
    result = refresh_user_tier(
        conn, user_id, getattr(g, "current_user_id", 0)
    )

    if "error" in result:
        return api_error(ErrorCode.NOT_FOUND, result["error"], status=404)

    return api_response(result)
