"""Tests for session tagging endpoints (#0154)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask
from web.routes.data_v2 import bp


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_session():
    return {
        "session_id": "s1",
        "csv_filename": "test.csv",
        "driver_id": 1,
        "session_date": "2026-01-01",
        "deleted_at": None,
    }


class TestGetTags:
    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_returns_tags(self, mock_models, mock_conn, client):
        mock_models.get_session_by_id.return_value = _mock_session()
        conn = mock_conn.return_value
        conn.execute.return_value.fetchall.return_value = [
            {"tag": "race-day", "confidence": 1.0, "source": "user", "created_at": "2026-01-01"},
        ]
        resp = client.get("/api/v1/sessions/s1/tags")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["tags"]) == 1
        assert data["data"]["tags"][0]["tag"] == "race-day"

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_404_for_missing_session(self, mock_models, mock_conn, client):
        mock_models.get_session_by_id.return_value = None
        resp = client.get("/api/v1/sessions/missing/tags")
        assert resp.status_code == 404


class TestAddTag:
    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_add_tag(self, mock_models, mock_conn, client):
        mock_models.get_session_by_id.return_value = _mock_session()
        resp = client.post(
            "/api/v1/sessions/s1/tags",
            json={"tag": "Race Day", "confidence": 0.9},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["data"]["tag"] == "race day"  # normalized to lowercase
        assert data["data"]["created"] is True

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_empty_tag_rejected(self, mock_models, mock_conn, client):
        mock_models.get_session_by_id.return_value = _mock_session()
        resp = client.post(
            "/api/v1/sessions/s1/tags",
            json={"tag": ""},
        )
        assert resp.status_code == 422

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_long_tag_rejected(self, mock_models, mock_conn, client):
        mock_models.get_session_by_id.return_value = _mock_session()
        resp = client.post(
            "/api/v1/sessions/s1/tags",
            json={"tag": "x" * 51},
        )
        assert resp.status_code == 422


class TestDeleteTag:
    @patch("web.routes.data_v2.get_db_connection")
    def test_delete_existing_tag(self, mock_conn, client):
        conn = mock_conn.return_value
        conn.execute.return_value.rowcount = 1
        resp = client.delete("/api/v1/sessions/s1/tags/race-day")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["deleted"] is True

    @patch("web.routes.data_v2.get_db_connection")
    def test_delete_missing_tag_404(self, mock_conn, client):
        conn = mock_conn.return_value
        conn.execute.return_value.rowcount = 0
        resp = client.delete("/api/v1/sessions/s1/tags/nonexistent")
        assert resp.status_code == 404
