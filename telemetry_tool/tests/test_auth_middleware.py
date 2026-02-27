"""Tests for auth middleware and @require_auth decorator."""
import pytest
from flask import Flask, g, jsonify
from unittest.mock import patch, MagicMock


def _make_app(auth_required=True):
    """Create a minimal Flask app with auth middleware + a protected route."""
    from web.middleware.auth import require_auth, auth_middleware
    from web.api_utils import init_request_id, api_response

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["AUTH_REQUIRED"] = auth_required
    app.config["JWT_SECRET"] = "test-secret"
    init_request_id(app)

    if auth_required:
        app.before_request(auth_middleware)

    @app.route("/api/v1/protected")
    @require_auth
    def protected():
        return api_response({"user_id": getattr(g, "current_user_id", None)})

    @app.route("/public")
    def public():
        return api_response({"msg": "hello"})

    return app


class TestRequireAuthDecorator:
    def test_returns_401_without_token_when_auth_required(self):
        app = _make_app(auth_required=True)
        client = app.test_client()
        resp = client.get("/api/v1/protected")
        assert resp.status_code == 401
        body = resp.get_json()
        assert body["ok"] is False

    def test_allows_request_when_auth_not_required(self):
        app = _make_app(auth_required=False)
        client = app.test_client()
        resp = client.get("/api/v1/protected")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    def test_returns_200_with_valid_token(self):
        from auth.service import create_access_token
        token = create_access_token(user_id=42, secret="test-secret")

        app = _make_app(auth_required=True)
        client = app.test_client()
        resp = client.get("/api/v1/protected", headers={
            "Authorization": f"Bearer {token}"
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["user_id"] == 42

    def test_returns_401_with_expired_token(self):
        from auth.service import create_access_token
        # Create a token that expires immediately (negative minutes = past exp)
        token = create_access_token(user_id=42, secret="test-secret", expiry_minutes=-1)

        app = _make_app(auth_required=True)
        client = app.test_client()
        resp = client.get("/api/v1/protected", headers={
            "Authorization": f"Bearer {token}"
        })
        assert resp.status_code == 401

    def test_returns_401_with_invalid_token(self):
        app = _make_app(auth_required=True)
        client = app.test_client()
        resp = client.get("/api/v1/protected", headers={
            "Authorization": "Bearer invalid-garbage"
        })
        assert resp.status_code == 401


    def test_sets_legacy_user_id_alias_for_migration(self):
        from auth.service import create_access_token
        token = create_access_token(user_id=7, secret="test-secret")

        app = _make_app(auth_required=True)

        @app.route("/api/v1/legacy-alias")
        def legacy_alias():
            return jsonify({"user_id": getattr(g, "user_id", None)})

        client = app.test_client()
        resp = client.get("/api/v1/legacy-alias", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["user_id"] == 7

    def test_public_route_accessible_without_auth(self):
        app = _make_app(auth_required=True)
        client = app.test_client()
        resp = client.get("/public")
        assert resp.status_code == 200
