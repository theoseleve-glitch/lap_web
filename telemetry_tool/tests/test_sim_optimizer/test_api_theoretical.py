"""Tests for the theoretical lap API endpoints."""
import pytest
from flask import Flask


def _create_test_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    from web.routes.theoretical import bp
    app.register_blueprint(bp)
    return app


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
