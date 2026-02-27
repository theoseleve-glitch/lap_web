"""Tests for admin middleware — superadmin guards and role checks.

Validates:
- Regular users get 403 on all admin endpoints
- Superadmin without TOTP enabled gets 403
- Superadmin with TOTP but wrong role gets 403
- Superadmin with TOTP and correct role passes
- admin_verified JWT claim is checked
- create_access_token supports admin_verified parameter
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _import_middleware():
    """Import admin middleware directly, bypassing __init__.py chain."""
    import importlib.util

    mw_path = _PROJECT_ROOT / "web" / "routes" / "admin" / "middleware.py"
    spec = importlib.util.spec_from_file_location(
        "admin_middleware_test", mw_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mw = _import_middleware()


class FakeConn:
    """Fake DB connection returning configurable user rows."""

    def __init__(self, user_row=None):
        self._user_row = user_row

    def execute(self, sql, params=None):
        cur = MagicMock()
        if self._user_row and "SELECT" in sql.upper():
            cur.fetchone.return_value = self._user_row
        else:
            cur.fetchone.return_value = None
        return cur

    def commit(self):
        pass


def _make_app_with_admin_blueprint():
    """Create a minimal Flask app with admin middleware wired up."""
    from flask import Flask, jsonify, Blueprint

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True

    test_bp = Blueprint("test_admin", __name__, url_prefix="/api/v1/admin")
    test_bp.before_request(_mw.admin_before_request)

    @test_bp.route("/any-admin")
    @_mw.require_superadmin
    def any_admin_endpoint():
        return jsonify({"ok": True})

    @test_bp.route("/root-only")
    @_mw.require_superadmin
    @_mw.require_admin_role("root_admin")
    def root_only_endpoint():
        return jsonify({"ok": True})

    @test_bp.route("/sre-or-root")
    @_mw.require_superadmin
    @_mw.require_admin_role("root_admin", "sre_admin")
    def sre_or_root_endpoint():
        return jsonify({"ok": True})

    app.register_blueprint(test_bp)
    return app


class TestAdminBeforeRequest:
    def test_sets_admin_user_on_g(self):
        from flask import g

        app = _make_app_with_admin_blueprint()
        user_row = {
            "is_superadmin": True,
            "admin_role": "root_admin",
            "totp_enabled": True,
        }

        with app.test_request_context("/api/v1/admin/any-admin"):
            g.current_user_id = 1
            g.admin_verified = True

            with patch.object(_mw, "_get_admin_conn") as mock_conn:
                mock_conn.return_value = FakeConn(user_row)
                result = _mw.admin_before_request()

            assert result is None
            assert g.admin_user["is_superadmin"] is True
            assert g.admin_user["admin_role"] == "root_admin"

    def test_no_user_id_returns_403(self):
        app = _make_app_with_admin_blueprint()

        with app.test_request_context("/api/v1/admin/any-admin"):
            result = _mw.admin_before_request()
            assert result is not None
            resp, status = result
            assert status == 403


class TestRequireSuperadmin:
    def test_regular_user_gets_403(self):
        app = _make_app_with_admin_blueprint()
        user_row = {
            "is_superadmin": False,
            "admin_role": None,
            "totp_enabled": False,
        }

        with patch.object(_mw, "_get_admin_conn", return_value=FakeConn(user_row)):
            with patch.object(_mw, "_get_current_user_id", return_value=1):
                with patch.object(_mw, "_get_admin_verified", return_value=False):
                    with app.test_client() as client:
                        resp = client.get("/api/v1/admin/any-admin")

        assert resp.status_code == 403

    def test_superadmin_without_totp_gets_403(self):
        app = _make_app_with_admin_blueprint()
        user_row = {
            "is_superadmin": True,
            "admin_role": "root_admin",
            "totp_enabled": False,
        }

        with patch.object(_mw, "_get_admin_conn", return_value=FakeConn(user_row)):
            with patch.object(_mw, "_get_current_user_id", return_value=1):
                with patch.object(_mw, "_get_admin_verified", return_value=True):
                    with app.test_client() as client:
                        resp = client.get("/api/v1/admin/any-admin")

        assert resp.status_code == 403

    def test_superadmin_with_totp_passes(self):
        app = _make_app_with_admin_blueprint()
        user_row = {
            "is_superadmin": True,
            "admin_role": "root_admin",
            "totp_enabled": True,
        }

        with patch.object(_mw, "_get_admin_conn", return_value=FakeConn(user_row)):
            with patch.object(_mw, "_get_current_user_id", return_value=1):
                with patch.object(_mw, "_get_admin_verified", return_value=True):
                    with app.test_client() as client:
                        resp = client.get("/api/v1/admin/any-admin")

        assert resp.status_code == 200


class TestRequireAdminRole:
    def test_wrong_role_gets_403(self):
        app = _make_app_with_admin_blueprint()
        user_row = {
            "is_superadmin": True,
            "admin_role": "billing_admin",
            "totp_enabled": True,
        }

        with patch.object(_mw, "_get_admin_conn", return_value=FakeConn(user_row)):
            with patch.object(_mw, "_get_current_user_id", return_value=1):
                with patch.object(_mw, "_get_admin_verified", return_value=True):
                    with app.test_client() as client:
                        resp = client.get("/api/v1/admin/root-only")

        assert resp.status_code == 403

    def test_correct_role_passes(self):
        app = _make_app_with_admin_blueprint()
        user_row = {
            "is_superadmin": True,
            "admin_role": "root_admin",
            "totp_enabled": True,
        }

        with patch.object(_mw, "_get_admin_conn", return_value=FakeConn(user_row)):
            with patch.object(_mw, "_get_current_user_id", return_value=1):
                with patch.object(_mw, "_get_admin_verified", return_value=True):
                    with app.test_client() as client:
                        resp = client.get("/api/v1/admin/root-only")

        assert resp.status_code == 200

    def test_multi_role_endpoint(self):
        app = _make_app_with_admin_blueprint()
        user_row = {
            "is_superadmin": True,
            "admin_role": "sre_admin",
            "totp_enabled": True,
        }

        with patch.object(_mw, "_get_admin_conn", return_value=FakeConn(user_row)):
            with patch.object(_mw, "_get_current_user_id", return_value=1):
                with patch.object(_mw, "_get_admin_verified", return_value=True):
                    with app.test_client() as client:
                        resp = client.get("/api/v1/admin/sre-or-root")

        assert resp.status_code == 200


class TestAccessTokenAdminClaim:
    def test_create_access_token_with_admin_verified(self):
        from auth.service import create_access_token, decode_access_token

        token = create_access_token(
            user_id=1, secret="test-secret", admin_verified=True
        )
        payload = decode_access_token(token, "test-secret")
        assert payload["admin_verified"] is True

    def test_create_access_token_without_admin_verified(self):
        from auth.service import create_access_token, decode_access_token

        token = create_access_token(user_id=1, secret="test-secret")
        payload = decode_access_token(token, "test-secret")
        assert "admin_verified" not in payload

    def test_backward_compatible(self):
        from auth.service import create_access_token, decode_access_token

        token = create_access_token(user_id=1, secret="test-secret")
        payload = decode_access_token(token, "test-secret")
        assert payload["user_id"] == 1
        assert payload["type"] == "access"
