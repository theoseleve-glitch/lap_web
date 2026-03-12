"""Tests for API response envelope and request ID utilities."""
import sys
from pathlib import Path
from uuid import UUID

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.api_utils import ERROR_CATALOG, ErrorCode, api_error, api_response, deprecated, init_request_id

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

    @app.route("/api/v1/sessions")
    def api_sessions():
        return api_response({"sessions": []})

    @app.route("/api/v1/sessions/s1/speed-trace")
    def api_speed_trace():
        return api_response({"trace": []})

    @app.route("/api/v1/sessions/s1/scores")
    def api_scores():
        return api_response({"scores": {}})

    @app.route("/api/v1/sessions/s1", methods=["DELETE"])
    def api_delete_session():
        return api_response({"deleted": "s1"})

    @app.route("/api/v1/healthz")
    def api_healthz():
        return api_response({"status": "ok"})

    @app.route("/deprecated-endpoint")
    @deprecated("2026-06-01", alternative="/api/v1/new-endpoint")
    def deprecated_route():
        return api_response({"legacy": True})

    @app.route("/api/v1/rich-dict")
    def api_rich_dict():
        return api_response({"id": "s1", "name": "Session 1", "score": 85, "track": "Monza"})

    @app.route("/api/v1/rich-list")
    def api_rich_list():
        return api_response([
            {"id": "s1", "name": "Session 1", "score": 85},
            {"id": "s2", "name": "Session 2", "score": 72},
        ])

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

    def test_server_timing_header(self, client):
        """Every response includes a Server-Timing header with total duration."""
        resp = client.get("/ok")
        st = resp.headers.get("Server-Timing")
        assert st is not None
        assert st.startswith("total;dur=")
        dur = float(st.split("=")[1])
        assert dur >= 0

    def test_x_request_id_header(self, client):
        """Every response includes X-Request-Id for client-side correlation."""
        resp = client.get("/ok")
        rid = resp.headers.get("X-Request-Id")
        assert rid is not None
        assert len(rid) == 32


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

class TestErrorCodes:
    ALL_CODES = [
        "INVALID_CREDENTIALS", "TOKEN_EXPIRED", "FORBIDDEN",
        "INSUFFICIENT_ROLE", "VALIDATION_ERROR", "NOT_FOUND",
        "CONFLICT", "QUOTA_EXCEEDED", "RATE_LIMITED",
        "ANALYSIS_FAILED", "FILE_TOO_LARGE", "UNSUPPORTED_FORMAT",
        "PLAN_REQUIRED", "IDEMPOTENCY_CONFLICT", "INTERNAL_ERROR",
        "SERVICE_UNAVAILABLE", "NOT_READY", "NOT_IMPLEMENTED",
        "API_HTML_RESPONSE", "UNAUTHORIZED", "DATA_UNAVAILABLE",
    ]

    def test_all_error_codes_exist(self):
        """ErrorCode class exposes all stable error code constants."""
        for code in self.ALL_CODES:
            assert hasattr(ErrorCode, code), f"Missing ErrorCode.{code}"
            assert getattr(ErrorCode, code) == code

    def test_error_code_count(self):
        """All error code constants are accounted for."""
        codes = {attr for attr in vars(ErrorCode) if not attr.startswith("_")}
        assert codes == set(self.ALL_CODES)

    def test_error_catalog_covers_all_codes(self):
        """ERROR_CATALOG has an entry for every ErrorCode."""
        for code in self.ALL_CODES:
            assert code in ERROR_CATALOG, f"Missing ERROR_CATALOG[{code!r}]"
            entry = ERROR_CATALOG[code]
            assert "status" in entry
            assert "message" in entry
            assert isinstance(entry["status"], int)
            assert 400 <= entry["status"] <= 599


# ---------------------------------------------------------------------------
# Deprecation headers
# ---------------------------------------------------------------------------

class TestDeprecation:
    def test_deprecated_sets_deprecation_header(self, client):
        """Deprecated endpoints include Deprecation: true."""
        resp = client.get("/deprecated-endpoint")
        assert resp.headers.get("Deprecation") == "true"

    def test_deprecated_sets_sunset_header(self, client):
        """Deprecated endpoints include Sunset header in HTTP-date format."""
        resp = client.get("/deprecated-endpoint")
        sunset = resp.headers.get("Sunset")
        assert sunset is not None
        assert "2026" in sunset

    def test_deprecated_sets_link_header(self, client):
        """Deprecated endpoints include Link with successor-version rel."""
        resp = client.get("/deprecated-endpoint")
        link = resp.headers.get("Link")
        assert link == '</api/v1/new-endpoint>; rel="successor-version"'

    def test_deprecated_response_still_works(self, client):
        """Deprecated endpoints still return normal response body."""
        resp = client.get("/deprecated-endpoint")
        body = resp.get_json()
        assert resp.status_code == 200
        assert body["ok"] is True
        assert body["data"]["legacy"] is True


# ---------------------------------------------------------------------------
# Cache-Control headers (#0595)
# ---------------------------------------------------------------------------


class TestCacheControl:
    def test_chart_data_cached_1_hour(self, client):
        """Chart data endpoints get private, max-age=3600."""
        resp = client.get("/api/v1/sessions/s1/speed-trace")
        assert "max-age=3600" in resp.headers.get("Cache-Control", "")
        assert "private" in resp.headers.get("Cache-Control", "")

    def test_scores_cached_5_minutes(self, client):
        """Score endpoints get private, max-age=300."""
        resp = client.get("/api/v1/sessions/s1/scores")
        assert "max-age=300" in resp.headers.get("Cache-Control", "")

    def test_default_api_no_cache(self, client):
        """Default API GET uses no-cache (revalidate every time, ETag saves bandwidth)."""
        resp = client.get("/api/v1/sessions")
        cc = resp.headers.get("Cache-Control", "")
        assert "no-cache" in cc

    def test_mutating_no_store(self, client):
        """DELETE/POST/PATCH responses get no-store."""
        resp = client.delete("/api/v1/sessions/s1")
        assert resp.headers.get("Cache-Control") == "no-store"

    def test_healthz_no_cache(self, client):
        """Health check endpoint should not be cached."""
        resp = client.get("/api/v1/healthz")
        cc = resp.headers.get("Cache-Control", "")
        assert "no-cache" in cc


# ---------------------------------------------------------------------------
# Field filtering (#0610)
# ---------------------------------------------------------------------------


class TestFieldFiltering:
    def test_no_fields_returns_all(self, client):
        """Without ?fields, all data keys are returned."""
        resp = client.get("/api/v1/rich-dict")
        body = resp.get_json()
        assert set(body["data"].keys()) == {"id", "name", "score", "track"}

    def test_fields_filters_dict(self, client):
        """?fields=id,score returns only those keys."""
        resp = client.get("/api/v1/rich-dict?fields=id,score")
        body = resp.get_json()
        assert set(body["data"].keys()) == {"id", "score"}
        assert body["data"]["id"] == "s1"
        assert body["data"]["score"] == 85

    def test_fields_filters_list(self, client):
        """?fields works on list-of-dict responses."""
        resp = client.get("/api/v1/rich-list?fields=id,name")
        body = resp.get_json()
        for item in body["data"]:
            assert set(item.keys()) == {"id", "name"}

    def test_fields_with_spaces(self, client):
        """Field names with surrounding spaces are trimmed."""
        resp = client.get("/api/v1/rich-dict?fields= id , score ")
        body = resp.get_json()
        assert set(body["data"].keys()) == {"id", "score"}

    def test_unknown_fields_ignored(self, client):
        """Requesting non-existent fields returns empty dict."""
        resp = client.get("/api/v1/rich-dict?fields=nonexistent")
        body = resp.get_json()
        assert body["data"] == {}

    def test_meta_not_filtered(self, client):
        """Meta section is never filtered by ?fields."""
        resp = client.get("/api/v1/rich-dict?fields=id")
        body = resp.get_json()
        assert "request_id" in body["meta"]
