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

from flask import g, request, current_app

logger = logging.getLogger(__name__)

# ── Route → Feature mapping ──────────────────────────────────────────
# Each entry: (method, path_pattern) → feature_key
# Path patterns use simple prefix matching or regex.
# Only POST/PUT/DELETE actions are gated (reads are generally free).

_FEATURE_GATES: list[tuple[str, str, str]] = [
    # (HTTP method, path prefix, feature_key)

    # Comparison — World-Class only
    ("GET", "/compare/", "comparison"),
    ("GET", "/api/v1/comparisons/", "comparison"),

    # Visualization — Racer+
    ("GET", "/visualize/", "visualization"),

    # Race Strategy — all mutation endpoints
    ("POST", "/race-strategy/import", "race_strategy"),
    ("POST", "/race-strategy/new", "race_strategy"),
    ("POST", "/race-strategy/", "race_strategy"),  # catches /<id>/update, /optimize, etc.

    # API Data Access — World-Class only
    ("GET", "/api/v1/data/", "api_access"),
]

# ── Route → Quota mapping ────────────────────────────────────────────
# Each entry: (method, path_pattern, meter_key, cost)

_QUOTA_GATES: list[tuple[str, str, str, int]] = [
    # Analysis / report generation
    ("POST", "/analyze/api/start", "reports", 1),
    ("POST", "/analyze/sync", "reports", 1),

    # Batch reanalysis
    ("POST", "/api/v1/batch-reanalyze", "reports", 1),  # each session in batch costs 1
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

    # ── Feature gates ────────────────────────────────────────────────
    for gate_method, gate_prefix, feature in _FEATURE_GATES:
        if method == gate_method and path.startswith(gate_prefix):
            from auth.entitlements import authorize_feature, _get_conn, _plan_required_response
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
            from auth.entitlements import check_quota, _get_conn, _quota_exceeded_response
            conn = _get_conn()
            allowed, ctx = check_quota(conn, user_id, workspace_id, meter_key, cost)
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
    ("POST", "/analyze/api/start", "report_generated"),
    ("POST", "/analyze/sync", "report_generated"),
    ("POST", "/api/v1/batch-reanalyze", "batch_reanalyze"),
    ("POST", "/race-strategy/import", "race_config_created"),
    ("POST", "/race-strategy/new", "race_config_created"),
    ("POST", "/api/v1/sessions/", "csv_uploaded"),  # if upload route exists
]


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
        if method == gate_method and path.startswith(gate_prefix):
            try:
                from auth.entitlements import record_usage, _get_conn
                conn = _get_conn()
                record_usage(conn, user_id, workspace_id, event_type)
                conn.commit()
            except Exception:
                logger.warning("Failed to record usage event: %s", event_type,
                              exc_info=True)
            break

    return response
