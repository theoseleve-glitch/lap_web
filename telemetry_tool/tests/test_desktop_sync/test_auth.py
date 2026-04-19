"""Tests for DeviceAuth."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import json

import pytest

from desktop_sync.auth import DeviceAuth, AuthError
from desktop_sync.config import UserConfig


class TestIsAuthenticated:
    def test_not_authenticated_by_default(self, tmp_path):
        cfg = UserConfig(path=tmp_path / "config.json")
        auth = DeviceAuth(config=cfg)
        assert not auth.is_authenticated
        assert auth.device_token is None

    def test_authenticated_with_stored_token(self, tmp_path):
        cfg = UserConfig(path=tmp_path / "config.json")
        cfg.set("device_token", "tok_abc123")
        auth = DeviceAuth(config=cfg)
        assert auth.is_authenticated
        assert auth.device_token == "tok_abc123"


class TestDisconnect:
    def test_clears_all_auth_fields(self, tmp_path):
        cfg = UserConfig(path=tmp_path / "config.json")
        cfg.set("device_token", "tok_abc123")
        cfg.set("device_id", "dev_456")
        cfg.set("paired_email", "user@example.com")
        cfg.set("cached_plan_tier", "world_class")

        auth = DeviceAuth(config=cfg)
        auth.disconnect()

        assert cfg.get("device_token") is None
        assert cfg.get("device_id") is None
        assert cfg.get("paired_email") is None
        assert cfg.get("cached_plan_tier") is None


class TestFetchEntitlements:
    def test_returns_data_on_200(self, tmp_path):
        cfg = UserConfig(path=tmp_path / "config.json")
        cfg.set("device_token", "tok_abc123")
        cfg.cloud_api_url = "http://localhost:9999"
        auth = DeviceAuth(config=cfg)

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "data": {"plan_tier": "world_class", "email": "user@example.com"},
        }).encode()

        with patch("desktop_sync.auth.urlopen", return_value=mock_response):
            result = auth.fetch_entitlements()

        assert result["plan_tier"] == "world_class"
        assert result["email"] == "user@example.com"

    def test_raises_on_401(self, tmp_path):
        from urllib.error import HTTPError
        cfg = UserConfig(path=tmp_path / "config.json")
        cfg.set("device_token", "tok_expired")
        cfg.cloud_api_url = "http://localhost:9999"
        auth = DeviceAuth(config=cfg)

        exc = HTTPError("url", 401, "Unauthorized", {}, None)
        with patch("desktop_sync.auth.urlopen", side_effect=exc):
            with pytest.raises(AuthError, match="expired or revoked"):
                auth.fetch_entitlements()

        # Token should be cleared
        assert cfg.get("device_token") is None

    def test_raises_when_not_authenticated(self, tmp_path):
        cfg = UserConfig(path=tmp_path / "config.json")
        auth = DeviceAuth(config=cfg)
        with pytest.raises(AuthError, match="Not authenticated"):
            auth.fetch_entitlements()

    def test_raises_when_no_api_url(self, tmp_path):
        cfg = UserConfig(path=tmp_path / "config.json")
        cfg.set("device_token", "tok_abc")
        auth = DeviceAuth(config=cfg)
        with pytest.raises(AuthError, match="cloud_api_url"):
            auth.fetch_entitlements()
