"""Centralized billing entitlement resolver."""
from __future__ import annotations

ACTIVE_BILLING_STATUSES = {"active", "trialing", "past_due"}

PLAN_RANK = {
    "free": 0,
    "racer": 1,
    "paid": 1,
    "world_class": 2,
}


def resolve_entitlements(billing: dict | None) -> dict:
    """Resolve product entitlements from normalized billing fields."""
    billing = billing or {}
    plan_tier = (billing.get("plan_tier") or "free").strip().lower()
    billing_status = (billing.get("billing_status") or "inactive").strip().lower()

    is_paid = billing_status in ACTIVE_BILLING_STATUSES and PLAN_RANK.get(plan_tier, 0) > 0
    rank = PLAN_RANK.get(plan_tier, 0) if is_paid else 0

    return {
        "plan_tier": plan_tier if rank > 0 else "free",
        "billing_status": billing_status,
        "is_paid": is_paid,
        "entitlements": {
            "advanced_analytics": rank >= 1,
            "team_workspaces": rank >= 2,
        },
    }
