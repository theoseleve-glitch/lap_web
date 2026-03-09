"""Entitlement query functions.

Provides plan tier lookup and effective entitlement resolution with
per-request caching. All functions accept a DB connection and return
plain Python types (str, dict) — no Flask imports at module level.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def get_user_plan_tier(conn, user_id: int) -> str:
    """Return the plan tier for a user, cached in g.plan_tier.

    Falls back to ``'demo'`` if user not found or plan_tier is NULL.
    """
    from flask import g

    from web.queries import get_cached

    def _load():
        cur = conn.execute(
            "SELECT plan_tier FROM users WHERE id = :uid",
            {"uid": user_id},
        )
        row = cur.fetchone()
        tier = (row.get("plan_tier") if row else None) or "demo"
        g.plan_tier = tier
        return tier

    return get_cached("plan_tier", _load)


def get_plan_definition(conn, tier: str) -> dict:
    """Return the plan_definitions row for a tier as a dict."""
    cur = conn.execute(
        "SELECT * FROM plan_definitions WHERE tier = :tier",
        {"tier": tier},
    )
    row = cur.fetchone()
    return dict(row) if row else {}


def get_effective_entitlements(conn, user_id: int, workspace_id: int) -> dict:
    """Resolve effective entitlements: plan limits + overrides.

    Returns a dict with all plan_definition columns, overlaid with any
    active entitlement_overrides for this user/workspace.
    Cached per-request via ``get_cached``.
    """
    from web.queries import get_cached

    def _load():
        tier = get_user_plan_tier(conn, user_id)
        plan = get_plan_definition(conn, tier)
        if not plan:
            plan = get_plan_definition(conn, "demo")

        # Apply overrides (user-level or workspace-level, active only)
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "SELECT override_key, override_value FROM entitlement_overrides "
            "WHERE (user_id = :uid OR workspace_id = :wid) "
            "AND (expires_at IS NULL OR expires_at > :now)",
            {"uid": user_id, "wid": workspace_id, "now": now},
        )
        for row in cur.fetchall():
            key = row["override_key"]
            try:
                val = json.loads(row["override_value"])
                if isinstance(val, dict) and "value" in val:
                    plan[key] = val["value"]
                else:
                    plan[key] = val
            except (json.JSONDecodeError, TypeError):
                plan[key] = row["override_value"]

        return plan

    return get_cached("entitlements", _load)
