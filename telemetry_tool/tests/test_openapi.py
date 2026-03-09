"""Tests for comprehensive OpenAPI spec generation."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask
from web.openapi import (
    generate_openapi_spec,
    register_openapi,
    _flask_rule_to_openapi_path,
    _collect_pydantic_schemas,
)


# ── Unit tests ────────────────────────────────────────────────────


class TestPathConversion:
    def test_simple_param(self):
        assert _flask_rule_to_openapi_path("/sessions/<session_id>") == "/sessions/{session_id}"

    def test_typed_param(self):
        assert _flask_rule_to_openapi_path("/sessions/<int:id>") == "/sessions/{id}"

    def test_no_params(self):
        assert _flask_rule_to_openapi_path("/sessions") == "/sessions"

    def test_multiple_params(self):
        result = _flask_rule_to_openapi_path("/api/<version>/sessions/<session_id>/laps/<int:lap>")
        assert result == "/api/{version}/sessions/{session_id}/laps/{lap}"


class TestPydanticSchemaExtraction:
    def test_collects_auth_schemas(self):
        schemas = _collect_pydantic_schemas()
        assert "RegisterSchema" in schemas
        assert "LoginSchema" in schemas

    def test_register_schema_has_email_field(self):
        schemas = _collect_pydantic_schemas()
        reg = schemas.get("RegisterSchema", {})
        props = reg.get("properties", {})
        assert "email" in props
        assert "password" in props

    def test_team_schemas_collected(self):
        schemas = _collect_pydantic_schemas()
        assert "CreateTeamSchema" in schemas
        assert "InviteMemberSchema" in schemas

    def test_pagination_params_collected(self):
        schemas = _collect_pydantic_schemas()
        assert "PaginationParams" in schemas
        props = schemas["PaginationParams"].get("properties", {})
        assert "limit" in props
        assert "cursor" in props


# ── Integration tests ─────────────────────────────────────────────


@pytest.fixture
def app():
    """Flask app with sample API routes."""
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/api/v1/sessions")
    def list_sessions():
        """List all sessions."""
        return {"ok": True}

    @app.route("/api/v1/sessions/<session_id>")
    def get_session(session_id):
        """Get session detail.

        Returns full session data including metadata.
        """
        return {"ok": True}

    @app.route("/api/v1/sessions/<session_id>", methods=["DELETE"])
    def delete_session(session_id):
        """Delete a session."""
        return {"ok": True}

    @app.route("/api/v1/sessions", methods=["POST"])
    def create_session():
        """Upload a new session."""
        return {"ok": True}

    @app.route("/healthz")
    def healthz():
        """Health check."""
        return {"ok": True}

    @app.route("/not-api/page")
    def page():
        return "html"

    register_openapi(app)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestOpenApiSpec:
    def test_spec_endpoint_returns_200(self, client):
        resp = client.get("/api/v1/openapi.json")
        assert resp.status_code == 200

    def test_spec_has_openapi_version(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        assert spec["openapi"] == "3.0.3"

    def test_spec_has_info(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        assert "title" in spec["info"]
        assert "version" in spec["info"]
        assert spec["info"]["version"] == "1.7.0"

    def test_spec_has_servers(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        urls = [s["url"] for s in spec["servers"]]
        assert "https://api.lap-coach.racing" in urls
        assert "http://localhost:5000" in urls

    def test_spec_includes_api_paths(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        assert "/api/v1/sessions" in spec["paths"]
        assert "/api/v1/sessions/{session_id}" in spec["paths"]

    def test_spec_includes_healthz(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        assert "/healthz" in spec["paths"]

    def test_spec_excludes_non_api_paths(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        assert "/not-api/page" not in spec["paths"]

    def test_spec_excludes_self(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        assert "/api/v1/openapi.json" not in spec["paths"]
        assert "/api/v1/docs" not in spec["paths"]

    def test_path_params_extracted(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        session_path = spec["paths"].get("/api/v1/sessions/{session_id}", {})
        get_op = session_path.get("get", {})
        params = get_op.get("parameters", [])
        assert any(p["name"] == "session_id" for p in params)

    def test_post_has_request_body(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        post_op = spec["paths"]["/api/v1/sessions"]["post"]
        assert "requestBody" in post_op

    def test_delete_method_present(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        session_path = spec["paths"]["/api/v1/sessions/{session_id}"]
        assert "delete" in session_path

    def test_docstring_used_as_summary(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        get_op = spec["paths"]["/api/v1/sessions"]["get"]
        # Route metadata overrides docstring when registered
        assert "session" in get_op["summary"].lower()

    def test_multiline_docstring_split(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        get_op = spec["paths"]["/api/v1/sessions/{session_id}"]["get"]
        assert "session" in get_op["summary"].lower()
        assert "description" in get_op or "summary" in get_op

    def test_security_scheme_defined(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        assert "bearerAuth" in spec["components"]["securitySchemes"]

    def test_api_envelope_schema(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        assert "ApiEnvelope" in spec["components"]["schemas"]
        envelope = spec["components"]["schemas"]["ApiEnvelope"]
        assert "ok" in envelope["properties"]

    def test_error_response_schema(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        assert "ErrorResponse" in spec["components"]["schemas"]
        assert "ValidationError" in spec["components"]["schemas"]

    def test_rate_limit_429_documented(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        sessions_get = spec["paths"]["/api/v1/sessions"]["get"]
        assert "429" in sessions_get["responses"]
        assert "Retry-After" in sessions_get["responses"]["429"]["headers"]

    def test_error_codes_enumerated(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        envelope = spec["components"]["schemas"]["ApiEnvelope"]
        error_code = envelope["properties"]["error"]["properties"]["code"]
        assert "enum" in error_code
        assert "RATE_LIMITED" in error_code["enum"]
        assert "NOT_FOUND" in error_code["enum"]

    def test_pydantic_schemas_included(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        schemas = spec["components"]["schemas"]
        assert "RegisterSchema" in schemas
        assert "LoginSchema" in schemas

    def test_tags_have_descriptions(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        assert "tags" in spec
        tag_names = {t["name"] for t in spec["tags"]}
        assert "auth" in tag_names
        assert "sessions" in tag_names
        assert "telemetry-data" in tag_names

    def test_info_description_has_rate_limits(self, client):
        spec = client.get("/api/v1/openapi.json").get_json()
        desc = spec["info"]["description"]
        assert "Rate Limits" in desc
        assert "read" in desc


class TestSwaggerUI:
    def test_docs_endpoint_returns_html(self, client):
        resp = client.get("/api/v1/docs")
        assert resp.status_code == 200
        assert b"swagger-ui" in resp.data

    def test_docs_content_type(self, client):
        resp = client.get("/api/v1/docs")
        assert "text/html" in resp.content_type

    def test_docs_references_spec_url(self, client):
        resp = client.get("/api/v1/docs")
        assert b"/api/v1/openapi.json" in resp.data
