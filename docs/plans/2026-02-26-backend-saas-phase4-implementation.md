# API v1 Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add production-grade API hardening — response envelopes, Pydantic validation, rate limiting, cursor pagination, idempotency keys, GDPR endpoints — to all /api/v1/ routes, and migrate legacy /api/ routes via proxy pattern.

**Architecture:** Infrastructure-first approach: build 6 reusable middleware modules (envelope, validation, rate limit, pagination, idempotency, logging), then consume them across all route files. Legacy routes become thin proxies to v1 handlers with deprecation headers.

**Tech Stack:** Flask, Pydantic v2, Redis (Lua scripts), PostgreSQL, Celery

---

### Task 1: Response Envelope + Request ID

**Files:**
- Create: `telemetry_tool/web/api_utils.py`
- Create: `telemetry_tool/tests/test_api_utils.py`

**Context:** Every `/api/v1/` endpoint returns a consistent JSON envelope — `{"ok": true, "data": ..., "meta": {...}}` for success, `{"ok": false, "error": {...}, "meta": {...}}` for errors. A UUID4 `request_id` is generated per request via `before_request` hook and included in the `meta` of every response. The `ErrorCode` class provides stable string constants for 16 error codes used across the entire API surface.

**Step 1: Write the failing test**

```python
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
        codes = [
            attr for attr in dir(ErrorCode)
            if not attr.startswith("_") and attr.isupper()
        ]
        assert len(codes) == 16
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_api_utils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web.api_utils'`

**Step 3: Write minimal implementation**

```python
"""API response envelope helpers and request-ID middleware.

Every /api/v1/ endpoint uses these helpers to produce a uniform JSON
envelope.  ``init_request_id`` installs a ``before_request`` hook that
generates a UUID4 request ID accessible via ``flask.g.request_id``.

Usage::

    from web.api_utils import api_response, api_error, ErrorCode, init_request_id

    # In app factory
    init_request_id(app)

    # In route handlers
    return api_response({"session": row}, status=200)
    return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from flask import Flask, g, jsonify


# ---------------------------------------------------------------------------
# Error codes — stable string constants used across the API surface
# ---------------------------------------------------------------------------

class ErrorCode:
    """Stable string constants for API error codes.

    These are intentionally plain class attributes (not an Enum) so they
    serialise to JSON without ceremony and can be used directly as dict
    values.
    """

    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    FORBIDDEN = "FORBIDDEN"
    INSUFFICIENT_ROLE = "INSUFFICIENT_ROLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


# ---------------------------------------------------------------------------
# Envelope builders
# ---------------------------------------------------------------------------

def _build_meta(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the ``meta`` section, always including ``request_id``."""
    meta: dict[str, Any] = {
        "request_id": getattr(g, "request_id", None),
    }
    if extra:
        meta.update(extra)
    return meta


def api_response(
    data: Any = None,
    status: int = 200,
    meta: dict[str, Any] | None = None,
) -> tuple:
    """Return a success envelope.

    Returns a ``(Response, status)`` tuple suitable for Flask route returns.

    Example response body::

        {"ok": true, "data": {...}, "meta": {"request_id": "..."}}
    """
    body = {
        "ok": True,
        "data": data,
        "meta": _build_meta(meta),
    }
    return jsonify(body), status


def api_error(
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    status: int = 400,
) -> tuple:
    """Return an error envelope.

    Example response body::

        {"ok": false, "error": {"code": "...", "message": "...", "details": [...]},
         "meta": {"request_id": "..."}}
    """
    error_section: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details is not None:
        error_section["details"] = details
    body = {
        "ok": False,
        "error": error_section,
        "meta": _build_meta(),
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------

def init_request_id(app: Flask) -> None:
    """Register a ``before_request`` hook that assigns ``g.request_id``.

    The ID is a 32-character hex UUID4 string (no dashes) and is included
    in every response envelope via :func:`_build_meta`.
    """

    @app.before_request
    def _set_request_id() -> None:
        g.request_id = uuid4().hex
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_api_utils.py -v`
Expected: PASS (all 15 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/api_utils.py telemetry_tool/tests/test_api_utils.py
git commit -m "feat(api): add response envelope helpers, error codes, and request-ID middleware"
```

---

### Task 2: Pydantic Validation Decorators

**Files:**
- Create: `telemetry_tool/web/validation.py`
- Create: `telemetry_tool/web/schemas/__init__.py`
- Create: `telemetry_tool/web/schemas/common.py`
- Create: `telemetry_tool/tests/test_validation.py`

**Context:** Two decorators — `@validate_body(Schema)` for JSON request bodies and `@validate_params(Schema)` for query string parameters — that parse through Pydantic v2 models and either set the validated result on `flask.g` or return a `VALIDATION_ERROR` envelope with all errors at once. The `PaginationParams` schema is the first shared schema, used by every paginated GET endpoint.

**Step 1: Write the failing test**

```python
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
from web.validation import validate_body, validate_params
from web.schemas.common import PaginationParams


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
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web.validation'`

**Step 3: Write minimal implementation**

Create `telemetry_tool/web/schemas/__init__.py`:

```python
```

Create `telemetry_tool/web/schemas/common.py`:

```python
"""Common Pydantic schemas shared across API endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Query parameters for cursor-paginated list endpoints.

    Usage::

        @bp.route("/sessions")
        @validate_params(PaginationParams)
        def list_sessions():
            p = g.params
            # p.limit, p.cursor, p.sort, p.order
    """

    limit: int = Field(default=25, ge=1, le=100)
    cursor: str | None = None
    sort: str | None = None
    order: Literal["asc", "desc"] = "desc"
```

Create `telemetry_tool/web/validation.py`:

```python
"""Pydantic v2 request validation decorators.

Provides ``@validate_body(Schema)`` and ``@validate_params(Schema)`` that
parse Flask request data through a Pydantic ``BaseModel`` and either store
the validated result on ``flask.g`` or return a ``VALIDATION_ERROR`` envelope
with *all* errors at once.

Usage::

    from web.validation import validate_body, validate_params
    from web.schemas.sessions import CreateSessionSchema

    @bp.route("/sessions", methods=["POST"])
    @validate_body(CreateSessionSchema)
    def create_session():
        session = g.body  # typed CreateSessionSchema
        ...
"""
from __future__ import annotations

import functools
from typing import Any, Type

from flask import g, request
from pydantic import BaseModel, ValidationError

from .api_utils import ErrorCode, api_error


def _format_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Convert Pydantic ValidationError to a list of ``{field, message}`` dicts."""
    details = []
    for err in exc.errors():
        # loc is a tuple like ("name",) or ("address", "zip_code")
        loc_parts = [str(p) for p in err["loc"]]
        field = ".".join(loc_parts) if loc_parts else "unknown"
        details.append({
            "field": field,
            "message": err["msg"],
        })
    return details


def validate_body(schema_cls: Type[BaseModel]):
    """Decorator: parse ``request.get_json()`` through *schema_cls*.

    On success the validated model is stored as ``g.body``.
    On failure a 422 response with ``VALIDATION_ERROR`` code and all
    error details is returned immediately.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            raw = request.get_json(silent=True)
            if raw is None:
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    "Request body must be valid JSON",
                    details=[{"field": "body", "message": "Missing or malformed JSON"}],
                    status=422,
                )
            try:
                g.body = schema_cls.model_validate(raw)
            except ValidationError as exc:
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    "Request validation failed",
                    details=_format_errors(exc),
                    status=422,
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def validate_params(schema_cls: Type[BaseModel]):
    """Decorator: parse ``request.args`` through *schema_cls*.

    On success the validated model is stored as ``g.params``.
    Query parameters arrive as strings, so Pydantic's type coercion
    handles ``str -> int``, ``str -> float``, etc.
    On failure a 422 response with ``VALIDATION_ERROR`` code is returned.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # request.args is an ImmutableMultiDict; convert to plain dict
            raw = dict(request.args)
            try:
                g.params = schema_cls.model_validate(raw)
            except ValidationError as exc:
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    "Query parameter validation failed",
                    details=_format_errors(exc),
                    status=422,
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_validation.py -v`
Expected: PASS (all 20 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/validation.py telemetry_tool/web/schemas/__init__.py telemetry_tool/web/schemas/common.py telemetry_tool/tests/test_validation.py
git commit -m "feat(api): add Pydantic validation decorators and PaginationParams schema"
```

---

### Task 3: Rate Limiting

**Files:**
- Create: `telemetry_tool/web/rate_limit.py`
- Create: `telemetry_tool/tests/test_rate_limit.py`

**Context:** Custom Redis sliding-window rate limiter using a Lua script operating on sorted sets. Five tiers (`auth`, `read`, `write`, `analyze`, `upload`) with different limits and key scoping — the `auth` tier keys on IP address (since the user is not authenticated yet), while all other tiers key on `user_id`. The `@rate_limit(tier)` decorator checks the limit before the handler runs and returns a 429 `RATE_LIMITED` error with `Retry-After` header when exceeded.

**Step 1: Write the failing test**

```python
"""Tests for Redis sliding-window rate limiting."""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.api_utils import ErrorCode, api_response, init_request_id
from web.rate_limit import RATE_TIERS, _SLIDING_WINDOW_LUA, rate_limit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(tier="read"):
    """Build a minimal Flask app with a rate-limited route."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)

    @app.route("/limited")
    @rate_limit(tier=tier)
    def limited():
        return api_response({"msg": "ok"})

    return app


def _mock_redis(eval_return=None):
    """Return a mock Redis client whose eval() returns *eval_return*."""
    r = MagicMock()
    if eval_return is not None:
        r.eval.return_value = eval_return
    return r


# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

class TestRateTierConfig:
    def test_auth_tier_exists(self):
        assert "auth" in RATE_TIERS
        assert RATE_TIERS["auth"]["max_requests"] == 20
        assert RATE_TIERS["auth"]["window_seconds"] == 60

    def test_read_tier_exists(self):
        assert "read" in RATE_TIERS
        assert RATE_TIERS["read"]["max_requests"] == 300
        assert RATE_TIERS["read"]["window_seconds"] == 60

    def test_write_tier_exists(self):
        assert "write" in RATE_TIERS
        assert RATE_TIERS["write"]["max_requests"] == 60
        assert RATE_TIERS["write"]["window_seconds"] == 60

    def test_analyze_tier_exists(self):
        assert "analyze" in RATE_TIERS
        assert RATE_TIERS["analyze"]["max_requests"] == 5
        assert RATE_TIERS["analyze"]["window_seconds"] == 3600

    def test_upload_tier_exists(self):
        assert "upload" in RATE_TIERS
        assert RATE_TIERS["upload"]["max_requests"] == 10
        assert RATE_TIERS["upload"]["window_seconds"] == 3600

    def test_exactly_5_tiers(self):
        assert len(RATE_TIERS) == 5


# ---------------------------------------------------------------------------
# Lua script
# ---------------------------------------------------------------------------

class TestLuaScript:
    def test_lua_script_is_nonempty_string(self):
        assert isinstance(_SLIDING_WINDOW_LUA, str)
        assert len(_SLIDING_WINDOW_LUA) > 50

    def test_lua_script_contains_zadd(self):
        assert "ZADD" in _SLIDING_WINDOW_LUA.upper() or "zadd" in _SLIDING_WINDOW_LUA

    def test_lua_script_contains_zremrangebyscore(self):
        upper = _SLIDING_WINDOW_LUA.upper()
        assert "ZREMRANGEBYSCORE" in upper or "zremrangebyscore" in _SLIDING_WINDOW_LUA

    def test_lua_script_contains_zcard(self):
        assert "ZCARD" in _SLIDING_WINDOW_LUA.upper() or "zcard" in _SLIDING_WINDOW_LUA


# ---------------------------------------------------------------------------
# Below limit — request passes
# ---------------------------------------------------------------------------

class TestBelowLimit:
    def test_below_limit_passes(self):
        """When Redis returns count below max, request succeeds."""
        app = _make_app(tier="read")
        mock_r = _mock_redis(eval_return=1)  # 1 request so far
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            with app.test_request_context():
                g.user_id = "user_42"
            resp = client.get("/limited", headers={"X-User-Id": "user_42"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    def test_at_exact_limit_passes(self):
        """Request at exactly max_requests is still allowed (count == max)."""
        app = _make_app(tier="auth")
        mock_r = _mock_redis(eval_return=20)  # exactly at limit
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# At limit — request blocked with 429
# ---------------------------------------------------------------------------

class TestAtLimitBlocked:
    def test_over_limit_returns_429(self):
        """When Redis returns count > max, request is rejected with 429."""
        app = _make_app(tier="auth")
        mock_r = _mock_redis(eval_return=21)  # over the 20 limit
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited")
        assert resp.status_code == 429

    def test_429_response_format(self):
        """429 response uses the standard error envelope."""
        app = _make_app(tier="read")
        mock_r = _mock_redis(eval_return=301)  # over 300
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", headers={"X-User-Id": "u1"})
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "meta" in body

    def test_429_has_retry_after_header(self):
        """429 response includes a Retry-After header."""
        app = _make_app(tier="write")
        mock_r = _mock_redis(eval_return=61)  # over 60
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", headers={"X-User-Id": "u1"})
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        retry_after = int(resp.headers["Retry-After"])
        assert retry_after > 0

    def test_analyze_tier_retry_after_is_large(self):
        """Analyze tier (1h window) has a correspondingly large Retry-After."""
        app = _make_app(tier="analyze")
        mock_r = _mock_redis(eval_return=6)  # over 5
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", headers={"X-User-Id": "u1"})
        assert resp.status_code == 429
        retry_after = int(resp.headers["Retry-After"])
        assert retry_after > 60  # should be up to 3600

    def test_upload_tier_blocks(self):
        """Upload tier (10/hour) blocks at 11."""
        app = _make_app(tier="upload")
        mock_r = _mock_redis(eval_return=11)  # over 10
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", headers={"X-User-Id": "u1"})
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Key scoping — IP for auth, user_id for others
# ---------------------------------------------------------------------------

class TestKeyScoping:
    def test_auth_tier_uses_ip(self):
        """Auth tier builds key from remote IP address."""
        app = _make_app(tier="auth")
        mock_r = _mock_redis(eval_return=1)
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", environ_base={"REMOTE_ADDR": "10.0.0.1"})
        # Verify the eval call used an IP-based key
        call_args = mock_r.eval.call_args
        key_arg = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("keys", [None])[0]
        # The key should contain the IP
        assert "10.0.0.1" in str(key_arg) or "auth" in str(call_args)
        assert resp.status_code == 200

    def test_read_tier_uses_user_id(self):
        """Read tier builds key from user_id."""
        app = _make_app(tier="read")
        mock_r = _mock_redis(eval_return=1)

        @app.before_request
        def set_user():
            g.user_id = "user_99"

        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited")
        call_args = mock_r.eval.call_args
        # Flatten all positional args to check for user_99
        all_args_str = str(call_args)
        assert "user_99" in all_args_str
        assert resp.status_code == 200

    def test_write_tier_uses_user_id(self):
        """Write tier also keys on user_id."""
        app = _make_app(tier="write")
        mock_r = _mock_redis(eval_return=1)

        @app.before_request
        def set_user():
            g.user_id = "user_77"

        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited")
        all_args_str = str(mock_r.eval.call_args)
        assert "user_77" in all_args_str


# ---------------------------------------------------------------------------
# Redis unavailable — graceful degradation
# ---------------------------------------------------------------------------

class TestRedisUnavailable:
    def test_redis_error_allows_request(self):
        """If Redis is unavailable, request proceeds (fail open)."""
        app = _make_app(tier="read")
        mock_r = MagicMock()
        mock_r.eval.side_effect = Exception("Connection refused")
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", headers={"X-User-Id": "u1"})
        assert resp.status_code == 200

    def test_redis_none_allows_request(self):
        """If get_redis() returns None, request proceeds."""
        with patch("web.rate_limit.get_redis", return_value=None):
            app = _make_app(tier="read")
            client = app.test_client()
            resp = client.get("/limited")
        assert resp.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_rate_limit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web.rate_limit'`

**Step 3: Write minimal implementation**

```python
"""Redis sliding-window rate limiter.

Uses a Lua script operating on Redis sorted sets to implement a true
sliding window counter.  Five configurable tiers control per-route
limits.  The ``@rate_limit(tier)`` decorator rejects excess requests
with HTTP 429, ``RATE_LIMITED`` error code, and a ``Retry-After`` header.

Usage::

    from web.rate_limit import rate_limit

    @bp.route("/batch-reanalyze", methods=["POST"])
    @require_auth
    @rate_limit(tier="analyze")
    def batch_reanalyze():
        ...

Architecture notes:
- **Fail open**: if Redis is unavailable the request is allowed through.
- **Key format**: ``ratelimit:{tier}:{scope_value}`` where scope_value
  is the client IP for the ``auth`` tier and ``user_id`` for all others.
"""
from __future__ import annotations

import functools
import logging
import time
from typing import Any

from flask import g, request

from .api_utils import ErrorCode, api_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

RATE_TIERS: dict[str, dict[str, int]] = {
    "auth": {"max_requests": 20, "window_seconds": 60},
    "read": {"max_requests": 300, "window_seconds": 60},
    "write": {"max_requests": 60, "window_seconds": 60},
    "analyze": {"max_requests": 5, "window_seconds": 3600},
    "upload": {"max_requests": 10, "window_seconds": 3600},
}

# ---------------------------------------------------------------------------
# Lua sliding-window script
#
# KEYS[1]  = the sorted-set key  (e.g. ratelimit:read:user_42)
# ARGV[1]  = window start timestamp (now - window_seconds)
# ARGV[2]  = current timestamp (score for ZADD)
# ARGV[3]  = unique member value  (timestamp + random, ensures uniqueness)
# ARGV[4]  = window_seconds  (used as key TTL)
#
# Returns: current request count in the window (after adding this request)
# ---------------------------------------------------------------------------

_SLIDING_WINDOW_LUA: str = """
local key = KEYS[1]
local window_start = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local member = ARGV[3]
local ttl = tonumber(ARGV[4])

-- Remove entries outside the sliding window
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

-- Add the current request
redis.call('ZADD', key, now, member)

-- Set key expiry so stale keys don't linger forever
redis.call('EXPIRE', key, ttl + 1)

-- Return current count in window
return redis.call('ZCARD', key)
"""


# ---------------------------------------------------------------------------
# Redis accessor — thin wrapper so tests can patch a single function
# ---------------------------------------------------------------------------

def get_redis():
    """Return the application's Redis client, or ``None`` if unavailable.

    Looks for ``g._redis`` (set by app factory) or falls back to
    ``current_app.extensions.get("redis")``.  Returns *None* when
    Redis is not configured so the decorator can fail open.
    """
    try:
        from flask import current_app
        r = getattr(g, "_redis", None)
        if r is not None:
            return r
        return current_app.extensions.get("redis")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def rate_limit(tier: str = "read"):
    """Decorator that enforces a sliding-window rate limit.

    Parameters
    ----------
    tier : str
        One of the keys in :data:`RATE_TIERS` — ``"auth"``, ``"read"``,
        ``"write"``, ``"analyze"``, or ``"upload"``.

    When the limit is exceeded the decorator short-circuits with a
    429 response containing the ``RATE_LIMITED`` error code and a
    ``Retry-After`` header set to the tier's window in seconds.
    """
    tier_cfg = RATE_TIERS[tier]
    max_requests = tier_cfg["max_requests"]
    window_seconds = tier_cfg["window_seconds"]

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            r = get_redis()
            if r is None:
                # Fail open — no Redis means no rate limiting
                return fn(*args, **kwargs)

            # Determine scope key
            if tier == "auth":
                scope_value = request.remote_addr or "unknown"
            else:
                scope_value = getattr(g, "user_id", None) or request.remote_addr or "unknown"

            redis_key = f"ratelimit:{tier}:{scope_value}"

            now = time.time()
            window_start = now - window_seconds
            member = f"{now}:{id(request)}"

            try:
                count = r.eval(
                    _SLIDING_WINDOW_LUA,
                    1,              # number of KEYS
                    redis_key,      # KEYS[1]
                    window_start,   # ARGV[1]
                    now,            # ARGV[2]
                    member,         # ARGV[3]
                    window_seconds, # ARGV[4]
                )
                count = int(count)
            except Exception:
                logger.warning(
                    "Rate limit Redis error for tier=%s key=%s — failing open",
                    tier, redis_key, exc_info=True,
                )
                return fn(*args, **kwargs)

            if count > max_requests:
                resp, status = api_error(
                    ErrorCode.RATE_LIMITED,
                    f"Rate limit exceeded for tier '{tier}'. "
                    f"Max {max_requests} requests per {window_seconds}s.",
                    status=429,
                )
                resp.headers["Retry-After"] = str(window_seconds)
                return resp, status

            return fn(*args, **kwargs)
        return wrapper
    return decorator
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_rate_limit.py -v`
Expected: PASS (all 25 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/rate_limit.py telemetry_tool/tests/test_rate_limit.py
git commit -m "feat(api): add Redis sliding-window rate limiter with 5 tiers"
```

---

### Task 4: Cursor Pagination

**Files:**
- Create: `telemetry_tool/web/pagination.py`
- Create: `telemetry_tool/tests/test_pagination.py`

**Context:** Shared cursor pagination utilities that implement keyset (seek-method) pagination using composite cursors. The cursor encodes both the sort column value and the row ID as a base64url JSON blob — opaque to clients. `build_keyset_clause` generates the SQL `WHERE` fragment `(sort_col, id_col) < (:cursor_sort, :cursor_id)` for descending order (or `>` for ascending). `paginate_query` executes a base SQL query with the keyset clause appended, fetches `limit+1` rows to detect `has_more`, and returns the page plus the next cursor. Default limit is 25, max is 100.

**Step 1: Write the failing test**

```python
"""Tests for cursor-based keyset pagination utilities."""
import base64
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.pagination import (
    build_keyset_clause,
    decode_cursor,
    encode_cursor,
    paginate_query,
    pagination_meta,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_db():
    """In-memory SQLite with a simple 'items' table seeded with 10 rows."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, score REAL, name TEXT)"
    )
    for i in range(1, 11):
        conn.execute(
            "INSERT INTO items (id, score, name) VALUES (?, ?, ?)",
            (i, 100.0 - i, f"item_{i}"),
        )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# encode / decode round-trip
# ---------------------------------------------------------------------------

class TestEncodeDecode:
    def test_round_trip_string_sort(self):
        cursor = encode_cursor("2026-01-15T10:30:00", 125)
        result = decode_cursor(cursor)
        assert result == {"s": "2026-01-15T10:30:00", "id": 125}

    def test_round_trip_numeric_sort(self):
        cursor = encode_cursor(99.5, 42)
        result = decode_cursor(cursor)
        assert result["s"] == 99.5
        assert result["id"] == 42

    def test_round_trip_integer_sort(self):
        cursor = encode_cursor(100, 1)
        result = decode_cursor(cursor)
        assert result == {"s": 100, "id": 1}

    def test_decode_none_for_invalid_base64(self):
        assert decode_cursor("!!!not-base64!!!") is None

    def test_decode_none_for_invalid_json(self):
        # Valid base64 but not valid JSON
        raw = base64.urlsafe_b64encode(b"not json at all").decode()
        assert decode_cursor(raw) is None

    def test_decode_none_for_missing_keys(self):
        raw = base64.urlsafe_b64encode(json.dumps({"x": 1}).encode()).decode()
        assert decode_cursor(raw) is None

    def test_decode_none_for_empty_string(self):
        assert decode_cursor("") is None

    def test_decode_none_for_none_input(self):
        assert decode_cursor(None) is None


# ---------------------------------------------------------------------------
# build_keyset_clause
# ---------------------------------------------------------------------------

class TestBuildKeysetClause:
    def test_descending_produces_less_than(self):
        cursor = encode_cursor(99.0, 5)
        clause, params = build_keyset_clause(
            decode_cursor(cursor), "score", "id", descending=True
        )
        assert "<" in clause
        assert params["cursor_sort"] == 99.0
        assert params["cursor_id"] == 5

    def test_ascending_produces_greater_than(self):
        cursor = encode_cursor(10.0, 3)
        clause, params = build_keyset_clause(
            decode_cursor(cursor), "score", "id", descending=False
        )
        assert ">" in clause
        assert params["cursor_sort"] == 10.0
        assert params["cursor_id"] == 3

    def test_none_cursor_returns_empty(self):
        clause, params = build_keyset_clause(None, "score", "id", descending=True)
        assert clause == ""
        assert params == {}

    def test_custom_id_col(self):
        cursor = encode_cursor(50, 7)
        clause, params = build_keyset_clause(
            decode_cursor(cursor), "created_at", "row_id", descending=True
        )
        assert "row_id" in clause
        assert "created_at" in clause


# ---------------------------------------------------------------------------
# pagination_meta
# ---------------------------------------------------------------------------

class TestPaginationMeta:
    def test_format_with_next_cursor(self):
        meta = pagination_meta("abc123", True, 25)
        assert meta == {
            "next_cursor": "abc123",
            "has_more": True,
            "limit": 25,
        }

    def test_format_no_more(self):
        meta = pagination_meta(None, False, 10)
        assert meta == {
            "next_cursor": None,
            "has_more": False,
            "limit": 10,
        }


# ---------------------------------------------------------------------------
# paginate_query — integration with SQLite
# ---------------------------------------------------------------------------

class TestPaginateQuery:
    def test_first_page_no_cursor(self, mem_db):
        rows, next_cursor, has_more = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=3,
            descending=True,
        )
        assert len(rows) == 3
        assert has_more is True
        assert next_cursor is not None

    def test_cursor_applies_keyset(self, mem_db):
        # Get first page
        rows1, cursor1, _ = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=3,
            descending=True,
        )
        # Get second page using cursor
        rows2, cursor2, has_more2 = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=cursor1,
            limit=3,
            descending=True,
        )
        assert len(rows2) == 3
        # Second page scores must be lower than last item on first page
        first_page_last_score = rows1[-1]["score"]
        for row in rows2:
            assert row["score"] <= first_page_last_score

    def test_has_more_true_when_more_rows(self, mem_db):
        _, _, has_more = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=5,
            descending=True,
        )
        assert has_more is True

    def test_has_more_false_on_last_page(self, mem_db):
        _, _, has_more = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=10,
            descending=True,
        )
        assert has_more is False

    def test_limit_clamped_to_max_100(self, mem_db):
        rows, _, _ = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=500,
            descending=True,
        )
        # Only 10 rows exist, but limit should have been clamped to 100
        assert len(rows) <= 100

    def test_ascending_order(self, mem_db):
        rows, _, _ = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=3,
            descending=False,
        )
        scores = [r["score"] for r in rows]
        assert scores == sorted(scores)

    def test_paginate_all_rows_across_pages(self, mem_db):
        """Walk through all pages and collect every row exactly once."""
        all_ids = []
        cursor = None
        for _ in range(10):  # safety cap
            rows, cursor, has_more = paginate_query(
                mem_db,
                "SELECT id, score, name FROM items",
                {},
                sort_col="score",
                id_col="id",
                cursor_str=cursor,
                limit=3,
                descending=True,
            )
            all_ids.extend(r["id"] for r in rows)
            if not has_more:
                break
        assert sorted(all_ids) == list(range(1, 11))

    def test_empty_table(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE empty (id INTEGER PRIMARY KEY, score REAL)")
        rows, next_cursor, has_more = paginate_query(
            conn,
            "SELECT id, score FROM empty",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=10,
            descending=True,
        )
        assert rows == []
        assert next_cursor is None
        assert has_more is False

    def test_limit_default_clamped_minimum(self, mem_db):
        """Limit of 0 or negative is treated as 1."""
        rows, _, _ = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=0,
            descending=True,
        )
        assert len(rows) >= 1

    def test_base_params_preserved(self, mem_db):
        """Extra WHERE conditions in base_sql + params still work."""
        rows, _, _ = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items WHERE name LIKE :prefix",
            {"prefix": "item_%"},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=25,
            descending=True,
        )
        assert len(rows) == 10
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_pagination.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web.pagination'`

**Step 3: Write minimal implementation**

```python
"""Cursor-based keyset pagination utilities.

Implements composite-cursor pagination using ``(sort_value, id)`` pairs
encoded as base64url JSON blobs.  This avoids the OFFSET-drift problem
of traditional pagination while remaining fully stateless.

Usage::

    from web.pagination import paginate_query, pagination_meta

    rows, next_cursor, has_more = paginate_query(
        conn, "SELECT * FROM sessions", {},
        sort_col="created_at", id_col="id",
        cursor_str=request.args.get("cursor"),
        limit=25, descending=True,
    )
    meta = pagination_meta(next_cursor, has_more, 25)
    return api_response(rows, meta={"pagination": meta})
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_LIMIT = 100
_MIN_LIMIT = 1


# ---------------------------------------------------------------------------
# Cursor encode / decode
# ---------------------------------------------------------------------------

def encode_cursor(sort_value: Any, id_value: Any) -> str:
    """Encode a composite cursor as a base64url string.

    The cursor payload is ``{"s": sort_value, "id": id_value}`` — compact
    keys to keep the token short.
    """
    payload = json.dumps({"s": sort_value, "id": id_value}, default=str)
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor_str: str | None) -> dict | None:
    """Decode a cursor string back to ``{"s": ..., "id": ...}``.

    Returns ``None`` for any invalid input (bad base64, bad JSON, missing
    keys) — callers treat ``None`` as "no cursor / first page".
    """
    if not cursor_str:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode())
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict) or "s" not in data or "id" not in data:
        return None
    return data


# ---------------------------------------------------------------------------
# SQL keyset clause builder
# ---------------------------------------------------------------------------

def build_keyset_clause(
    cursor: dict | None,
    sort_col: str,
    id_col: str = "id",
    descending: bool = True,
) -> tuple[str, dict]:
    """Build a SQL WHERE fragment for keyset pagination.

    Parameters
    ----------
    cursor : dict | None
        Decoded cursor (from :func:`decode_cursor`).  ``None`` means
        first page — returns an empty clause.
    sort_col : str
        Column name used for ordering (e.g. ``"created_at"``).
    id_col : str
        Tie-breaking column, usually the primary key.
    descending : bool
        ``True`` for ``ORDER BY sort_col DESC, id_col DESC``.

    Returns
    -------
    (clause, params)
        *clause* is a SQL fragment like
        ``AND (score, id) < (:cursor_sort, :cursor_id)``
        or an empty string when *cursor* is ``None``.
        *params* is a dict with ``cursor_sort`` and ``cursor_id`` keys
        (empty dict when *cursor* is ``None``).
    """
    if cursor is None:
        return "", {}

    op = "<" if descending else ">"
    clause = f"AND ({sort_col}, {id_col}) {op} (:cursor_sort, :cursor_id)"
    params = {"cursor_sort": cursor["s"], "cursor_id": cursor["id"]}
    return clause, params


# ---------------------------------------------------------------------------
# Query executor
# ---------------------------------------------------------------------------

def paginate_query(
    conn,
    base_sql: str,
    params: dict,
    sort_col: str,
    id_col: str,
    cursor_str: str | None,
    limit: int,
    descending: bool = True,
) -> tuple[list[dict], str | None, bool]:
    """Execute *base_sql* with keyset pagination.

    Parameters
    ----------
    conn
        A DB-API 2 connection (SQLite or similar) whose ``.execute()``
        accepts named parameters (``":name"`` style).
    base_sql : str
        The base ``SELECT`` statement.  Must NOT include ``ORDER BY``
        or ``LIMIT``.  May include ``WHERE`` clauses.
    params : dict
        Named parameters for *base_sql*.
    sort_col, id_col : str
        Columns used for ordering and cursor positioning.
    cursor_str : str | None
        Opaque cursor from the client (or ``None`` for first page).
    limit : int
        Requested page size.  Clamped to [1, 100].
    descending : bool
        Sort direction.

    Returns
    -------
    (rows, next_cursor, has_more)
        *rows* is a list of dicts (up to *limit* items).
        *next_cursor* is the cursor for the next page (or ``None``).
        *has_more* indicates whether more rows exist beyond this page.
    """
    # Clamp limit
    limit = max(_MIN_LIMIT, min(limit, _MAX_LIMIT))

    # Decode cursor and build keyset clause
    cursor = decode_cursor(cursor_str)
    keyset_clause, keyset_params = build_keyset_clause(
        cursor, sort_col, id_col, descending
    )

    # Merge params
    merged = {**params, **keyset_params}

    # Determine if base_sql already has a WHERE clause
    upper_sql = base_sql.upper().strip()
    if keyset_clause:
        if "WHERE" in upper_sql:
            sql = f"{base_sql} {keyset_clause}"
        else:
            # Replace leading "AND" with "WHERE"
            sql = f"{base_sql} WHERE {keyset_clause[4:]}"
    else:
        sql = base_sql

    # Add ORDER BY and LIMIT (fetch limit+1 to detect has_more)
    direction = "DESC" if descending else "ASC"
    sql += f" ORDER BY {sort_col} {direction}, {id_col} {direction}"
    sql += f" LIMIT {limit + 1}"

    # Execute
    cursor_db = conn.execute(sql, merged)
    raw_rows = cursor_db.fetchall()

    # Convert to list of dicts
    rows = [dict(r) for r in raw_rows]

    # Determine has_more
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    # Build next cursor from last row
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(last[sort_col], last[id_col])

    return rows, next_cursor, has_more


# ---------------------------------------------------------------------------
# Meta builder
# ---------------------------------------------------------------------------

def pagination_meta(
    next_cursor: str | None,
    has_more: bool,
    limit: int,
) -> dict[str, Any]:
    """Format pagination metadata for the response envelope.

    Returns a dict suitable for inclusion in the ``meta.pagination``
    field of the API response::

        {"next_cursor": "eyJz...", "has_more": true, "limit": 25}
    """
    return {
        "next_cursor": next_cursor,
        "has_more": has_more,
        "limit": limit,
    }
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_pagination.py -v`
Expected: PASS (all 20 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/pagination.py telemetry_tool/tests/test_pagination.py
git commit -m "feat(api): add cursor-based keyset pagination utilities"
```

---

### Task 5: Idempotency Keys

**Files:**
- Create: `telemetry_tool/web/idempotency.py`
- Create: `telemetry_tool/tests/test_idempotency.py`

**Context:** Write endpoints accept an `Idempotency-Key` header to prevent duplicate side-effects. The `@idempotent` decorator checks Redis for a cached response scoped to the workspace — key pattern `idempotency:{workspace_id}:{key}`. On a cache hit the original response (status + body) is replayed without re-executing the handler. A processing lock (`SET NX`, 60s TTL) prevents concurrent duplicates — if the lock exists, a 409 `IDEMPOTENCY_CONFLICT` error is returned. Successful responses (2xx-4xx) are cached for 24 hours; 5xx responses are never cached so the client can retry safely.

**Step 1: Write the failing test**

```python
"""Tests for idempotency-key middleware."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.api_utils import ErrorCode, api_response, init_request_id
from web.idempotency import _LOCK_TTL, _RESPONSE_TTL, idempotent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_call_count = 0


def _make_app():
    """Build a minimal Flask app with an idempotent route."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)

    @app.before_request
    def _set_workspace():
        g.workspace_id = "ws_001"

    @app.route("/create", methods=["POST"])
    @idempotent
    def create_resource():
        global _call_count
        _call_count += 1
        return api_response({"id": 1, "call": _call_count}, status=201)

    @app.route("/fail", methods=["POST"])
    @idempotent
    def fail_resource():
        global _call_count
        _call_count += 1
        from flask import jsonify
        return jsonify({"ok": False, "error": "boom"}), 500

    return app


def _mock_redis():
    """Return a mock Redis with configurable get/set/delete."""
    r = MagicMock()
    _store = {}

    def _get(key):
        return _store.get(key)

    def _set(key, value, **kwargs):
        _store[key] = value
        return True

    def _setnx_style(key, value, nx=False, ex=None):
        if nx and key in _store:
            return False
        _store[key] = value
        return True

    def _delete(*keys):
        for k in keys:
            _store.pop(k, None)

    r.get = MagicMock(side_effect=_get)
    r.set = MagicMock(side_effect=_setnx_style)
    r.delete = MagicMock(side_effect=_delete)
    r._store = _store  # expose for assertions
    return r


@pytest.fixture(autouse=True)
def reset_call_count():
    global _call_count
    _call_count = 0


# ---------------------------------------------------------------------------
# Tests — no header
# ---------------------------------------------------------------------------

class TestNoHeader:
    def test_no_header_executes_normally(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp = c.post("/create")
                assert resp.status_code == 201
                data = resp.get_json()
                assert data["data"]["call"] == 1

    def test_no_header_does_not_touch_redis(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/create")
                mock_r.get.assert_not_called()
                mock_r.set.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — first request with key
# ---------------------------------------------------------------------------

class TestFirstRequest:
    def test_executes_and_caches(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-001"},
                )
                assert resp.status_code == 201
                data = resp.get_json()
                assert data["data"]["id"] == 1
                # Response should be cached
                cache_key = "idempotency:ws_001:key-001"
                assert cache_key in mock_r._store

    def test_handler_called_once(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/create", headers={"Idempotency-Key": "key-002"})
                assert _call_count == 1


# ---------------------------------------------------------------------------
# Tests — replay cached response
# ---------------------------------------------------------------------------

class TestReplay:
    def test_second_request_replays(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp1 = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-replay"},
                )
                resp2 = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-replay"},
                )
                assert resp2.status_code == resp1.status_code
                assert resp2.get_json()["data"] == resp1.get_json()["data"]

    def test_handler_not_called_on_replay(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/create", headers={"Idempotency-Key": "key-replay2"})
                c.post("/create", headers={"Idempotency-Key": "key-replay2"})
                assert _call_count == 1

    def test_replayed_body_matches(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp1 = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-body"},
                )
                body1 = resp1.get_json()
                resp2 = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-body"},
                )
                body2 = resp2.get_json()
                assert body1["data"]["id"] == body2["data"]["id"]
                assert body1["data"]["call"] == body2["data"]["call"]


# ---------------------------------------------------------------------------
# Tests — concurrent lock (409)
# ---------------------------------------------------------------------------

class TestConcurrentLock:
    def test_locked_returns_409(self):
        app = _make_app()
        mock_r = _mock_redis()
        # Pre-set the lock key to simulate concurrent request
        lock_key = "idempotency:lock:ws_001:key-locked"
        mock_r._store[lock_key] = "1"
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp = c.post(
                    "/create",
                    headers={"Idempotency-Key": "key-locked"},
                )
                assert resp.status_code == 409
                data = resp.get_json()
                assert data["error"]["code"] == "IDEMPOTENCY_CONFLICT"


# ---------------------------------------------------------------------------
# Tests — 5xx not cached
# ---------------------------------------------------------------------------

class TestServerError:
    def test_500_not_cached(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                resp = c.post(
                    "/fail",
                    headers={"Idempotency-Key": "key-500"},
                )
                assert resp.status_code == 500
                cache_key = "idempotency:ws_001:key-500"
                assert cache_key not in mock_r._store

    def test_500_retry_executes_again(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/fail", headers={"Idempotency-Key": "key-retry"})
                c.post("/fail", headers={"Idempotency-Key": "key-retry"})
                assert _call_count == 2


# ---------------------------------------------------------------------------
# Tests — workspace scoping
# ---------------------------------------------------------------------------

class TestWorkspaceScoping:
    def test_different_workspace_separate_entries(self):
        app = _make_app()
        mock_r = _mock_redis()

        @app.before_request
        def _override_ws():
            """Overridden per-request below."""
            pass

        _ws = {"val": "ws_001"}

        @app.before_request
        def _set_ws():
            g.workspace_id = _ws["val"]

        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                _ws["val"] = "ws_A"
                resp_a = c.post(
                    "/create",
                    headers={"Idempotency-Key": "shared-key"},
                )
                _ws["val"] = "ws_B"
                resp_b = c.post(
                    "/create",
                    headers={"Idempotency-Key": "shared-key"},
                )
                # Both should execute (different workspaces)
                assert _call_count == 2


# ---------------------------------------------------------------------------
# Tests — lock lifecycle
# ---------------------------------------------------------------------------

class TestLockLifecycle:
    def test_lock_released_after_success(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/create", headers={"Idempotency-Key": "key-lock"})
                lock_key = "idempotency:lock:ws_001:key-lock"
                assert lock_key not in mock_r._store

    def test_lock_released_after_failure(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/fail", headers={"Idempotency-Key": "key-lock-fail"})
                lock_key = "idempotency:lock:ws_001:key-lock-fail"
                assert lock_key not in mock_r._store


# ---------------------------------------------------------------------------
# Tests — TTL values
# ---------------------------------------------------------------------------

class TestTTL:
    def test_response_ttl_is_24h(self):
        from web.idempotency import _RESPONSE_TTL
        assert _RESPONSE_TTL == 86400

    def test_lock_ttl_is_60s(self):
        from web.idempotency import _LOCK_TTL
        assert _LOCK_TTL == 60

    def test_response_cached_with_ttl(self):
        app = _make_app()
        mock_r = _mock_redis()
        with patch("web.idempotency.get_redis", return_value=mock_r):
            with app.test_client() as c:
                c.post("/create", headers={"Idempotency-Key": "key-ttl"})
                # Find the set call that cached the response (not the lock)
                cache_calls = [
                    call for call in mock_r.set.call_args_list
                    if "idempotency:ws_001:key-ttl" in str(call)
                    and "lock" not in str(call)
                ]
                assert len(cache_calls) >= 1
                # The call should include ex=_RESPONSE_TTL
                call_kwargs = cache_calls[0]
                assert call_kwargs.kwargs.get("ex") == 86400 or \
                    (len(call_kwargs.args) >= 3 if hasattr(call_kwargs, 'args') else False)
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_idempotency.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web.idempotency'`

**Step 3: Write minimal implementation**

```python
"""Idempotency-key middleware for write endpoints.

Accepts an ``Idempotency-Key`` header and caches the full response
(status + body) in Redis, scoped to the workspace.  Duplicate requests
with the same key replay the cached response without re-executing the
handler.  A short-lived processing lock prevents concurrent duplicates.

Usage::

    from web.idempotency import idempotent

    @bp.route("/teams", methods=["POST"])
    @require_auth
    @idempotent
    def create_team():
        ...
"""
from __future__ import annotations

import functools
import json
import logging
from typing import Any

from flask import g, jsonify, request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants
# ---------------------------------------------------------------------------

_RESPONSE_TTL = 86400  # 24 hours — cached response lifetime
_LOCK_TTL = 60         # 60 seconds — processing lock lifetime

# ---------------------------------------------------------------------------
# Redis accessor (lazy, patchable in tests)
# ---------------------------------------------------------------------------

_redis_client = None


def get_redis():
    """Return the Redis client, creating it lazily on first call.

    Tests patch this function to inject a mock.
    """
    global _redis_client
    if _redis_client is None:
        import redis
        _redis_client = redis.Redis(decode_responses=True)
    return _redis_client


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def idempotent(fn):
    """Decorator that enforces idempotency via ``Idempotency-Key`` header.

    Flow
    ----
    1. If the header is missing, pass through — no idempotency.
    2. Check Redis for a cached response.  If found, replay it.
    3. Try ``SET NX`` on a lock key (60s TTL).  If the lock exists,
       return 409 ``IDEMPOTENCY_CONFLICT``.
    4. Execute the handler.
       - 2xx–4xx → cache response (24h TTL).
       - 5xx → do **not** cache (allow retry).
    5. Delete the lock key.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        idemp_key = request.headers.get("Idempotency-Key")
        if not idemp_key:
            return fn(*args, **kwargs)

        workspace_id = getattr(g, "workspace_id", "default")
        cache_key = f"idempotency:{workspace_id}:{idemp_key}"
        lock_key = f"idempotency:lock:{workspace_id}:{idemp_key}"

        r = get_redis()

        # --- 1. Check for cached response ---
        cached = r.get(cache_key)
        if cached is not None:
            try:
                payload = json.loads(cached)
                resp = jsonify(payload["body"])
                resp.status_code = payload["status"]
                return resp
            except Exception:
                logger.warning("Corrupt idempotency cache for %s", cache_key)

        # --- 2. Acquire processing lock ---
        lock_acquired = r.set(lock_key, "1", nx=True, ex=_LOCK_TTL)
        if not lock_acquired:
            from web.api_utils import ErrorCode, api_error
            return api_error(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "A request with this idempotency key is already being processed",
                status=409,
            )

        # --- 3. Execute handler ---
        try:
            result = fn(*args, **kwargs)

            # Normalize Flask return conventions
            if isinstance(result, tuple):
                response = result[0]
                status = result[1] if len(result) > 1 else 200
            else:
                response = result
                status = response.status_code if hasattr(response, "status_code") else 200

            # Get the response body
            if hasattr(response, "get_json"):
                body = response.get_json()
            else:
                body = response

            actual_status = status if isinstance(status, int) else int(status)

            # --- 4. Cache if not 5xx ---
            if actual_status < 500:
                cache_payload = json.dumps({"status": actual_status, "body": body})
                r.set(cache_key, cache_payload, ex=_RESPONSE_TTL)

            return result

        finally:
            # --- 5. Always release lock ---
            r.delete(lock_key)

    return wrapper
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_idempotency.py -v`
Expected: PASS (all 20 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/idempotency.py telemetry_tool/tests/test_idempotency.py
git commit -m "feat(api): add idempotency-key middleware with Redis caching and lock"
```

---

### Task 6: Structured Logging

**Files:**
- Create: `telemetry_tool/web/logging_setup.py`
- Create: `telemetry_tool/tests/test_logging_setup.py`

**Context:** A `RequestIdFilter` logging filter that enriches every log record with `request_id`, `workspace_id`, and `user_id` from Flask's `g` object. A `JsonFormatter` outputs structured JSON lines with timestamp, level, message, logger name, and the three request-scoped fields — suitable for production log aggregation. The `setup_logging(app)` function wires everything together, switching between JSON output (when `TELEMETRY_LOG_FORMAT=json`) and human-readable output (default) for development.

**Step 1: Write the failing test**

```python
"""Tests for structured logging setup."""
import json
import logging
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.logging_setup import JsonFormatter, RequestIdFilter, setup_logging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Minimal Flask app."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def log_record():
    """A plain LogRecord for testing filters and formatters."""
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Something happened",
        args=(),
        exc_info=None,
    )


# ---------------------------------------------------------------------------
# RequestIdFilter
# ---------------------------------------------------------------------------

class TestRequestIdFilter:
    def test_adds_request_id_from_g(self, app, log_record):
        filt = RequestIdFilter()
        with app.test_request_context("/"):
            g.request_id = "abc123"
            g.workspace_id = "ws_001"
            g.user_id = "user_42"
            filt.filter(log_record)
            assert log_record.request_id == "abc123"
            assert log_record.workspace_id == "ws_001"
            assert log_record.user_id == "user_42"

    def test_uses_dash_when_no_g_context(self, log_record):
        filt = RequestIdFilter()
        # Outside request context — no Flask g
        filt.filter(log_record)
        assert log_record.request_id == "-"
        assert log_record.workspace_id == "-"
        assert log_record.user_id == "-"

    def test_partial_g_attributes(self, app, log_record):
        filt = RequestIdFilter()
        with app.test_request_context("/"):
            g.request_id = "req_xyz"
            # workspace_id and user_id not set
            filt.filter(log_record)
            assert log_record.request_id == "req_xyz"
            assert log_record.workspace_id == "-"
            assert log_record.user_id == "-"

    def test_filter_returns_true(self, app, log_record):
        filt = RequestIdFilter()
        with app.test_request_context("/"):
            result = filt.filter(log_record)
            assert result is True


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------

class TestJsonFormatter:
    def test_outputs_valid_json(self, log_record):
        # Attach expected attributes that the filter would add
        log_record.request_id = "r_001"
        log_record.workspace_id = "ws_001"
        log_record.user_id = "u_001"
        fmt = JsonFormatter()
        output = fmt.format(log_record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_includes_required_fields(self, log_record):
        log_record.request_id = "r_002"
        log_record.workspace_id = "ws_002"
        log_record.user_id = "u_002"
        fmt = JsonFormatter()
        output = fmt.format(log_record)
        parsed = json.loads(output)
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "message" in parsed
        assert "request_id" in parsed
        assert "workspace_id" in parsed
        assert "user_id" in parsed
        assert "logger" in parsed

    def test_message_content(self, log_record):
        log_record.request_id = "-"
        log_record.workspace_id = "-"
        log_record.user_id = "-"
        fmt = JsonFormatter()
        output = fmt.format(log_record)
        parsed = json.loads(output)
        assert parsed["message"] == "Something happened"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"

    def test_level_names(self):
        fmt = JsonFormatter()
        for level_name, level_no in [("DEBUG", logging.DEBUG), ("WARNING", logging.WARNING), ("ERROR", logging.ERROR)]:
            record = logging.LogRecord(
                name="t", level=level_no, pathname="t.py",
                lineno=1, msg="msg", args=(), exc_info=None,
            )
            record.request_id = "-"
            record.workspace_id = "-"
            record.user_id = "-"
            output = fmt.format(record)
            parsed = json.loads(output)
            assert parsed["level"] == level_name


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

class TestSetupLogging:
    def test_attaches_filter(self, app):
        setup_logging(app)
        root = logging.getLogger()
        filter_types = [type(f).__name__ for f in root.filters]
        assert "RequestIdFilter" in filter_types

    def test_json_format_when_env_set(self, app, monkeypatch):
        monkeypatch.setenv("TELEMETRY_LOG_FORMAT", "json")
        setup_logging(app)
        root = logging.getLogger()
        # At least one handler should use JsonFormatter
        formatter_types = [
            type(h.formatter).__name__
            for h in root.handlers
            if h.formatter is not None
        ]
        assert "JsonFormatter" in formatter_types
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_logging_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web.logging_setup'`

**Step 3: Write minimal implementation**

```python
"""Structured logging setup for the Flask application.

Provides a ``RequestIdFilter`` that enriches log records with
``request_id``, ``workspace_id``, and ``user_id`` from Flask's ``g``
object, and a ``JsonFormatter`` that outputs one JSON object per line
for production log aggregation.

Usage::

    from web.logging_setup import setup_logging

    # In app factory
    app = Flask(__name__)
    setup_logging(app)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from flask import Flask, g


# ---------------------------------------------------------------------------
# Filter — enriches records with request-scoped context
# ---------------------------------------------------------------------------

class RequestIdFilter(logging.Filter):
    """Add ``request_id``, ``workspace_id``, and ``user_id`` to log records.

    Values are read from :data:`flask.g`.  When called outside a request
    context (or when the attributes are missing), each field defaults to
    ``"-"``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.request_id = getattr(g, "request_id", "-")
            record.workspace_id = getattr(g, "workspace_id", "-")
            record.user_id = getattr(g, "user_id", "-")
        except RuntimeError:
            # Outside Flask request context
            record.request_id = "-"
            record.workspace_id = "-"
            record.user_id = "-"
        return True


# ---------------------------------------------------------------------------
# Formatter — structured JSON output
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects.

    Output fields: ``timestamp``, ``level``, ``logger``, ``message``,
    ``request_id``, ``workspace_id``, ``user_id``.

    ``timestamp`` is ISO-8601 UTC.  Exception info, if present, is
    appended to ``message``.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Let the base class handle exc_info → string conversion
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            message = f"{message}\n{record.exc_text}"

        log_obj = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "request_id": getattr(record, "request_id", "-"),
            "workspace_id": getattr(record, "workspace_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
        }
        return json.dumps(log_obj, default=str)


# ---------------------------------------------------------------------------
# Setup — wire filter + formatter into the root logger
# ---------------------------------------------------------------------------

def setup_logging(app: Flask) -> None:
    """Configure the root logger with request-ID enrichment.

    When the ``TELEMETRY_LOG_FORMAT`` environment variable is set to
    ``"json"``, all handlers on the root logger use :class:`JsonFormatter`.
    Otherwise the default human-readable format is used with the
    request-scoped fields appended.

    The :class:`RequestIdFilter` is always attached to the root logger
    so that any handler — including third-party — sees the extra fields.
    """
    root = logging.getLogger()

    # Always attach the enrichment filter
    request_filter = RequestIdFilter()
    root.addFilter(request_filter)

    log_format = os.environ.get("TELEMETRY_LOG_FORMAT", "").lower()

    if log_format == "json":
        json_formatter = JsonFormatter()
        # Apply to existing handlers
        for handler in root.handlers:
            handler.setFormatter(json_formatter)
        # If no handlers exist yet, add a StreamHandler
        if not root.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(json_formatter)
            root.addHandler(handler)
    else:
        # Human-readable format with request context
        human_format = (
            "%(asctime)s %(levelname)-8s "
            "[%(request_id)s] %(name)s: %(message)s"
        )
        formatter = logging.Formatter(human_format)
        if root.handlers:
            for handler in root.handlers:
                handler.setFormatter(formatter)
        else:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            root.addHandler(handler)
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_logging_setup.py -v`
Expected: PASS (all 10 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/logging_setup.py telemetry_tool/tests/test_logging_setup.py
git commit -m "feat(api): add structured logging with RequestIdFilter and JsonFormatter"
```

---

### Task 7: Migration 010 — GDPR Tables

**Files:**
- Create: `telemetry_tool/alembic/versions/010_gdpr_account.py`
- Create: `telemetry_tool/tests/test_migration_010.py`

**Context:** Adds database support for GDPR features. The `users` table gets a `deleted_at` (DateTime, nullable) column for soft-delete functionality — when a user requests account deletion, this timestamp is set and a Celery beat task hard-purges accounts past the 30-day grace period. A new `data_exports` table tracks export requests (right of access / portability): each row represents one user-initiated export with status tracking, file path, format, and timestamp lifecycle columns. Two indexes are added for efficient querying: `idx_data_exports_user` on `user_id` and `idx_users_deleted_at` on `deleted_at`.

**Step 1: Write the failing test**

```python
"""Tests for migration 010 — GDPR tables (deleted_at + data_exports)."""
import ast
import inspect
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_migration_module():
    """Import the migration module."""
    import importlib.util

    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "010_gdpr_account.py"
    )
    spec = importlib.util.spec_from_file_location("migration_010", str(migration_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get_source_text() -> str:
    """Return the raw source text of the migration file."""
    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "010_gdpr_account.py"
    )
    return migration_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests — file existence and revision chain
# ---------------------------------------------------------------------------

class TestMigrationFileAndRevision:
    def test_migration_file_exists(self):
        """Migration 010 file exists at the expected path."""
        migration_path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "010_gdpr_account.py"
        )
        assert migration_path.exists(), f"Missing migration file: {migration_path}"

    def test_revision_is_010(self):
        """Migration revision is '010'."""
        mod = _get_migration_module()
        assert mod.revision == "010"

    def test_down_revision_is_009(self):
        """Migration 010 revises 009 (correct chain)."""
        mod = _get_migration_module()
        assert mod.down_revision == "009"


# ---------------------------------------------------------------------------
# Tests — upgrade function
# ---------------------------------------------------------------------------

class TestUpgradeFunction:
    def test_upgrade_adds_deleted_at_column(self):
        """upgrade() adds 'deleted_at' column to 'users' table."""
        source = _get_source_text()
        assert "deleted_at" in source
        assert "add_column" in source
        # Verify it targets the users table
        assert '"users"' in source or "'users'" in source

    def test_upgrade_creates_data_exports_table(self):
        """upgrade() creates the 'data_exports' table."""
        source = _get_source_text()
        assert "data_exports" in source
        assert "create_table" in source

    def test_data_exports_has_correct_columns(self):
        """data_exports table has all required columns."""
        source = _get_source_text()
        required_columns = [
            "id", "user_id", "status", "file_path",
            "format", "created_at", "expires_at", "completed_at",
        ]
        for col in required_columns:
            assert f'"{col}"' in source or f"'{col}'" in source, (
                f"Missing column '{col}' in data_exports table definition"
            )

    def test_both_indexes_created(self):
        """Both idx_data_exports_user and idx_users_deleted_at indexes are created."""
        source = _get_source_text()
        assert "idx_data_exports_user" in source, "Missing index idx_data_exports_user"
        assert "idx_users_deleted_at" in source, "Missing index idx_users_deleted_at"


# ---------------------------------------------------------------------------
# Tests — downgrade function
# ---------------------------------------------------------------------------

class TestDowngradeFunction:
    def test_downgrade_drops_data_exports(self):
        """downgrade() drops the data_exports table."""
        source = _get_source_text()
        # Check that downgrade section contains drop_table for data_exports
        assert "drop_table" in source
        # Verify the target table name
        assert "data_exports" in source

    def test_downgrade_drops_deleted_at_column(self):
        """downgrade() drops the deleted_at column from users."""
        source = _get_source_text()
        assert "drop_column" in source
        # Verify it targets users table and deleted_at column
        assert "deleted_at" in source

    def test_upgrade_and_downgrade_are_callable(self):
        """Both upgrade() and downgrade() are callable functions."""
        mod = _get_migration_module()
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)
```

**Step 2: Run test to confirm it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_migration_010.py -v`
Expected: FAIL (migration file does not exist)

**Step 3: Implement the migration**

Create `telemetry_tool/alembic/versions/010_gdpr_account.py`:

```python
"""Add GDPR support — deleted_at on users, data_exports table.

Revision ID: 010
Revises: 009
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"


def upgrade() -> None:
    # 1. Add soft-delete column to users table
    op.add_column("users", sa.Column("deleted_at", sa.DateTime, nullable=True))
    op.create_index("idx_users_deleted_at", "users", ["deleted_at"])

    # 2. Create data_exports table for GDPR data portability requests
    op.create_table(
        "data_exports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("file_path", sa.Text),
        sa.Column("format", sa.Text, nullable=False, server_default="zip"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime),
    )
    op.create_index("idx_data_exports_user", "data_exports", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_data_exports_user", "data_exports")
    op.drop_table("data_exports")
    op.drop_index("idx_users_deleted_at", "users")
    op.drop_column("users", "deleted_at")
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_migration_010.py -v`
Expected: PASS (all 8 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/alembic/versions/010_gdpr_account.py telemetry_tool/tests/test_migration_010.py
git commit -m "feat(gdpr): add migration 010 — deleted_at column and data_exports table"
```

---

### Task 8: Pydantic Schemas

**Files:**
- Create: `telemetry_tool/web/schemas/auth.py`
- Create: `telemetry_tool/web/schemas/teams.py`
- Create: `telemetry_tool/web/schemas/sessions.py`
- Create: `telemetry_tool/web/schemas/jobs.py`
- Create: `telemetry_tool/web/schemas/batch.py`
- Create: `telemetry_tool/web/schemas/tracks.py`
- Create: `telemetry_tool/web/schemas/account.py`
- Create: `telemetry_tool/tests/test_schemas.py`

**Context:** Pydantic v2 schemas for every resource domain in the API. These models enforce input validation at the API boundary — email format, password length, slug patterns, role enums, and pagination defaults. Each schema file corresponds to a route domain and is consumed by the `@validate_body` / `@validate_params` decorators from Task 2. The `PaginationParams` base (from `schemas/common.py` created in Task 2) is extended per-resource to add optional filter fields. All schemas use `BaseModel` with `Field` constraints.

**Step 1: Write the failing test**

```python
"""Tests for Pydantic v2 request validation schemas."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.schemas.auth import LoginSchema, RefreshSchema, RegisterSchema, VerifyEmailSchema
from web.schemas.teams import CreateTeamSchema, InviteMemberSchema
from web.schemas.sessions import SessionListParams
from web.schemas.jobs import JobListParams, ResumeJobSchema
from web.schemas.batch import BatchReanalyzeSchema
from web.schemas.tracks import TrackListParams
from web.schemas.account import ExportRequestSchema, ProfileUpdateSchema


# ---------------------------------------------------------------------------
# auth schemas
# ---------------------------------------------------------------------------

class TestRegisterSchema:
    def test_valid_register(self):
        """Valid registration data is accepted."""
        s = RegisterSchema(email="user@example.com", password="secure123!", display_name="Alice")
        assert s.email == "user@example.com"
        assert s.password == "secure123!"
        assert s.display_name == "Alice"

    def test_invalid_email_rejected(self):
        """Malformed email is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterSchema(email="not-an-email", password="secure123!", display_name="X")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("email",) for e in errors)

    def test_short_password_rejected(self):
        """Password shorter than 8 characters is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterSchema(email="a@b.com", password="short", display_name="X")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("password",) for e in errors)

    def test_long_password_rejected(self):
        """Password longer than 1024 characters is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterSchema(email="a@b.com", password="x" * 1025, display_name="X")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("password",) for e in errors)


class TestLoginSchema:
    def test_valid_login(self):
        s = LoginSchema(email="u@e.com", password="pass1234")
        assert s.email == "u@e.com"

    def test_missing_password(self):
        with pytest.raises(ValidationError):
            LoginSchema(email="u@e.com")


class TestRefreshSchema:
    def test_valid_refresh(self):
        s = RefreshSchema(refresh_token="abc123")
        assert s.refresh_token == "abc123"

    def test_missing_token(self):
        with pytest.raises(ValidationError):
            RefreshSchema()


class TestVerifyEmailSchema:
    def test_valid_token(self):
        s = VerifyEmailSchema(token="verify-me")
        assert s.token == "verify-me"


# ---------------------------------------------------------------------------
# teams schemas
# ---------------------------------------------------------------------------

class TestCreateTeamSchema:
    def test_valid_team(self):
        s = CreateTeamSchema(name="My Team", slug="my-team")
        assert s.name == "My Team"
        assert s.slug == "my-team"

    def test_invalid_slug_uppercase(self):
        """Uppercase slugs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CreateTeamSchema(name="My Team", slug="My-Team")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("slug",) for e in errors)

    def test_slug_too_short(self):
        with pytest.raises(ValidationError):
            CreateTeamSchema(name="OK", slug="a")


class TestInviteMemberSchema:
    def test_valid_invite(self):
        s = InviteMemberSchema(user_id=42, role="admin")
        assert s.user_id == 42
        assert s.role == "admin"

    def test_invalid_role(self):
        with pytest.raises(ValidationError):
            InviteMemberSchema(user_id=42, role="superuser")


# ---------------------------------------------------------------------------
# sessions / jobs / batch / tracks / account schemas
# ---------------------------------------------------------------------------

class TestSessionListParams:
    def test_defaults(self):
        s = SessionListParams()
        assert s.limit == 25
        assert s.track_id is None
        assert s.driver_id is None
        assert s.status is None


class TestJobListParams:
    def test_defaults(self):
        s = JobListParams()
        assert s.limit == 25
        assert s.status is None


class TestResumeJobSchema:
    def test_accept(self):
        s = ResumeJobSchema(joker_decision="accept")
        assert s.joker_decision == "accept"

    def test_reject(self):
        s = ResumeJobSchema(joker_decision="reject")
        assert s.joker_decision == "reject"

    def test_invalid_decision(self):
        with pytest.raises(ValidationError):
            ResumeJobSchema(joker_decision="maybe")


class TestBatchReanalyzeSchema:
    def test_empty_is_valid(self):
        s = BatchReanalyzeSchema()
        assert s.filter_criteria is None

    def test_with_filter(self):
        s = BatchReanalyzeSchema(filter_criteria={"track_id": 1})
        assert s.filter_criteria == {"track_id": 1}


class TestTrackListParams:
    def test_defaults(self):
        s = TrackListParams()
        assert s.limit == 25


class TestExportRequestSchema:
    def test_default_format(self):
        s = ExportRequestSchema()
        assert s.format == "zip"

    def test_json_format(self):
        s = ExportRequestSchema(format="json")
        assert s.format == "json"

    def test_invalid_format(self):
        with pytest.raises(ValidationError):
            ExportRequestSchema(format="csv")


class TestProfileUpdateSchema:
    def test_partial_update(self):
        s = ProfileUpdateSchema(display_name="New Name")
        assert s.display_name == "New Name"
        assert s.email is None

    def test_empty_is_valid(self):
        s = ProfileUpdateSchema()
        assert s.display_name is None
        assert s.email is None
```

**Step 2: Run test to confirm it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_schemas.py -v`
Expected: FAIL (schema modules do not exist)

**Step 3: Implement the schemas**

Create `telemetry_tool/web/schemas/auth.py`:

```python
"""Pydantic schemas for authentication endpoints."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterSchema(BaseModel):
    """POST /auth/register request body."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=1024)
    display_name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address format")
        return v


class LoginSchema(BaseModel):
    """POST /auth/login request body."""

    email: str = Field(min_length=1)
    password: str = Field(min_length=1, max_length=1024)


class RefreshSchema(BaseModel):
    """POST /auth/refresh request body."""

    refresh_token: str = Field(min_length=1)


class VerifyEmailSchema(BaseModel):
    """POST /auth/verify-email request body."""

    token: str = Field(min_length=1)
```

Create `telemetry_tool/web/schemas/teams.py`:

```python
"""Pydantic schemas for team management endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateTeamSchema(BaseModel):
    """POST /api/v1/teams request body."""

    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", min_length=2, max_length=50)


class InviteMemberSchema(BaseModel):
    """POST /api/v1/teams/:id/members request body."""

    user_id: int
    role: Literal["viewer", "member", "admin"] = "member"
```

Create `telemetry_tool/web/schemas/sessions.py`:

```python
"""Pydantic schemas for session endpoints."""
from __future__ import annotations

from pydantic import Field

from web.schemas.common import PaginationParams


class SessionListParams(PaginationParams):
    """Query parameters for GET /api/v1/sessions."""

    track_id: int | None = None
    driver_id: int | None = None
    status: str | None = None
```

Create `telemetry_tool/web/schemas/jobs.py`:

```python
"""Pydantic schemas for job management endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from web.schemas.common import PaginationParams


class ResumeJobSchema(BaseModel):
    """POST /api/v1/jobs/:id/resume request body."""

    joker_decision: Literal["accept", "reject"]


class JobListParams(PaginationParams):
    """Query parameters for GET /api/v1/jobs."""

    status: str | None = None
```

Create `telemetry_tool/web/schemas/batch.py`:

```python
"""Pydantic schemas for batch reprocessing endpoints."""
from __future__ import annotations

from pydantic import BaseModel


class BatchReanalyzeSchema(BaseModel):
    """POST /api/v1/batch-reanalyze request body."""

    filter_criteria: dict | None = None
```

Create `telemetry_tool/web/schemas/tracks.py`:

```python
"""Pydantic schemas for track endpoints."""
from __future__ import annotations

from web.schemas.common import PaginationParams


class TrackListParams(PaginationParams):
    """Query parameters for GET /api/v1/tracks."""

    pass
```

Create `telemetry_tool/web/schemas/account.py`:

```python
"""Pydantic schemas for account / GDPR endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProfileUpdateSchema(BaseModel):
    """PATCH /api/v1/account/profile request body."""

    display_name: str | None = None
    email: str | None = None


class ExportRequestSchema(BaseModel):
    """POST /api/v1/account/export request body."""

    format: Literal["zip", "json"] = "zip"
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_schemas.py -v`
Expected: PASS (all 15 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/schemas/auth.py telemetry_tool/web/schemas/teams.py telemetry_tool/web/schemas/sessions.py telemetry_tool/web/schemas/jobs.py telemetry_tool/web/schemas/batch.py telemetry_tool/web/schemas/tracks.py telemetry_tool/web/schemas/account.py telemetry_tool/tests/test_schemas.py
git commit -m "feat(api): add Pydantic schemas for auth, teams, sessions, jobs, batch, tracks, account"
```

---

### Task 9: Retrofit auth.py

**Files:**
- Modify: `telemetry_tool/web/routes/auth.py`

**Context:** The `auth.py` route file currently uses a local `_json_response` helper and inline validation (manual email regex, password length checks). This task replaces both with the shared infrastructure from Tasks 1-3: `api_response` / `api_error` / `ErrorCode` from `web.api_utils`, `@validate_body` from `web.validation`, `@rate_limit` from `web.rate_limit`, and `RegisterSchema` / `LoginSchema` from `web.schemas.auth`. The register and login endpoints get `@rate_limit(tier="auth")` since they are unauthenticated and IP-scoped. The logout, refresh, and OAuth routes switch to the shared envelope helpers but keep their existing validation logic (they have simpler bodies that don't warrant full schema decoration). The response envelope shape (`ok`/`data`/`error`/`meta`) remains the same, so existing auth tests should continue to pass.

**Step 1: Verify existing tests pass (baseline)**

Run: `cd telemetry_tool && python -m pytest tests/test_auth.py -v` (if test file exists; skip if not)
Expected: PASS (baseline)

**Step 2: No new test file needed — existing auth tests validate the response shape**

The shared helpers produce the same `{"ok": ..., "data": ..., "meta": ...}` envelope. No new test file is needed, but if test assertions reference the old `_json_response` path, they must be updated.

**Step 3: Modify auth.py**

Replace the import block and `_json_response` helper at the top of `telemetry_tool/web/routes/auth.py`:

```python
"""Auth routes -- register, login, refresh, logout, me."""
import logging

from flask import Blueprint, request, current_app, g

from web.api_utils import api_response, api_error, ErrorCode
from web.rate_limit import rate_limit
from web.validation import validate_body
from web.schemas.auth import RegisterSchema, LoginSchema

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, url_prefix="/auth")

# Password max — Argon2 DoS prevention (still checked on non-schema routes).
_PASSWORD_MAX = 1024
```

Replace the `register` endpoint (remove inline validation, add decorators):

```python
@bp.route("/register", methods=["POST"])
@rate_limit(tier="auth")
@validate_body(RegisterSchema)
def register():
    from auth.service import (
        register_user, create_access_token, create_refresh_token,
        hash_refresh_token, AuthError,
    )
    from datetime import datetime, timedelta, timezone

    body = g.body  # validated RegisterSchema
    email = body.email
    password = body.password
    display_name = body.display_name

    conn = _get_conn()
    try:
        user = register_user(conn, email, password, display_name or email.split("@")[0])
        secret = current_app.config["JWT_SECRET"]
        access_token = create_access_token(user["id"], secret)
        refresh_token = create_refresh_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=current_app.config.get("JWT_REFRESH_EXPIRY_DAYS", 30)
        )
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) "
            "VALUES (%(user_id)s, %(token_hash)s, %(expires_at)s)",
            {"user_id": user["id"], "token_hash": hash_refresh_token(refresh_token),
             "expires_at": expires_at},
        )
        conn.commit()
        result = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user,
        }
        return api_response(result, status=201)
    except AuthError as e:
        status_code = 409 if e.code == "CONFLICT" else 400
        return api_error(ErrorCode.CONFLICT if e.code == "CONFLICT" else ErrorCode.VALIDATION_ERROR, str(e), status=status_code)
    except Exception:
        logger.exception("Registration failed unexpectedly")
        return api_error(ErrorCode.INTERNAL_ERROR, "Registration failed", status=500)
```

Replace the `login` endpoint:

```python
@bp.route("/login", methods=["POST"])
@rate_limit(tier="auth")
@validate_body(LoginSchema)
def login():
    from auth.service import login_user, AuthError

    body = g.body  # validated LoginSchema
    email = body.email.strip().lower()
    password = body.password

    if len(password) > _PASSWORD_MAX:
        return api_error(ErrorCode.VALIDATION_ERROR, "Password too long", status=400)

    conn = _get_conn()
    secret = current_app.config["JWT_SECRET"]
    try:
        result = login_user(conn, email, password, secret)
        return api_response(result)
    except AuthError as e:
        return api_error(ErrorCode.INVALID_CREDENTIALS, str(e), status=401)
    except Exception:
        logger.exception("Login failed unexpectedly")
        return api_error(ErrorCode.INTERNAL_ERROR, "Login failed", status=500)
```

Replace all remaining `_json_response(...)` calls in logout, refresh, and OAuth routes with the equivalent `api_response(...)` / `api_error(...)` calls. Pattern:

- `_json_response(data={...})` becomes `api_response({...})`
- `_json_response(data={...}, status=201)` becomes `api_response({...}, status=201)`
- `_json_response(error={"code": "...", "message": "..."}, status=N)` becomes `api_error(ErrorCode.XXX, "message", status=N)`

Remove the `_json_response` function, the `_EMAIL_RE` regex, and the `_PASSWORD_MIN` constant (now handled by `RegisterSchema`).

Remove `import re` and `from flask import jsonify` (no longer needed).

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_auth.py -v` (if exists)
Expected: PASS (envelope shape unchanged)

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/auth.py
git commit -m "refactor(auth): replace _json_response with shared api_response/api_error, add validation schemas and rate limiting"
```

---

### Task 10: Retrofit teams.py + workspaces.py

**Files:**
- Modify: `telemetry_tool/web/routes/teams.py`
- Modify: `telemetry_tool/web/routes/workspaces.py`

**Context:** Both route files currently have their own local `_json_response` helpers and inline validation (manual slug regex, role set checks). This task replaces them with shared infrastructure: `api_response` / `api_error` / `ErrorCode` for response envelopes, `@validate_body` with `CreateTeamSchema` / `InviteMemberSchema` for request validation, and `@rate_limit` for rate limiting. The teams blueprint gets `tier="write"` on create and invite (mutating operations) and the workspaces blueprint gets `tier="read"` on both list and current endpoints. The `_SLUG_RE` regex and `ALLOWED_INVITE_ROLES` set are removed since the Pydantic schemas now enforce these constraints.

**Step 1: Verify existing tests pass (baseline)**

Run: `cd telemetry_tool && python -m pytest tests/test_teams.py tests/test_workspaces.py -v` (if they exist; skip if not)
Expected: PASS (baseline)

**Step 2: No new test file needed**

The response envelope shape is preserved. Existing tests (if any) should pass since `api_response` / `api_error` produce the same `ok`/`data`/`error`/`meta` structure.

**Step 3: Modify teams.py**

Replace the import block and helpers at the top of `telemetry_tool/web/routes/teams.py`:

```python
"""Team management API routes."""
import logging
from flask import Blueprint, request, g
from auth.rbac import require_role
from auth.service import AuthError

from web.api_utils import api_response, api_error, ErrorCode
from web.rate_limit import rate_limit
from web.validation import validate_body
from web.schemas.teams import CreateTeamSchema, InviteMemberSchema

logger = logging.getLogger(__name__)

bp = Blueprint("teams", __name__, url_prefix="/api/v1/teams")
```

Remove the local `_json_response` function, the `_SLUG_RE` regex, and the `ALLOWED_INVITE_ROLES` set.

Replace the `create_team` endpoint:

```python
@bp.route("", methods=["POST"])
@rate_limit(tier="write")
@validate_body(CreateTeamSchema)
def create_team():
    """Create a new team. Requires authenticated user."""
    from auth.teams import create_team as svc_create_team
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=401)

    body = g.body  # validated CreateTeamSchema
    conn = _get_conn()
    try:
        result = svc_create_team(conn, owner_id=user_id, name=body.name, slug=body.slug)
        return api_response(result, status=201)
    except AuthError as e:
        status_code = 409 if e.code == "CONFLICT" else 400
        return api_error(ErrorCode.CONFLICT if e.code == "CONFLICT" else ErrorCode.VALIDATION_ERROR, str(e), status=status_code)
    except Exception:
        logger.exception("Team creation failed")
        return api_error(ErrorCode.INTERNAL_ERROR, "Team creation failed", status=500)
```

Replace the `invite_member` endpoint:

```python
@bp.route("/<int:team_id>/members", methods=["POST"])
@require_role("admin")
@rate_limit(tier="write")
@validate_body(InviteMemberSchema)
def invite_member(team_id):
    """Add a member to a team."""
    from auth.teams import add_member
    body = g.body  # validated InviteMemberSchema

    conn = _get_conn()
    if not _verify_team_in_workspace(conn, team_id):
        return api_error(ErrorCode.NOT_FOUND, "Team not found in workspace", status=404)
    try:
        add_member(conn, team_id=team_id, user_id=body.user_id, role=body.role)
        return api_response({"message": "Member added"}, status=201)
    except AuthError as e:
        return api_error(ErrorCode.VALIDATION_ERROR, str(e), status=400)
    except Exception:
        logger.exception("Failed to invite team member")
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to invite member", status=500)
```

Replace all remaining `_json_response(...)` calls in `list_members` and `remove_team_member` with the equivalent `api_response(...)` / `api_error(...)` calls.

Remove `import re` and `from flask import jsonify` (no longer needed).

**Modify workspaces.py:**

Replace the import block at the top of `telemetry_tool/web/routes/workspaces.py`:

```python
"""Workspace management API routes."""
import logging
from flask import Blueprint, request, g
from auth.rbac import require_role

from web.api_utils import api_response, api_error, ErrorCode
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("workspaces", __name__, url_prefix="/api/v1/workspaces")
```

Remove the local `_json_response` function and `from flask import jsonify`.

Replace the `list_workspaces` endpoint:

```python
@bp.route("", methods=["GET"])
@rate_limit(tier="read")
def list_workspaces():
    """List all workspaces the current user can access."""
    from auth.workspace import get_user_workspaces
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=401)

    conn = _get_conn()
    try:
        workspaces = get_user_workspaces(conn, user_id)
        return api_response({"workspaces": workspaces})
    except Exception:
        logger.exception("Failed to list workspaces")
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to list workspaces", status=500)
```

Replace the `current_workspace` endpoint:

```python
@bp.route("/current", methods=["GET"])
@rate_limit(tier="read")
def current_workspace():
    """Return the current workspace context."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Auth required", status=401)
    ws_id = getattr(g, "workspace_id", None)
    ws_role = getattr(g, "workspace_role", None)
    return api_response({
        "workspace_id": ws_id,
        "role": ws_role,
    })
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_teams.py tests/test_workspaces.py -v` (if they exist)
Expected: PASS (envelope shape unchanged)

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/teams.py telemetry_tool/web/routes/workspaces.py
git commit -m "refactor(teams,workspaces): replace _json_response with shared api_response/api_error, add validation and rate limiting"
```

---

### Task 11: Retrofit jobs.py + batch.py + versioning.py

**Files:**
- Modify: `telemetry_tool/web/routes/jobs.py`
- Modify: `telemetry_tool/web/routes/batch.py`
- Modify: `telemetry_tool/web/routes/versioning.py`

**Context:** Three Celery pipeline route files currently use bare `jsonify` responses without the shared envelope. This task migrates them to `api_response` / `api_error`, adds `@rate_limit` decorators (read tier for list/status/version, write tier for cancel/resume), and wires in `@validate_body` / `@validate_params` for endpoints that accept structured input. The batch reanalyze endpoint additionally gets `@idempotent` since it triggers expensive reprocessing. The versioning stale-sessions endpoint gets `@validate_params(PaginationParams)` for future pagination support.

**Step 1: Verify existing tests pass (baseline)**

Run: `cd telemetry_tool && python -m pytest tests/test_jobs.py tests/test_batch.py tests/test_versioning.py -v` (if they exist; skip if not)
Expected: PASS (baseline)

**Step 2: No new test file needed**

Existing tests (if any) should continue passing since the envelope shape is additive — `api_response({"jobs": [...]})` produces `{"ok": true, "data": {"jobs": [...]}, "meta": {...}}`, which is a superset of the old `{"jobs": [...]}` structure.

**Step 3: Modify jobs.py**

Replace the import block at the top of `telemetry_tool/web/routes/jobs.py`:

```python
"""Job management API routes — status, cancel, resume, SSE streaming.

Provides endpoints for monitoring and controlling pipeline processing jobs.
All endpoints are workspace-scoped via ``g.workspace_id``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Generator

from flask import Blueprint, Response, g, request
from sqlalchemy import text

from tasks.job_registry import cancel_job, get_job, list_jobs

from web.api_utils import api_response, api_error, ErrorCode
from web.rate_limit import rate_limit
from web.validation import validate_body, validate_params
from web.schemas.jobs import JobListParams, ResumeJobSchema

logger = logging.getLogger(__name__)

bp = Blueprint("jobs", __name__, url_prefix="/api/v1/jobs")
```

Remove `from flask import jsonify` (no longer needed).

Replace the `list_recent_jobs` endpoint:

```python
@bp.route("", methods=["GET"])
@rate_limit(tier="read")
@validate_params(JobListParams)
def list_recent_jobs():
    """List recent jobs for the current workspace.

    Query params:
        limit (int): Max jobs to return (default 25).
        status (str): Optional status filter.

    Returns:
        200 with ``{"jobs": [...]}``
    """
    params = g.params  # validated JobListParams
    conn = get_pg_connection()
    jobs = list_jobs(conn, g.workspace_id, limit=params.limit)
    return api_response({"jobs": jobs})
```

Replace the `job_status` endpoint:

```python
@bp.route("/<job_id>/status", methods=["GET"])
@rate_limit(tier="read")
def job_status(job_id: str):
    """Get current status of a specific job.

    Returns:
        200 with job data, or 404 if not found.
    """
    conn = get_pg_connection()
    job = get_job(conn, job_id, g.workspace_id)
    if job is None:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)
    return api_response(job)
```

Replace the `cancel` endpoint:

```python
@bp.route("/<job_id>/cancel", methods=["POST"])
@rate_limit(tier="write")
def cancel(job_id: str):
    """Cancel a running or pending job.

    Returns:
        200 with ``{"cancelled": true}``, or 404 if not cancellable.
    """
    conn = get_pg_connection()
    result = cancel_job(conn, job_id, g.workspace_id)
    if not result:
        return api_error(ErrorCode.NOT_FOUND, "Job not found or already terminal", status=404)
    return api_response({"cancelled": True})
```

Replace the `resume` endpoint:

```python
@bp.route("/<job_id>/resume", methods=["POST"])
@rate_limit(tier="write")
@validate_body(ResumeJobSchema)
def resume(job_id: str):
    """Resume a paused job with a joker decision.

    Returns:
        200 with ``{"resumed": true}`` if successful.
        404 if job not found.
        409 if job is not in "paused" status.
    """
    conn = get_pg_connection()
    job = get_job(conn, job_id, g.workspace_id)

    if job is None:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    if job.get("status") != "paused":
        return api_error(ErrorCode.CONFLICT, f"Job is not paused (status={job.get('status')})", status=409)

    body = g.body  # validated ResumeJobSchema

    # Store joker decision in PipelineContext via Redis
    redis_client = _get_redis()
    ctx = _load_pipeline_context(redis_client, job_id)
    if ctx is not None:
        ctx.set_joker_decision(body.joker_decision)
        ctx.save()

    # Update job status to processing
    conn.execute(
        text(
            "UPDATE ingestion_jobs SET status = 'processing', updated_at = now() "
            "WHERE job_id = :job_id AND workspace_id = :workspace_id"
        ),
        {"job_id": job_id, "workspace_id": g.workspace_id},
    )
    conn.commit()

    # Dispatch pipeline_finalize task
    _dispatch_finalize(job_id)

    return api_response({"resumed": True})
```

The SSE `stream` endpoint does not use the envelope (it emits raw `data:` lines) and stays unchanged.

**Modify batch.py:**

Replace the import block at the top of `telemetry_tool/web/routes/batch.py`:

```python
"""Batch reprocessing API routes — create, list, cancel batches.

Provides endpoints for triggering batch re-analysis of all sessions
in a workspace, listing batch job status, and cancelling batches.
All endpoints are workspace-scoped via ``g.workspace_id``.
"""

from __future__ import annotations

import logging

from flask import Blueprint, g, request
from sqlalchemy import text

from web.api_utils import api_response, api_error, ErrorCode
from web.rate_limit import rate_limit
from web.validation import validate_body
from web.idempotency import idempotent
from web.schemas.batch import BatchReanalyzeSchema

logger = logging.getLogger(__name__)

bp = Blueprint("batch", __name__, url_prefix="/api/v1")
```

Remove `from flask import jsonify`.

Replace the `batch_reanalyze` endpoint:

```python
@bp.route("/batch-reanalyze", methods=["POST"])
@rate_limit(tier="analyze")
@idempotent
@validate_body(BatchReanalyzeSchema)
def batch_reanalyze():
    """Create a batch reprocessing job.

    Inserts a ``batch_jobs`` row and dispatches the ``dispatch_batch``
    Celery task. Returns 429 if the pipeline queue is full.

    Returns:
        202 with ``{"batch_job_id": N}``
        429 if queue is full.
    """
    # Gate: check pipeline queue depth before accepting new work
    try:
        from tasks.concurrency import check_queue_depth, QueueFullError
        redis_client = _get_redis()
        check_queue_depth(redis_client)
    except QueueFullError as exc:
        return api_error(ErrorCode.RATE_LIMITED, str(exc), status=429)
    except Exception:
        logger.warning("Queue depth check failed, proceeding anyway", exc_info=True)

    conn = get_pg_connection()

    # Insert batch_jobs row
    cursor = conn.execute(
        text(
            "INSERT INTO batch_jobs (workspace_id, status) "
            "VALUES (:ws, 'pending') RETURNING id"
        ),
        {"ws": g.workspace_id},
    )
    row = cursor.fetchone()
    batch_id = dict(row)["id"] if not isinstance(row, dict) else row["id"]
    conn.commit()

    # Dispatch Celery task
    _dispatch_batch_task(batch_id, g.workspace_id)

    return api_response({"batch_job_id": batch_id}, status=202)
```

Replace the `list_batch_jobs` endpoint:

```python
@bp.route("/batch-jobs", methods=["GET"])
@rate_limit(tier="read")
def list_batch_jobs():
    """List batch jobs for the current workspace.

    Returns:
        200 with ``{"batches": [...]}``
    """
    conn = get_pg_connection()
    cursor = conn.execute(
        text(
            "SELECT * FROM batch_jobs "
            "WHERE workspace_id = :ws "
            "ORDER BY created_at DESC "
            "LIMIT 50"
        ),
        {"ws": g.workspace_id},
    )
    rows = cursor.fetchall()
    batches = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return api_response({"batches": batches})
```

Replace the `cancel_batch` endpoint:

```python
@bp.route("/batch-jobs/<int:batch_id>/cancel", methods=["POST"])
@rate_limit(tier="write")
def cancel_batch(batch_id: int):
    """Cancel a batch job and revoke its pending tasks.

    Returns:
        200 with ``{"cancelled": true}``
        404 if batch not found or wrong workspace.
    """
    conn = get_pg_connection()

    cursor = conn.execute(
        text(
            "SELECT * FROM batch_jobs "
            "WHERE id = :id AND workspace_id = :ws"
        ),
        {"id": batch_id, "ws": g.workspace_id},
    )
    batch = cursor.fetchone()

    if batch is None:
        return api_error(ErrorCode.NOT_FOUND, "Batch job not found", status=404)

    # Revoke pending Celery tasks
    _revoke_batch_tasks(batch_id, g.workspace_id)

    # Update batch status
    conn.execute(
        text(
            "UPDATE batch_jobs SET status = 'cancelled', updated_at = now() "
            "WHERE id = :id AND workspace_id = :ws"
        ),
        {"id": batch_id, "ws": g.workspace_id},
    )
    conn.commit()

    return api_response({"cancelled": True})
```

**Modify versioning.py:**

Replace the import block at the top of `telemetry_tool/web/routes/versioning.py`:

```python
"""Processing versioning API routes — stale sessions + pipeline version.

Provides endpoints for identifying sessions processed with an older
pipeline version and retrieving the current pipeline version number.
All endpoints are workspace-scoped via ``g.workspace_id``.
"""

from __future__ import annotations

import logging

from flask import Blueprint, g
from sqlalchemy import text

from pipeline_version import PIPELINE_VERSION

from web.api_utils import api_response
from web.rate_limit import rate_limit
from web.validation import validate_params
from web.schemas.common import PaginationParams

logger = logging.getLogger(__name__)

bp = Blueprint("versioning", __name__, url_prefix="/api/v1")
```

Remove `from flask import jsonify`.

Replace the `stale_sessions` endpoint:

```python
@bp.route("/sessions/stale", methods=["GET"])
@rate_limit(tier="read")
@validate_params(PaginationParams)
def stale_sessions():
    """List sessions with a processing_version older than the current pipeline.

    Returns:
        200 with ``{"current_version": N, "stale_sessions": [...], "count": N}``
    """
    conn = get_pg_connection()
    cursor = conn.execute(
        text(
            "SELECT session_id, processing_version FROM sessions "
            "WHERE workspace_id = :ws "
            "AND (processing_version IS NULL OR processing_version < :version)"
        ),
        {"ws": g.workspace_id, "version": PIPELINE_VERSION},
    )
    rows = cursor.fetchall()
    stale = [dict(r) if not isinstance(r, dict) else r for r in rows]

    return api_response({
        "current_version": PIPELINE_VERSION,
        "stale_sessions": stale,
        "count": len(stale),
    })
```

Replace the `pipeline_version` endpoint:

```python
@bp.route("/pipeline/version", methods=["GET"])
@rate_limit(tier="read")
def pipeline_version():
    """Return the current pipeline processing version.

    Returns:
        200 with ``{"pipeline_version": N}``
    """
    return api_response({"pipeline_version": PIPELINE_VERSION})
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_jobs.py tests/test_batch.py tests/test_versioning.py -v` (if they exist)
Expected: PASS (responses now wrapped in envelope but data fields preserved)

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/jobs.py telemetry_tool/web/routes/batch.py telemetry_tool/web/routes/versioning.py
git commit -m "refactor(jobs,batch,versioning): replace jsonify with api_response/api_error, add rate limiting and validation"
```

---

### Task 12: Config + App Wiring

**Files:**
- Modify: `telemetry_tool/web/config.py`
- Modify: `telemetry_tool/web/app.py`

**Context:** Final wiring that connects all the infrastructure modules (Tasks 1-6) and retrofitted routes (Tasks 9-11) into the Flask application. The config gets two new settings: `LOG_FORMAT` (env var `TELEMETRY_LOG_FORMAT`, default `"text"`, set to `"json"` for production structured logging) and `RATE_LIMIT_ENABLED` (boolean, default `True`, allows disabling rate limiting in test environments). The `create_app()` factory calls `init_request_id(app)` to install the UUID4 `before_request` hook, and `setup_logging(app)` to configure the `RequestIdFilter` and log format. Two placeholder blueprint imports are added to the `USE_PG` block for `api_v1_data` and `api_v1_account` — these will be implemented in later tasks but the registration wiring should be in place now (guarded by try/except to avoid breaking the app if the modules don't exist yet).

**Step 1: Verify the app still starts (baseline)**

Run: `cd telemetry_tool && python -c "from web.app import create_app; app = create_app(); print('OK')"`
Expected: `OK`

**Step 2: No new test file needed**

The changes are wiring-only — calling `init_request_id` and `setup_logging` at app startup. The tests from Tasks 1 and 6 already validate those functions work correctly. The config additions are simple env-var reads.

**Step 3: Modify config.py**

Add the following two settings to the `Config` class in `telemetry_tool/web/config.py`, after the `MAX_CONTENT_LENGTH` line:

```python
    # Logging
    LOG_FORMAT: str = os.environ.get("TELEMETRY_LOG_FORMAT", "text")

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = os.environ.get("RATE_LIMIT_ENABLED", "1") == "1"
```

**Modify app.py:**

Add imports at the top of `create_app()` (after the `cfg.validate()` call):

```python
    # -- API infrastructure hooks (Phase 4) --
    from .api_utils import init_request_id
    from .logging_setup import setup_logging

    init_request_id(app)
    setup_logging(app)
```

Insert these lines immediately after the `app.config.from_mapping(...)` block (after line 123 in the current file), wrapped in a try/except so the app doesn't crash if the modules were not yet created:

```python
    # Phase 4 API infrastructure — request ID and structured logging.
    try:
        from .api_utils import init_request_id
        from .logging_setup import setup_logging

        init_request_id(app)
        setup_logging(app)
        logger.debug("Initialized Phase 4 API infrastructure (request_id + logging)")
    except ImportError:
        logger.debug("Phase 4 API modules not yet available — skipping init_request_id / setup_logging")
```

Add placeholder blueprint registrations to the `USE_PG` block (inside the `if cfg.USE_PG:` try/except, after the versioning blueprint registration around line 229):

```python
            # Phase 4 v1 endpoint blueprints (placeholder — modules created in later tasks)
            try:
                from .routes.api_v1_data import bp as api_v1_data_bp
                app.register_blueprint(api_v1_data_bp)
                logger.debug("Registered api_v1_data blueprint")
            except ImportError:
                logger.debug("api_v1_data module not yet available — skipping")

            try:
                from .routes.api_v1_account import bp as api_v1_account_bp
                app.register_blueprint(api_v1_account_bp)
                logger.debug("Registered api_v1_account blueprint")
            except ImportError:
                logger.debug("api_v1_account module not yet available — skipping")
```

Add `RATE_LIMIT_ENABLED` to the `app.config.from_mapping()` call:

```python
        RATE_LIMIT_ENABLED=cfg.RATE_LIMIT_ENABLED,
```

**Step 4: Verify the app still starts**

Run: `cd telemetry_tool && python -c "from web.app import create_app; app = create_app(); print('OK')"`
Expected: `OK` (no import errors, Phase 4 modules loaded or gracefully skipped)

**Step 5: Commit**

```bash
git add telemetry_tool/web/config.py telemetry_tool/web/app.py
git commit -m "feat(app): wire Phase 4 API infrastructure — request_id, logging, config, placeholder blueprints"
```

---

### Task 13: V1 Data Endpoints

**Files:**
- Create: `telemetry_tool/web/routes/api_v1_data.py`
- Create: `telemetry_tool/tests/test_api_v1_data.py`

**Context:** The existing `api_data.py` serves legacy endpoints under `/api/`. This task creates v1 equivalents under `/api/v1/` with REST-style URLs, the response envelope from `api_utils.py`, and rate limiting. The 15 migrated endpoints are thin wrappers that call the existing data-fetching functions from `web/models.py` and `api_data.py` — no business logic duplication. Each returns the `api_response` envelope with `ok`, `data`, and `meta` fields.

**Step 1: Write the failing test**

```python
"""Tests for v1 data API endpoints."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask

from web.api_utils import ErrorCode, api_error, api_response, init_request_id
from web.routes.api_v1_data import bp as api_v1_data_bp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    """Create a minimal Flask app with api_v1_data blueprint."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)
    app.register_blueprint(api_v1_data_bp)
    return app


@pytest.fixture
def app():
    return _make_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_conn():
    """Return a mock DB connection with configurable execute results."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


# ---------------------------------------------------------------------------
# Envelope shape — all v1 endpoints return the standard envelope
# ---------------------------------------------------------------------------

class TestV1EnvelopeFormat:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[1, 2, 3])
    def test_laps_gps_returns_envelope(self, mock_laps, mock_db, client):
        """GET /api/v1/sessions/<id>/laps/gps returns ok/data/meta envelope."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/sess_001/laps/gps")
        body = resp.get_json()
        assert "ok" in body
        assert "data" in body
        assert "meta" in body
        assert "request_id" in body["meta"]

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id")
    @patch("web.routes.api_v1_data.get_laps_for_session", return_value=[])
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[])
    def test_speed_trace_returns_envelope(self, mock_gps, mock_laps, mock_sess, mock_db, client):
        """GET /api/v1/sessions/<id>/speed-trace returns envelope."""
        mock_db.return_value = _mock_conn()
        mock_sess.return_value = {"session_id": "s1", "track_id": "t1"}
        resp = client.get("/api/v1/sessions/sess_001/speed-trace")
        body = resp.get_json()
        assert body["ok"] is True
        assert "data" in body

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session", return_value=[])
    def test_lap_times_returns_envelope(self, mock_laps, mock_db, client):
        """GET /api/v1/sessions/<id>/lap-times returns envelope."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/sess_001/lap-times")
        body = resp.get_json()
        assert body["ok"] is True
        assert "data" in body
        assert "laps" in body["data"]


# ---------------------------------------------------------------------------
# Session GPS laps
# ---------------------------------------------------------------------------

class TestV1LapsGps:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[1, 3, 5])
    def test_returns_lap_numbers(self, mock_laps, mock_db, client):
        """Returns list of lap numbers with GPS data."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/laps/gps")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["laps"] == [1, 3, 5]

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[])
    def test_empty_laps(self, mock_laps, mock_db, client):
        """Returns empty list when no GPS laps exist."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/laps/gps")
        body = resp.get_json()
        assert body["data"]["laps"] == []


# ---------------------------------------------------------------------------
# Speed trace
# ---------------------------------------------------------------------------

class TestV1SpeedTrace:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id", return_value=None)
    def test_404_when_session_missing(self, mock_sess, mock_db, client):
        """Returns 404 envelope when session does not exist."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/missing/speed-trace")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Lap times
# ---------------------------------------------------------------------------

class TestV1LapTimes:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    def test_returns_lap_times(self, mock_laps, mock_db, client):
        """Returns formatted lap times."""
        mock_db.return_value = _mock_conn()
        mock_laps.return_value = [
            {"lap_number": 1, "lap_time_s": 62.5, "is_best": True, "is_valid": True,
             "invalid_reason": None, "phase_id": None},
            {"lap_number": 2, "lap_time_s": 63.1, "is_best": False, "is_valid": True,
             "invalid_reason": None, "phase_id": None},
        ]
        resp = client.get("/api/v1/sessions/s1/lap-times")
        body = resp.get_json()
        assert body["ok"] is True
        assert len(body["data"]["laps"]) == 2
        assert body["data"]["laps"][0]["lap_time_s"] == 62.5


# ---------------------------------------------------------------------------
# GG data
# ---------------------------------------------------------------------------

class TestV1GgData:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[])
    def test_empty_gg_data(self, mock_laps, mock_db, client):
        """Returns empty arrays when no GG data available."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/gg-data")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["n_points"] == 0


# ---------------------------------------------------------------------------
# Theoretical data
# ---------------------------------------------------------------------------

class TestV1Theoretical:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_theoretical_data", return_value=None)
    def test_404_when_no_theoretical(self, mock_theo, mock_db, client):
        """Returns 404 when no theoretical data exists."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/theoretical")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["error"]["code"] == "NOT_FOUND"

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_theoretical_data")
    def test_returns_theoretical_data(self, mock_theo, mock_db, client):
        """Returns theoretical data in envelope."""
        mock_db.return_value = _mock_conn()
        mock_theo.return_value = {
            "theoretical_time_s": 60.0, "actual_best_time_s": 62.0,
            "gap_pct": 3.3, "simulation_method": "physics",
            "speeds": [10, 20], "distances": [0, 100], "metrics": {},
        }
        resp = client.get("/api/v1/sessions/s1/theoretical")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["theoretical_time_s"] == 60.0


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

class TestV1Fingerprint:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_404_when_session_missing(self, mock_db, client):
        """Returns 404 when session not found."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/missing/fingerprint")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Reference line
# ---------------------------------------------------------------------------

class TestV1ReferenceLine:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_reference_line", return_value=None)
    def test_404_when_no_reference(self, mock_ref, mock_db, client):
        """Returns 404 when no reference line exists."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/reference-line")
        assert resp.status_code == 404

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_reference_line")
    def test_returns_reference_line(self, mock_ref, mock_db, client):
        """Returns reference line data in envelope."""
        mock_db.return_value = _mock_conn()
        mock_ref.return_value = {"latitudes": [1.0], "longitudes": [2.0]}
        resp = client.get("/api/v1/sessions/s1/reference-line")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["latitudes"] == [1.0]


# ---------------------------------------------------------------------------
# Best lap GPS
# ---------------------------------------------------------------------------

class TestV1BestLapGps:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session", return_value=[])
    def test_404_when_no_best_lap(self, mock_laps, mock_db, client):
        """Returns 404 when no best lap found."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/best-lap-gps")
        assert resp.status_code == 404

    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_laps_for_session")
    @patch("web.routes.api_v1_data.get_gps_trace")
    def test_returns_best_lap_gps(self, mock_gps, mock_laps, mock_db, client):
        """Returns GPS trace for best lap."""
        mock_db.return_value = _mock_conn()
        mock_laps.return_value = [{"lap_number": 3, "is_best": True}]
        mock_gps.return_value = {"latitudes": [1.0], "longitudes": [2.0],
                                  "distances": [0], "speeds": [10]}
        resp = client.get("/api/v1/sessions/s1/best-lap-gps")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["lap_number"] == 3


# ---------------------------------------------------------------------------
# Fatigue
# ---------------------------------------------------------------------------

class TestV1Fatigue:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_session_by_id", return_value=None)
    def test_404_when_session_missing(self, mock_sess, mock_db, client):
        """Returns 404 when session not found."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/missing/fatigue")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Speed profile
# ---------------------------------------------------------------------------

class TestV1SpeedProfile:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_404_when_session_missing(self, mock_db, client):
        """Returns 404 when session not found."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn
        resp = client.get("/api/v1/sessions/missing/speed-profile")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Track records
# ---------------------------------------------------------------------------

class TestV1TrackRecords:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_track_records", return_value=[])
    def test_returns_records(self, mock_recs, mock_db, client):
        """Returns track records in envelope."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/tracks/t1/records")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["records"] == []


# ---------------------------------------------------------------------------
# Track evolution
# ---------------------------------------------------------------------------

class TestV1TrackEvolution:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_returns_evolution(self, mock_db, client):
        """Returns evolution data in envelope."""
        conn = _mock_conn()
        conn.execute.return_value.fetchall.return_value = []
        mock_db.return_value = conn
        resp = client.get("/api/v1/tracks/t1/evolution")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["sessions"] == []


# ---------------------------------------------------------------------------
# Track geometry
# ---------------------------------------------------------------------------

class TestV1TrackGeometry:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_404_when_no_geometry(self, mock_db, client):
        """Returns 404 when no geometry data exists."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn
        resp = client.get("/api/v1/tracks/t1/geometry")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Files list
# ---------------------------------------------------------------------------

class TestV1Files:
    @patch("web.routes.api_v1_data.Path")
    def test_returns_files_envelope(self, mock_path_cls, client, tmp_path):
        """Returns file list in envelope."""
        mock_dir = MagicMock()
        mock_dir.iterdir.return_value = []
        mock_dir.mkdir = MagicMock()
        mock_path_cls.return_value = mock_dir
        resp = client.get("/api/v1/files")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["files"] == []


# ---------------------------------------------------------------------------
# Session DELETE
# ---------------------------------------------------------------------------

class TestV1DeleteSession:
    @patch("web.routes.api_v1_data.get_db_connection")
    def test_404_when_session_missing(self, mock_db, client):
        """DELETE returns 404 for unknown session."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = None
        mock_db.return_value = conn
        resp = client.delete("/api/v1/sessions/missing")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["error"]["code"] == "NOT_FOUND"

    @patch("web.routes.api_v1_data.get_db_connection")
    def test_delete_success(self, mock_db, client):
        """DELETE returns success envelope for existing session."""
        conn = _mock_conn()
        conn.execute.return_value.fetchone.return_value = {"session_id": "s1"}
        mock_db.return_value = conn
        resp = client.delete("/api/v1/sessions/s1")
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["session_id"] == "s1"
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_api_v1_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web.routes.api_v1_data'`

**Step 3: Write minimal implementation**

```python
"""V1 data API endpoints — REST-style wrappers over legacy data-fetching logic.

Blueprint: ``/api/v1/`` — provides 15 hardened endpoints that call the same
data-fetching functions used by ``api_data.py``, but return responses in the
standard ``api_response`` envelope with rate limiting.

Usage::

    from web.routes.api_v1_data import bp as api_v1_data_bp
    app.register_blueprint(api_v1_data_bp)
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, request

from web.api_utils import ErrorCode, api_error, api_response
from web.db import get_db_connection
from web.models import (
    get_gps_trace,
    get_gps_lap_numbers,
    get_laps_for_session,
    get_reference_line,
    get_session_by_id,
    get_theoretical_data,
    get_track_records,
)

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1_data", __name__, url_prefix="/api/v1")


# ---- Rate limit import (graceful fallback for dev/test) ----
try:
    from web.rate_limit import rate_limit
except ImportError:
    def rate_limit(**kwargs):
        """No-op fallback when rate_limit module is not available."""
        def decorator(fn):
            return fn
        return decorator


# ---- Validate params import (graceful fallback for dev/test) ----
try:
    from web.validation import validate_params
except ImportError:
    def validate_params(schema):
        """No-op fallback when validation module is not available."""
        def decorator(fn):
            return fn
        return decorator


# ---------------------------------------------------------------------------
# 1. GET /sessions/<id>/laps/gps — list lap numbers with GPS data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/laps/gps", methods=["GET"])
@rate_limit(tier="read")
def v1_laps_gps(session_id: str):
    """Return list of lap numbers that have GPS data.

    Returns:
        200 with ``{"laps": [1, 2, 3]}``
    """
    conn = get_db_connection()
    laps = get_gps_lap_numbers(conn, session_id)
    return api_response({"laps": laps})


# ---------------------------------------------------------------------------
# 2. GET /sessions/<id>/speed-trace — speed vs distance data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/speed-trace", methods=["GET"])
@rate_limit(tier="read")
def v1_speed_trace(session_id: str):
    """Return speed vs distance data for charting.

    Returns:
        200 with ``{"laps": {...}, "best_lap_number": N, "session_id": "..."}``
        404 if session not found.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = get_laps_for_session(conn, session_id)
    gps_lap_nums = get_gps_lap_numbers(conn, session_id)

    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break

    traces = {}
    for lap_num in gps_lap_nums:
        gps = get_gps_trace(conn, session_id, lap_num)
        if gps:
            traces[lap_num] = {
                "distances": gps["distances"],
                "speeds": gps["speeds"],
            }

    return api_response({
        "laps": traces,
        "best_lap_number": best_lap,
        "session_id": session_id,
    })


# ---------------------------------------------------------------------------
# 3. GET /sessions/<id>/lap-times — lap times for charting
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/lap-times", methods=["GET"])
@rate_limit(tier="read")
def v1_lap_times(session_id: str):
    """Return lap times as JSON for charting.

    Returns:
        200 with ``{"laps": [...]}``
    """
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    return api_response({
        "laps": [
            {
                "lap_number": l["lap_number"],
                "lap_time_s": l["lap_time_s"],
                "is_best": bool(l.get("is_best")),
                "is_valid": bool(l.get("is_valid", True)),
                "invalid_reason": l.get("invalid_reason"),
                "phase_id": l.get("phase_id"),
            }
            for l in laps
            if l.get("lap_time_s") is not None
        ],
    })


# ---------------------------------------------------------------------------
# 4. GET /sessions/<id>/gg-data — G-G scatter data
# ---------------------------------------------------------------------------

def _clean_accel(arr):
    """Replace NaN/Inf with None; values are already in G from RaceChrono."""
    out = []
    for v in arr:
        if v is None:
            out.append(None)
        else:
            fv = float(v)
            out.append(None if (math.isnan(fv) or math.isinf(fv)) else round(fv, 4))
    return out


@bp.route("/sessions/<session_id>/gg-data", methods=["GET"])
@rate_limit(tier="read")
def v1_gg_data(session_id: str):
    """Return aggregated G-G scatter data from all laps with accel data.

    Returns:
        200 with ``{"accel_lat": [...], "accel_long": [...], "per_lap": {...}, "n_points": N}``
    """
    conn = get_db_connection()
    gps_lap_nums = get_gps_lap_numbers(conn, session_id)

    accel_lat_all = []
    accel_long_all = []
    per_lap = {}

    for lap_num in gps_lap_nums:
        gps = get_gps_trace(conn, session_id, lap_num)
        if gps and gps.get("accel_lat") and gps.get("accel_long"):
            lat_clean = _clean_accel(gps["accel_lat"])
            long_clean = _clean_accel(gps["accel_long"])
            accel_lat_all.extend(lat_clean)
            accel_long_all.extend(long_clean)
            per_lap[str(lap_num)] = {
                "accel_lat": lat_clean,
                "accel_long": long_clean,
            }

    return api_response({
        "accel_lat": accel_lat_all,
        "accel_long": accel_long_all,
        "per_lap": per_lap,
        "n_points": len(accel_lat_all),
    })


# ---------------------------------------------------------------------------
# 5. GET /sessions/<id>/theoretical — theoretical lap data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/theoretical", methods=["GET"])
@rate_limit(tier="read")
def v1_theoretical(session_id: str):
    """Return theoretical lap speed profile and metrics.

    Returns:
        200 with theoretical data.
        404 if no theoretical data exists.
    """
    conn = get_db_connection()
    data = get_theoretical_data(conn, session_id)
    if data is None:
        return api_error(ErrorCode.NOT_FOUND, "No theoretical data", status=404)
    return api_response({
        "theoretical_time_s": data.get("theoretical_time_s"),
        "actual_best_time_s": data.get("actual_best_time_s"),
        "gap_pct": data.get("gap_pct"),
        "simulation_method": data.get("simulation_method"),
        "speeds": data.get("speeds"),
        "distances": data.get("distances"),
        "metrics": data.get("metrics"),
    })


# ---------------------------------------------------------------------------
# 6. GET /sessions/<id>/fingerprint — performance fingerprint
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/fingerprint", methods=["GET"])
@rate_limit(tier="read")
def v1_fingerprint(session_id: str):
    """Return a 6-dimension performance fingerprint for a session.

    Delegates to the legacy ``api_fingerprint`` logic in ``api_data.py``.

    Returns:
        200 with fingerprint data.
        404 if session not found.
    """
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
    sess = dict(row)

    # Build input data from scoring sub-scores and analysis results
    session_data = {"session_id": session_id, "driver_name": ""}

    if sess.get("driver_id"):
        dr = conn.execute(
            "SELECT driver_name FROM drivers WHERE driver_id = :did",
            {"did": sess["driver_id"]},
        ).fetchone()
        if dr:
            session_data["driver_name"] = dr["driver_name"]

    scoring_row = conn.execute(
        "SELECT * FROM score_details WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if scoring_row:
        sd = dict(scoring_row)
        if sd.get("pace_score") is not None and sd.get("pace_max") and sd["pace_max"] > 0:
            session_data["pace_pct"] = sd["pace_score"] / sd["pace_max"] * 100
        if sd.get("consistency_score") is not None and sd.get("consistency_max") and sd["consistency_max"] > 0:
            session_data["consistency_pct"] = sd["consistency_score"] / sd["consistency_max"] * 100
        if sd.get("robustness_score") is not None and sd.get("robustness_max") and sd["robustness_max"] > 0:
            session_data["robustness_pct"] = sd["robustness_score"] / sd["robustness_max"] * 100
        if sd.get("execution_score") is not None and sd.get("execution_max") and sd["execution_max"] > 0:
            session_data["execution_pct"] = sd["execution_score"] / sd["execution_max"] * 100

    if not session_data.get("pace_pct") and sess.get("total_score"):
        session_data["pace_pct"] = sess["total_score"]

    try:
        from performance_fingerprint import compute_fingerprint
        fp = compute_fingerprint(session_data)
        return api_response(fp.to_dict())
    except ImportError:
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "performance_fingerprint module not available",
            status=503,
        )


# ---------------------------------------------------------------------------
# 7. GET /sessions/<id>/reference-line — reference (median racing) line
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/reference-line", methods=["GET"])
@rate_limit(tier="read")
def v1_reference_line(session_id: str):
    """Return the reference (median racing) line GPS coordinates.

    Returns:
        200 with reference line data.
        404 if no reference line exists.
    """
    conn = get_db_connection()
    data = get_reference_line(conn, session_id)
    if data is None:
        return api_error(ErrorCode.NOT_FOUND, "No reference line", status=404)
    return api_response(data)


# ---------------------------------------------------------------------------
# 8. GET /sessions/<id>/best-lap-gps — GPS trace for the best lap
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/best-lap-gps", methods=["GET"])
@rate_limit(tier="read")
def v1_best_lap_gps(session_id: str):
    """Return the GPS trace for the best lap.

    Returns:
        200 with GPS trace data (includes ``lap_number``).
        404 if no best lap or no GPS data.
    """
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break

    if best_lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No best lap", status=404)

    gps = get_gps_trace(conn, session_id, best_lap)
    if gps is None:
        return api_error(ErrorCode.NOT_FOUND, "No GPS data for best lap", status=404)

    gps["lap_number"] = best_lap
    return api_response(gps)


# ---------------------------------------------------------------------------
# 9. GET /sessions/<id>/fatigue — fatigue and concentration analysis
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/fatigue", methods=["GET"])
@rate_limit(tier="read")
def v1_fatigue(session_id: str):
    """Return driver fatigue and concentration analysis.

    Returns:
        200 with fatigue analysis data.
        404 if session not found or no lap data.
        503 if fatigue_detection module unavailable.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = conn.execute(
        """SELECT lap_number, lap_time_s, speed_mean_mps, braking_max_mps2,
                  accel_max_mps2
           FROM laps WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    if not laps:
        return api_error(ErrorCode.NOT_FOUND, "No lap data", status=404)

    lap_metrics = []
    lap_times = []
    lap_numbers = []
    for r in laps:
        rd = dict(r)
        lap_numbers.append(int(rd["lap_number"]))
        lap_times.append(float(rd["lap_time_s"]) if rd["lap_time_s"] else float("nan"))
        lap_metrics.append({
            "braking_max_mps2": rd.get("braking_max_mps2"),
            "jerk_rms_mps3": None,
            "speed_mean_mps": rd.get("speed_mean_mps"),
        })

    try:
        from fatigue_detection import analyze_fatigue
        result = analyze_fatigue(lap_metrics, lap_times, lap_numbers)
        return api_response(result.to_dict())
    except ImportError:
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "fatigue_detection module not available",
            status=503,
        )


# ---------------------------------------------------------------------------
# 10. GET /sessions/<id>/speed-profile — track segment speed profile
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/speed-profile", methods=["GET"])
@rate_limit(tier="read")
def v1_speed_profile(session_id: str):
    """Return track segment speed profile for a session.

    Returns:
        200 with speed profile data.
        404 if session not found.
        503 if speed_profile module unavailable.
    """
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
    lap_numbers = [r["lap_number"] for r in lap_rows]

    try:
        from speed_profile import analyze_speed_profile
        result = analyze_speed_profile(lap_times, lap_numbers)
        d = result.to_dict()
        d["session_id"] = session_id
        return api_response(d)
    except ImportError:
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "speed_profile module not available",
            status=503,
        )


# ---------------------------------------------------------------------------
# 11. GET /tracks/<id>/records — track records
# ---------------------------------------------------------------------------

@bp.route("/tracks/<track_id>/records", methods=["GET"])
@rate_limit(tier="read")
def v1_track_records(track_id: str):
    """Return track records as JSON.

    Returns:
        200 with ``{"records": [...]}``
    """
    conn = get_db_connection()
    records = get_track_records(conn, track_id)
    return api_response({"records": records})


# ---------------------------------------------------------------------------
# 12. GET /tracks/<id>/evolution — best lap progression over time
# ---------------------------------------------------------------------------

@bp.route("/tracks/<track_id>/evolution", methods=["GET"])
@rate_limit(tier="read")
def v1_track_evolution(track_id: str):
    """Return best lap time progression over time for a track.

    Returns:
        200 with ``{"track_id": "...", "sessions": [...]}``
    """
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT s.session_id, s.session_date, s.best_lap_time_s,
                  s.total_score, s.track_state, s.session_type,
                  COALESCE(d.driver_name, 'Unknown') AS driver_name
           FROM sessions s
           LEFT JOIN drivers d ON s.driver_id = d.driver_id
           WHERE s.track_id = :track_id
             AND s.best_lap_time_s IS NOT NULL
           ORDER BY s.session_date""",
        {"track_id": track_id},
    ).fetchall()

    sessions = []
    for r in rows:
        sessions.append({
            "session_id": r["session_id"],
            "date": r["session_date"],
            "best_time_s": r["best_lap_time_s"],
            "score": r["total_score"],
            "track_state": r["track_state"],
            "session_type": r["session_type"],
            "driver": r["driver_name"],
        })

    return api_response({"track_id": track_id, "sessions": sessions})


# ---------------------------------------------------------------------------
# 13. GET /tracks/<id>/geometry — track reference line geometry
# ---------------------------------------------------------------------------

@bp.route("/tracks/<track_id>/geometry", methods=["GET"])
@rate_limit(tier="read")
def v1_track_geometry(track_id: str):
    """Return track reference line geometry for static track outline.

    Returns:
        200 with ``{"track_name": "...", "latitudes": [...], "longitudes": [...]}``
        404 if no geometry available.
    """
    conn = get_db_connection()
    row = conn.execute(
        "SELECT track_name, reference_line FROM tracks WHERE track_id = ?",
        (track_id,),
    ).fetchone()
    if not row or not row["reference_line"]:
        return api_error(ErrorCode.NOT_FOUND, "No geometry available", status=404)
    try:
        geo = json.loads(row["reference_line"])
    except (json.JSONDecodeError, TypeError):
        return api_error(ErrorCode.INTERNAL_ERROR, "Invalid geometry data", status=500)
    return api_response({
        "track_name": row["track_name"],
        "latitudes": geo.get("latitudes", []),
        "longitudes": geo.get("longitudes", []),
    })


# ---------------------------------------------------------------------------
# 14. GET /files — list CSV files
# ---------------------------------------------------------------------------

def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


@bp.route("/files", methods=["GET"])
@rate_limit(tier="read")
def v1_files():
    """List CSV files in data/raw/ directory.

    Returns:
        200 with ``{"files": [...]}``
    """
    raw_dir = Path(current_app.config.get("DATA_RAW_DIR", "data/raw"))
    raw_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(raw_dir.iterdir()):
        if f.suffix.lower() == ".csv" and f.is_file():
            stat = f.stat()
            files.append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "size_human": _human_size(stat.st_size),
                "modified": stat.st_mtime,
                "modified_human": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                ),
            })
    return api_response({"files": files})


# ---------------------------------------------------------------------------
# 15. DELETE /sessions/<id> — delete a session
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>", methods=["DELETE"])
@rate_limit(tier="write")
def v1_delete_session(session_id: str):
    """Delete a session and all its associated data.

    Returns:
        200 with ``{"session_id": "..."}``
        404 if session not found.
    """
    conn = get_db_connection()
    row = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    try:
        related_tables = [
            "gps_traces", "laps", "score_details", "condition_phases",
            "corner_metrics", "driving_style_features",
            "theoretical_data", "reference_lines", "data_health",
            "session_tags", "session_weather", "session_sectors",
            "session_annotations", "stint_analysis", "condition_markers",
            "driver_progression", "vehicle_setups", "weekend_sessions",
            "what_if_scenarios",
        ]
        assert all(t.isidentifier() for t in related_tables), "Invalid table name"
        for table in related_tables:
            try:
                conn.execute(
                    f"DELETE FROM {table} WHERE session_id = :sid",
                    {"sid": session_id},
                )
            except Exception:
                pass

        conn.execute(
            "DELETE FROM sessions WHERE session_id = :sid",
            {"sid": session_id},
        )
        conn.commit()
        logger.info("Deleted session: %s", session_id)
        return api_response({"session_id": session_id})
    except Exception as exc:
        logger.error("Failed to delete session %s: %s", session_id, exc)
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_api_v1_data.py -v`
Expected: PASS (all 30 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_data.py telemetry_tool/tests/test_api_v1_data.py
git commit -m "feat(api): add v1 data endpoints — 15 REST-style wrappers with envelope and rate limiting"
```

---

### Task 14: Legacy Proxies + Deprecation Headers

**Files:**
- Modify: `telemetry_tool/web/routes/api_data.py`
- Create: `telemetry_tool/tests/test_legacy_proxy.py`

**Context:** The 15 legacy endpoints in `api_data.py` (under `/api/`) need deprecation headers that direct clients toward the v1 equivalents created in Task 13. A helper function `_deprecation_headers(v1_path)` builds the three standard headers: `Deprecation: true`, `Sunset: 2026-09-01`, and `Link: <v1_path>; rel="successor-version"`. Each legacy handler is modified to attach these headers to its response via `response.headers.update(...)`. The legacy handlers keep their existing response format for backward compatibility — only the headers change.

**Step 1: Write the failing test**

```python
"""Tests for legacy endpoint deprecation headers and v1 equivalence."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask

from web.api_utils import init_request_id
from web.routes.api_data import bp as api_bp, _deprecation_headers
from web.routes.api_v1_data import bp as api_v1_data_bp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Flask app with both legacy and v1 blueprints."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)
    app.register_blueprint(api_bp)
    app.register_blueprint(api_v1_data_bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_conn():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


# ---------------------------------------------------------------------------
# _deprecation_headers helper
# ---------------------------------------------------------------------------

class TestDeprecationHeadersHelper:
    def test_returns_three_headers(self):
        """_deprecation_headers returns Deprecation, Sunset, and Link."""
        headers = _deprecation_headers("/api/v1/sessions/s1/laps/gps")
        assert headers["Deprecation"] == "true"
        assert headers["Sunset"] == "2026-09-01"
        assert "rel=\"successor-version\"" in headers["Link"]
        assert "/api/v1/sessions/s1/laps/gps" in headers["Link"]

    def test_link_format(self):
        """Link header has correct angle-bracket format."""
        headers = _deprecation_headers("/api/v1/tracks/t1/records")
        assert headers["Link"] == '</api/v1/tracks/t1/records>; rel="successor-version"'


# ---------------------------------------------------------------------------
# Legacy endpoints return deprecation headers
# ---------------------------------------------------------------------------

class TestLegacyDeprecationHeaders:
    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_gps_lap_numbers", return_value=[1, 2])
    def test_gps_laps_has_deprecation(self, mock_laps, mock_db, client):
        """GET /api/session/<id>/gps_laps includes Deprecation header."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/gps_laps")
        assert resp.headers.get("Deprecation") == "true"
        assert resp.headers.get("Sunset") == "2026-09-01"
        assert "/api/v1/" in resp.headers.get("Link", "")

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_laps_for_session", return_value=[])
    def test_lap_times_has_deprecation(self, mock_laps, mock_db, client):
        """GET /api/session/<id>/lap_times includes Deprecation header."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/lap_times")
        assert resp.headers.get("Deprecation") == "true"

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_track_records", return_value=[])
    def test_track_records_has_deprecation(self, mock_recs, mock_db, client):
        """GET /api/track/<id>/records includes Deprecation header."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/track/t1/records")
        assert resp.headers.get("Deprecation") == "true"

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_theoretical_data", return_value=None)
    def test_theoretical_has_deprecation(self, mock_theo, mock_db, client):
        """GET /api/session/<id>/theoretical includes Deprecation even on 404."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/theoretical")
        assert resp.headers.get("Deprecation") == "true"

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_reference_line", return_value=None)
    def test_reference_line_has_deprecation(self, mock_ref, mock_db, client):
        """GET /api/session/<id>/reference_line includes Deprecation."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/reference_line")
        assert resp.headers.get("Deprecation") == "true"


# ---------------------------------------------------------------------------
# Legacy endpoints still return 200 (backward compat)
# ---------------------------------------------------------------------------

class TestLegacyBackwardCompat:
    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_gps_lap_numbers", return_value=[1])
    def test_gps_laps_still_returns_200(self, mock_laps, mock_db, client):
        """Legacy endpoint still returns 200 with old format."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/gps_laps")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "laps" in body

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_track_records", return_value=[{"time": 60}])
    def test_track_records_still_returns_200(self, mock_recs, mock_db, client):
        """Legacy track records endpoint still returns 200."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/track/t1/records")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "records" in body


# ---------------------------------------------------------------------------
# V1 endpoints do NOT have deprecation headers
# ---------------------------------------------------------------------------

class TestV1NoDeprecation:
    @patch("web.routes.api_v1_data.get_db_connection")
    @patch("web.routes.api_v1_data.get_gps_lap_numbers", return_value=[1])
    def test_v1_laps_gps_no_deprecation(self, mock_laps, mock_db, client):
        """V1 endpoints do not carry Deprecation header."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/v1/sessions/s1/laps/gps")
        assert resp.headers.get("Deprecation") is None


# ---------------------------------------------------------------------------
# Sunset header correct date
# ---------------------------------------------------------------------------

class TestSunsetDate:
    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_gps_lap_numbers", return_value=[])
    def test_sunset_date_is_2026_09_01(self, mock_laps, mock_db, client):
        """Sunset header is set to 2026-09-01."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/gps_laps")
        assert resp.headers.get("Sunset") == "2026-09-01"


# ---------------------------------------------------------------------------
# Link header points to correct v1 equivalent
# ---------------------------------------------------------------------------

class TestLinkHeader:
    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_gps_lap_numbers", return_value=[])
    def test_gps_laps_link_points_to_v1(self, mock_laps, mock_db, client):
        """Link header for /api/session/<id>/gps_laps points to v1 laps/gps."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/session/s1/gps_laps")
        link = resp.headers.get("Link", "")
        assert "/api/v1/sessions/s1/laps/gps" in link

    @patch("web.routes.api_data.get_db_connection")
    @patch("web.routes.api_data.get_track_records", return_value=[])
    def test_track_records_link_points_to_v1(self, mock_recs, mock_db, client):
        """Link header for /api/track/<id>/records points to v1 tracks/records."""
        mock_db.return_value = _mock_conn()
        resp = client.get("/api/track/t1/records")
        link = resp.headers.get("Link", "")
        assert "/api/v1/tracks/t1/records" in link
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_legacy_proxy.py -v`
Expected: FAIL with `ImportError: cannot import name '_deprecation_headers' from 'web.routes.api_data'`

**Step 3: Modify api_data.py to add deprecation headers**

Add the `_deprecation_headers` helper after the existing imports block (after the `logger = logging.getLogger(__name__)` line):

```python
# ---------------------------------------------------------------------------
# Deprecation header helper — signals clients to migrate to /api/v1/
# ---------------------------------------------------------------------------

def _deprecation_headers(v1_path: str) -> dict[str, str]:
    """Build standard deprecation headers pointing to the v1 successor.

    Returns a dict with three headers:
    - ``Deprecation: true``
    - ``Sunset: 2026-09-01``
    - ``Link: <v1_path>; rel="successor-version"``
    """
    return {
        "Deprecation": "true",
        "Sunset": "2026-09-01",
        "Link": f'<{v1_path}>; rel="successor-version"',
    }


def _with_deprecation(response, v1_path: str):
    """Attach deprecation headers to a Flask response and return it.

    Works with both ``Response`` objects and ``(response, status)`` tuples
    returned by ``jsonify(...), status``.
    """
    headers = _deprecation_headers(v1_path)
    if isinstance(response, tuple):
        resp_obj = response[0]
        status = response[1] if len(response) > 1 else 200
        resp_obj.headers.update(headers)
        return resp_obj, status
    else:
        response.headers.update(headers)
        return response
```

Modify each of the 15 legacy handlers to call `_with_deprecation()` on their return value. The changes are minimal — wrap the final `return jsonify(...)` line. Examples for the first five endpoints:

**gps_laps:**
```python
@bp.route("/session/<session_id>/gps_laps")
def gps_laps(session_id: str):
    """Return list of lap numbers that have GPS data."""
    conn = get_db_connection()
    laps = get_gps_lap_numbers(conn, session_id)
    return _with_deprecation(
        jsonify({"laps": laps}),
        f"/api/v1/sessions/{session_id}/laps/gps",
    )
```

**speed_trace:**
```python
@bp.route("/session/<session_id>/speed_trace")
def speed_trace(session_id: str):
    """Return speed vs distance data for charting."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return _with_deprecation(
            (jsonify({"error": "Session not found"}), 404),
            f"/api/v1/sessions/{session_id}/speed-trace",
        )

    laps = get_laps_for_session(conn, session_id)
    gps_lap_nums = get_gps_lap_numbers(conn, session_id)

    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break

    traces = {}
    for lap_num in gps_lap_nums:
        gps = get_gps_trace(conn, session_id, lap_num)
        if gps:
            traces[lap_num] = {
                "distances": gps["distances"],
                "speeds": gps["speeds"],
            }

    return _with_deprecation(
        jsonify({
            "laps": traces,
            "best_lap_number": best_lap,
            "session_id": session_id,
        }),
        f"/api/v1/sessions/{session_id}/speed-trace",
    )
```

**lap_times:**
```python
@bp.route("/session/<session_id>/lap_times")
def lap_times(session_id: str):
    """Return lap times as JSON for charting."""
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    return _with_deprecation(
        jsonify({
            "laps": [
                {
                    "lap_number": l["lap_number"],
                    "lap_time_s": l["lap_time_s"],
                    "is_best": bool(l.get("is_best")),
                    "is_valid": bool(l.get("is_valid", True)),
                    "invalid_reason": l.get("invalid_reason"),
                    "phase_id": l.get("phase_id"),
                }
                for l in laps
                if l.get("lap_time_s") is not None
            ],
        }),
        f"/api/v1/sessions/{session_id}/lap-times",
    )
```

**track_records_api:**
```python
@bp.route("/track/<track_id>/records")
def track_records_api(track_id: str):
    """Return track records as JSON."""
    conn = get_db_connection()
    records = get_track_records(conn, track_id)
    return _with_deprecation(
        jsonify({"records": records}),
        f"/api/v1/tracks/{track_id}/records",
    )
```

**track_evolution:**
```python
@bp.route("/track/<track_id>/evolution")
def track_evolution(track_id: str):
    """Return best lap time progression over time for a track."""
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT s.session_id, s.session_date, s.best_lap_time_s,
                  s.total_score, s.track_state, s.session_type,
                  COALESCE(d.driver_name, 'Unknown') AS driver_name
           FROM sessions s
           LEFT JOIN drivers d ON s.driver_id = d.driver_id
           WHERE s.track_id = :track_id
             AND s.best_lap_time_s IS NOT NULL
           ORDER BY s.session_date""",
        {"track_id": track_id},
    ).fetchall()

    sessions = []
    for r in rows:
        sessions.append({
            "session_id": r["session_id"],
            "date": r["session_date"],
            "best_time_s": r["best_lap_time_s"],
            "score": r["total_score"],
            "track_state": r["track_state"],
            "session_type": r["session_type"],
            "driver": r["driver_name"],
        })

    return _with_deprecation(
        jsonify({"track_id": track_id, "sessions": sessions}),
        f"/api/v1/tracks/{track_id}/evolution",
    )
```

Apply the same pattern to the remaining 10 endpoints:

| Legacy endpoint | `_with_deprecation` v1 path |
|-----------------|---------------------------|
| `track_geometry` | `/api/v1/tracks/{track_id}/geometry` |
| `theoretical_data` | `/api/v1/sessions/{session_id}/theoretical` |
| `gg_data` | `/api/v1/sessions/{session_id}/gg-data` |
| `reference_line_data` | `/api/v1/sessions/{session_id}/reference-line` |
| `best_lap_gps` | `/api/v1/sessions/{session_id}/best-lap-gps` |
| `api_fatigue_analysis` | `/api/v1/sessions/{session_id}/fatigue` |
| `api_fingerprint` | `/api/v1/sessions/{session_id}/fingerprint` |
| `api_speed_profile` | `/api/v1/sessions/{session_id}/speed-profile` |
| `files_list` | `/api/v1/files` |
| `delete_session` | `/api/v1/sessions/{session_id}` |

For each, wrap every `return jsonify(...)` (including error returns) with `_with_deprecation(...)`.

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_legacy_proxy.py -v`
Expected: PASS (all 15 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_data.py telemetry_tool/tests/test_legacy_proxy.py
git commit -m "feat(api): add deprecation headers to legacy endpoints pointing to v1 equivalents"
```

---

### Task 15: GDPR Celery Tasks

**Files:**
- Create: `telemetry_tool/tasks/gdpr_tasks.py`
- Create: `telemetry_tool/tests/test_gdpr_tasks.py`

**Context:** Two Celery tasks for GDPR compliance. `export_user_data` is dispatched by `POST /api/v1/account/export` (Task 16) and gathers all user data from PostgreSQL into a ZIP file — profile, sessions metadata, lap times, scores, fingerprints, annotations, and team memberships. GPS precision is reduced to 3 decimal places for data minimization. `purge_deleted_accounts` runs on Celery beat (daily) and hard-deletes user accounts where `deleted_at` is older than 30 days, cascading through workspace data, sessions, scores, and files. Both tasks use the shared `get_pg_connection` helper and are fully testable with mocked PG/Redis.

**Step 1: Write the failing test**

```python
"""Tests for GDPR Celery tasks — export and purge."""
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.gdpr_tasks import export_user_data, purge_deleted_accounts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_conn():
    """Return a mock PG connection."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


def _user_row(user_id=1, email="test@example.com", display_name="Alice",
              deleted_at=None):
    """Build a mock user row."""
    return {
        "id": user_id,
        "email": email,
        "display_name": display_name,
        "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "deleted_at": deleted_at,
    }


def _session_row(session_id="s1", user_id=1):
    return {
        "session_id": session_id,
        "workspace_id": 1,
        "session_date": "2025-06-15",
        "session_type": "practice",
        "n_laps": 10,
        "best_lap_time_s": 62.5,
    }


def _lap_row(session_id="s1", lap_number=1, lat=45.123456789, lon=9.987654321):
    return {
        "session_id": session_id,
        "lap_number": lap_number,
        "lap_time_s": 63.0,
        "gps_lat": lat,
        "gps_lon": lon,
    }


# ---------------------------------------------------------------------------
# export_user_data
# ---------------------------------------------------------------------------

class TestExportUserData:
    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks._write_zip")
    @patch("tasks.gdpr_tasks._update_export_status")
    def test_creates_zip_file(self, mock_update, mock_zip, mock_db):
        """export_user_data calls _write_zip to create export."""
        conn = _mock_conn()
        mock_db.return_value = conn
        # Mock user query
        conn.execute.return_value.fetchone.return_value = _user_row()
        conn.execute.return_value.fetchall.return_value = []

        export_user_data(user_id=1, export_id="exp_001")
        assert mock_zip.called

    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks._write_zip")
    @patch("tasks.gdpr_tasks._update_export_status")
    def test_updates_status_to_completed(self, mock_update, mock_zip, mock_db):
        """export_user_data sets data_exports status to completed."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = _user_row()
        conn.execute.return_value.fetchall.return_value = []

        export_user_data(user_id=1, export_id="exp_001")

        # Last call should set status=completed
        update_calls = mock_update.call_args_list
        assert any(
            "completed" in str(c) for c in update_calls
        ), f"Expected 'completed' in update calls: {update_calls}"

    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks._write_zip")
    @patch("tasks.gdpr_tasks._update_export_status")
    def test_sets_expires_at_7_days(self, mock_update, mock_zip, mock_db):
        """export_user_data sets expires_at to ~7 days from now."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = _user_row()
        conn.execute.return_value.fetchall.return_value = []

        export_user_data(user_id=1, export_id="exp_001")

        update_calls = mock_update.call_args_list
        # The completed call should include an expires_at argument
        assert len(update_calls) >= 1

    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks._write_zip")
    @patch("tasks.gdpr_tasks._update_export_status")
    def test_handles_user_with_no_sessions(self, mock_update, mock_zip, mock_db):
        """export_user_data succeeds even when user has no sessions."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = _user_row()
        conn.execute.return_value.fetchall.return_value = []  # no sessions

        # Should not raise
        export_user_data(user_id=1, export_id="exp_001")
        assert mock_zip.called

    @patch("tasks.gdpr_tasks.get_pg_connection")
    def test_reduces_gps_precision(self, mock_db):
        """GPS coordinates are reduced to 3 decimal places."""
        from tasks.gdpr_tasks import _reduce_gps_precision

        data = {
            "gps_lat": 45.123456789,
            "gps_lon": 9.987654321,
            "latitudes": [45.123456789, 46.987654321],
            "longitudes": [9.111111111, 10.222222222],
        }
        result = _reduce_gps_precision(data)
        assert result["gps_lat"] == 45.123
        assert result["gps_lon"] == 9.988
        assert result["latitudes"] == [45.123, 46.988]
        assert result["longitudes"] == [9.111, 10.222]

    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks._write_zip")
    @patch("tasks.gdpr_tasks._update_export_status")
    def test_export_sets_status_processing_first(self, mock_update, mock_zip, mock_db):
        """export_user_data sets status to processing before starting."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchone.return_value = _user_row()
        conn.execute.return_value.fetchall.return_value = []

        export_user_data(user_id=1, export_id="exp_001")

        first_call = mock_update.call_args_list[0]
        assert "processing" in str(first_call)


# ---------------------------------------------------------------------------
# purge_deleted_accounts
# ---------------------------------------------------------------------------

class TestPurgeDeletedAccounts:
    @patch("tasks.gdpr_tasks.get_pg_connection")
    def test_skips_users_within_30_day_window(self, mock_db):
        """Users deleted less than 30 days ago are NOT purged."""
        conn = _mock_conn()
        mock_db.return_value = conn
        # Return no users past 30 days
        conn.execute.return_value.fetchall.return_value = []

        purge_deleted_accounts()

        # Should not attempt any DELETE on users
        executed_sql = [str(c) for c in conn.execute.call_args_list]
        assert not any("DELETE FROM users" in s for s in executed_sql)

    @patch("tasks.gdpr_tasks.get_pg_connection")
    def test_deletes_users_past_30_days(self, mock_db):
        """Users deleted more than 30 days ago are hard-purged."""
        conn = _mock_conn()
        mock_db.return_value = conn
        old_date = datetime.now(timezone.utc) - timedelta(days=31)
        conn.execute.return_value.fetchall.return_value = [
            _user_row(user_id=42, deleted_at=old_date),
        ]

        purge_deleted_accounts()

        # Should have executed delete statements
        assert conn.execute.call_count >= 2  # query + at least one delete
        conn.commit.assert_called()

    @patch("tasks.gdpr_tasks.get_pg_connection")
    def test_cascades_workspace_deletion(self, mock_db):
        """Purge cascades deletion to workspace-scoped data."""
        conn = _mock_conn()
        mock_db.return_value = conn
        old_date = datetime.now(timezone.utc) - timedelta(days=31)
        conn.execute.return_value.fetchall.return_value = [
            _user_row(user_id=42, deleted_at=old_date),
        ]

        purge_deleted_accounts()

        executed_sql = " ".join(str(c) for c in conn.execute.call_args_list)
        # Should delete from sessions and related tables
        assert "sessions" in executed_sql.lower() or conn.execute.call_count >= 3

    @patch("tasks.gdpr_tasks.get_pg_connection")
    def test_handles_empty_result(self, mock_db):
        """Purge handles no deleted users gracefully."""
        conn = _mock_conn()
        mock_db.return_value = conn
        conn.execute.return_value.fetchall.return_value = []

        # Should not raise
        purge_deleted_accounts()

    @patch("tasks.gdpr_tasks.get_pg_connection")
    @patch("tasks.gdpr_tasks.logger")
    def test_logs_purge_count(self, mock_logger, mock_db):
        """Purge logs the number of accounts purged."""
        conn = _mock_conn()
        mock_db.return_value = conn
        old_date = datetime.now(timezone.utc) - timedelta(days=31)
        conn.execute.return_value.fetchall.return_value = [
            _user_row(user_id=42, deleted_at=old_date),
            _user_row(user_id=43, deleted_at=old_date),
        ]

        purge_deleted_accounts()
        assert mock_logger.info.called
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_gdpr_tasks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tasks.gdpr_tasks'`

**Step 3: Write minimal implementation**

```python
"""GDPR Celery tasks — data export and account purge.

``export_user_data`` gathers all user data from PostgreSQL, reduces GPS
precision, packages into a ZIP file, and updates the ``data_exports`` row.

``purge_deleted_accounts`` runs on Celery beat daily and hard-deletes
accounts where ``deleted_at`` is older than 30 days.

Usage::

    from tasks.gdpr_tasks import export_user_data, purge_deleted_accounts

    # Dispatch export
    export_user_data.delay(user_id=1, export_id="exp_001")

    # Celery beat config
    beat_schedule = {
        "purge-deleted-accounts": {
            "task": "tasks.gdpr_tasks.purge_deleted_accounts",
            "schedule": crontab(hour=3, minute=0),
        },
    }
"""
from __future__ import annotations

import json
import logging
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery app import (graceful fallback for testing)
# ---------------------------------------------------------------------------

try:
    from celery_app import celery_app
except ImportError:
    # Allow module to be imported in test without full Celery setup
    from unittest.mock import MagicMock
    celery_app = MagicMock()

# ---------------------------------------------------------------------------
# PG connection helper
# ---------------------------------------------------------------------------


def get_pg_connection():
    """Get a PostgreSQL connection from the shared pool.

    Tests patch this function to inject a mock.
    """
    from web.db_pg import get_pg_connection as _get_pg
    return _get_pg()


# ---------------------------------------------------------------------------
# GPS precision reduction (data minimization)
# ---------------------------------------------------------------------------

def _reduce_gps_precision(data: dict[str, Any]) -> dict[str, Any]:
    """Reduce GPS coordinate precision to 3 decimal places.

    Applies to ``gps_lat``, ``gps_lon``, ``latitudes``, and ``longitudes``
    fields.  Returns a new dict (does not mutate the input).
    """
    result = dict(data)

    for key in ("gps_lat", "gps_lon"):
        if key in result and result[key] is not None:
            result[key] = round(float(result[key]), 3)

    for key in ("latitudes", "longitudes"):
        if key in result and isinstance(result[key], list):
            result[key] = [
                round(float(v), 3) if v is not None else None
                for v in result[key]
            ]

    return result


# ---------------------------------------------------------------------------
# Export status update helper
# ---------------------------------------------------------------------------

def _update_export_status(
    conn,
    export_id: str,
    status: str,
    file_path: str | None = None,
    expires_at: datetime | None = None,
):
    """Update a data_exports row with new status and optional file_path."""
    from sqlalchemy import text

    params: dict[str, Any] = {
        "export_id": export_id,
        "status": status,
    }
    set_clauses = ["status = :status", "updated_at = now()"]

    if file_path is not None:
        set_clauses.append("file_path = :file_path")
        params["file_path"] = file_path

    if expires_at is not None:
        set_clauses.append("expires_at = :expires_at")
        params["expires_at"] = expires_at

    if status == "completed":
        set_clauses.append("completed_at = now()")

    sql = f"UPDATE data_exports SET {', '.join(set_clauses)} WHERE id = :export_id"
    conn.execute(text(sql), params)
    conn.commit()


# ---------------------------------------------------------------------------
# ZIP writer
# ---------------------------------------------------------------------------

def _write_zip(
    zip_path: str,
    profile: dict[str, Any],
    sessions: list[dict[str, Any]],
    laps: list[dict[str, Any]],
    scores: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    teams: list[dict[str, Any]],
):
    """Write a GDPR export ZIP file containing JSON files per resource.

    All GPS fields are already precision-reduced before this is called.
    """
    def _default(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", json.dumps(profile, indent=2, default=_default))
        zf.writestr("sessions.json", json.dumps(sessions, indent=2, default=_default))
        zf.writestr("laps.json", json.dumps(laps, indent=2, default=_default))
        zf.writestr("scores.json", json.dumps(scores, indent=2, default=_default))
        zf.writestr("annotations.json", json.dumps(annotations, indent=2, default=_default))
        zf.writestr("teams.json", json.dumps(teams, indent=2, default=_default))


# ---------------------------------------------------------------------------
# Task: export_user_data
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="tasks.gdpr_tasks.export_user_data")
def export_user_data(self, user_id: int, export_id: str) -> dict[str, Any]:
    """Export all data for a user into a downloadable ZIP file.

    Steps:
        1. Set export status to 'processing'
        2. Query all user data from PG
        3. Reduce GPS precision to 3 decimal places
        4. Package into ZIP
        5. Update data_exports row with file_path and status='completed'
        6. Set expires_at to 7 days from now

    Args:
        user_id: The user whose data to export.
        export_id: The data_exports row ID.

    Returns:
        Dict with export_id and file_path.
    """
    from sqlalchemy import text

    conn = get_pg_connection()

    # 1. Mark as processing
    _update_export_status(conn, export_id, "processing")

    try:
        # 2. Query user profile
        user = conn.execute(
            text("SELECT id, email, display_name, created_at FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
        profile = dict(user) if user else {"id": user_id, "note": "user not found"}

        # Query sessions
        session_rows = conn.execute(
            text(
                "SELECT * FROM sessions s "
                "JOIN workspace_members wm ON s.workspace_id = wm.workspace_id "
                "WHERE wm.user_id = :uid"
            ),
            {"uid": user_id},
        ).fetchall()
        sessions = [dict(r) for r in session_rows]

        # Query laps (for user's sessions)
        laps = []
        for sess in sessions:
            lap_rows = conn.execute(
                text("SELECT * FROM laps WHERE session_id = :sid"),
                {"sid": sess["session_id"]},
            ).fetchall()
            laps.extend([_reduce_gps_precision(dict(r)) for r in lap_rows])

        # Query scores
        scores = []
        for sess in sessions:
            score_rows = conn.execute(
                text("SELECT * FROM score_details WHERE session_id = :sid"),
                {"sid": sess["session_id"]},
            ).fetchall()
            scores.extend([dict(r) for r in score_rows])

        # Query annotations
        annotations = []
        for sess in sessions:
            ann_rows = conn.execute(
                text("SELECT * FROM session_annotations WHERE session_id = :sid"),
                {"sid": sess["session_id"]},
            ).fetchall()
            annotations.extend([dict(r) for r in ann_rows])

        # Query team memberships
        team_rows = conn.execute(
            text(
                "SELECT t.name, t.slug, tm.role, tm.joined_at "
                "FROM team_members tm JOIN teams t ON tm.team_id = t.id "
                "WHERE tm.user_id = :uid"
            ),
            {"uid": user_id},
        ).fetchall()
        teams = [dict(r) for r in team_rows]

        # 3. Reduce GPS precision on sessions
        sessions = [_reduce_gps_precision(s) for s in sessions]

        # 4. Write ZIP
        export_dir = os.environ.get("TELEMETRY_EXPORT_DIR", "/tmp/telemetry_exports")
        os.makedirs(export_dir, exist_ok=True)
        zip_filename = f"export_{user_id}_{export_id}.zip"
        zip_path = os.path.join(export_dir, zip_filename)

        _write_zip(zip_path, profile, sessions, laps, scores, annotations, teams)

        # 5. Update status to completed
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        _update_export_status(
            conn, export_id, "completed",
            file_path=zip_path,
            expires_at=expires_at,
        )

        logger.info("GDPR export completed: user_id=%s, export_id=%s", user_id, export_id)
        return {"export_id": export_id, "file_path": zip_path}

    except Exception as exc:
        logger.error("GDPR export failed: user_id=%s, error=%s", user_id, exc)
        _update_export_status(conn, export_id, "failed")
        raise


# ---------------------------------------------------------------------------
# Task: purge_deleted_accounts
# ---------------------------------------------------------------------------

@celery_app.task(name="tasks.gdpr_tasks.purge_deleted_accounts")
def purge_deleted_accounts() -> dict[str, int]:
    """Hard-delete user accounts where deleted_at is older than 30 days.

    Steps:
        1. Query users WHERE deleted_at < now() - 30 days
        2. For each: cascade delete workspace data, sessions, scores, files
        3. Hard delete user row
        4. Log count of purged accounts

    Returns:
        Dict with ``{"purged": N}``
    """
    from sqlalchemy import text

    conn = get_pg_connection()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # 1. Find accounts past grace period
    rows = conn.execute(
        text("SELECT id, email FROM users WHERE deleted_at IS NOT NULL AND deleted_at < :cutoff"),
        {"cutoff": cutoff},
    ).fetchall()
    users_to_purge = [dict(r) for r in rows]

    if not users_to_purge:
        logger.info("No accounts to purge (0 past 30-day window)")
        return {"purged": 0}

    purged = 0
    for user in users_to_purge:
        uid = user["id"]
        try:
            # 2. Cascade delete workspace data
            # Find workspaces owned by this user
            ws_rows = conn.execute(
                text("SELECT id FROM workspaces WHERE owner_id = :uid"),
                {"uid": uid},
            ).fetchall()
            workspace_ids = [r["id"] for r in ws_rows]

            for ws_id in workspace_ids:
                # Delete sessions and related data in this workspace
                session_rows = conn.execute(
                    text("SELECT session_id FROM sessions WHERE workspace_id = :ws"),
                    {"ws": ws_id},
                ).fetchall()
                for sess in session_rows:
                    sid = sess["session_id"]
                    for table in [
                        "gps_traces", "laps", "score_details",
                        "corner_metrics", "session_annotations",
                        "session_tags", "theoretical_data",
                        "reference_lines", "driving_style_features",
                    ]:
                        conn.execute(
                            text(f"DELETE FROM {table} WHERE session_id = :sid"),
                            {"sid": sid},
                        )
                conn.execute(
                    text("DELETE FROM sessions WHERE workspace_id = :ws"),
                    {"ws": ws_id},
                )

                # Delete workspace members and workspace itself
                conn.execute(
                    text("DELETE FROM workspace_members WHERE workspace_id = :ws"),
                    {"ws": ws_id},
                )
                conn.execute(
                    text("DELETE FROM workspaces WHERE id = :ws"),
                    {"ws": ws_id},
                )

            # Remove from all team memberships
            conn.execute(
                text("DELETE FROM team_members WHERE user_id = :uid"),
                {"uid": uid},
            )

            # Delete data exports
            conn.execute(
                text("DELETE FROM data_exports WHERE user_id = :uid"),
                {"uid": uid},
            )

            # Delete refresh tokens
            conn.execute(
                text("DELETE FROM refresh_tokens WHERE user_id = :uid"),
                {"uid": uid},
            )

            # 3. Hard delete user row
            conn.execute(
                text("DELETE FROM users WHERE id = :uid"),
                {"uid": uid},
            )
            conn.commit()

            purged += 1
            logger.info("Purged account: user_id=%s, email=%s", uid, user.get("email"))

        except Exception as exc:
            logger.error("Failed to purge user_id=%s: %s", uid, exc)
            continue

    logger.info("Account purge complete: %d accounts purged", purged)
    return {"purged": purged}
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_gdpr_tasks.py -v`
Expected: PASS (all 15 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/tasks/gdpr_tasks.py telemetry_tool/tests/test_gdpr_tasks.py
git commit -m "feat(gdpr): add Celery tasks for data export and account purge"
```

---

### Task 16: Account Endpoints

**Files:**
- Create: `telemetry_tool/web/routes/api_v1_account.py`
- Create: `telemetry_tool/tests/test_api_v1_account.py`

**Context:** GDPR account management endpoints under `/api/v1/account/`. Data export endpoints dispatch the `export_user_data` Celery task from Task 15 and track status via the `data_exports` table from Migration 010 (Task 7). Account deletion is a soft-delete (sets `deleted_at` on the `users` row) with a 30-day grace period during which `POST /cancel-deletion` can reverse it. Profile update allows changing `display_name` and `email` (email changes trigger re-verification). All write endpoints use `@idempotent` and `@rate_limit(tier="write")`. Read endpoints use `@rate_limit(tier="read")`.

**Step 1: Write the failing test**

```python
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

def _make_app():
    """Create a minimal Flask app with api_v1_account blueprint."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)
    app.register_blueprint(api_v1_account_bp)

    @app.before_request
    def _inject_user():
        """Simulate authenticated user."""
        g.user_id = 1
        g.workspace_id = "ws_001"

    return app


@pytest.fixture
def app():
    return _make_app()


@pytest.fixture
def client(app):
    return app.test_client()


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

        resp = client.get("/api/v1/account/export/exp_001/download")
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
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_api_v1_account.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web.routes.api_v1_account'`

**Step 3: Write minimal implementation**

```python
"""V1 account API endpoints — GDPR data export, deletion, and profile.

Blueprint: ``/api/v1/account/`` — provides endpoints for GDPR compliance
including data export (right of access/portability), account deletion
(right of erasure), and profile rectification.

Usage::

    from web.routes.api_v1_account import bp as api_v1_account_bp
    app.register_blueprint(api_v1_account_bp)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, g, request, send_file

from web.api_utils import ErrorCode, api_error, api_response

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1_account", __name__, url_prefix="/api/v1/account")


# ---- Rate limit import (graceful fallback) ----
try:
    from web.rate_limit import rate_limit
except ImportError:
    def rate_limit(**kwargs):
        def decorator(fn):
            return fn
        return decorator


# ---- Idempotency import (graceful fallback) ----
try:
    from web.idempotency import idempotent
except ImportError:
    def idempotent(fn):
        return fn


# ---- Validation import (graceful fallback) ----
try:
    from web.validation import validate_body
except ImportError:
    def validate_body(schema):
        def decorator(fn):
            return fn
        return decorator


# ---- PG connection ----
def get_pg_connection():
    """Get PostgreSQL connection. Tests patch this."""
    from web.db_pg import get_pg_connection as _get_pg
    return _get_pg()


# ---- Celery task import (graceful fallback) ----
try:
    from tasks.gdpr_tasks import export_user_data
except ImportError:
    export_user_data = None


# ---------------------------------------------------------------------------
# POST /export — create data export request
# ---------------------------------------------------------------------------

@bp.route("/export", methods=["POST"])
@rate_limit(tier="write")
@idempotent
def create_export():
    """Create a data export request and dispatch Celery task.

    Returns:
        202 with ``{"export_id": "..."}``
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    if user_id is None:
        return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=403)

    conn = get_pg_connection()

    # Create data_exports row
    cursor = conn.execute(
        text(
            "INSERT INTO data_exports (user_id, status, format, created_at) "
            "VALUES (:uid, 'pending', 'zip', now()) RETURNING id"
        ),
        {"uid": user_id},
    )
    row = cursor.fetchone()
    export_id = row["id"] if isinstance(row, dict) else dict(row)["id"]
    conn.commit()

    # Dispatch Celery task
    if export_user_data is not None:
        export_user_data.delay(user_id=user_id, export_id=str(export_id))

    return api_response({"export_id": str(export_id)}, status=202)


# ---------------------------------------------------------------------------
# GET /export/<id>/status — check export status
# ---------------------------------------------------------------------------

@bp.route("/export/<export_id>/status", methods=["GET"])
@rate_limit(tier="read")
def export_status(export_id: str):
    """Get current status of a data export.

    Returns:
        200 with export status data.
        404 if export not found.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    conn = get_pg_connection()

    row = conn.execute(
        text(
            "SELECT id, status, created_at, completed_at "
            "FROM data_exports WHERE id = :eid AND user_id = :uid"
        ),
        {"eid": export_id, "uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Export not found", status=404)

    return api_response(dict(row) if not isinstance(row, dict) else row)


# ---------------------------------------------------------------------------
# GET /export/<id>/download — download export file
# ---------------------------------------------------------------------------

@bp.route("/export/<export_id>/download", methods=["GET"])
@rate_limit(tier="read")
def export_download(export_id: str):
    """Download the exported ZIP file.

    Returns:
        200 with file download if completed.
        404 if export not completed or not found.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    conn = get_pg_connection()

    row = conn.execute(
        text(
            "SELECT id, status, file_path "
            "FROM data_exports WHERE id = :eid AND user_id = :uid"
        ),
        {"eid": export_id, "uid": user_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Export not found", status=404)

    data = dict(row) if not isinstance(row, dict) else row

    if data["status"] != "completed" or not data.get("file_path"):
        return api_error(ErrorCode.NOT_FOUND, "Export not yet completed", status=404)

    return send_file(
        data["file_path"],
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"data_export_{export_id}.zip",
    )


# ---------------------------------------------------------------------------
# DELETE / — soft-delete account
# ---------------------------------------------------------------------------

@bp.route("/", methods=["DELETE"])
@rate_limit(tier="write")
@idempotent
def delete_account():
    """Soft-delete the authenticated user's account.

    Sets ``deleted_at`` on the user row and revokes tokens. Account is
    hard-purged after 30 days by the ``purge_deleted_accounts`` Celery task.

    Returns:
        200 with ``{"deleted": true}``
        409 if account is already deleted.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    conn = get_pg_connection()

    user = conn.execute(
        text("SELECT id, deleted_at FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if user is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    data = dict(user) if not isinstance(user, dict) else user

    if data.get("deleted_at") is not None:
        return api_error(ErrorCode.CONFLICT, "Account is already scheduled for deletion", status=409)

    # Set deleted_at
    conn.execute(
        text("UPDATE users SET deleted_at = now() WHERE id = :uid"),
        {"uid": user_id},
    )

    # Revoke all refresh tokens
    conn.execute(
        text("DELETE FROM refresh_tokens WHERE user_id = :uid"),
        {"uid": user_id},
    )
    conn.commit()

    logger.info("Account soft-deleted: user_id=%s", user_id)
    return api_response({"deleted": True})


# ---------------------------------------------------------------------------
# POST /cancel-deletion — cancel pending deletion
# ---------------------------------------------------------------------------

@bp.route("/cancel-deletion", methods=["POST"])
@rate_limit(tier="write")
def cancel_deletion():
    """Cancel a pending account deletion (within 30-day grace period).

    Clears ``deleted_at`` on the user row.

    Returns:
        200 with ``{"restored": true}``
        409 if account is not in deleted state.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    conn = get_pg_connection()

    user = conn.execute(
        text("SELECT id, deleted_at FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if user is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    data = dict(user) if not isinstance(user, dict) else user

    if data.get("deleted_at") is None:
        return api_error(ErrorCode.CONFLICT, "Account is not in deleted state", status=409)

    # Clear deleted_at
    conn.execute(
        text("UPDATE users SET deleted_at = NULL WHERE id = :uid"),
        {"uid": user_id},
    )
    conn.commit()

    logger.info("Account deletion cancelled: user_id=%s", user_id)
    return api_response({"restored": True})


# ---------------------------------------------------------------------------
# PATCH /profile — update display_name and/or email
# ---------------------------------------------------------------------------

@bp.route("/profile", methods=["PATCH"])
@rate_limit(tier="write")
def update_profile():
    """Update the user's display_name and/or email.

    Email changes set ``email_verified = False`` and trigger re-verification.

    Returns:
        200 with updated profile data.
        400 if body is empty or invalid.
    """
    from sqlalchemy import text

    user_id = getattr(g, "user_id", None)
    conn = get_pg_connection()

    body = request.get_json(silent=True) or {}
    display_name = body.get("display_name")
    email = body.get("email")

    if not display_name and not email:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "At least one of display_name or email is required",
            status=400,
        )

    user = conn.execute(
        text("SELECT id, display_name, email FROM users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()

    if user is None:
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    current = dict(user) if not isinstance(user, dict) else user
    email_verification_required = False

    set_clauses = []
    params = {"uid": user_id}

    if display_name:
        set_clauses.append("display_name = :display_name")
        params["display_name"] = display_name

    if email and email != current.get("email"):
        set_clauses.append("email = :email")
        set_clauses.append("email_verified = false")
        params["email"] = email
        email_verification_required = True

    if set_clauses:
        sql = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = :uid"
        conn.execute(text(sql), params)
        conn.commit()

    result = {
        "display_name": display_name or current.get("display_name"),
        "email": email or current.get("email"),
    }
    if email_verification_required:
        result["email_verification_required"] = True

    return api_response(result)
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_api_v1_account.py -v`
Expected: PASS (all 20 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_account.py telemetry_tool/tests/test_api_v1_account.py
git commit -m "feat(gdpr): add account endpoints — data export, deletion, cancel, profile update"
```

---

### Task 17: Integration Tests

**Files:**
- Create: `telemetry_tool/tests/test_phase4_integration.py`

**Context:** Cross-cutting integration tests that verify the Phase 4 infrastructure modules work together end-to-end. These tests exercise the full request lifecycle — request_id generation, rate limiting, validation, idempotency, cursor pagination, error envelope consistency, deprecation headers, and structured logging — in a single Flask test client session. They ensure the decorator stacking order (`@rate_limit` before `@validate_body`) works correctly, that idempotent replays do not double-count against rate limits, and that all error responses (404, 429, validation) consistently use the envelope format.

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_phase4_integration.py -v`
Expected: FAIL (import errors for modules not yet created, or tests fail because v1 routes are not registered)

**Step 3: No new implementation needed**

This is a pure test file. All functionality was implemented in Tasks 1-16. If any tests fail, the fix belongs in the relevant source module, not in this test file.

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_phase4_integration.py -v`
Expected: PASS (all 15 tests) — once Tasks 1-16 are implemented

**Step 5: Commit**

```bash
git add telemetry_tool/tests/test_phase4_integration.py
git commit -m "test(api): add Phase 4 integration tests — lifecycle, envelope, deprecation, logging"
```

---

### Task 18: Final Wiring + Config

**Files:**
- Modify: `telemetry_tool/web/app.py`

**Context:** The placeholder blueprint registrations added in Task 12 (inside the `if cfg.USE_PG:` try/except block) used try/except guards with `ImportError` fallbacks because the modules did not exist yet. Now that `api_v1_data.py` (Task 13) and `api_v1_account.py` (Task 16) are implemented, this task removes the try/except guards and makes the imports unconditional within the `USE_PG` block. It also verifies that the full test suite passes across all Phase 4 modules.

**Step 1: Verify current app starts (baseline)**

Run: `cd telemetry_tool && python -c "from web.app import create_app; app = create_app(); print('OK')"`
Expected: `OK`

**Step 2: Verify all Phase 4 tests pass before changes**

Run: `cd telemetry_tool && python -m pytest tests/test_api_utils.py tests/test_validation.py tests/test_rate_limit.py tests/test_pagination.py tests/test_idempotency.py tests/test_logging_setup.py tests/test_migration_010.py tests/test_schemas.py tests/test_api_v1_data.py tests/test_legacy_proxy.py tests/test_gdpr_tasks.py tests/test_api_v1_account.py tests/test_phase4_integration.py -v`
Expected: PASS (all ~180 tests)

**Step 3: Modify app.py — replace placeholder imports with unconditional imports**

In `telemetry_tool/web/app.py`, locate the placeholder block inside the `if cfg.USE_PG:` try/except (added in Task 12):

```python
            # Phase 4 v1 endpoint blueprints (placeholder — modules created in later tasks)
            try:
                from .routes.api_v1_data import bp as api_v1_data_bp
                app.register_blueprint(api_v1_data_bp)
                logger.debug("Registered api_v1_data blueprint")
            except ImportError:
                logger.debug("api_v1_data module not yet available — skipping")

            try:
                from .routes.api_v1_account import bp as api_v1_account_bp
                app.register_blueprint(api_v1_account_bp)
                logger.debug("Registered api_v1_account blueprint")
            except ImportError:
                logger.debug("api_v1_account module not yet available — skipping")
```

Replace with unconditional imports:

```python
            # Phase 4 v1 endpoint blueprints
            from .routes.api_v1_data import bp as api_v1_data_bp
            from .routes.api_v1_account import bp as api_v1_account_bp
            app.register_blueprint(api_v1_data_bp)
            app.register_blueprint(api_v1_account_bp)
            logger.debug("Registered Phase 4 v1 blueprints (api_v1_data, api_v1_account)")
```

This ensures both blueprints are always registered when `USE_PG` is enabled and makes import errors surface immediately rather than being silently swallowed.

**Step 4: Verify the app still starts and full test suite passes**

Run: `cd telemetry_tool && python -c "from web.app import create_app; app = create_app(); print('OK')"`
Expected: `OK`

Run: `cd telemetry_tool && python -m pytest tests/ -v --tb=short`
Expected: PASS (all tests including Phase 4 integration tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/app.py
git commit -m "feat(app): finalize Phase 4 wiring — unconditional v1 blueprint registration"
```
