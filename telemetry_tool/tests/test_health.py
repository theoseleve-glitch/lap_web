"""Tests for /healthz endpoint."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.routes.health import bp


@pytest.fixture
def app():
    """Minimal Flask app with health blueprint."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False
    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestHealthz:
    def test_returns_200_when_healthy(self, client):
        with patch("web.db.get_db_connection") as mock_db:
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn
            resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["db"] == "ok"

    def test_returns_503_when_db_fails(self, client):
        with patch("web.db.get_db_connection", side_effect=Exception("DB down")):
            resp = client.get("/healthz")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "degraded"
        assert data["db"] == "error"

    def test_includes_redis_field(self, client):
        with patch("web.db.get_db_connection") as mock_db:
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn
            resp = client.get("/healthz")
        data = resp.get_json()
        assert "redis" in data

    def test_pg_mode_uses_pg_connection(self, app):
        app.config["USE_PG"] = True
        client = app.test_client()
        with patch("web.db_pg.get_pg_connection") as mock_pg:
            mock_conn = MagicMock()
            mock_pg.return_value = mock_conn
            resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["db"] == "ok"
