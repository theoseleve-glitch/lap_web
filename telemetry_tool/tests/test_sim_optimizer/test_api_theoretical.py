"""Tests for the theoretical lap API endpoints."""
from unittest.mock import patch

import pytest
from flask import Flask


def _create_test_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    from web.routes.theoretical import bp
    app.register_blueprint(bp)
    return app


# _load_session_raw_data now resolves session_id via the RLS-scoped request
# connection (IDOR fix: it used to build the sidecar path from the client
# session_id with no DB query at all). These tests never seeded a "test123"
# session, so the real behaviour post-fix is still 404 -- but the route
# needs a *working* DB connection to reach that conclusion instead of
# raising on an unconfigured DB_PATH. Patch get_db_connection to the shared
# in-memory `test_db` fixture (empty schema, no "test123" row) so
# models.get_session_by_id() legitimately returns None.
@pytest.fixture(autouse=True)
def _patched_db(test_db):
    with patch("web.routes.theoretical.get_db_connection", return_value=test_db):
        yield


class TestTheoreticalEndpoints:
    def test_theoretical_returns_404_without_data(self):
        app = _create_test_app()
        with app.test_client() as client:
            resp = client.get("/api/v1/sessions/test123/theoretical")
            assert resp.status_code == 404

    def test_delta_returns_404_without_data(self):
        app = _create_test_app()
        with app.test_client() as client:
            resp = client.get("/api/v1/sessions/test123/theoretical/delta")
            assert resp.status_code == 404

    def test_corners_returns_404_without_data(self):
        app = _create_test_app()
        with app.test_client() as client:
            resp = client.get("/api/v1/sessions/test123/theoretical/corners")
            assert resp.status_code == 404

    def test_delta_accepts_lap_param(self):
        app = _create_test_app()
        with app.test_client() as client:
            resp = client.get("/api/v1/sessions/test123/theoretical/delta?lap=3")
            assert resp.status_code == 404  # still 404, but didn't crash

    def test_response_envelope_format(self):
        """Verify error responses follow the standard envelope format."""
        app = _create_test_app()
        with app.test_client() as client:
            resp = client.get("/api/v1/sessions/test123/theoretical")
            data = resp.get_json()
            assert data["ok"] is False
            assert "error" in data
            assert "code" in data["error"]
            assert "message" in data["error"]
