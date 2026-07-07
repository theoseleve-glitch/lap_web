"""Integration tests for the Turnstile step-up challenge on /auth/login.

See auth/turnstile.py (verify_turnstile) and auth/lockout.py
(challenge_required) for the underlying pieces this wires together. This
exercises the real Flask blueprint (mirroring tests/test_auth_login_abuse.py):

  - a flagged email without a token must get 428 challenge_required WITHOUT
    ever running password verification (not a password oracle);
  - a flagged email with a valid token must log in exactly as normal;
  - a flagged email with an invalid/missing token stays at 428;
  - an unflagged email must never see a 428 at all;
  - with Turnstile unconfigured, challenge_required() itself gates closed,
    so the route never returns 428 -- exercised against the REAL
    challenge_required() (not mocked) to prove the config-gate end to end.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import auth.lockout as lockout_mod
import web.rate_limit as rate_limit_mod
from web.api_utils import init_request_id
from web.routes.auth import bp as auth_bp


def _make_auth_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["JWT_SECRET"] = "test-secret-key-1234567890123456"
    init_request_id(app)
    app.register_blueprint(auth_bp)
    return app


def _conn_with_user(email: str, password_hash: str, user_id: int = 1):
    """Minimal DB-connection stub covering every query login() touches."""
    conn = MagicMock()

    def execute(sql, params=None):
        cur = MagicMock()
        if "SELECT id, email, password_hash" in sql:
            cur.fetchone.return_value = {
                "id": user_id,
                "email": email,
                "password_hash": password_hash,
                "display_name": "Test User",
                "totp_enabled": False,
            }
        elif "SELECT suspension_reason" in sql:
            cur.fetchone.return_value = None
        elif "SELECT 1 FROM audit_log" in sql:
            cur.fetchone.return_value = None
        elif "SELECT COUNT" in sql:
            cur.fetchone.return_value = {"cnt": 0}
        else:
            cur.fetchone.return_value = None
        return cur

    conn.execute.side_effect = execute
    return conn


@pytest.fixture(autouse=True)
def _reset_degraded_state():
    """Degraded-mode buckets are module-level (per-worker) -- reset around
    every test so these don't bleed into each other or other test modules."""
    rate_limit_mod._degraded_auth_buckets.clear()
    lockout_mod._degraded_buckets.clear()
    yield
    rate_limit_mod._degraded_auth_buckets.clear()
    lockout_mod._degraded_buckets.clear()


def _post_login(client, email, password, ip="203.0.113.50", token=None):
    payload = {"email": email, "password": password}
    if token is not None:
        payload["cf-turnstile-response"] = token
    return client.post("/auth/login", json=payload, environ_base={"REMOTE_ADDR": ip})


class TestChallengeRequiredLoginFlow:
    def test_flagged_email_without_token_gets_428_and_skips_password_check(self):
        from auth.service import hash_password

        password_hash = hash_password("correct-horse-battery-staple")
        conn = _conn_with_user("flagged@example.com", password_hash)
        app = _make_auth_app()
        client = app.test_client()

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=None),
            patch("auth.lockout._get_redis", return_value=None),
            patch("auth.lockout.challenge_required", return_value=True),
            patch("auth.turnstile.verify_turnstile") as mock_verify,
        ):
            # Even a WRONG password must not be checked -- a flagged email
            # without a token short-circuits to 428 before login_user() runs,
            # so the response can't be used to test password guesses.
            resp = _post_login(client, "flagged@example.com", "totally-wrong-password")

        assert resp.status_code == 428
        body = resp.get_json()
        assert body["data"]["challenge_required"] is True
        mock_verify.assert_not_called()

    def test_flagged_email_with_valid_token_logs_in_normally(self):
        from auth.service import hash_password

        password_hash = hash_password("correct-horse-battery-staple")
        conn = _conn_with_user("flagged2@example.com", password_hash)
        app = _make_auth_app()
        client = app.test_client()

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=None),
            patch("auth.lockout._get_redis", return_value=None),
            patch("auth.lockout.challenge_required", return_value=True),
            patch("auth.turnstile.verify_turnstile", return_value=True),
        ):
            resp = _post_login(
                client, "flagged2@example.com", "correct-horse-battery-staple",
                token="good-token",
            )

        assert resp.status_code == 200

    def test_flagged_email_with_invalid_token_stays_428(self):
        from auth.service import hash_password

        password_hash = hash_password("correct-horse-battery-staple")
        conn = _conn_with_user("flagged3@example.com", password_hash)
        app = _make_auth_app()
        client = app.test_client()

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=None),
            patch("auth.lockout._get_redis", return_value=None),
            patch("auth.lockout.challenge_required", return_value=True),
            patch("auth.turnstile.verify_turnstile", return_value=False),
        ):
            resp = _post_login(
                client, "flagged3@example.com", "correct-horse-battery-staple",
                token="bad-token",
            )

        assert resp.status_code == 428

    def test_unflagged_email_never_sees_428(self):
        from auth.service import hash_password

        password_hash = hash_password("correct-horse-battery-staple")
        conn = _conn_with_user("normal@example.com", password_hash)
        app = _make_auth_app()
        client = app.test_client()

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=None),
            patch("auth.lockout._get_redis", return_value=None),
            patch("auth.lockout.challenge_required", return_value=False),
        ):
            resp = _post_login(client, "normal@example.com", "correct-horse-battery-staple")

        assert resp.status_code == 200

    def test_unconfigured_turnstile_never_returns_428(self, monkeypatch):
        """Exercises the REAL challenge_required() (not mocked) to prove the
        config-gate end to end: with no TURNSTILE_SECRET_KEY set, even an
        email with a sky-high distinct-failing-IP count must not trip a 428."""
        from auth.service import hash_password

        monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
        monkeypatch.delenv("TURNSTILE_SITEKEY", raising=False)
        password_hash = hash_password("correct-horse-battery-staple")
        conn = _conn_with_user("real-gate@example.com", password_hash)
        app = _make_auth_app()
        client = app.test_client()

        r = MagicMock()
        r.scard.return_value = 999  # would flag if Turnstile were configured

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=None),
            patch("auth.lockout._get_redis", return_value=r),
        ):
            resp = _post_login(client, "real-gate@example.com", "correct-horse-battery-staple")

        assert resp.status_code == 200

    def test_secret_only_never_returns_428(self, monkeypatch):
        """Misconfig foot-gun (Fix #1): TURNSTILE_SECRET_KEY set WITHOUT
        TURNSTILE_SITEKEY must not activate the challenge, since the 428
        body would carry a null sitekey the widget can't render -- a
        secret-only config would soft-lock a flagged victim out for the
        whole detection window. Exercises the REAL challenge_required() ->
        turnstile_configured() gate end to end, same shape as the
        both-unset case above."""
        from auth.service import hash_password

        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x_test_secret")
        monkeypatch.delenv("TURNSTILE_SITEKEY", raising=False)
        password_hash = hash_password("correct-horse-battery-staple")
        conn = _conn_with_user("secret-only@example.com", password_hash)
        app = _make_auth_app()
        client = app.test_client()

        r = MagicMock()
        r.scard.return_value = 999  # would flag if Turnstile were fully configured

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=None),
            patch("auth.lockout._get_redis", return_value=r),
        ):
            resp = _post_login(client, "secret-only@example.com", "correct-horse-battery-staple")

        assert resp.status_code == 200

    def test_both_configured_returns_428_with_non_null_sitekey(self, monkeypatch):
        """Happy path for Fix #1: with BOTH env vars set and the distinct-IP
        threshold crossed, the REAL challenge_required() gate activates and
        the 428 body carries a non-null, renderable sitekey."""
        from auth.service import hash_password

        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x_test_secret")
        monkeypatch.setenv("TURNSTILE_SITEKEY", "0x_test_sitekey")
        password_hash = hash_password("correct-horse-battery-staple")
        conn = _conn_with_user("both-configured@example.com", password_hash)
        app = _make_auth_app()
        client = app.test_client()

        r = MagicMock()
        r.scard.return_value = 999  # past the distinct-IP threshold

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=None),
            patch("auth.lockout._get_redis", return_value=r),
        ):
            resp = _post_login(client, "both-configured@example.com", "correct-horse-battery-staple")

        assert resp.status_code == 428
        body = resp.get_json()
        assert body["data"]["challenge_required"] is True
        assert body["data"]["sitekey"] == "0x_test_sitekey"
