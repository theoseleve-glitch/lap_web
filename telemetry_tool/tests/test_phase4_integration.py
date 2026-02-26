"""Phase 4 integration tests — cross-cutting middleware verification."""
import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.api_utils import ErrorCode, api_error, api_response, init_request_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_integration_app():
    """Create a Flask app with all Phase 4 infrastructure wired up."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["RATE_LIMIT_ENABLED"] = False  # disable real Redis
    init_request_id(app)

    @app.before_request
    def _inject_user():
        g.user_id = 1
        g.workspace_id = "ws_test"

    # Register v1 data and account blueprints
    try:
        from web.routes.api_v1_data import bp as data_bp
        app.register_blueprint(data_bp)
    except ImportError:
        pass

    try:
        from web.routes.api_v1_account import bp as account_bp
        app.register_blueprint(account_bp)
    except ImportError:
        pass

    # Register legacy blueprint
    try:
        from web.routes.api_data import bp as legacy_bp
        app.register_blueprint(legacy_bp)
    except ImportError:
        pass

    # Test-only routes for middleware stacking
    @app.route("/test/error-404")
    def test_404():
        return api_error(ErrorCode.NOT_FOUND, "Not found", status=404)

    @app.route("/test/error-429")
    def test_429():
        return api_error(ErrorCode.RATE_LIMITED, "Too many requests", status=429)

    @app.route("/test/error-validation")
    def test_validation():
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed",
            details=[{"field": "name", "message": "required"}],
            status=422,
        )

    @app.route("/test/success")
    def test_success():
        return api_response({"msg": "ok"})

    return app


@pytest.fixture
def app():
    return _make_integration_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_conn():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


# ---------------------------------------------------------------------------
# 1. Request ID lifecycle
# ---------------------------------------------------------------------------

class TestRequestIdLifecycle:
    def test_request_id_in_success_response(self, client):
        """Success responses include request_id in meta."""
        resp = client.get("/test/success")
        body = resp.get_json()
        rid = body["meta"]["request_id"]
        assert len(rid) == 32
        UUID(rid)  # validates format

    def test_request_id_in_error_response(self, client):
        """Error responses include request_id in meta."""
        resp = client.get("/test/error-404")
        body = resp.get_json()
        rid = body["meta"]["request_id"]
        assert len(rid) == 32
        UUID(rid)

    def test_request_id_unique_across_requests(self, client):
        """Each request gets a unique request_id."""
        rid1 = client.get("/test/success").get_json()["meta"]["request_id"]
        rid2 = client.get("/test/success").get_json()["meta"]["request_id"]
        assert rid1 != rid2


# ---------------------------------------------------------------------------
# 2. Error envelope consistency
# ---------------------------------------------------------------------------

class TestErrorEnvelopeConsistency:
    def test_404_has_envelope_format(self, client):
        """404 error uses the standard envelope."""
        resp = client.get("/test/error-404")
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"
        assert "meta" in body

    def test_429_has_envelope_format(self, client):
        """429 error uses the standard envelope."""
        resp = client.get("/test/error-429")
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "meta" in body

    def test_validation_error_has_envelope_format(self, client):
        """Validation error includes details array in envelope."""
        resp = client.get("/test/error-validation")
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["details"] == [{"field": "name", "message": "required"}]
        assert "meta" in body

    def test_all_error_codes_are_valid(self, client):
        """All error codes used in test routes are valid ErrorCode constants."""
        for code in ["NOT_FOUND", "RATE_LIMITED", "VALIDATION_ERROR"]:
            assert hasattr(ErrorCode, code)
            assert getattr(ErrorCode, code) == code


# ---------------------------------------------------------------------------
# 3. V1 data endpoint integration
# ---------------------------------------------------------------------------

class TestV1DataIntegration:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[1, 2])
    def test_v1_endpoint_has_request_id(self, mock_laps, mock_db, client):
        """V1 data endpoint response includes request_id."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/laps/gps")
        body = resp.get_json()
        assert "request_id" in body["meta"]

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_theoretical_data", return_value=None)
    def test_v1_404_uses_envelope(self, mock_theo, mock_db, client):
        """V1 404 error uses the standard envelope format."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/theoretical")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"
        assert "request_id" in body["meta"]


# ---------------------------------------------------------------------------
# 4. Deprecation headers on legacy + v1 contrast
# ---------------------------------------------------------------------------

class TestDeprecationIntegration:
    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_gps_lap_numbers", return_value=[1])
    def test_legacy_has_deprecation_header(self, mock_laps, mock_db, client):
        """Legacy endpoint includes Deprecation header."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/gps_laps")
        assert resp.headers.get("Deprecation") == "true"

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[1])
    def test_v1_has_no_deprecation_header(self, mock_laps, mock_db, client):
        """V1 equivalent does NOT include Deprecation header."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/laps/gps")
        assert resp.headers.get("Deprecation") is None

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_gps_lap_numbers", return_value=[1, 2])
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[1, 2])
    def test_legacy_and_v1_return_equivalent_data(
        self, mock_v1_laps, mock_v1_db, mock_legacy_laps, mock_legacy_db, client
    ):
        """Legacy and v1 endpoints return the same core data."""
        mock_legacy_db.return_value = _mock_conn()
        mock_v1_db.return_value = _mock_conn()

        legacy_resp = client.get("/api/session/s1/gps_laps")
        v1_resp = client.get("/api/v1/sessions/s1/laps/gps")

        legacy_body = legacy_resp.get_json()
        v1_body = v1_resp.get_json()

        # Both return the same lap numbers
        assert legacy_body["laps"] == v1_body["data"]["laps"]


# ---------------------------------------------------------------------------
# 5. Logging filter enrichment
# ---------------------------------------------------------------------------

class TestLoggingFilterIntegration:
    def test_logging_filter_exists(self):
        """RequestIdFilter can be imported."""
        from web.logging_setup import RequestIdFilter
        f = RequestIdFilter()
        assert callable(getattr(f, "filter", None))

    def test_json_formatter_exists(self):
        """JsonFormatter can be imported."""
        from web.logging_setup import JsonFormatter
        f = JsonFormatter()
        assert callable(getattr(f, "format", None))
