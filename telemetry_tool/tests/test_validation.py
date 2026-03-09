"""Tests for Pydantic request validation decorators."""
import json
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.api_utils import ErrorCode, api_response, init_request_id
from web.schemas.common import PaginationParams
from web.validation import validate_body, validate_params

# ---------------------------------------------------------------------------
# Test schemas
# ---------------------------------------------------------------------------

class CreateItemSchema(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    quantity: int = Field(gt=0)
    tags: list[str] = Field(default_factory=list)


class OptionalFieldsSchema(BaseModel):
    title: str
    description: str | None = None
    priority: int = 1


class StrictTypesSchema(BaseModel):
    count: int
    enabled: bool
    ratio: float


class FilterParamsSchema(BaseModel):
    status: str = "active"
    min_score: float = 0.0
    limit: int = Field(default=10, ge=1, le=100)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Flask app with validation-decorated routes."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)

    @app.route("/items", methods=["POST"])
    @validate_body(CreateItemSchema)
    def create_item():
        item = g.body
        return api_response({"name": item.name, "quantity": item.quantity, "tags": item.tags}, status=201)

    @app.route("/optional", methods=["POST"])
    @validate_body(OptionalFieldsSchema)
    def create_optional():
        return api_response({"title": g.body.title, "description": g.body.description, "priority": g.body.priority})

    @app.route("/strict", methods=["POST"])
    @validate_body(StrictTypesSchema)
    def strict_route():
        return api_response({"count": g.body.count})

    @app.route("/search")
    @validate_params(FilterParamsSchema)
    def search():
        p = g.params
        return api_response({"status": p.status, "min_score": p.min_score, "limit": p.limit})

    @app.route("/paginated")
    @validate_params(PaginationParams)
    def paginated():
        p = g.params
        return api_response({"limit": p.limit, "cursor": p.cursor, "sort": p.sort, "order": p.order})

    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# @validate_body — happy path
# ---------------------------------------------------------------------------

class TestValidateBodySuccess:
    def test_valid_body_passes(self, client):
        """Well-formed JSON body is accepted and accessible via g.body."""
        resp = client.post("/items", json={"name": "Widget", "quantity": 5})
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["name"] == "Widget"
        assert body["data"]["quantity"] == 5

    def test_optional_fields_use_defaults(self, client):
        """Optional / defaulted fields get their default values."""
        resp = client.post("/optional", json={"title": "Hello"})
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["description"] is None
        assert data["priority"] == 1

    def test_tags_default_to_empty_list(self, client):
        """Default factory fields initialise correctly."""
        resp = client.post("/items", json={"name": "Widget", "quantity": 1})
        data = resp.get_json()["data"]
        assert data["tags"] == []

    def test_explicit_tags(self, client):
        """Provided list fields are preserved."""
        resp = client.post("/items", json={"name": "Widget", "quantity": 1, "tags": ["a", "b"]})
        data = resp.get_json()["data"]
        assert data["tags"] == ["a", "b"]


# ---------------------------------------------------------------------------
# @validate_body — error cases
# ---------------------------------------------------------------------------

class TestValidateBodyErrors:
    def test_missing_required_field(self, client):
        """Missing required field returns VALIDATION_ERROR with field name."""
        resp = client.post("/items", json={"name": "Widget"})
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
        fields = [d["field"] for d in body["error"]["details"]]
        assert "quantity" in fields

    def test_type_error(self, client):
        """Wrong type returns VALIDATION_ERROR."""
        resp = client.post("/strict", json={"count": "not_int", "enabled": True, "ratio": 1.5})
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        fields = [d["field"] for d in body["error"]["details"]]
        assert "count" in fields

    def test_all_errors_returned_at_once(self, client):
        """Multiple validation errors are returned in a single response."""
        resp = client.post("/items", json={"name": "x", "quantity": -1})
        assert resp.status_code == 422
        body = resp.get_json()
        details = body["error"]["details"]
        assert len(details) >= 2
        fields = {d["field"] for d in details}
        assert "name" in fields
        assert "quantity" in fields

    def test_constraint_violation(self, client):
        """Constraint violations (min_length, gt) surface as details."""
        resp = client.post("/items", json={"name": "A", "quantity": 0})
        assert resp.status_code == 422
        body = resp.get_json()
        assert len(body["error"]["details"]) >= 2

    def test_missing_json_body(self, client):
        """Request with no JSON body returns VALIDATION_ERROR."""
        resp = client.post("/items", content_type="application/json", data="")
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_malformed_json(self, client):
        """Unparseable JSON returns VALIDATION_ERROR."""
        resp = client.post("/items", content_type="application/json", data="{bad json")
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_error_details_have_field_and_message(self, client):
        """Each detail entry has 'field' and 'message' keys."""
        resp = client.post("/items", json={"name": "x", "quantity": -1})
        body = resp.get_json()
        for detail in body["error"]["details"]:
            assert "field" in detail
            assert "message" in detail

    def test_error_contains_request_id(self, client):
        """Validation error responses still include request_id in meta."""
        resp = client.post("/items", json={})
        body = resp.get_json()
        assert "request_id" in body["meta"]
        assert len(body["meta"]["request_id"]) == 32


# ---------------------------------------------------------------------------
# @validate_params
# ---------------------------------------------------------------------------

class TestValidateParams:
    def test_valid_params(self, client):
        """Query params are parsed and accessible via g.params."""
        resp = client.get("/search?status=inactive&min_score=75.0&limit=50")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["status"] == "inactive"
        assert data["min_score"] == 75.0
        assert data["limit"] == 50

    def test_default_params(self, client):
        """Missing query params use schema defaults."""
        resp = client.get("/search")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["status"] == "active"
        assert data["min_score"] == 0.0
        assert data["limit"] == 10

    def test_invalid_params(self, client):
        """Invalid query params return VALIDATION_ERROR."""
        resp = client.get("/search?limit=999")
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        fields = [d["field"] for d in body["error"]["details"]]
        assert "limit" in fields

    def test_type_coercion_params(self, client):
        """Numeric query params are coerced from strings."""
        resp = client.get("/search?min_score=42.5")
        data = resp.get_json()["data"]
        assert data["min_score"] == 42.5


# ---------------------------------------------------------------------------
# PaginationParams schema
# ---------------------------------------------------------------------------

class TestPaginationParams:
    def test_defaults(self, client):
        """PaginationParams provides correct defaults."""
        resp = client.get("/paginated")
        data = resp.get_json()["data"]
        assert data["limit"] == 25
        assert data["cursor"] is None
        assert data["sort"] is None
        assert data["order"] == "desc"

    def test_explicit_values(self, client):
        """PaginationParams accepts explicit overrides."""
        resp = client.get("/paginated?limit=10&cursor=abc123&sort=created_at&order=asc")
        data = resp.get_json()["data"]
        assert data["limit"] == 10
        assert data["cursor"] == "abc123"
        assert data["sort"] == "created_at"
        assert data["order"] == "asc"

    def test_limit_min_boundary(self, client):
        """Limit below 1 is rejected."""
        resp = client.get("/paginated?limit=0")
        assert resp.status_code == 422

    def test_limit_max_boundary(self, client):
        """Limit above 100 is rejected."""
        resp = client.get("/paginated?limit=101")
        assert resp.status_code == 422

    def test_sort_rejects_sql_injection(self, client):
        """Sort field rejects values that aren't simple identifiers."""
        resp = client.get("/paginated?sort=name;DROP TABLE users")
        assert resp.status_code == 422

    def test_sort_accepts_valid_identifier(self, client):
        """Sort field accepts valid column names like 'created_at'."""
        resp = client.get("/paginated?sort=created_at")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["sort"] == "created_at"
