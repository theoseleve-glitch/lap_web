"""Tests for API response envelope and request ID utilities."""
import sys
from pathlib import Path
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

@pytest.fixture
def app():
    """Minimal Flask app with request_id hook installed."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)

    @app.route("/ok")
    def ok_route():
        return api_response({"key": "value"})

    @app.route("/ok-meta")
    def ok_meta_route():
        return api_response({"x": 1}, meta={"pagination": {"next_cursor": "abc"}})

    @app.route("/ok-status")
    def ok_status_route():
        return api_response({"created": True}, status=201)

    @app.route("/err")
    def err_route():
        return api_error(ErrorCode.VALIDATION_ERROR, "bad input")

    @app.route("/err-details")
    def err_details_route():
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed",
            details=[{"field": "name", "message": "required"}],
            status=422,
        )

    @app.route("/err-404")
    def err_404_route():
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    @app.route("/no-data")
    def no_data_route():
        return api_response()

    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Envelope shape — success
# ---------------------------------------------------------------------------

class TestApiResponse:
    def test_success_envelope_shape(self, client):
        """Success response has ok=True, data, meta keys."""
        resp = client.get("/ok")
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["ok"] is True
        assert body["data"] == {"key": "value"}
        assert "meta" in body
        assert "request_id" in body["meta"]

    def test_success_custom_status(self, client):
        """api_response respects explicit status code."""
        resp = client.get("/ok-status")
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["created"] is True

    def test_success_with_extra_meta(self, client):
        """Extra meta fields are merged into the meta dict."""
        resp = client.get("/ok-meta")
        body = resp.get_json()
        assert body["meta"]["pagination"] == {"next_cursor": "abc"}
        assert "request_id" in body["meta"]

    def test_success_none_data(self, client):
        """api_response() with no data returns data: null."""
        resp = client.get("/no-data")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"] is None

    def test_success_content_type(self, client):
        """Success responses are application/json."""
        resp = client.get("/ok")
        assert resp.content_type.startswith("application/json")


# ---------------------------------------------------------------------------
# Envelope shape — error
# ---------------------------------------------------------------------------

class TestApiError:
    def test_error_envelope_shape(self, client):
        """Error response has ok=False, error, meta keys."""
        resp = client.get("/err")
        body = resp.get_json()
        assert resp.status_code == 400
        assert body["ok"] is False
        assert "error" in body
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["message"] == "bad input"
        assert "meta" in body

    def test_error_with_details(self, client):
        """Error response includes details array when provided."""
        resp = client.get("/err-details")
        body = resp.get_json()
        assert resp.status_code == 422
        assert body["error"]["details"] == [{"field": "name", "message": "required"}]

    def test_error_without_details(self, client):
        """Error response omits details key when not provided."""
        resp = client.get("/err")
        body = resp.get_json()
        assert body["error"].get("details") is None

    def test_error_custom_status(self, client):
        """api_error respects the status parameter."""
        resp = client.get("/err-404")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Request ID
# ---------------------------------------------------------------------------

class TestRequestId:
    def test_request_id_is_valid_hex_uuid(self, client):
        """request_id in meta is a valid 32-char hex UUID."""
        resp = client.get("/ok")
        body = resp.get_json()
        rid = body["meta"]["request_id"]
        assert len(rid) == 32
        UUID(rid)  # raises if invalid

    def test_request_id_unique_per_request(self, client):
        """Each request gets a distinct request_id."""
        rid1 = client.get("/ok").get_json()["meta"]["request_id"]
        rid2 = client.get("/ok").get_json()["meta"]["request_id"]
        assert rid1 != rid2

    def test_request_id_in_error_response(self, client):
        """Error responses also contain request_id in meta."""
        resp = client.get("/err")
        body = resp.get_json()
        rid = body["meta"]["request_id"]
        assert len(rid) == 32
        UUID(rid)


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

class TestErrorCodes:
    ALL_CODES = [
        "INVALID_CREDENTIALS", "TOKEN_EXPIRED", "FORBIDDEN",
        "INSUFFICIENT_ROLE", "VALIDATION_ERROR", "NOT_FOUND",
        "CONFLICT", "QUOTA_EXCEEDED", "RATE_LIMITED",
        "ANALYSIS_FAILED", "FILE_TOO_LARGE", "UNSUPPORTED_FORMAT",
        "IDEMPOTENCY_CONFLICT", "INTERNAL_ERROR", "SERVICE_UNAVAILABLE",
        "NOT_IMPLEMENTED",
    ]

    def test_all_16_error_codes_exist(self):
        """ErrorCode class exposes all 16 stable error code constants."""
        for code in self.ALL_CODES:
            assert hasattr(ErrorCode, code), f"Missing ErrorCode.{code}"
            assert getattr(ErrorCode, code) == code

    def test_error_code_count(self):
        """Exactly 16 error code constants are defined."""
        codes = {attr for attr in vars(ErrorCode) if not attr.startswith("_")}
        assert codes == set(self.ALL_CODES)
