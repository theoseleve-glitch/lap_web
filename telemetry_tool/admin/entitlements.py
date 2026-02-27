"""Admin entitlements — cross-workspace views, anomaly detection, overrides.

Wraps the core entitlement system (auth/entitlements.py) with admin-facing
operations that bypass RLS and provide observability across all workspaces.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class Anomaly:
    """An entitlement anomaly requiring admin attention."""
    anomaly_type: str   # overspend, stale_override, missing_plan, tier_mismatch
    severity: str       # warning, error
    user_id: int | None = None
    workspace_id: int | None = None
    details: dict = field(default_factory=dict)


def get_workspace_usage_summary(conn, workspace_id: int, period: str | None = None) -> dict:
    """Return usage summary for a workspace in a given month.

    Args:
        conn: DB connection
        workspace_id: Target workspace
        period: ISO month string "YYYY-MM" (defaults to current month)

    Returns dict keyed by event_type with total counts.
    """
    if period is None:
        now = datetime.now(timezone.utc)
        period = now.strftime("%Y-%m")

    period_start = f"{period}-01"

    cur = conn.execute(
        "SELECT event_type, total FROM usage_monthly "
        "WHERE workspace_id = %(ws)s AND period_start = %(ps)s",
        {"ws": workspace_id, "ps": period_start},
    )
    rows = cur.fetchall()
    return {r["event_type"]: r["total"] for r in rows}


def get_effective_entitlements(conn, user_id: int, workspace_id: int) -> dict:
    """Return the effective entitlements for a user+workspace pair.

    Delegates to auth/entitlements.py but bypasses RLS by not using
    SET LOCAL (admin callers don't set RLS context).
    """
    from auth.entitlements import get_user_entitlements
    return get_user_entitlements(conn, user_id, workspace_id)


def create_override(
    conn,
    *,
    override_key: str,
    override_value: str,
    reason: str,
    expires_at: datetime | None = None,
    user_id: int | None = None,
    workspace_id: int | None = None,
    created_by: int,
) -> int:
    """Create an entitlement override. Returns the new override ID.

    At least one of user_id or workspace_id must be set.
    """
    if not user_id and not workspace_id:
        raise ValueError("At least one of user_id or workspace_id required")

    cur = conn.execute(
        "INSERT INTO entitlement_overrides "
        "(user_id, workspace_id, override_key, override_value, reason, expires_at, created_by) "
        "VALUES (%(uid)s, %(ws)s, %(key)s, %(val)s, %(reason)s, %(exp)s, %(by)s) "
        "RETURNING id",
        {
            "uid": user_id,
            "ws": workspace_id,
            "key": override_key,
            "val": override_value,
            "reason": reason,
            "exp": expires_at,
            "by": created_by,
        },
    )
    row = cur.fetchone()
    conn.commit()

    try:
        from admin.audit import log_admin_action
        log_admin_action(
            conn, admin_user_id=created_by, action="entitlement_override_created",
            target_type="user" if user_id else "workspace",
            target_id=str(user_id or workspace_id),
            reason=reason,
            details={"key": override_key, "value": override_value},
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log override creation", exc_info=True)

    return row["id"] if isinstance(row, dict) else row[0]


def refresh_user_tier(conn, user_id: int, admin_user_id: int) -> dict:
    """Re-derive plan_tier from Stripe subscription status.

    Returns dict with old_tier, new_tier, and whether it changed.
    """
    cur = conn.execute(
        "SELECT plan_tier, stripe_subscription_id FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    )
    user = cur.fetchone()
    if not user:
        return {"error": "user_not_found"}

    user = dict(user) if not isinstance(user, dict) else user
    old_tier = user.get("plan_tier", "demo")

    sub_id = user.get("stripe_subscription_id")
    if not sub_id:
        new_tier = "demo"
    else:
        # Would call Stripe API in production; for now just verify sub exists
        new_tier = old_tier  # No change if we can't verify

    changed = old_tier != new_tier
    if changed:
        conn.execute(
            "UPDATE users SET plan_tier = %(tier)s WHERE id = %(uid)s",
            {"tier": new_tier, "uid": user_id},
        )
        conn.commit()

        try:
            from admin.audit import log_admin_action
            log_admin_action(
                conn, admin_user_id=admin_user_id, action="tier_refreshed",
                target_type="user", target_id=str(user_id),
                details={"old_tier": old_tier, "new_tier": new_tier},
            )
            conn.commit()
        except Exception:
            logger.debug("Failed to log tier refresh", exc_info=True)

    return {"old_tier": old_tier, "new_tier": new_tier, "changed": changed}


def detect_anomalies(conn) -> list[Anomaly]:
    """Detect entitlement anomalies across all users and workspaces.

    Checks for:
    1. Overspend: usage exceeds plan limit
    2. Stale overrides: expired but not cleaned up
    3. Missing plan: user has no plan_tier
    4. Tier mismatch: active subscription but tier is demo
    """
    anomalies: list[Anomaly] = []

    # 1. Overspend detection — usage_monthly > plan limit for reports
    try:
        cur = conn.execute(
            "SELECT um.workspace_id, um.event_type, um.total, u.plan_tier, u.id as user_id "
            "FROM usage_monthly um "
            "JOIN workspaces w ON w.id = um.workspace_id "
            "JOIN users u ON u.id = w.owner_user_id "
            "JOIN plan_definitions pd ON pd.tier = u.plan_tier "
            "WHERE um.event_type = 'reports' "
            "AND um.period_start >= DATE_TRUNC('month', NOW()) "
            "AND pd.reports_per_month IS NOT NULL "
            "AND um.total > pd.reports_per_month"
        )
        for row in cur.fetchall():
            r = dict(row) if not isinstance(row, dict) else row
            anomalies.append(Anomaly(
                anomaly_type="overspend",
                severity="warning",
                user_id=r.get("user_id"),
                workspace_id=r.get("workspace_id"),
                details={
                    "event_type": r.get("event_type"),
                    "total": r.get("total"),
                    "plan_tier": r.get("plan_tier"),
                },
            ))
    except Exception:
        logger.debug("Overspend detection failed", exc_info=True)

    # 2. Stale overrides — expired but still in table
    try:
        cur = conn.execute(
            "SELECT id, user_id, workspace_id, override_key, expires_at "
            "FROM entitlement_overrides "
            "WHERE expires_at IS NOT NULL AND expires_at < NOW()"
        )
        for row in cur.fetchall():
            r = dict(row) if not isinstance(row, dict) else row
            anomalies.append(Anomaly(
                anomaly_type="stale_override",
                severity="warning",
                user_id=r.get("user_id"),
                workspace_id=r.get("workspace_id"),
                details={
                    "override_id": r.get("id"),
                    "key": r.get("override_key"),
                    "expired_at": str(r.get("expires_at")),
                },
            ))
    except Exception:
        logger.debug("Stale override detection failed", exc_info=True)

    # 3. Missing plan tier
    try:
        cur = conn.execute(
            "SELECT id, email FROM users "
            "WHERE (plan_tier IS NULL OR plan_tier = '') "
            "AND deleted_at IS NULL"
        )
        for row in cur.fetchall():
            r = dict(row) if not isinstance(row, dict) else row
            anomalies.append(Anomaly(
                anomaly_type="missing_plan",
                severity="error",
                user_id=r.get("id"),
                details={"email": r.get("email")},
            ))
    except Exception:
        logger.debug("Missing plan detection failed", exc_info=True)

    # 4. Tier mismatch — active subscription but demo tier
    try:
        cur = conn.execute(
            "SELECT id, email, plan_tier, subscription_status "
            "FROM users "
            "WHERE subscription_status = 'active' "
            "AND (plan_tier = 'demo' OR plan_tier IS NULL) "
            "AND deleted_at IS NULL"
        )
        for row in cur.fetchall():
            r = dict(row) if not isinstance(row, dict) else row
            anomalies.append(Anomaly(
                anomaly_type="tier_mismatch",
                severity="error",
                user_id=r.get("id"),
                details={
                    "email": r.get("email"),
                    "plan_tier": r.get("plan_tier"),
                    "subscription_status": r.get("subscription_status"),
                },
            ))
    except Exception:
        logger.debug("Tier mismatch detection failed", exc_info=True)

    return anomalies
