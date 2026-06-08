"""Admin entitlements — cross-workspace views, anomaly detection, overrides.

Wraps the core entitlement system (auth/entitlements.py) with admin-facing
operations that bypass RLS and provide observability across all workspaces.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ── Override allowlist & bounds ─────────────────────────────────────────
# Only keys that appear in the entitlements dict built by
# auth.entitlements.get_user_entitlements are permitted.  Every other key
# is rejected so a billing_admin cannot inject arbitrary state.

# Maximum calendar duration for any single override.
OVERRIDE_MAX_DURATION_DAYS = 90

# Keys whose values must be booleans.
_OVERRIDE_BOOL_KEYS: frozenset[str] = frozenset({
    "api_access",
    "comparison_enabled",
    "coaching_plans_enabled",
    "visualization_enabled",
    "gamification",
    "badge_share_card",
    "live_monitoring",
    "device_sync",
    "auto_analyze_on_sync",
})

# Keys whose values must be non-negative integers (or -1 = unlimited).
# Each entry: key → (min_value, max_value) where -1 is always permitted as
# the unlimited sentinel for keys that support it.
_OVERRIDE_INT_KEYS: dict[str, tuple[int, int]] = {
    # (inclusive min, inclusive max); -1 = unlimited permitted separately
    "analyses_per_month":           (0, 10_000),  # -1 = unlimited allowed
    "upload_volume_mb_per_month":   (0, 500_000), # -1 = unlimited allowed
    "max_upload_size_mb":           (0, 10_000),  # -1 = unlimited allowed
    "max_session_data_mb":          (0, 10_000),  # -1 = unlimited allowed
    "raw_retention_days":           (1, 3_650),   # no unlimited sentinel
    "max_linked_devices":           (0, 100),
    "max_concurrent_jobs":          (1, 50),
    "race_strategy_max_duration_s": (0, 86_400 * 7),  # up to 1 week
    "telemetry_retention_days":     (1, 3_650),
}

# Keys that support -1 as the "unlimited" sentinel.
_OVERRIDE_INT_UNLIMITED_KEYS: frozenset[str] = frozenset({
    "analyses_per_month",
    "upload_volume_mb_per_month",
    "max_upload_size_mb",
    "max_session_data_mb",
})

# Keys whose values must be floats in a stated range.
_OVERRIDE_FLOAT_KEYS: dict[str, tuple[float, float]] = {
    "rate_multiplier": (0.1, 10.0),
}

# Keys whose values are free-form strings from a restricted set.
_OVERRIDE_STRING_KEYS: dict[str, frozenset[str]] = {
    "race_strategy_limit": frozenset({
        "none", "24h_complex", "unlimited",
    }),
    "race_strategy_params": frozenset({
        "none", "basic", "complex",
    }),
}

# All allowed override keys (union of all categories above).
OVERRIDE_ALLOWLIST: frozenset[str] = (
    _OVERRIDE_BOOL_KEYS
    | frozenset(_OVERRIDE_INT_KEYS)
    | frozenset(_OVERRIDE_FLOAT_KEYS)
    | frozenset(_OVERRIDE_STRING_KEYS)
)

# Threshold above which an active override is flagged as long-lived.
_ANOMALY_LONG_OVERRIDE_DAYS = 30


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


def _validate_override_key_value(override_key: str, override_value: str) -> None:
    """Validate override_key is allowlisted and override_value is in-range.

    Raises ValueError with a descriptive message on any violation.
    The value is expected as a JSON-encoded string (the DB column type).
    """
    if override_key not in OVERRIDE_ALLOWLIST:
        raise ValueError(
            f"Override key {override_key!r} is not permitted. "
            f"Allowed keys: {sorted(OVERRIDE_ALLOWLIST)}"
        )

    # Parse the value — it must be valid JSON.
    try:
        parsed = json.loads(override_value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(
            f"override_value must be valid JSON (got {override_value!r})"
        ) from exc

    # Boolean keys
    if override_key in _OVERRIDE_BOOL_KEYS:
        if not isinstance(parsed, bool):
            raise ValueError(
                f"Override key {override_key!r} requires a boolean value "
                f"(true/false), got {type(parsed).__name__}"
            )
        return

    # Integer keys
    if override_key in _OVERRIDE_INT_KEYS:
        if not isinstance(parsed, int) or isinstance(parsed, bool):
            raise ValueError(
                f"Override key {override_key!r} requires an integer value, "
                f"got {type(parsed).__name__}"
            )
        min_val, max_val = _OVERRIDE_INT_KEYS[override_key]
        if parsed == -1 and override_key in _OVERRIDE_INT_UNLIMITED_KEYS:
            return  # -1 = unlimited is explicitly permitted for these keys
        if not (min_val <= parsed <= max_val):
            raise ValueError(
                f"Override key {override_key!r} value {parsed} is out of range "
                f"[{min_val}, {max_val}] (use -1 for unlimited where supported)"
            )
        return

    # Float keys
    if override_key in _OVERRIDE_FLOAT_KEYS:
        if not isinstance(parsed, (int, float)) or isinstance(parsed, bool):
            raise ValueError(
                f"Override key {override_key!r} requires a numeric value, "
                f"got {type(parsed).__name__}"
            )
        min_val, max_val = _OVERRIDE_FLOAT_KEYS[override_key]
        if not (min_val <= float(parsed) <= max_val):
            raise ValueError(
                f"Override key {override_key!r} value {parsed} is out of range "
                f"[{min_val}, {max_val}]"
            )
        return

    # String enum keys
    if override_key in _OVERRIDE_STRING_KEYS:
        allowed_vals = _OVERRIDE_STRING_KEYS[override_key]
        if not isinstance(parsed, str) or parsed not in allowed_vals:
            raise ValueError(
                f"Override key {override_key!r} must be one of "
                f"{sorted(allowed_vals)}, got {parsed!r}"
            )
        return


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

    Hardening rules (fail-closed, defense-in-depth):
    - override_key must be in OVERRIDE_ALLOWLIST; arbitrary keys are rejected.
    - override_value must be valid JSON and in-range for its key type.
    - expires_at is mandatory; NULL (forever) overrides are rejected.
    - expires_at must be within OVERRIDE_MAX_DURATION_DAYS from now.
    """
    if not user_id and not workspace_id:
        raise ValueError("At least one of user_id or workspace_id required")

    # 1. Allowlist + value-range validation
    _validate_override_key_value(override_key, override_value)

    # 2. Require a bounded, non-NULL expires_at
    now_utc = datetime.now(timezone.utc)
    if expires_at is None:
        raise ValueError(
            "expires_at is required; open-ended (never-expiring) overrides are not permitted"
        )
    # Normalise naive datetimes to UTC
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= now_utc:
        raise ValueError("expires_at must be in the future")

    max_expires = now_utc + timedelta(days=OVERRIDE_MAX_DURATION_DAYS)
    if expires_at > max_expires:
        raise ValueError(
            f"expires_at exceeds the maximum allowed duration of "
            f"{OVERRIDE_MAX_DURATION_DAYS} days from now "
            f"(max: {max_expires.isoformat()})"
        )

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
    if row is None:
        conn.commit()
        raise RuntimeError("INSERT RETURNING id returned no row for entitlement_overrides")
    conn.commit()

    try:
        from admin.audit import log_admin_action
        log_admin_action(
            conn, admin_user_id=created_by, action="entitlement_override_created",
            target_type="user" if user_id else "workspace",
            target_id=str(user_id or workspace_id),
            reason=reason,
            details={"key": override_key, "value": override_value, "expires_at": expires_at.isoformat()},
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
    old_tier = user.get("plan_tier", "locked")

    sub_id = user.get("stripe_subscription_id")
    if not sub_id:
        # No active subscription → the zero-access locked floor (no free tier).
        new_tier = "locked"
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
    4. Tier mismatch: active subscription but tier is the locked floor
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

    # 4. Tier mismatch — active subscription but the locked (no-access) floor.
    # 'demo'/'free' are legacy aliases of 'locked'; catch un-migrated rows too.
    try:
        cur = conn.execute(
            "SELECT id, email, plan_tier, subscription_status "
            "FROM users "
            "WHERE subscription_status = 'active' "
            "AND (plan_tier IN ('locked', 'demo', 'free') OR plan_tier IS NULL) "
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

    # 5. Long-lived or powerful active overrides.
    # Flags any non-expired override that either:
    #   (a) has more than _ANOMALY_LONG_OVERRIDE_DAYS remaining, or
    #   (b) grants a high-privilege key (api_access=true or an unlimited quota).
    try:
        cur = conn.execute(
            "SELECT id, user_id, workspace_id, override_key, override_value, "
            "       expires_at, created_by "
            "FROM entitlement_overrides "
            "WHERE (expires_at IS NULL OR expires_at > NOW())"
        )
        now_utc = datetime.now(timezone.utc)
        _HIGH_PRIV_KEYS = frozenset({
            "api_access",
            "analyses_per_month",
            "upload_volume_mb_per_month",
            "max_upload_size_mb",
        })
        for row in cur.fetchall():
            r = dict(row) if not isinstance(row, dict) else row
            exp = r.get("expires_at")
            key = r.get("override_key", "")
            raw_val = r.get("override_value")

            # (a) Long-lived: NULL expiry or > threshold days remaining
            remaining_days: float | None = None
            if exp is None:
                remaining_days = float("inf")
                is_long = True
            else:
                if isinstance(exp, str):
                    try:
                        exp = datetime.fromisoformat(exp)
                    except ValueError:
                        exp = None
                if exp is not None:
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    remaining_days = (exp - now_utc).total_seconds() / 86400
                    is_long = remaining_days > _ANOMALY_LONG_OVERRIDE_DAYS
                else:
                    is_long = False

            # (b) Powerful grant: api_access=true or unlimited quota (-1)
            is_powerful = False
            if key in _HIGH_PRIV_KEYS and raw_val is not None:
                try:
                    parsed_val = json.loads(raw_val)
                    if key == "api_access" and parsed_val is True:
                        is_powerful = True
                    elif key in ("analyses_per_month",
                                 "upload_volume_mb_per_month",
                                 "max_upload_size_mb") and parsed_val == -1:
                        is_powerful = True
                except (json.JSONDecodeError, TypeError):
                    pass

            if is_long or is_powerful:
                anomalies.append(Anomaly(
                    anomaly_type="long_lived_override",
                    severity="warning",
                    user_id=r.get("user_id"),
                    workspace_id=r.get("workspace_id"),
                    details={
                        "override_id": r.get("id"),
                        "key": key,
                        "value": raw_val,
                        "expires_at": str(exp),
                        "remaining_days": remaining_days,
                        "is_powerful_grant": is_powerful,
                        "is_long_lived": is_long,
                    },
                ))
    except Exception:
        logger.debug("Long-lived override detection failed", exc_info=True)

    return anomalies
