"""Centralized entitlement enforcement middleware.

Maps API routes to required features and quotas. Runs as a ``before_request``
hook so all gating rules live in one place rather than scattered across 32
blueprint files.

Usage in ``create_app()``::

    from web.middleware.entitlements import entitlement_middleware
    app.before_request(entitlement_middleware)

The mapping approach means a pricing change is a config change in this file,
not a code change across 15 route files.
"""
from __future__ import annotations

import logging
import re

from flask import current_app, g, request

logger = logging.getLogger(__name__)

# ── Route → Feature mapping ──────────────────────────────────────────
# Each entry: (method, path_pattern) → feature_key
# Path patterns use simple prefix matching or regex.
# Only POST/PUT/DELETE actions are gated (reads are generally free).

_FEATURE_GATES: list[tuple] = [
    # (HTTP method, path prefix, feature_key[, required_suffix])
    # When a 4th element (suffix) is present, the path must ALSO end with
    # that suffix.  This prevents over-broad prefix matches such as gating
    # all of /api/v1/sessions/ behind visualization when only the
    # /api/v1/sessions/{id}/visualize sub-path should be gated.

    # Comparison — Racer+
    ("GET", "/compare/", "comparison"),
    ("GET", "/api/v1/comparisons/", "comparison"),
    ("GET", "/api/v1/compare/", "comparison"),

    # Visualization — Racer+
    ("GET", "/visualize/", "visualization"),
    ("GET", "/api/v1/sessions/", "visualization", "/visualize"),

    # Race Strategy — all mutation endpoints (both URL schemes)
    ("POST", "/race-strategy/", "race_strategy"),
    ("POST", "/api/v1/race-strategy/", "race_strategy"),
    ("PUT", "/api/v1/race-strategy/", "race_strategy"),
    ("DELETE", "/api/v1/race-strategy/", "race_strategy"),

    # Session → race bridge (creates a race from an uploaded endurance
    # session's detected stints) — same gate as the primary create path.
    ("POST", "/api/v1/sessions/", "race_strategy", "/endurance-race"),

    # API Data Access — World-Class only
    ("GET", "/api/v1/data/", "api_access"),

    # Exports — Racer+
    ("POST", "/api/data/export/", "exports"),
    ("POST", "/api/v1/exports/", "exports"),

    # Simulations — Racer+
    ("POST", "/api/data/simulate-race", "race_strategy"),
    ("POST", "/api/data/what-if", "race_strategy"),
    ("POST", "/api/data/weight-simulation", "race_strategy"),
    ("POST", "/api/data/weight-scenarios", "race_strategy"),
]

# ── Route → Quota mapping ────────────────────────────────────────────
# Each entry: (method, path_pattern, meter_key, cost)

_QUOTA_GATES: list[tuple[str, str, str, int]] = [
    # Every upload runs the full pipeline inline — one unified "analyses" meter
    ("POST", "/api/v1/sessions/upload", "analyses", 1),
    ("POST", "/api/data/files/upload", "analyses", 1),
    ("POST", "/api/v1/files/upload", "analyses", 1),
    ("POST", "/api/v1/ingest/start", "analyses", 1),
    ("POST", "/analyze/api/start", "analyses", 1),
    ("POST", "/analyze/sync", "analyses", 1),
    ("POST", "/api/v1/batch-reanalyze", "analyses", 1),
]

# ── Paths explicitly excluded from gating ────────────────────────────
_EXEMPT_PREFIXES = (
    "/auth/",
    "/healthz",
    "/api/v1/billing/",
    "/api/v1/me",
    "/api/v1/account/",
    "/api/v1/workspaces/",
    "/api/v1/teams/",
    "/static/",
)


# ── Grace period policy matrix ──────────────────────────────────────
# billing_state → action_category → allowed (True/False)
#
# Action categories:
#   ACCESS_VIEW  — read sessions, laps, dashboard, track list
#   EXPORT       — download CSV/PDF, report download
#   COMPUTE      — analysis, batch reanalyze, pipeline tasks
#   UPLOAD       — file upload, ingest
#   API_WRITE    — any POST/PUT/DELETE (catch-all for mutations)

GRACE_POLICY: dict[str, dict[str, bool]] = {
    "active":   {"ACCESS_VIEW": True,  "EXPORT": True,  "COMPUTE": True,  "UPLOAD": True,  "API_WRITE": True},
    "trialing": {"ACCESS_VIEW": True,  "EXPORT": True,  "COMPUTE": True,  "UPLOAD": True,  "API_WRITE": True},
    "past_due": {"ACCESS_VIEW": True,  "EXPORT": True,  "COMPUTE": True,  "UPLOAD": False, "API_WRITE": True},
    "canceled": {"ACCESS_VIEW": True,  "EXPORT": True,  "COMPUTE": False, "UPLOAD": False, "API_WRITE": False},
    "paused":   {"ACCESS_VIEW": True,  "EXPORT": False, "COMPUTE": False, "UPLOAD": False, "API_WRITE": False},
    "unpaid":   {"ACCESS_VIEW": True,  "EXPORT": False, "COMPUTE": False, "UPLOAD": False, "API_WRITE": False},
    # Subscription fully ended (one-membership: no free tier to fall back to).
    # View existing data only — no new analysis/upload/export/mutations.
    # Without this row, 'expired' fell through to the active default = FULL
    # access (a fail-OPEN gap) until the daily grace-job repointed plan_tier.
    "expired":  {"ACCESS_VIEW": True,  "EXPORT": False, "COMPUTE": False, "UPLOAD": False, "API_WRITE": False},
    # New / never-subscribed users (subscription_status='free'). The free
    # *status* still exists; the free *tier* does not — they are view-only
    # and must start the trial/subscribe to do anything.
    "free":     {"ACCESS_VIEW": True,  "EXPORT": False, "COMPUTE": False, "UPLOAD": False, "API_WRITE": False},
}

# Route → action category mapping
_ACTION_CATEGORY_OVERRIDES: list[tuple[str, str, str]] = [
    # (method, path_prefix, category)
    ("POST", "/analyze/", "COMPUTE"),
    ("POST", "/api/v1/batch-reanalyze", "COMPUTE"),
    ("POST", "/api/data/files/upload", "UPLOAD"),
    ("POST", "/api/v1/files/upload", "UPLOAD"),
    ("POST", "/api/v1/ingest/start", "UPLOAD"),
    ("POST", "/api/v1/sessions/upload", "UPLOAD"),
    ("POST", "/api/v1/exports/", "EXPORT"),
    ("POST", "/api/data/export/", "EXPORT"),
    ("GET", "/api/v1/exports/", "EXPORT"),
]


def _classify_action(method: str, path: str) -> str:
    """Classify a request into an action category for grace policy checks."""
    for gate_method, gate_prefix, category in _ACTION_CATEGORY_OVERRIDES:
        if method == gate_method and path.startswith(gate_prefix):
            return category
    if method == "GET":
        return "ACCESS_VIEW"
    return "API_WRITE"


def entitlement_middleware():
    """Before-request hook: enforce plan-based feature and quota gates.

    Runs after auth + tenant middleware (needs g.current_user_id and
    g.workspace_id). Skips if PG mode is off or user is not authenticated.
    """
    if not current_app.config.get("USE_PG"):
        return  # SQLite mode — no entitlements

    if not current_app.config.get("AUTH_REQUIRED"):
        return  # Legacy mode — no entitlements

    # Skip exempt paths
    path = request.path
    if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return

    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return  # Auth middleware handles 401

    method = request.method

    # ── Billing state enforcement (grace period policy matrix) ───────
    # Only applies when the user has a non-demo plan_tier.
    # The locked floor (and legacy demo/free aliases) is already zero-access
    # via its tier entitlements, so it skips the subscription-status gate —
    # which keeps new/locked users able to reach checkout. The gate applies to
    # real paid tiers (racer/world-class), where it now also covers 'expired'
    # (previously fell through to full access — a fail-open gap).
    plan_tier = getattr(g, "plan_tier", "locked")
    if plan_tier not in ("locked", "demo", "free", None):
        from auth.entitlements import _get_conn as _ent_conn
        from auth.entitlements import get_user_subscription_status
        conn = _ent_conn()
        sub_status = get_user_subscription_status(conn, user_id)

        # For canceled: check if grace period has expired → treat as "unpaid"
        effective_status = sub_status
        if sub_status == "canceled":
            cur = conn.execute(
                "SELECT grace_period_end FROM users WHERE id = %(uid)s",
                {"uid": user_id},
            )
            row = cur.fetchone()
            if row:
                from datetime import datetime, timezone
                grace_end = (dict(row) if not isinstance(row, dict) else row).get("grace_period_end")
                if grace_end is not None:
                    if hasattr(grace_end, "tzinfo") and grace_end.tzinfo is None:
                        grace_end = grace_end.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) > grace_end:
                        effective_status = "unpaid"  # Grace expired → full block

        policy = GRACE_POLICY.get(effective_status, GRACE_POLICY["active"])
        action_category = _classify_action(method, path)

        if not policy.get(action_category, True):
            from web.api_utils import ReasonCode, billing_error

            reason_map = {
                "unpaid": (ReasonCode.SUBSCRIPTION_UNPAID, "Your subscription payment is overdue. Please update your payment method."),
                "canceled": (ReasonCode.SUBSCRIPTION_CANCELED, "Your subscription has been canceled. This action is not available during the grace period."),
                "paused": (ReasonCode.SUBSCRIPTION_PAUSED, "Your subscription is paused. Resume to use this feature."),
                "past_due": (ReasonCode.SUBSCRIPTION_UNPAID, "Your payment is past due. Uploads are blocked until resolved."),
            }
            reason_code, message = reason_map.get(
                effective_status,
                (ReasonCode.SUBSCRIPTION_UNPAID, "Action not available in current billing state."),
            )
            return billing_error(
                reason_code=reason_code,
                message=message,
                current_plan=plan_tier,
                status=403,
            )

    # ── Feature gates ────────────────────────────────────────────────
    for gate_entry in _FEATURE_GATES:
        gate_method, gate_prefix, feature = gate_entry[0], gate_entry[1], gate_entry[2]
        gate_suffix = gate_entry[3] if len(gate_entry) > 3 else None
        if method == gate_method and path.startswith(gate_prefix):
            if gate_suffix and not path.endswith(gate_suffix):
                continue
            from auth.entitlements import _get_conn, _plan_required_response, authorize_feature
            conn = _get_conn()
            allowed, ctx = authorize_feature(conn, user_id, feature)
            if not allowed:
                logger.info("Feature gate blocked: user=%s feature=%s path=%s",
                            user_id, feature, path)
                return _plan_required_response(feature, ctx)
            break  # Only apply first matching gate

    # ── Quota gates ──────────────────────────────────────────────────
    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return  # No workspace context — quota checks need workspace

    for gate_method, gate_prefix, meter_key, cost in _QUOTA_GATES:
        if method == gate_method and path.startswith(gate_prefix):
            from auth.entitlements import (
                _get_conn,
                _quota_exceeded_response,
                check_and_record_quota,
            )
            conn = _get_conn()
            allowed, ctx = check_and_record_quota(conn, user_id, workspace_id, meter_key, cost)
            if not allowed:
                logger.info("Quota gate blocked: user=%s meter=%s path=%s",
                            user_id, meter_key, path)
                return _quota_exceeded_response(meter_key, ctx)
            break


def record_request_usage():
    """After-request hook: record usage for successful mutation requests.

    Only records usage for routes that match the usage mapping and
    returned a 2xx status code.
    """
    # This is called from @app.after_request — no return value check here.
    # Instead, we check in the after_request wrapper.
    pass


# ── Usage recording mapping ──────────────────────────────────────────
# Maps successful requests to usage event types.
# Called from an after_request hook in app.py.

_USAGE_EVENTS: list[tuple[str, str, str]] = [
    # (method, path_prefix, event_type)
    # All upload/analyze routes are recorded atomically by check_and_record_quota
    # Only non-quota events need after-request recording:
    ("POST", "/race-strategy/import", "race_config_created"),
    ("POST", "/race-strategy/new", "race_config_created"),
]


# Routes where usage is already recorded atomically by check_and_record_quota
_ATOMIC_QUOTA_ROUTES: set[tuple[str, str]] = {
    ("POST", "/analyze/api/start"),
    ("POST", "/analyze/sync"),
    ("POST", "/api/v1/batch-reanalyze"),
    ("POST", "/api/v1/sessions/upload"),
    ("POST", "/api/data/files/upload"),
    ("POST", "/api/v1/files/upload"),
    ("POST", "/api/v1/ingest/start"),
}


def record_successful_usage(response):
    """After-request hook: record usage for successful mutations.

    Only records if response status is 2xx and route matches _USAGE_EVENTS.
    Fails silently — usage recording should never break the response.
    """
    if not current_app.config.get("USE_PG"):
        return response

    if response.status_code < 200 or response.status_code >= 300:
        return response

    user_id = getattr(g, "current_user_id", None)
    workspace_id = getattr(g, "workspace_id", None)
    if user_id is None or workspace_id is None:
        return response

    path = request.path
    method = request.method

    for gate_method, gate_prefix, event_type in _USAGE_EVENTS:
        if (gate_method, gate_prefix) in _ATOMIC_QUOTA_ROUTES:
            continue
        if method == gate_method and path.startswith(gate_prefix):
            try:
                from auth.entitlements import _get_conn, record_usage
                conn = _get_conn()
                record_usage(conn, user_id, workspace_id, event_type)
                conn.commit()
            except Exception:
                logger.warning("Failed to record usage event: %s", event_type,
                              exc_info=True)
            break

    return response


# ── Decorator-based entitlement enforcement ───────────────────────────
# Per-route decorators for feature, quota, and upload-size enforcement.
# These use entitlement_snapshot() so tests can mock at the middleware level.

from datetime import datetime, timezone
from functools import wraps

from auth.entitlements import get_plan_entitlements, get_user_entitlements
from web.api_utils import ErrorCode, api_error


def _get_conn():
    if current_app.config.get("USE_PG"):
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    from web.db import get_db_connection
    return get_db_connection()


def _identity() -> tuple[int | None, int | None]:
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        user_id = getattr(g, "user_id", None)
    workspace_id = getattr(g, "workspace_id", None)
    return user_id, workspace_id


def entitlement_snapshot() -> dict:
    """Resolve entitlement snapshot from request context.

    Fails CLOSED: if user_id or workspace_id cannot be resolved, returns the
    locked/zero-access entitlement snapshot instead of inheriting workspace-1's
    entitlements.  Never substitutes DEFAULT_WORKSPACE_ID for an unresolved
    workspace — doing so would grant workspace-1's grants to an unauthenticated
    or tenant-less caller.

    Uses Redis cache (cache-aside) when available. Falls back to DB.
    """
    user_id, workspace_id = _identity()
    if user_id is None or workspace_id is None:
        # Unresolved identity → return zero-access locked floor immediately.
        # Auth middleware is responsible for the 401; here we just ensure that
        # any downstream code that calls entitlement_snapshot() before the auth
        # check can't accidentally inherit real grants.
        locked = get_plan_entitlements("locked")
        return {
            "plan_tier": "locked",
            "subscription_status": "none",
            "analyses_per_month": locked["analyses_per_month"],
            "analyses_used": 0,
            "analyses_remaining": 0,
            "upload_volume_mb_per_month": locked["upload_volume_mb_per_month"],
            "upload_volume_mb_used": 0,
            "upload_volume_mb_remaining": 0,
            "max_upload_size_mb": locked["max_upload_size_mb"],
            "max_session_data_mb": locked["max_session_data_mb"],
            "api_access": False,
            "comparison_enabled": False,
            "coaching_plans_enabled": False,
            "visualization_enabled": False,
            "gamification": False,
            "badge_share_card": False,
            "live_monitoring": False,
            "device_sync": False,
            "auto_analyze_on_sync": False,
            "max_linked_devices": 0,
            "race_strategy_limit": locked["strategy_dashboard"],
            "export_formats": ["csv"],
            "max_concurrent_jobs": 1,
            "rate_multiplier": 1.0,
            "_locked_by_missing_identity": True,
        }
    try:
        from web.entitlement_cache import cached_entitlements
        return cached_entitlements(user_id, workspace_id)
    except Exception:
        conn = _get_conn()
        return get_user_entitlements(conn, user_id=user_id, workspace_id=workspace_id)


def require_feature(feature_name: str):
    """Gate a route behind a feature flag using authorize_feature()."""

    def _decorator(fn):
        @wraps(fn)
        def _wrapped(*args, **kwargs):
            # Skip entitlement check if PG mode or auth is off
            if not current_app.config.get("USE_PG") or not current_app.config.get("AUTH_REQUIRED"):
                return fn(*args, **kwargs)

            user_id, _ = _identity()
            if user_id is None:
                return fn(*args, **kwargs)  # Auth middleware handles 401

            conn = _get_conn()
            from auth.entitlements import authorize_feature as _authorize
            allowed, ctx = _authorize(conn, user_id, feature_name)
            if not allowed:
                from web.api_utils import ReasonCode, billing_error
                return billing_error(
                    reason_code=ReasonCode.FEATURE_LOCKED,
                    message=ctx.get("reason", f"Feature '{feature_name}' requires a plan upgrade."),
                    current_plan=ctx.get("current_tier"),
                    required_plan=ctx.get("upgrade_tier"),
                    upgrade_url=ctx.get("upgrade_url"),
                    status=403,
                )
            g.entitlement_snapshot = ctx
            return fn(*args, **kwargs)

        return _wrapped

    return _decorator


def require_report_quota(fn):
    """Check monthly analyses quota before allowing report generation."""

    @wraps(fn)
    def _wrapped(*args, **kwargs):
        snapshot = entitlement_snapshot()

        policy = get_plan_entitlements(snapshot.get("plan_tier", "locked"))
        limit = policy.get("analyses_per_month", 0)
        used = snapshot.get("analyses_used", 0)
        remaining = max(0, limit - used) if limit != -1 else 999
        if remaining <= 0:
            from web.api_utils import ErrorCode, ReasonCode, billing_error
            return billing_error(
                reason_code=ReasonCode.LIMIT_EXCEEDED,
                message="Monthly analyses quota exceeded.",
                current_plan=snapshot.get("plan_tier"),
                error_code=ErrorCode.QUOTA_EXCEEDED,
                status=429,
                extra={
                    "limit": limit,
                    "used": used,
                    "remaining": 0,
                },
            )

        g.entitlement_snapshot = snapshot
        return fn(*args, **kwargs)

    return _wrapped


def require_upload_size(max_field_name: str = "file"):
    """Check upload request size against current entitlement tier limits."""

    def _decorator(fn):
        @wraps(fn)
        def _wrapped(*args, **kwargs):
            # SQLite / desktop mode — no entitlement tables, allow upload
            if not current_app.config.get("USE_PG"):
                return fn(*args, **kwargs)

            snapshot = entitlement_snapshot()
            max_bytes = int(snapshot.get("max_upload_size_mb", 0) * 1024 * 1024)

            uploaded = request.files.get(max_field_name)
            if uploaded and getattr(uploaded, "stream", None) is not None:
                stream = uploaded.stream
                pos = stream.tell()
                stream.seek(0, 2)
                actual_size = int(stream.tell())
                stream.seek(pos)
            elif uploaded and hasattr(uploaded, "content_length") and uploaded.content_length:
                actual_size = int(uploaded.content_length)
            else:
                actual_size = int(request.content_length or 0)

            if max_bytes > 0 and actual_size > max_bytes:
                return api_error(
                    ErrorCode.FILE_TOO_LARGE,
                    f"Upload exceeds your tier limit of {snapshot['max_upload_size_mb']} MB.",
                    status=413,
                )

            g.entitlement_snapshot = snapshot
            return fn(*args, **kwargs)

        return _wrapped

    return _decorator
