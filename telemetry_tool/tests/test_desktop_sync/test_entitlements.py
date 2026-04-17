"""Tests for CachedEntitlements and SyncPolicy."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from desktop_sync.auth import AuthError
from desktop_sync.entitlements import CachedEntitlements, SyncPolicy


class TestSyncPolicy:
    def test_world_class_enables_everything(self):
        p = SyncPolicy.from_entitlements({
            "plan_tier": "world_class",
            "entitlements": {"analyses_per_month": -1},
        })
        assert p.can_upload
        assert p.auto_upload
        assert p.auto_analyze
        assert p.plan_tier == "world_class"

    def test_racer_manual_only(self):
        p = SyncPolicy.from_entitlements({
            "plan_tier": "racer",
            "entitlements": {"analyses_per_month": 10},
        })
        assert p.can_upload
        assert not p.auto_upload
        assert not p.auto_analyze
        assert p.max_uploads_month == 10

    def test_free_blocks_upload(self):
        p = SyncPolicy.from_entitlements({"plan_tier": "free"})
        assert not p.can_upload
        assert not p.auto_upload
        assert not p.auto_analyze

    def test_free_default(self):
        p = SyncPolicy.free_default()
        assert not p.can_upload
        assert p.plan_tier == "free"


class TestCachedEntitlements:
    def test_returns_fresh_policy_on_fetch(self, tmp_path):
        from desktop_sync.config import UserConfig
        cfg = UserConfig(path=tmp_path / "config.json")

        mock_auth = MagicMock()
        mock_auth.is_authenticated = True
        mock_auth.fetch_entitlements.return_value = {
            "plan_tier": "world_class",
            "entitlements": {"analyses_per_month": -1},
        }

        cache = CachedEntitlements(auth=mock_auth, config=cfg)
        policy = cache.get_policy()
        assert policy.plan_tier == "world_class"
        assert policy.auto_upload
        mock_auth.fetch_entitlements.assert_called_once()

    def test_returns_cached_on_second_call(self, tmp_path):
        from desktop_sync.config import UserConfig
        cfg = UserConfig(path=tmp_path / "config.json")

        mock_auth = MagicMock()
        mock_auth.is_authenticated = True
        mock_auth.fetch_entitlements.return_value = {"plan_tier": "racer"}

        cache = CachedEntitlements(auth=mock_auth, config=cfg)
        cache.get_policy()
        cache.get_policy()
        # Only called once (cached)
        mock_auth.fetch_entitlements.assert_called_once()

    def test_falls_back_on_network_error(self, tmp_path):
        from desktop_sync.config import UserConfig
        cfg = UserConfig(path=tmp_path / "config.json")
        cfg.set("cached_plan_tier", "racer")

        mock_auth = MagicMock()
        mock_auth.is_authenticated = True
        mock_auth.fetch_entitlements.side_effect = AuthError("offline", "NETWORK_ERROR")

        cache = CachedEntitlements(auth=mock_auth, config=cfg)
        policy = cache.get_policy()
        # Falls back to persisted plan tier
        assert policy.plan_tier == "racer"
        assert policy.can_upload

    def test_returns_free_when_not_authenticated(self, tmp_path):
        from desktop_sync.config import UserConfig
        cfg = UserConfig(path=tmp_path / "config.json")

        mock_auth = MagicMock()
        mock_auth.is_authenticated = False

        cache = CachedEntitlements(auth=mock_auth, config=cfg)
        policy = cache.get_policy()
        assert policy.plan_tier == "free"
        assert not policy.can_upload

    def test_clears_on_token_expired(self, tmp_path):
        from desktop_sync.config import UserConfig
        cfg = UserConfig(path=tmp_path / "config.json")

        mock_auth = MagicMock()
        mock_auth.is_authenticated = True
        mock_auth.fetch_entitlements.side_effect = AuthError("expired", "TOKEN_EXPIRED")

        cache = CachedEntitlements(auth=mock_auth, config=cfg)
        policy = cache.get_policy()
        assert policy.plan_tier == "free"
        assert not policy.can_upload
