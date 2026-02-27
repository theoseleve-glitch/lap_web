"""Workspace/user tier entitlements and quota policy helpers."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


DEFAULT_TIER = "demo"


@dataclass(frozen=True)
class EntitlementPolicy:
    """Normalized capability snapshot for a subscription tier."""

    tier: str
    report_quota_monthly: int
    max_upload_size_mb: int
    api_access: bool
    strategy_live: bool
    exports: bool
    raw_retention_days: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TIER_POLICIES: dict[str, EntitlementPolicy] = {
    "demo": EntitlementPolicy(
        tier="Demo",
        report_quota_monthly=5,
        max_upload_size_mb=200,
        api_access=False,
        strategy_live=False,
        exports=False,
        raw_retention_days=7,
    ),
    "racer": EntitlementPolicy(
        tier="Racer",
        report_quota_monthly=40,
        max_upload_size_mb=1024,
        api_access=True,
        strategy_live=False,
        exports=True,
        raw_retention_days=30,
    ),
    "world-class": EntitlementPolicy(
        tier="World-Class",
        report_quota_monthly=200,
        max_upload_size_mb=4096,
        api_access=True,
        strategy_live=True,
        exports=True,
        raw_retention_days=180,
    ),
    "b2b": EntitlementPolicy(
        tier="B2B",
        report_quota_monthly=10_000,
        max_upload_size_mb=12 * 1024,
        api_access=True,
        strategy_live=True,
        exports=True,
        raw_retention_days=365,
    ),
}

_PLAN_TO_TIER = {
    "free": "demo",
    "trial": "demo",
    "demo": "demo",
    "racer": "racer",
    "pro": "racer",
    "active": "racer",
    "world-class": "world-class",
    "world_class": "world-class",
    "enterprise": "b2b",
    "b2b": "b2b",
}


def normalize_tier(raw_tier: str | None) -> str:
    """Map external plan/tier values to one of the canonical internal tiers."""
    if not raw_tier:
        return DEFAULT_TIER
    key = raw_tier.strip().lower()
    return _PLAN_TO_TIER.get(key, key if key in TIER_POLICIES else DEFAULT_TIER)


def get_policy_for_tier(tier: str | None) -> EntitlementPolicy:
    """Get the immutable policy object for a tier name/plan."""
    normalized = normalize_tier(tier)
    return TIER_POLICIES.get(normalized, TIER_POLICIES[DEFAULT_TIER])


def resolve_workspace_tier(conn, workspace_id: int, user_id: int | None = None) -> str:
    """Resolve effective tier from workspace plan, then owner/user billing plan."""
    row = conn.execute(
        "SELECT w.plan_tier AS workspace_tier, "
        "       owner.billing_plan AS owner_plan, "
        "       u.billing_plan AS user_plan "
        "FROM workspaces w "
        "LEFT JOIN users owner ON owner.id = w.owner_user_id "
        "LEFT JOIN users u ON u.id = %(user_id)s "
        "WHERE w.id = %(workspace_id)s",
        {"workspace_id": workspace_id, "user_id": user_id},
    ).fetchone()

    if not row:
        return DEFAULT_TIER

    data = dict(row)
    return normalize_tier(
        data.get("workspace_tier") or data.get("user_plan") or data.get("owner_plan")
    )


def get_workspace_entitlements(conn, workspace_id: int, user_id: int | None = None) -> dict[str, Any]:
    """Return capability snapshot for the effective workspace/user tier."""
    tier = resolve_workspace_tier(conn, workspace_id=workspace_id, user_id=user_id)
    policy = get_policy_for_tier(tier)
    out = policy.to_dict()
    out["tier_key"] = normalize_tier(tier)
    out["resolved_at"] = datetime.now(timezone.utc).isoformat()
    out["workspace_id"] = workspace_id
    if user_id is not None:
        out["user_id"] = user_id
    return out


def report_quota_remaining(policy: EntitlementPolicy, reports_used: int) -> int:
    """Compute remaining monthly report quota (never below zero)."""
    return max(policy.report_quota_monthly - max(0, reports_used), 0)
