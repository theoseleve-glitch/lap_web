"""Tests for admin 2FA auth routes.

Validates:
- POST /admin/2fa/setup returns provisioning URI + recovery codes
- POST /admin/2fa/verify with correct code enables 2FA
- POST /admin/2fa/verify with wrong code returns 400
- POST /admin/2fa/challenge issues admin_verified JWT
- DELETE /admin/2fa requires root_admin role
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyotp
import pytest
from cryptography.fernet import Fernet

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_TEST_ADMIN_KEY = Fernet.generate_key().decode()
_TEST_JWT_SECRET = "test-jwt-secret-for-admin-routes-1234567890"


class FakeConn:
    """Fake DB that tracks state for 2FA flow testing."""

    def __init__(self, user_row=None):
        self._user_row = user_row
        self._calls = []
        self._updates = {}

    def execute(self, sql, params=None):
        self._calls.append((sql, params))
        cur = MagicMock()

        if "SELECT" in sql.upper() and self._user_row:
            # Apply any updates
            row = dict(self._user_row)
            row.update(self._updates)
            cur.fetchone.return_value = row
        elif "UPDATE" in sql.upper():
            # Track updates
            if params:
                self._updates.update(params)
            cur.rowcount = 1
            cur.fetchone.return_value = None
        else:
            cur.fetchone.return_value = None

        cur.fetchall.return_value = []
        return cur

    def commit(self):
        pass


def _make_app():
    """Create Flask app with admin auth blueprint."""
    from flask import Blueprint, Flask, g, jsonify

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True

    # Import auth_admin blueprint directly
    import importlib.util

    bp_path = _PROJECT_ROOT / "web" / "routes" / "admin" / "auth_admin.py"
    spec = importlib.util.spec_from_file_location("auth_admin_test", bp_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    app.register_blueprint(mod.bp, url_prefix="/api/v1/admin")
    return app, mod


class TestSetup2FA:
    def test_returns_provisioning_uri(self):
        app, mod = _make_app()
        user_row = {
            "is_superadmin": True,
            "email": "admin@test.com",
            "totp_enabled": False,
            "totp_secret": None,
        }
        conn = FakeConn(user_row)

        with patch.object(mod, "_get_conn", return_value=conn):
            with patch.object(mod, "_get_admin_key", return_value=_TEST_ADMIN_KEY):
                with app.test_request_context():
                    from flask import g

                    g.current_user_id = 1
                    resp = mod.setup_2fa()

        data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
        assert data["ok"] is True
        assert "otpauth://totp/" in data["data"]["provisioning_uri"]
        assert len(data["data"]["recovery_codes"]) == 8

    def test_blocks_non_superadmin(self):
        app, mod = _make_app()
        user_row = {
            "is_superadmin": False,
            "email": "user@test.com",
            "totp_enabled": False,
        }
        conn = FakeConn(user_row)

        with patch.object(mod, "_get_conn", return_value=conn):
            with app.test_request_context():
                from flask import g

                g.current_user_id = 1
                resp = mod.setup_2fa()

        data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
        status = resp[1] if isinstance(resp, tuple) else 200
        assert status == 403

    def test_blocks_if_already_enabled(self):
        app, mod = _make_app()
        user_row = {
            "is_superadmin": True,
            "email": "admin@test.com",
            "totp_enabled": True,
        }
        conn = FakeConn(user_row)

        with patch.object(mod, "_get_conn", return_value=conn):
            with app.test_request_context():
                from flask import g

                g.current_user_id = 1
                resp = mod.setup_2fa()

        data = resp[0].get_json()
        assert resp[1] == 400


class TestVerify2FA:
    def test_correct_code_enables_2fa(self):
        app, mod = _make_app()
        secret = pyotp.random_base32()
        from admin.totp import encrypt_secret

        encrypted = encrypt_secret(secret, _TEST_ADMIN_KEY)
        user_row = {
            "totp_secret": encrypted,
            "totp_enabled": False,
        }
        conn = FakeConn(user_row)
        totp = pyotp.TOTP(secret)
        code = totp.now()

        with patch.object(mod, "_get_conn", return_value=conn):
            with patch.object(mod, "_get_admin_key", return_value=_TEST_ADMIN_KEY):
                with app.test_request_context(
                    json={"code": code},
                    content_type="application/json",
                ):
                    from flask import g

                    g.current_user_id = 1
                    resp = mod.verify_2fa_setup()

        data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
        assert data["ok"] is True
        assert data["data"]["totp_enabled"] is True

    def test_wrong_code_returns_400(self):
        app, mod = _make_app()
        secret = pyotp.random_base32()
        from admin.totp import encrypt_secret

        encrypted = encrypt_secret(secret, _TEST_ADMIN_KEY)
        user_row = {
            "totp_secret": encrypted,
            "totp_enabled": False,
        }
        conn = FakeConn(user_row)

        with patch.object(mod, "_get_conn", return_value=conn):
            with patch.object(mod, "_get_admin_key", return_value=_TEST_ADMIN_KEY):
                with app.test_request_context(
                    json={"code": "000000"},
                    content_type="application/json",
                ):
                    from flask import g

                    g.current_user_id = 1
                    resp = mod.verify_2fa_setup()

        status = resp[1] if isinstance(resp, tuple) else 200
        assert status == 400


class TestChallenge2FA:
    def test_correct_code_returns_admin_verified_jwt(self):
        app, mod = _make_app()
        secret = pyotp.random_base32()
        from admin.totp import encrypt_secret

        encrypted = encrypt_secret(secret, _TEST_ADMIN_KEY)
        user_row = {
            "totp_secret": encrypted,
            "totp_enabled": True,
            "totp_backup_codes": "[]",
        }
        conn = FakeConn(user_row)
        code = pyotp.TOTP(secret).now()

        with patch.object(mod, "_get_conn", return_value=conn):
            with patch.object(mod, "_get_admin_key", return_value=_TEST_ADMIN_KEY):
                with patch.dict(os.environ, {"TELEMETRY_JWT_SECRET": _TEST_JWT_SECRET}):
                    with app.test_request_context(
                        json={"code": code},
                        content_type="application/json",
                    ):
                        from flask import g

                        g.current_user_id = 1
                        resp = mod.challenge_2fa()

        data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
        assert data["ok"] is True
        assert data["data"]["admin_verified"] is True

        # Decode the JWT and check admin_verified claim
        from auth.service import decode_access_token

        token = data["data"]["access_token"]
        payload = decode_access_token(token, _TEST_JWT_SECRET)
        assert payload["admin_verified"] is True
        assert payload["user_id"] == 1


class TestDisable2FA:
    def test_root_admin_can_disable(self):
        app, mod = _make_app()
        conn = FakeConn()

        with patch.object(mod, "_get_conn", return_value=conn):
            with app.test_request_context(
                json={"user_id": 42, "reason": "Lost device"},
                content_type="application/json",
            ):
                from flask import g

                g.current_user_id = 1
                g.admin_user = {"admin_role": "root_admin"}
                resp = mod.disable_2fa()

        data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
        assert data["ok"] is True
        assert data["data"]["totp_disabled"] is True

    def test_non_root_admin_blocked(self):
        app, mod = _make_app()
        conn = FakeConn()

        with patch.object(mod, "_get_conn", return_value=conn):
            with app.test_request_context(
                json={"user_id": 42, "reason": "Lost device"},
                content_type="application/json",
            ):
                from flask import g

                g.current_user_id = 1
                g.admin_user = {"admin_role": "support_admin"}
                resp = mod.disable_2fa()

        status = resp[1] if isinstance(resp, tuple) else 200
        assert status == 403

    def test_missing_reason_returns_400(self):
        app, mod = _make_app()
        conn = FakeConn()

        with patch.object(mod, "_get_conn", return_value=conn):
            with app.test_request_context(
                json={"user_id": 42},
                content_type="application/json",
            ):
                from flask import g

                g.current_user_id = 1
                g.admin_user = {"admin_role": "root_admin"}
                resp = mod.disable_2fa()

        status = resp[1] if isinstance(resp, tuple) else 200
        assert status == 400
