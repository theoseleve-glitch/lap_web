"""Tests for web.routes.versioning — pipeline version + stale sessions API.

Uses a minimal Flask app with the versioning blueprint registered.
All DB access is mocked via MagicMock connections.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Create a minimal Flask app with the versioning blueprint."""
    from flask import Flask, g
    from web.routes.versioning import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)

    @app.before_request
    def _set_context():
        g.workspace_id = 1
        g.user_id = 42
        g.current_user_id = 42

    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /api/v1/sessions/stale
# ---------------------------------------------------------------------------


class TestStaleSessions:
    """GET /api/v1/sessions/stale returns stale sessions."""

    @patch("web.routes.versioning.get_pg_connection")
    def test_returns_stale_sessions_list(self, mock_pg, client):
        from pipeline_version import PIPELINE_VERSION

        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn

        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"session_id": "sess-1", "processing_version": 0},
            {"session_id": "sess-2", "processing_version": None},
        ]
        mock_conn.execute.return_value = cursor

        resp = client.get("/api/v1/sessions/stale")

        assert resp.status_code == 200
        body = resp.get_json()
        data = body["data"]
        assert data["current_version"] == PIPELINE_VERSION
        assert data["count"] == 2
        assert len(data["stale_sessions"]) == 2
        assert data["stale_sessions"][0]["session_id"] == "sess-1"

    @patch("web.routes.versioning.get_pg_connection")
    def test_returns_empty_when_all_current(self, mock_pg, client):
        from pipeline_version import PIPELINE_VERSION

        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn

        cursor = MagicMock()
        cursor.fetchall.return_value = []
        mock_conn.execute.return_value = cursor

        resp = client.get("/api/v1/sessions/stale")

        assert resp.status_code == 200
        body = resp.get_json()
        data = body["data"]
        assert data["current_version"] == PIPELINE_VERSION
        assert data["count"] == 0
        assert data["stale_sessions"] == []


# ---------------------------------------------------------------------------
# GET /api/v1/pipeline/version
# ---------------------------------------------------------------------------


class TestPipelineVersion:
    """GET /api/v1/pipeline/version returns PIPELINE_VERSION."""

    def test_returns_pipeline_version(self, client):
        from pipeline_version import PIPELINE_VERSION

        resp = client.get("/api/v1/pipeline/version")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["pipeline_version"] == PIPELINE_VERSION
