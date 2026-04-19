"""Server-trusted entitlement cache for the desktop app.

Fetches the user's plan and feature flags from ``GET /api/v1/me``, caches
for 1 hour. Falls back to last-known state when offline. NEVER trusts
local-only values for paid features.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from desktop_sync.auth import AuthError, DeviceAuth
from desktop_sync.config import UserConfig

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 3600   # 1 hour


@dataclass(frozen=True)
class SyncPolicy:
    """What the desktop is allowed to do, derived from server entitlements."""
    can_upload: bool
    auto_upload: bool
    auto_analyze: bool
    max_uploads_month: int
    plan_tier: str

    @classmethod
    def from_entitlements(cls, ent: dict[str, Any]) -> "SyncPolicy":
        plan = ent.get("plan_tier", "free")
        entitlements = ent.get("entitlements", {})
        return cls(
            can_upload=plan in ("racer", "world_class"),
            auto_upload=plan == "world_class",
            auto_analyze=plan == "world_class",
            max_uploads_month=entitlements.get("analyses_per_month", 0),
            plan_tier=plan,
        )

    @classmethod
    def free_default(cls) -> "SyncPolicy":
        return cls(
            can_upload=False, auto_upload=False, auto_analyze=False,
            max_uploads_month=0, plan_tier="free",
        )


class CachedEntitlements:
    """Fetches + caches entitlements with TTL. Offline-safe."""

    def __init__(self, auth: DeviceAuth | None = None, config: UserConfig | None = None):
        self._auth = auth or DeviceAuth()
        self._config = config or UserConfig()
        self._cached_policy: SyncPolicy | None = None
        self._cached_at: float = 0.0

    def get_policy(self) -> SyncPolicy:
        """Return the current sync policy. Fetches if stale."""
        if self._is_cache_fresh():
            return self._cached_policy   # type: ignore[return-value]

        if not self._auth.is_authenticated:
            return SyncPolicy.free_default()

        try:
            ent = self._auth.fetch_entitlements()
            policy = SyncPolicy.from_entitlements(ent)
            self._cached_policy = policy
            self._cached_at = time.monotonic()
            # Persist for offline fallback
            self._config.set("cached_plan_tier", policy.plan_tier)
            logger.info("[ENTITLEMENTS] Fetched: plan=%s can_upload=%s auto=%s",
                       policy.plan_tier, policy.can_upload, policy.auto_upload)
            return policy
        except AuthError as exc:
            if exc.code == "TOKEN_EXPIRED":
                return SyncPolicy.free_default()
            # Network error → fall back to cached
            return self._offline_fallback()
        except Exception as exc:
            logger.warning("[ENTITLEMENTS] Fetch failed: %s — using fallback", exc)
            return self._offline_fallback()

    def _is_cache_fresh(self) -> bool:
        if self._cached_policy is None:
            return False
        return (time.monotonic() - self._cached_at) < _CACHE_TTL_S

    def _offline_fallback(self) -> SyncPolicy:
        """Use the last-known plan tier from config. Conservative defaults."""
        if self._cached_policy is not None:
            logger.info("[ENTITLEMENTS] Using in-memory cached policy (offline)")
            return self._cached_policy

        cached_tier = self._config.get("cached_plan_tier")
        if cached_tier:
            logger.info("[ENTITLEMENTS] Using persisted plan tier %r (offline)", cached_tier)
            return SyncPolicy.from_entitlements({"plan_tier": cached_tier})

        return SyncPolicy.free_default()
