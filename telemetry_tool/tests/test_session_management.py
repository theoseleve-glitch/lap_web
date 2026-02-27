"""Tests for session management endpoints (list, revoke, revoke-others)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.api_utils import init_request_id
from web.routes.api_v1_account import bp as api_v1_account_bp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    """Create a minimal Flask app with api_v1_account blueprint."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)
    app.register_blueprint(api_v1_account_bp)

    @app.before_request
    def _inject_user():
        g.user_id = 1
        g.current_user_id = 1
        g.workspace_id = "ws_001"

    return app


@pytest.fixture
def app():
    return _make_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_conn():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


# ---------------------------------------------------------------------------
# GET /api/v1/account/sessions
# ---------------------------------------------------------------------------

class TestListSessions:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_returns_active_sessions(self, mock_db, client):
        """GET /sessions returns list of active sessions."""
        now = datetime.now(timezone.utc)
        conn = _mock_conn()

        # First call returns sessions list, subsequent calls return token_hash
        session_rows = [
            {
                "id": 1,
                "user_agent": "Chrome/120",
                "ip_address": "1.2.3.4",
                "created_at": now - timedelta(days=1),
                "last_used_at": now,
            },
            {
                "id": 2,
                "user_agent": "Firefox/115",
                "ip_address": "5.6.7.8",
                "created_at": now - timedelta(hours=6),
                "last_used_at": now - timedelta(hours=1),
            },
        ]

        # Mock: first execute().fetchall() returns sessions, then
        # subsequent execute().fetchone() calls return token_hash for is_current check
        call_count = [0]
        original_execute = conn.execute

        def side_effect_execute(*args, **kwargs):
            result = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: SELECT sessions
                result.fetchall.return_value = session_rows
                result.fetchone.return_value = None
            else:
                # Subsequent calls: SELECT token_hash for is_current check
                result.fetchone.return_value = {"token_hash": "some-hash"}
            return result

        conn.execute = MagicMock(side_effect=side_effect_execute)
        mock_db.return_value = conn

        resp = client.get("/api/v1/account/sessions")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]) == 2
        assert body["data"][0]["id"] == 1
        assert body["data"][0]["user_agent"] == "Chrome/120"
        assert body["data"][0]["ip_address"] == "1.2.3.4"

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_returns_empty_when_no_sessions(self, mock_db, client):
        """GET /sessions returns empty list when no active sessions."""
        conn = _mock_conn()
        conn.execute.return_value.fetchall.return_value = []
        mock_db.return_value = conn

        resp = client.get("/api/v1/account/sessions")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"] == []

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_sessions_include_is_current(self, mock_db, client):
        """GET /sessions includes is_current field."""
        now = datetime.now(timezone.utc)
        conn = _mock_conn()

        session_rows = [
            {
                "id": 1,
                "user_agent": "Chrome/120",
                "ip_address": "1.2.3.4",
                "created_at": now,
                "last_used_at": now,
            },
        ]

        call_count = [0]

        def side_effect_execute(*args, **kwargs):
            result = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                result.fetchall.return_value = session_rows
                result.fetchone.return_value = None
            else:
                result.fetchone.return_value = {"token_hash": "some-hash"}
            return result

        conn.execute = MagicMock(side_effect=side_effect_execute)
        mock_db.return_value = conn

        resp = client.get("/api/v1/account/sessions")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "is_current" in body["data"][0]


# ---------------------------------------------------------------------------
# DELETE /api/v1/account/sessions/<id>
# ---------------------------------------------------------------------------

class TestRevokeSession:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_revokes_session_by_id(self, mock_db, client):
        """DELETE /sessions/<id> revokes the session."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {"id": 5}
        mock_db.return_value = conn

        resp = client.delete("/api/v1/account/sessions/5")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["revoked"] is True

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_returns_404_for_unknown_session(self, mock_db, client):
        """DELETE /sessions/<id> returns 404 for non-existent session."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn

        resp = client.delete("/api/v1/account/sessions/999")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["error"]["code"] == "NOT_FOUND"

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_revoke_commits_transaction(self, mock_db, client):
        """DELETE /sessions/<id> commits the transaction."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {"id": 5}
        mock_db.return_value = conn

        client.delete("/api/v1/account/sessions/5")
        conn.commit.assert_called()


# ---------------------------------------------------------------------------
# POST /api/v1/account/sessions/revoke-all
# ---------------------------------------------------------------------------

class TestRevokeAllSessions:
    @patch("auth.service.hash_refresh_token")
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_revoke_others_with_cookie(self, mock_db, mock_hash, client):
        """POST /sessions/revoke-all keeps current session when cookie present."""
        conn = _mock_conn()
        mock_db.return_value = conn
        mock_hash.return_value = "current-hash"

        # Set cookie using the client
        client.set_cookie("lap_refresh_token", "some-token", domain="localhost")
        resp = client.post("/api/v1/account/sessions/revoke-all")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_revoke_all_without_cookie(self, mock_db, client):
        """POST /sessions/revoke-all revokes ALL tokens when no cookie."""
        conn = _mock_conn()
        mock_db.return_value = conn

        resp = client.post("/api/v1/account/sessions/revoke-all")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_revoke_all_commits_transaction(self, mock_db, client):
        """POST /sessions/revoke-all commits the transaction."""
        conn = _mock_conn()
        mock_db.return_value = conn

        client.post("/api/v1/account/sessions/revoke-all")
        conn.commit.assert_called()
