"""Tests for v1 account API endpoints (GDPR)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

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

def _make_app(authenticated=True):
    """Create a minimal Flask app with api_v1_account blueprint."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)
    app.register_blueprint(api_v1_account_bp)

    @app.before_request
    def _inject_user():
        if authenticated:
            g.current_user_id = 1
        g.workspace_id = "ws_001"

    return app


@pytest.fixture
def app():
    return _make_app(authenticated=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def anonymous_client():
    return _make_app(authenticated=False).test_client()


def _mock_conn():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


def _mock_cursor_with_id(row_id):
    """Mock cursor that returns a row with 'id' from fetchone."""
    cursor = MagicMock()
    cursor.fetchone.return_value = {"id": row_id}
    return cursor


class TestAuthRequiredForEveryEndpoint:
    @pytest.mark.parametrize(
        "method,path,payload",
        [
            ("post", "/api/v1/account/export", None),
            ("get", "/api/v1/account/export/exp_001/status", None),
            ("get", "/api/v1/account/export/exp_001/download", None),
            ("delete", "/api/v1/account/", None),
            ("post", "/api/v1/account/cancel-deletion", None),
            ("patch", "/api/v1/account/profile", {"display_name": "New Name"}),
        ],
    )
    def test_anonymous_user_gets_403(self, anonymous_client, method, path, payload):
        kwargs = {}
        if payload is not None:
            kwargs["data"] = json.dumps(payload)
            kwargs["content_type"] = "application/json"
        resp = getattr(anonymous_client, method)(path, **kwargs)
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# POST /api/v1/account/export — create export request
# ---------------------------------------------------------------------------

class TestPostExport:
    @patch("web.routes.api_v1_account.export_user_data")
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_returns_202_with_export_id(self, mock_db, mock_task, client):
        """POST /export returns 202 with export_id."""
        conn = _mock_conn()
        conn.execute.return_value = _mock_cursor_with_id("exp_001")
        mock_db.return_value = conn
        mock_task.delay = MagicMock()

        resp = client.post("/api/v1/account/export")
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["ok"] is True
        assert "export_id" in body["data"]

    @patch("web.routes.api_v1_account.export_user_data")
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_dispatches_celery_task(self, mock_db, mock_task, client):
        """POST /export dispatches export_user_data Celery task."""
        conn = _mock_conn()
        conn.execute.return_value = _mock_cursor_with_id("exp_001")
        mock_db.return_value = conn
        mock_task.delay = MagicMock()

        client.post("/api/v1/account/export")
        mock_task.delay.assert_called_once()


# ---------------------------------------------------------------------------
# GET /api/v1/account/export/<id>/status
# ---------------------------------------------------------------------------

class TestExportStatus:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_returns_status(self, mock_db, client):
        """GET /export/<id>/status returns export status."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "id": "exp_001", "status": "completed", "user_id": 1,
            "created_at": "2026-01-01", "completed_at": "2026-01-01",
        }
        mock_db.return_value = conn

        resp = client.get("/api/v1/account/export/exp_001/status")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["status"] == "completed"

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_404_when_not_found(self, mock_db, client):
        """GET /export/<id>/status returns 404 for unknown export."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn

        resp = client.get("/api/v1/account/export/missing/status")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/account/export/<id>/download
# ---------------------------------------------------------------------------

class TestExportDownload:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_404_when_not_completed(self, mock_db, client):
        """GET /export/<id>/download returns 404 if not completed."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "id": "exp_001", "status": "processing", "user_id": 1,
            "file_path": None,
        }
        mock_db.return_value = conn

        resp = client.get("/api/v1/account/export/exp_001/download")
        assert resp.status_code == 404

    @patch("web.routes.api_v1_account.send_file")
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_returns_file_when_completed(self, mock_db, mock_send, client):
        """GET /export/<id>/download returns file if completed."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "id": "exp_001", "status": "completed", "user_id": 1,
            "file_path": "/tmp/export.zip",
        }
        mock_db.return_value = conn
        mock_send.return_value = MagicMock(status_code=200)

        client.get("/api/v1/account/export/exp_001/download")
        mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# DELETE /api/v1/account/ — soft-delete account
# ---------------------------------------------------------------------------

class TestDeleteAccount:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_sets_deleted_at(self, mock_db, client):
        """DELETE / sets deleted_at and returns 200."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "id": 1, "deleted_at": None,
        }
        mock_db.return_value = conn

        resp = client.delete("/api/v1/account/")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_409_if_already_deleted(self, mock_db, client):
        """DELETE / returns 409 if account already soft-deleted."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "id": 1, "deleted_at": datetime.now(timezone.utc),
        }
        mock_db.return_value = conn

        resp = client.delete("/api/v1/account/")
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"]["code"] == "CONFLICT"


# ---------------------------------------------------------------------------
# POST /api/v1/account/cancel-deletion
# ---------------------------------------------------------------------------

class TestCancelDeletion:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_clears_deleted_at(self, mock_db, client):
        """POST /cancel-deletion clears deleted_at and returns 200."""
        conn = _mock_conn()
        recent = datetime.now(timezone.utc) - timedelta(days=5)
        conn.execute.return_value.fetchone.return_value = {
            "id": 1, "deleted_at": recent,
        }
        mock_db.return_value = conn

        resp = client.post("/api/v1/account/cancel-deletion")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_409_if_not_deleted(self, mock_db, client):
        """POST /cancel-deletion returns 409 if account is not deleted."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "id": 1, "deleted_at": None,
        }
        mock_db.return_value = conn

        resp = client.post("/api/v1/account/cancel-deletion")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# PATCH /api/v1/account/profile
# ---------------------------------------------------------------------------

class TestPatchProfile:
    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_updates_display_name(self, mock_db, client):
        """PATCH /profile updates display_name."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "id": 1, "display_name": "Old", "email": "a@b.com",
        }
        mock_db.return_value = conn

        resp = client.patch(
            "/api/v1/account/profile",
            data=json.dumps({"display_name": "New Name"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_email_change_triggers_reverification(self, mock_db, client):
        """PATCH /profile with email change sets email_verified=False."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {
            "id": 1, "display_name": "Alice", "email": "old@b.com",
        }
        mock_db.return_value = conn

        resp = client.patch(
            "/api/v1/account/profile",
            data=json.dumps({"email": "new@b.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"].get("email_verification_required") is True

    @patch("web.routes.api_v1_account.get_pg_connection")
    def test_empty_body_returns_validation_error(self, mock_db, client):
        """PATCH /profile with empty body returns 400."""
        conn = _mock_conn()
        mock_db.return_value = conn

        resp = client.patch(
            "/api/v1/account/profile",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400
