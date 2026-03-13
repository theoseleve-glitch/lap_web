"""Tests for session soft-delete, favorites, restore, and bulk operations (#0579, #0157, #0552)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.schema import ALL_TABLES
from db.migrate import ensure_schema
from web.repos.session_repo import (
    get_sessions,
    get_session_by_id,
    count_sessions,
    soft_delete_session,
    restore_session,
    purge_deleted_sessions,
)


@pytest.fixture
def db():
    """In-memory SQLite with full schema + a test session."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    # Seed a driver and track
    conn.execute(
        "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test Driver')"
    )
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m) "
        "VALUES ('trk1', 'Test Track', 1000.0)"
    )

    # Seed two sessions
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
        "session_date, n_laps) VALUES ('s1', 'file1.csv', 1, 'trk1', '2026-01-01', 10)"
    )
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
        "session_date, n_laps) VALUES ('s2', 'file2.csv', 1, 'trk1', '2026-01-02', 8)"
    )
    # Seed related data for s1
    conn.execute(
        "INSERT INTO laps (session_id, lap_number, lap_time_s) VALUES ('s1', 1, 60.5)"
    )
    conn.commit()
    return conn


class TestSoftDelete:
    def test_soft_delete_hides_from_list(self, db):
        """Soft-deleted sessions should not appear in get_sessions."""
        assert len(get_sessions(db, limit=10, offset=0)) == 2
        soft_delete_session(db, "s1")
        db.commit()
        sessions = get_sessions(db, limit=10, offset=0)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "s2"

    def test_soft_delete_reduces_count(self, db):
        assert count_sessions(db) == 2
        soft_delete_session(db, "s1")
        db.commit()
        assert count_sessions(db) == 1

    def test_soft_delete_idempotent(self, db):
        assert soft_delete_session(db, "s1") is True
        db.commit()
        # Second call returns False (already deleted)
        assert soft_delete_session(db, "s1") is False

    def test_get_by_id_still_finds_soft_deleted(self, db):
        """get_session_by_id with include_deleted=True should find soft-deleted (for restore)."""
        soft_delete_session(db, "s1")
        db.commit()
        session = get_session_by_id(db, "s1", include_deleted=True)
        assert session is not None
        assert session["deleted_at"] is not None

    def test_restore_session(self, db):
        soft_delete_session(db, "s1")
        db.commit()
        assert count_sessions(db) == 1
        restore_session(db, "s1")
        db.commit()
        assert count_sessions(db) == 2
        session = get_session_by_id(db, "s1")
        assert session["deleted_at"] is None

    def test_restore_non_deleted_returns_false(self, db):
        assert restore_session(db, "s1") is False

    def test_filtered_query_excludes_soft_deleted(self, db):
        soft_delete_session(db, "s1")
        db.commit()
        sessions = get_sessions(
            db, limit=10, offset=0, filters={"track": "Test Track"}
        )
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "s2"


class TestPurge:
    def test_purge_old_deleted_sessions(self, db):
        """Sessions deleted > 30 days ago should be purged."""
        # Manually set deleted_at to 31 days ago
        db.execute(
            "UPDATE sessions SET deleted_at = datetime('now', '-31 days') "
            "WHERE session_id = 's1'"
        )
        db.commit()
        purged = purge_deleted_sessions(db, retention_days=30)
        db.commit()
        assert purged == 1
        # Session is gone
        assert get_session_by_id(db, "s1") is None
        # Related laps also gone
        row = db.execute(
            "SELECT COUNT(*) FROM laps WHERE session_id = 's1'"
        ).fetchone()
        assert row[0] == 0

    def test_purge_respects_retention_window(self, db):
        """Recently deleted sessions should NOT be purged."""
        soft_delete_session(db, "s1")
        db.commit()
        purged = purge_deleted_sessions(db, retention_days=30)
        assert purged == 0
        # Session still exists (soft-deleted, not purged)
        assert get_session_by_id(db, "s1", include_deleted=True) is not None

    def test_purge_skips_non_deleted(self, db):
        """Active sessions should never be purged."""
        purged = purge_deleted_sessions(db, retention_days=0)
        assert purged == 0
        assert count_sessions(db) == 2


# ── API-level tests for restore, favorite, and bulk endpoints ─────


@pytest.fixture
def api_app():
    """Minimal Flask app with data_v2 blueprint for API testing."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False

    from web.routes.data_v2 import bp
    app.register_blueprint(bp)
    return app


@pytest.fixture
def api_client(api_app):
    return api_app.test_client()


def _mock_session(session_id="s1", deleted_at=None, is_favorite=0):
    return {
        "session_id": session_id,
        "csv_filename": "test.csv",
        "driver_id": 1,
        "driver_name": "TestDriver",
        "track_id": "t1",
        "track_name": "TestTrack",
        "session_type": "practice",
        "track_state": "dry",
        "session_date": "2026-01-01",
        "n_laps": 10,
        "best_lap_time_s": 60.0,
        "mean_lap_time_s": 61.5,
        "total_score": 75.0,
        "grade": "B",
        "deleted_at": deleted_at,
        "is_favorite": is_favorite,
    }


class TestRestoreEndpoint:
    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_restore_soft_deleted(self, mock_models, mock_conn, api_client):
        mock_models.get_session_by_id.return_value = _mock_session(deleted_at="2026-03-01T00:00:00")
        resp = api_client.post("/api/v1/sessions/s1/restore")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["data"]["restored"] == "s1"

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_restore_not_deleted_returns_409(self, mock_models, mock_conn, api_client):
        mock_models.get_session_by_id.return_value = _mock_session(deleted_at=None)
        resp = api_client.post("/api/v1/sessions/s1/restore")
        assert resp.status_code == 409

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_restore_not_found(self, mock_models, mock_conn, api_client):
        mock_models.get_session_by_id.return_value = None
        resp = api_client.post("/api/v1/sessions/s1/restore")
        assert resp.status_code == 404


class TestFavoriteEndpoint:
    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_toggle_on(self, mock_models, mock_conn, api_client):
        mock_models.get_session_by_id.return_value = _mock_session(is_favorite=0)
        resp = api_client.post("/api/v1/sessions/s1/favorite")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["is_favorite"] is True
        mock_models.update_session_field.assert_called_once_with(
            mock_conn.return_value, "s1", "is_favorite", 1
        )

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_toggle_off(self, mock_models, mock_conn, api_client):
        mock_models.get_session_by_id.return_value = _mock_session(is_favorite=1)
        resp = api_client.post("/api/v1/sessions/s1/favorite")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["is_favorite"] is False

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_favorite_not_found(self, mock_models, mock_conn, api_client):
        mock_models.get_session_by_id.return_value = None
        resp = api_client.post("/api/v1/sessions/s1/favorite")
        assert resp.status_code == 404


class TestBulkEndpoint:
    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_bulk_delete(self, mock_models, mock_conn, api_client):
        mock_models.get_session_by_id.return_value = _mock_session()
        mock_models.soft_delete_session.return_value = True
        resp = api_client.post(
            "/api/v1/sessions/bulk",
            json={"action": "delete", "session_ids": ["s1", "s2"]},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["action"] == "delete"
        assert data["data"]["processed"] == 2
        assert data["data"]["requested"] == 2

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_bulk_favorite(self, mock_models, mock_conn, api_client):
        mock_models.get_session_by_id.return_value = _mock_session()
        resp = api_client.post(
            "/api/v1/sessions/bulk",
            json={"action": "favorite", "session_ids": ["s1"]},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["action"] == "favorite"
        assert data["data"]["processed"] == 1

    def test_bulk_invalid_action(self, api_client):
        resp = api_client.post(
            "/api/v1/sessions/bulk",
            json={"action": "explode", "session_ids": ["s1"]},
        )
        assert resp.status_code == 422

    def test_bulk_empty_ids(self, api_client):
        resp = api_client.post(
            "/api/v1/sessions/bulk",
            json={"action": "delete", "session_ids": []},
        )
        assert resp.status_code == 422

    def test_bulk_exceeds_limit(self, api_client):
        resp = api_client.post(
            "/api/v1/sessions/bulk",
            json={"action": "delete", "session_ids": [f"s{i}" for i in range(101)]},
        )
        assert resp.status_code == 422

    @patch("web.routes.data_v2.get_db_connection")
    @patch("web.routes.data_v2.models")
    def test_bulk_skips_missing(self, mock_models, mock_conn, api_client):
        # First call returns session, second returns None
        mock_models.get_session_by_id.side_effect = [_mock_session(), None]
        mock_models.soft_delete_session.return_value = True
        resp = api_client.post(
            "/api/v1/sessions/bulk",
            json={"action": "delete", "session_ids": ["s1", "missing"]},
        )
        data = resp.get_json()
        assert data["data"]["requested"] == 2
        assert data["data"]["processed"] == 1
