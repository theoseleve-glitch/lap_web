"""Entitlement resolution — single source of truth for plan-based access control.

Resolves what a user/workspace can do by merging:
  1. Plan tier defaults (from plan_definitions table)
  2. Active entitlement overrides (for grandfathering, promos, support credits)
  3. Current month usage (from usage_monthly table)

Usage::

    from auth.entitlements import get_user_entitlements, authorize_feature, check_quota

    ents = get_user_entitlements(conn, user_id, workspace_id)
    allowed, ctx = authorize_feature(conn, user_id, "comparison")
    allowed, ctx = check_quota(conn, user_id, workspace_id, "reports", cost=1)
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from functools import wraps

from flask import g, request

logger = logging.getLogger(__name__)

# ── Pure-Python plan entitlements (no DB dependency) ─────────────────
# Used for lightweight limit checks without a DB connection.

PLAN_ENTITLEMENTS: dict[str, dict] = {
    "free": {
        "reports_per_month": 1,
        "uploads_per_month": 1,
        "raw_retention_days": 30,
        "report_retention": "indefinite",
        "comparison_progress": False,
        "coaching_drills": False,
        "viz_workspace": False,
        "strategy_dashboard": "3h_limit",
        "live_pace": False,
        "pit_planning": False,
        "pdf_reports": False,
        "api_access": False,
        "track_management": "basic",
        "max_workspace_members": 1,
    },
    "racer": {
        "reports_per_month": 10,
        "uploads_per_month": 10,
        "raw_retention_days": 90,
        "report_retention": "indefinite",
        "comparison_progress": False,
        "coaching_drills": True,
        "viz_workspace": True,
        "strategy_dashboard": "full",
        "live_pace": True,
        "pit_planning": True,
        "pdf_reports": True,
        "api_access": False,
        "track_management": "full",
        "max_workspace_members": 1,
    },
    "world_class": {
        "reports_per_month": -1,  # unlimited
        "uploads_per_month": -1,
        "raw_retention_days": 365,
        "report_retention": "indefinite",
        "comparison_progress": True,
        "coaching_drills": True,
        "viz_workspace": True,
        "strategy_dashboard": "full",
        "live_pace": True,
        "pit_planning": True,
        "pdf_reports": True,
        "api_access": True,
        "track_management": "full",
        "max_workspace_members": 5,
    },
}

# "demo" is an alias for "free"
PLAN_ENTITLEMENTS["demo"] = PLAN_ENTITLEMENTS["free"]

KNOWN_PLANS = set(PLAN_ENTITLEMENTS.keys())

# Maps metric names to entitlement keys for usage limit checks
METRIC_TO_ENTITLEMENT: dict[str, str] = {
    "reports": "reports_per_month",
    "uploads": "uploads_per_month",
}


def get_plan_entitlements(plan: str) -> dict:
    """Return the entitlement dict for *plan*, falling back to free."""
    return PLAN_ENTITLEMENTS.get(plan, PLAN_ENTITLEMENTS["free"])


def check_usage_limit(
    plan: str, metric: str, current_count: int
) -> tuple[bool, dict]:
    """Check whether *current_count* of *metric* is within plan limits.

    Returns (allowed: bool, info: dict) where info contains
    limit, used, and remaining.  -1 means unlimited.
    """
    ent = get_plan_entitlements(plan)
    ent_key = METRIC_TO_ENTITLEMENT.get(metric)
    if ent_key is None:
        # Unknown metric — deny by default
        return False, {"limit": 0, "used": current_count, "remaining": 0}

    limit = ent.get(ent_key, 0)

    if limit == -1:  # unlimited
        return True, {"limit": -1, "used": current_count, "remaining": -1}

    remaining = max(0, limit - current_count)
    allowed = current_count < limit
    return allowed, {"limit": limit, "used": current_count, "remaining": remaining}


# ── Feature keys that map to boolean plan columns ──────────────────────
_BOOLEAN_FEATURES = {
    "api_access": "api_access",
    "comparison": "comparison_enabled",
    "coaching_plans": "coaching_plans_enabled",
    "visualization": "visualization_enabled",
    "live_monitoring": "live_monitoring",
}

# ── Feature keys that map to non-boolean plan columns ──────────────────
_LIMIT_FEATURES = {
    "reports_per_month": "reports_per_month",
    "max_upload_size_mb": "max_upload_size_mb",
    "telemetry_retention_days": "telemetry_retention_days",
    "max_concurrent_jobs": "max_concurrent_jobs",
    "rate_multiplier": "rate_multiplier",
}

# ── Upgrade path: which tier unlocks a feature ─────────────────────────
_UPGRADE_TIERS = {
    "api_access": "world-class",
    "comparison": "world-class",
    "coaching_plans": "racer",
    "visualization": "racer",
    "live_monitoring": "racer",
    "export_pdf": "racer",
    "race_strategy_full": "racer",
}

# ── Meter keys that map to quota columns ───────────────────────────────
_METER_TO_QUOTA = {
    "reports": "reports_per_month",
}


def get_plan_definitions(conn, tier: str) -> dict | None:
    """Fetch plan definition row for a tier. Returns dict or None."""
    cur = conn.execute(
        "SELECT * FROM plan_definitions WHERE tier = %(tier)s",
        {"tier": tier},
    )
    row = cur.fetchone()
    if row is None:
        return None
    return dict(row) if not isinstance(row, dict) else row


def get_user_plan_tier(conn, user_id: int) -> str:
    """Fast lookup for user's plan tier. Returns 'demo' as fallback."""
    cur = conn.execute(
        "SELECT plan_tier FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    )
    row = cur.fetchone()
    if row is None:
        return "demo"
    data = dict(row) if not isinstance(row, dict) else row
    return data.get("plan_tier") or "demo"


def get_user_subscription_status(conn, user_id: int) -> str:
    """Fast lookup for user's subscription status."""
    cur = conn.execute(
        "SELECT subscription_status FROM users WHERE id = %(uid)s",
        {"uid": user_id},
    )
    row = cur.fetchone()
    if row is None:
        return "free"
    data = dict(row) if not isinstance(row, dict) else row
    return data.get("subscription_status") or "free"


def _get_active_overrides(conn, user_id: int, workspace_id: int | None) -> dict:
    """Fetch non-expired entitlement overrides for user/workspace.

    Returns dict of override_key → override_value (parsed JSON).
    User-level overrides (workspace_id IS NULL) are fetched without RLS.
    """
    now = datetime.now(timezone.utc).isoformat()
    overrides = {}

    # User-level overrides (bypass RLS — these have NULL workspace_id)
    cur = conn.execute(
        "SELECT override_key, override_value FROM entitlement_overrides "
        "WHERE user_id = %(uid)s AND workspace_id IS NULL "
        "AND (expires_at IS NULL OR expires_at > %(now)s)",
        {"uid": user_id, "now": now},
    )
    for row in cur.fetchall():
        r = dict(row) if not isinstance(row, dict) else row
        try:
            overrides[r["override_key"]] = json.loads(r["override_value"])
        except (json.JSONDecodeError, TypeError):
            overrides[r["override_key"]] = r["override_value"]

    # Workspace-level overrides (within RLS scope)
    if workspace_id is not None:
        cur = conn.execute(
            "SELECT override_key, override_value FROM entitlement_overrides "
            "WHERE workspace_id = %(wsid)s "
            "AND (expires_at IS NULL OR expires_at > %(now)s)",
            {"wsid": workspace_id, "now": now},
        )
        for row in cur.fetchall():
            r = dict(row) if not isinstance(row, dict) else row
            try:
                overrides[r["override_key"]] = json.loads(r["override_value"])
            except (json.JSONDecodeError, TypeError):
                overrides[r["override_key"]] = r["override_value"]

    return overrides


def _get_current_month_usage(conn, workspace_id: int) -> dict:
    """Fetch usage_monthly totals for current month.

    Returns dict of event_type → total.
    """
    first_of_month = date.today().replace(day=1).isoformat()
    cur = conn.execute(
        "SELECT event_type, total FROM usage_monthly "
        "WHERE workspace_id = %(wsid)s AND period_start = %(period)s",
        {"wsid": workspace_id, "period": first_of_month},
    )
    usage = {}
    for row in cur.fetchall():
        r = dict(row) if not isinstance(row, dict) else row
        usage[r["event_type"]] = r["total"]
    return usage


def get_user_entitlements(conn, user_id: int, workspace_id: int | None = None) -> dict:
    """Resolve effective entitlements for a user.

    Priority: entitlement_overrides > plan_definitions > defaults.

    Returns dict with all feature keys, limits, and remaining quotas::

        {
            "plan_tier": "racer",
            "subscription_status": "active",
            "reports_per_month": 10,
            "reports_used": 3,
            "reports_remaining": 7,
            "api_access": False,
            "comparison_enabled": False,
            ...
        }
    """
    plan_tier = get_user_plan_tier(conn, user_id)
    sub_status = get_user_subscription_status(conn, user_id)
    plan = get_plan_definitions(conn, plan_tier)

    if plan is None:
        # Fallback to demo if tier not found
        plan = get_plan_definitions(conn, "demo") or {}

    # Start with plan defaults
    entitlements = {
        "plan_tier": plan_tier,
        "subscription_status": sub_status,
        "reports_per_month": plan.get("reports_per_month"),
        "max_upload_size_mb": plan.get("max_upload_size_mb", 500),
        "telemetry_retention_days": plan.get("telemetry_retention_days"),
        "api_access": plan.get("api_access", False),
        "comparison_enabled": plan.get("comparison_enabled", False),
        "coaching_plans_enabled": plan.get("coaching_plans_enabled", False),
        "visualization_enabled": plan.get("visualization_enabled", False),
        "race_strategy_limit": plan.get("race_strategy_limit"),
        "live_monitoring": plan.get("live_monitoring", False),
        "export_formats": _parse_json_or_default(plan.get("export_formats"), ["csv"]),
        "max_concurrent_jobs": plan.get("max_concurrent_jobs", 1),
        "rate_multiplier": plan.get("rate_multiplier", 1.0),
    }

    # Apply overrides
    if workspace_id is not None or user_id is not None:
        overrides = _get_active_overrides(conn, user_id, workspace_id)
        for key, value in overrides.items():
            if isinstance(value, dict) and "value" in value:
                entitlements[key] = value["value"]
            else:
                entitlements[key] = value

    # Add usage data if workspace is available
    if workspace_id is not None:
        usage = _get_current_month_usage(conn, workspace_id)
        reports_limit = entitlements.get("reports_per_month")
        reports_used = usage.get("report_generated", 0)
        entitlements["reports_used"] = reports_used
        entitlements["reports_remaining"] = (
            None if reports_limit is None
            else max(0, reports_limit - reports_used)
        )
    else:
        entitlements["reports_used"] = 0
        entitlements["reports_remaining"] = entitlements.get("reports_per_month")

    # Handle subscription status impact on entitlements
    # | active/trialing  | Full per plan           |
    # | past_due         | Full per plan (grace)   |
    # | canceled         | Downgrade to demo after period ends |
    # | paused           | Read-only (no new uploads/analyses) |
    if sub_status == "paused":
        # Paused: read-only access, block new uploads and analyses
        entitlements["_paused"] = True
        entitlements["reports_per_month"] = 0
        entitlements["reports_remaining"] = 0
    elif sub_status == "canceled":
        # Canceled: grace period features kept, but flag for downstream
        entitlements["_cancel_pending"] = True
    elif sub_status in ("active", "trialing"):
        # Full access per plan tier (default state, nothing to override)
        pass
    elif sub_status == "past_due":
        # Grace period: full access, but flag it
        entitlements["_past_due"] = True

    return entitlements


def authorize_feature(conn, user_id: int, feature: str) -> tuple[bool, dict]:
    """Check if a user can access a feature.

    Returns (allowed, context) where context contains:
    - allowed: bool
    - reason: str (if denied)
    - upgrade_tier: str (the tier that unlocks this feature)
    - current_tier: str
    """
    workspace_id = getattr(g, "workspace_id", None)
    entitlements = get_user_entitlements(conn, user_id, workspace_id)
    tier = entitlements["plan_tier"]

    # Check boolean features
    if feature in _BOOLEAN_FEATURES:
        col = _BOOLEAN_FEATURES[feature]
        allowed = bool(entitlements.get(col, False))
        if not allowed:
            upgrade_tier = _UPGRADE_TIERS.get(feature, "racer")
            return False, {
                "reason": f"{feature} requires {upgrade_tier} plan or higher",
                "upgrade_tier": upgrade_tier,
                "upgrade_url": f"/billing?plan={upgrade_tier.upper()}",
                "current_tier": tier,
            }
        return True, {"current_tier": tier}

    # Check export_pdf (derived from export_formats)
    if feature == "export_pdf":
        formats = entitlements.get("export_formats", ["csv"])
        if "pdf" not in formats:
            return False, {
                "reason": "PDF export requires Racer plan or higher",
                "upgrade_tier": "racer",
                "upgrade_url": "/billing?plan=RACER",
                "current_tier": tier,
            }
        return True, {"current_tier": tier}

    # Check race_strategy_full (demo has 3h limit)
    if feature == "race_strategy_full":
        limit = entitlements.get("race_strategy_limit")
        if limit == "limited_3h":
            return False, {
                "reason": "Full race strategy requires Racer plan or higher",
                "upgrade_tier": "racer",
                "upgrade_url": "/billing?plan=RACER",
                "current_tier": tier,
            }
        return True, {"current_tier": tier}

    # Check paused state
    if entitlements.get("_paused") and feature in ("upload", "analyze", "create"):
        return False, {
            "reason": "Subscription is paused. Resume to use this feature.",
            "current_tier": tier,
        }

    # Unknown feature — allow by default (fail open for non-gated features)
    return True, {"current_tier": tier}


def check_quota(conn, user_id: int, workspace_id: int, meter_key: str, cost: int = 1) -> tuple[bool, dict]:
    """Check if a quota-limited action is allowed.

    Returns (allowed, context) where context contains:
    - allowed: bool
    - remaining: int | None (None = unlimited)
    - limit: int | None
    - resets_at: str (ISO date of first of next month)
    """
    entitlements = get_user_entitlements(conn, user_id, workspace_id)

    quota_col = _METER_TO_QUOTA.get(meter_key)
    if quota_col is None:
        # No quota defined for this meter — allow
        return True, {"remaining": None, "limit": None}

    limit = entitlements.get(quota_col)
    if limit is None:
        # Unlimited
        return True, {"remaining": None, "limit": None}

    used = entitlements.get(f"{meter_key}_used", 0)
    remaining = max(0, limit - used)

    # Calculate next reset date (first of next month)
    today = date.today()
    if today.month == 12:
        resets_at = date(today.year + 1, 1, 1).isoformat()
    else:
        resets_at = date(today.year, today.month + 1, 1).isoformat()

    if remaining < cost:
        return False, {
            "remaining": remaining,
            "limit": limit,
            "used": used,
            "resets_at": resets_at,
        }

    return True, {
        "remaining": remaining - cost,
        "limit": limit,
        "used": used,
        "resets_at": resets_at,
    }


def check_and_record_quota(conn, user_id: int, workspace_id: int,
                           meter_key: str, cost: int = 1,
                           metadata: dict | None = None) -> tuple[bool, dict]:
    """Atomic check-then-record using SELECT FOR UPDATE on usage_monthly.

    Prevents concurrent over-spending by locking the monthly aggregate row
    before checking the quota and recording the usage event.

    Returns (allowed, context) — same shape as check_quota().
    """
    plan_tier = get_user_plan_tier(conn, user_id)
    plan = get_plan_definitions(conn, plan_tier) or {}

    quota_col = _METER_TO_QUOTA.get(meter_key)
    if quota_col is None:
        return True, {"remaining": None, "limit": None}

    limit = plan.get(quota_col)
    if limit is None:
        # Unlimited — record usage but don't enforce
        record_usage(conn, user_id, workspace_id, meter_key, cost, metadata)
        return True, {"remaining": None, "limit": None}

    first_of_month = date.today().replace(day=1).isoformat()

    # Lock the aggregate row (or create it) using SELECT FOR UPDATE
    cur = conn.execute(
        "SELECT total FROM usage_monthly "
        "WHERE workspace_id = %(wsid)s AND period_start = %(period)s "
        "AND event_type = %(etype)s FOR UPDATE",
        {"wsid": workspace_id, "period": first_of_month, "etype": meter_key},
    )
    row = cur.fetchone()
    current_total = 0
    if row is not None:
        r = dict(row) if not isinstance(row, dict) else row
        current_total = r.get("total", 0)

    remaining = max(0, limit - current_total)

    today = date.today()
    if today.month == 12:
        resets_at = date(today.year + 1, 1, 1).isoformat()
    else:
        resets_at = date(today.year, today.month + 1, 1).isoformat()

    if remaining < cost:
        return False, {
            "remaining": remaining,
            "limit": limit,
            "used": current_total,
            "resets_at": resets_at,
        }

    # Record the usage within the same transaction (row is locked)
    record_usage(conn, user_id, workspace_id, meter_key, cost, metadata)

    return True, {
        "remaining": remaining - cost,
        "limit": limit,
        "used": current_total + cost,
        "resets_at": resets_at,
    }


def record_usage(conn, user_id: int, workspace_id: int,
                 event_type: str, cost: int = 1, metadata: dict | None = None):
    """Record a usage event and update monthly aggregate.

    Inserts into usage_events and upserts usage_monthly.
    """
    meta_json = json.dumps(metadata) if metadata else None

    conn.execute(
        "INSERT INTO usage_events (user_id, workspace_id, event_type, cost, metadata_json) "
        "VALUES (%(uid)s, %(wsid)s, %(etype)s, %(cost)s, %(meta)s)",
        {"uid": user_id, "wsid": workspace_id, "etype": event_type,
         "cost": cost, "meta": meta_json},
    )

    # Upsert monthly aggregate
    first_of_month = date.today().replace(day=1).isoformat()
    conn.execute(
        "INSERT INTO usage_monthly (workspace_id, period_start, event_type, total) "
        "VALUES (%(wsid)s, %(period)s, %(etype)s, %(cost)s) "
        "ON CONFLICT (workspace_id, period_start, event_type) "
        "DO UPDATE SET total = usage_monthly.total + %(cost)s",
        {"wsid": workspace_id, "period": first_of_month,
         "etype": event_type, "cost": cost},
    )


def log_audit_event(conn, action: str, details: dict | None = None,
                    user_id: int | None = None, workspace_id: int | None = None):
    """Record an audit log entry.

    Uses g.user_id and g.workspace_id as defaults if available.
    """
    uid = user_id or getattr(g, "current_user_id", None)
    wsid = workspace_id or getattr(g, "workspace_id", None)
    ip = request.remote_addr if request else None
    details_json = json.dumps(details) if details else None

    conn.execute(
        "INSERT INTO audit_log (user_id, workspace_id, action, details_json, ip_address) "
        "VALUES (%(uid)s, %(wsid)s, %(action)s, %(details)s, %(ip)s)",
        {"uid": uid, "wsid": wsid, "action": action,
         "details": details_json, "ip": ip},
    )


# ── Flask decorators for route-level enforcement ─────────────────────

def require_feature(feature: str):
    """Decorator: denies if user's plan doesn't include this feature.

    Returns 403 with PLAN_REQUIRED error and upgrade CTA.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from web.api_utils import api_error, ErrorCode
            user_id = getattr(g, "current_user_id", None)
            if user_id is None:
                return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=401)

            conn = _get_conn()
            allowed, ctx = authorize_feature(conn, user_id, feature)
            if not allowed:
                return _plan_required_response(feature, ctx)

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_quota(meter_key: str, cost: int = 1):
    """Decorator: checks quota before running endpoint.

    Returns 429 with QUOTA_EXCEEDED error and quota info.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from web.api_utils import api_error, ErrorCode
            user_id = getattr(g, "current_user_id", None)
            workspace_id = getattr(g, "workspace_id", None)
            if user_id is None:
                return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=401)
            if workspace_id is None:
                return api_error(ErrorCode.FORBIDDEN, "No workspace context", status=403)

            conn = _get_conn()
            allowed, ctx = check_quota(conn, user_id, workspace_id, meter_key, cost)
            if not allowed:
                return _quota_exceeded_response(meter_key, ctx)

            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ── Helpers ──────────────────────────────────────────────────────────

def _get_conn():
    """Get database connection (same pattern as other modules)."""
    from flask import current_app
    if current_app.config.get("USE_PG"):
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    from web.db import get_db_connection
    return get_db_connection()


def _plan_required_response(feature: str, ctx: dict):
    """Build 403 response for plan-gated features."""
    from flask import jsonify
    return jsonify({
        "ok": False,
        "error": {
            "code": "PLAN_REQUIRED",
            "message": ctx.get("reason", f"{feature} is not available on your current plan"),
            "upgrade_tier": ctx.get("upgrade_tier"),
            "upgrade_url": ctx.get("upgrade_url"),
        },
        "meta": {},
    }), 403


def _quota_exceeded_response(meter_key: str, ctx: dict):
    """Build 429 response for quota-limited features."""
    from flask import jsonify
    return jsonify({
        "ok": False,
        "error": {
            "code": "QUOTA_EXCEEDED",
            "message": f"Monthly {meter_key} limit reached ({ctx.get('used', 0)}/{ctx.get('limit', 0)})",
            "limit": ctx.get("limit"),
            "remaining": ctx.get("remaining", 0),
            "used": ctx.get("used", 0),
            "resets_at": ctx.get("resets_at"),
        },
        "meta": {},
    }), 429


def _parse_json_or_default(value, default):
    """Parse a JSON string or return the value as-is if already parsed."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
