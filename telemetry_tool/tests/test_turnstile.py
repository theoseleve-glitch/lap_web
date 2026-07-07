"""Tests for auth.turnstile -- Cloudflare Turnstile step-up verification.

Fully mocked -- no live network calls. See auth/lockout.py::challenge_required
for the companion "should we even ask for a token?" decision; this module
only covers "is THIS token valid?".
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.turnstile import turnstile_configured, verify_turnstile


class TestTurnstileConfigured:
    def test_unconfigured_when_secret_unset(self, monkeypatch):
        monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
        assert turnstile_configured() is False

    def test_configured_when_secret_set(self, monkeypatch):
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x_test_secret")
        assert turnstile_configured() is True


class TestVerifyTurnstileDisabled:
    """Fix-not-configured sentinel: verify_turnstile() reports "not passed"
    without ever contacting Cloudflare when the feature is off."""

    def test_unset_secret_returns_false_without_network_call(self, monkeypatch):
        monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
        with patch("auth.turnstile.requests.post") as mock_post:
            result = verify_turnstile("some-token", "1.2.3.4")
        assert result is False
        mock_post.assert_not_called()


class TestVerifyTurnstileConfigured:
    def test_missing_token_returns_false_without_network_call(self, monkeypatch):
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x_test_secret")
        with patch("auth.turnstile.requests.post") as mock_post:
            result = verify_turnstile(None, "1.2.3.4")
        assert result is False
        mock_post.assert_not_called()

    def test_success_true_passes(self, monkeypatch):
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x_test_secret")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": True}
        with patch("auth.turnstile.requests.post", return_value=mock_resp) as mock_post:
            result = verify_turnstile("good-token", "1.2.3.4")
        assert result is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["data"]["secret"] == "0x_test_secret"
        assert kwargs["data"]["response"] == "good-token"
        assert kwargs["data"]["remoteip"] == "1.2.3.4"
        assert kwargs["timeout"] > 0

    def test_success_false_fails(self, monkeypatch):
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x_test_secret")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": False, "error-codes": ["invalid-input-response"]}
        with patch("auth.turnstile.requests.post", return_value=mock_resp):
            result = verify_turnstile("bad-token", "1.2.3.4")
        assert result is False

    def test_network_error_fails_closed(self, monkeypatch):
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x_test_secret")
        with patch(
            "auth.turnstile.requests.post",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            result = verify_turnstile("token", "1.2.3.4")
        assert result is False

    def test_timeout_fails_closed(self, monkeypatch):
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x_test_secret")
        with patch(
            "auth.turnstile.requests.post",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            result = verify_turnstile("token", "1.2.3.4")
        assert result is False

    def test_malformed_json_response_fails_closed(self, monkeypatch):
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x_test_secret")
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        with patch("auth.turnstile.requests.post", return_value=mock_resp):
            result = verify_turnstile("token", "1.2.3.4")
        assert result is False
