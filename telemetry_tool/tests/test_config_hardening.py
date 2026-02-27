"""Config hardening validation tests for dev/production matrix."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_STRONG_SECRET = "a" * 40 + "Z9!"


def _load_config_with_env(monkeypatch, env: dict[str, str]):
    keys = {
        "ENV",
        "AUTH_REQUIRED",
        "TELEMETRY_JWT_SECRET",
        "TELEMETRY_SECRET_KEY",
        "USE_PG",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
        "OAUTH_REDIRECT_BASE",
        "FRONTEND_URL",
    }
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import web.config

    importlib.reload(web.config)
    return web.config.Config()


class TestConfigHardening:
    def test_dev_defaults_validate(self, monkeypatch):
        cfg = _load_config_with_env(monkeypatch, {})
        cfg.validate()

    def test_production_requires_explicit_auth(self, monkeypatch):
        cfg = _load_config_with_env(
            monkeypatch,
            {
                "ENV": "production",
                "TELEMETRY_JWT_SECRET": _STRONG_SECRET,
                "TELEMETRY_SECRET_KEY": _STRONG_SECRET,
            },
        )
        with pytest.raises(ValueError, match="AUTH_REQUIRED=1"):
            cfg.validate()

    def test_production_rejects_weak_secrets(self, monkeypatch):
        cfg = _load_config_with_env(
            monkeypatch,
            {
                "ENV": "production",
                "AUTH_REQUIRED": "1",
                "TELEMETRY_JWT_SECRET": "jwt-dev-secret-change-me",
                "TELEMETRY_SECRET_KEY": "telemetry-local-dev-key",
            },
        )
        with pytest.raises(ValueError, match="JWT_SECRET"):
            cfg.validate()

    def test_production_valid_with_strong_secrets(self, monkeypatch):
        cfg = _load_config_with_env(
            monkeypatch,
            {
                "ENV": "production",
                "AUTH_REQUIRED": "1",
                "TELEMETRY_JWT_SECRET": _STRONG_SECRET,
                "TELEMETRY_SECRET_KEY": _STRONG_SECRET,
            },
        )
        cfg.validate()

    def test_pg_requires_oauth_provider(self, monkeypatch):
        cfg = _load_config_with_env(
            monkeypatch,
            {
                "USE_PG": "1",
                "AUTH_REQUIRED": "1",
                "TELEMETRY_JWT_SECRET": _STRONG_SECRET,
                "TELEMETRY_SECRET_KEY": _STRONG_SECRET,
            },
        )
        with pytest.raises(ValueError, match="OAuth provider"):
            cfg.validate()

    def test_pg_accepts_complete_oauth_provider(self, monkeypatch):
        cfg = _load_config_with_env(
            monkeypatch,
            {
                "USE_PG": "1",
                "AUTH_REQUIRED": "1",
                "TELEMETRY_JWT_SECRET": _STRONG_SECRET,
                "TELEMETRY_SECRET_KEY": _STRONG_SECRET,
                "GOOGLE_CLIENT_ID": "google-id",
                "GOOGLE_CLIENT_SECRET": "google-secret",
                "OAUTH_REDIRECT_BASE": "https://api.example.com",
                "FRONTEND_URL": "https://app.example.com",
            },
        )
        cfg.validate()

    def test_hardening_summary_redacts_secret_values(self, monkeypatch):
        cfg = _load_config_with_env(
            monkeypatch,
            {
                "ENV": "production",
                "AUTH_REQUIRED": "1",
                "TELEMETRY_JWT_SECRET": _STRONG_SECRET,
                "TELEMETRY_SECRET_KEY": _STRONG_SECRET,
            },
        )
        summary = cfg.hardening_summary()
        serialized = str(summary)
        assert _STRONG_SECRET not in serialized
        assert summary["jwt_secret_strong"] is True
        assert summary["secret_key_strong"] is True
