"""Auto-generate a comprehensive OpenAPI 3.0 specification from Flask routes.

Introspects the Flask app's URL map, route docstrings, and Pydantic schemas
to produce a rich OpenAPI spec with typed request/response bodies, query
parameters, rate-limit headers, error codes, and authentication schemes.

Serves:
- ``GET /api/v1/openapi.json``  — machine-readable spec
- ``GET /api/v1/docs``          — Swagger UI (interactive explorer)

Usage::

    from web.openapi import register_openapi
    register_openapi(app)
"""
from __future__ import annotations

import re
from typing import Any

from flask import Flask, jsonify, make_response


# ---------------------------------------------------------------------------
# Route metadata registry
# ---------------------------------------------------------------------------
# Maps (method, path_pattern) → extra OpenAPI metadata for that operation.
# Used to enrich the auto-generated spec with query params, request bodies,
# response schemas, and descriptions that can't be inferred from Flask alone.

_ROUTE_META: dict[tuple[str, str], dict[str, Any]] = {}


def _meta(method: str, path: str, **kwargs: Any) -> None:
    """Register extra metadata for a route."""
    _ROUTE_META[(method.lower(), path)] = kwargs


# ── Auth endpoints ──────────────────────────────────────────────
_meta("post", "/api/v1/auth/register",
      request_schema="RegisterSchema",
      tag="auth",
      summary="Register a new user account",
      description="Creates a user with email/password. Auto-creates a personal workspace.",
      responses={"201": "User created", "409": "Email already registered"})

_meta("post", "/api/v1/auth/login",
      request_schema="LoginSchema",
      tag="auth",
      summary="Authenticate with email and password",
      description="Returns access token (in body) and refresh token (httpOnly cookie).",
      responses={"200": "Authenticated", "401": "Invalid credentials"})

_meta("post", "/api/v1/auth/refresh",
      tag="auth",
      summary="Refresh access token",
      description="Uses httpOnly refresh cookie. Returns new access token and rotates refresh token.",
      no_auth=True)

_meta("post", "/api/v1/auth/logout",
      tag="auth",
      summary="Invalidate refresh token")

_meta("get", "/api/v1/auth/verify-email",
      tag="auth",
      summary="Verify email address via token link",
      no_auth=True,
      query_params=[{"name": "token", "required": True, "schema": {"type": "string"}}])

_meta("get", "/api/v1/me",
      tag="auth",
      summary="Get current user profile",
      description="Returns user info, workspace memberships, and plan tier.")

# ── Session endpoints ──────────────────────────────────────────
_meta("get", "/api/v1/sessions",
      tag="sessions",
      summary="List sessions with pagination and filters",
      query_params=[
          {"name": "limit", "schema": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100}},
          {"name": "cursor", "schema": {"type": "string"}, "description": "Keyset cursor for next page"},
          {"name": "sort", "schema": {"type": "string"}, "description": "Column name to sort by"},
          {"name": "order", "schema": {"type": "string", "enum": ["asc", "desc"], "default": "desc"}},
          {"name": "track_id", "schema": {"type": "integer"}},
          {"name": "driver_id", "schema": {"type": "integer"}},
          {"name": "status", "schema": {"type": "string"}},
      ])

_meta("get", "/api/v1/sessions/{session_id}",
      tag="sessions",
      summary="Get session detail",
      description="Returns full session metadata, track info, and driver info.")

_meta("delete", "/api/v1/sessions/{session_id}",
      tag="sessions",
      summary="Delete a session and all related data")

_meta("patch", "/api/v1/sessions/{session_id}",
      tag="sessions",
      summary="Update session fields",
      description="Partial update — only provided fields are changed.",
      request_body_schema={
          "type": "object",
          "properties": {
              "name": {"type": "string"},
              "notes": {"type": "string"},
              "vehicle": {"type": "string"},
          },
      })

_meta("post", "/api/v1/sessions/upload",
      tag="sessions",
      summary="Upload a telemetry CSV for analysis",
      description=(
          "Accepts multipart/form-data with a CSV file. Runs the 14-stage "
          "analysis pipeline synchronously and returns results. "
          "Rate limited to upload tier (10/hour base)."
      ),
      request_body_content="multipart/form-data",
      responses={"200": "Analysis complete", "413": "File too large", "415": "Unsupported format"})

# ── Lap & chart data endpoints ────────────────────────────────
_meta("get", "/api/v1/sessions/{session_id}/laps",
      tag="telemetry-data",
      summary="Get lap list for a session",
      description="Returns lap times, sectors, and per-lap scoring.")

_meta("get", "/api/v1/sessions/{session_id}/speed-trace",
      tag="telemetry-data",
      summary="Get speed vs distance data",
      description="Returns arrays of distance and speed for chart rendering.",
      query_params=[
          {"name": "lap", "schema": {"type": "integer"}, "description": "Filter to a specific lap number"},
      ])

_meta("get", "/api/v1/sessions/{session_id}/gps-trace",
      tag="telemetry-data",
      summary="Get GPS coordinates for track map",
      query_params=[
          {"name": "lap", "schema": {"type": "integer"}},
      ])

_meta("get", "/api/v1/sessions/{session_id}/gg-data",
      tag="telemetry-data",
      summary="Get G-G diagram data (lateral vs longitudinal acceleration)")

_meta("get", "/api/v1/sessions/{session_id}/scores",
      tag="telemetry-data",
      summary="Get score breakdown",
      description="Returns Pace, Consistency, Execution, and Robustness scores (/25 each).")

_meta("get", "/api/v1/sessions/{session_id}/corners",
      tag="telemetry-data",
      summary="Get corner coaching data",
      description="Returns per-corner deltas for braking, turn-in, and throttle with ranked suggestions.")

_meta("get", "/api/v1/sessions/{session_id}/grip-map",
      tag="telemetry-data",
      summary="Get distance-binned grip map")

_meta("get", "/api/v1/sessions/{session_id}/friction-envelope",
      tag="telemetry-data",
      summary="Get speed-binned friction envelope")

_meta("get", "/api/v1/sessions/{session_id}/predict",
      tag="predictions",
      summary="Predict expected lap time from conditions and history",
      description=(
          "Uses weighted k-nearest-neighbor regression over historical sessions "
          "to predict expected lap time. Adjusts for grip, temperature, and driver "
          "improvement trends. If the session has completed laps, blends observed "
          "data with historical prediction for a more accurate estimate."
      ))

_meta("get", "/api/v1/sessions/{session_id}/coaching",
      tag="coaching",
      summary="Get AI coaching debrief with narrative and drills",
      description=(
          "Synthesizes corner data, CoachingV2, scores, lap metrics, and "
          "driving style into a structured session debrief. Returns a session "
          "theme, narrative summary, ranked focus areas, targeted practice "
          "drills, lap-to-lap progression analysis, and next-session goals."
      ))

# ── Comparison endpoints ──────────────────────────────────────
_meta("get", "/api/v1/compare/multi",
      tag="compare",
      summary="Compare up to 8 sessions side by side",
      description=(
          "Returns scores, laps, best times, and a pairwise delta matrix "
          "for 2-8 sessions. Identifies the overall fastest session."
      ),
      query_params=[
          {"name": "ids", "required": True, "schema": {"type": "string"},
           "description": "Comma-separated session IDs (2-8)"},
      ])

_meta("get", "/api/v1/compare/sessions",
      tag="compare",
      summary="Compare two sessions side by side",
      query_params=[
          {"name": "a", "required": True, "schema": {"type": "string"}, "description": "Session A ID"},
          {"name": "b", "required": True, "schema": {"type": "string"}, "description": "Session B ID"},
      ])

_meta("get", "/api/v1/compare/drivers",
      tag="compare",
      summary="Compare two drivers across sessions",
      query_params=[
          {"name": "a", "required": True, "schema": {"type": "integer"}, "description": "Driver A ID"},
          {"name": "b", "required": True, "schema": {"type": "integer"}, "description": "Driver B ID"},
      ])

_meta("get", "/api/v1/sessions/{session_id}/compare/sectors",
      tag="compare",
      summary="Compare sectors/corners within a session")

# ── Dashboard & export ────────────────────────────────────────
_meta("get", "/api/v1/dashboard/stats",
      tag="dashboard",
      summary="Get dashboard aggregate statistics",
      description="Returns total sessions, tracks, drivers, recent activity.")

_meta("get", "/api/v1/sessions/{session_id}/report",
      tag="export",
      summary="Download session analysis report",
      query_params=[
          {"name": "format", "schema": {"type": "string", "enum": ["html", "pdf"], "default": "html"}},
      ])

_meta("get", "/api/v1/export/scores",
      tag="export",
      summary="Export scoring history as CSV",
      description="Returns a CSV file of all session scores for the workspace.")

# ── Teams & workspaces ────────────────────────────────────────
_meta("post", "/api/v1/teams",
      tag="teams",
      summary="Create a new team workspace",
      request_schema="CreateTeamSchema")

_meta("get", "/api/v1/teams/{team_id}/members",
      tag="teams",
      summary="List team members with roles")

_meta("post", "/api/v1/teams/{team_id}/members",
      tag="teams",
      summary="Invite a user to the team",
      request_schema="InviteMemberSchema")

_meta("delete", "/api/v1/teams/{team_id}/members/{user_id}",
      tag="teams",
      summary="Remove a member from the team")

_meta("get", "/api/v1/workspaces",
      tag="workspaces",
      summary="List workspaces the current user belongs to")

_meta("get", "/api/v1/workspaces/current",
      tag="workspaces",
      summary="Get current workspace context")

# ── Account & GDPR ────────────────────────────────────────────
_meta("get", "/api/v1/account/profile",
      tag="account",
      summary="Get user profile and preferences")

_meta("patch", "/api/v1/account/profile",
      tag="account",
      summary="Update user profile",
      request_schema="ProfileUpdateSchema")

_meta("post", "/api/v1/account/export",
      tag="account",
      summary="Request GDPR data export",
      request_schema="ExportRequestSchema")

_meta("delete", "/api/v1/account",
      tag="account",
      summary="Delete account and all data (GDPR erasure)",
      description="Schedules account for deletion after 30-day grace period.")

# ── Billing ───────────────────────────────────────────────────
_meta("get", "/api/v1/billing/portal",
      tag="billing",
      summary="Get Stripe Customer Portal URL")

_meta("post", "/api/v1/billing/checkout",
      tag="billing",
      summary="Create Stripe Checkout session",
      request_body_schema={
          "type": "object",
          "required": ["price_id"],
          "properties": {
              "price_id": {"type": "string", "description": "Stripe Price ID"},
          },
      })

_meta("post", "/api/v1/billing/webhook",
      tag="billing",
      summary="Stripe webhook receiver",
      no_auth=True,
      description="Verifies Stripe-Signature header. Handles checkout.session.completed and subscription events.")

# ── Health ────────────────────────────────────────────────────
_meta("get", "/healthz",
      tag="health",
      summary="Health check",
      no_auth=True,
      description="Returns 200 with DB, Redis, and Celery status. 503 if any critical service is down.")


# ---------------------------------------------------------------------------
# Pydantic schema extraction
# ---------------------------------------------------------------------------

def _collect_pydantic_schemas() -> dict[str, dict[str, Any]]:
    """Import Pydantic schemas and extract JSON Schema dicts."""
    schemas: dict[str, dict[str, Any]] = {}
    schema_modules = [
        ("web.schemas.auth", ["RegisterSchema", "LoginSchema", "RefreshSchema", "VerifyEmailSchema"]),
        ("web.schemas.account", ["ProfileUpdateSchema", "ExportRequestSchema", "UserPreferences", "NotificationPreferences"]),
        ("web.schemas.teams", ["CreateTeamSchema", "InviteMemberSchema"]),
        ("web.schemas.sessions", ["SessionListParams"]),
        ("web.schemas.common", ["PaginationParams"]),
    ]
    for module_path, class_names in schema_modules:
        try:
            mod = __import__(module_path, fromlist=class_names)
            for cls_name in class_names:
                cls = getattr(mod, cls_name, None)
                if cls is not None and hasattr(cls, "model_json_schema"):
                    json_schema = cls.model_json_schema()
                    # Remove $defs if present — flatten for OpenAPI
                    json_schema.pop("$defs", None)
                    json_schema.pop("title", None)
                    schemas[cls_name] = json_schema
        except (ImportError, Exception):
            pass
    return schemas


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _flask_rule_to_openapi_path(rule: str) -> str:
    """Convert Flask rule ``/sessions/<session_id>`` to OpenAPI ``/sessions/{session_id}``."""
    return re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule)


def _extract_path_params(rule: str) -> list[dict[str, Any]]:
    """Extract path parameters from a Flask URL rule."""
    params = []
    for match in re.finditer(r"<(?:(\w+):)?(\w+)>", rule):
        param_type = match.group(1) or "string"
        param_name = match.group(2)
        schema: dict[str, str] = {"type": "string"}
        if param_type == "int":
            schema = {"type": "integer"}
        params.append({
            "name": param_name,
            "in": "path",
            "required": True,
            "schema": schema,
        })
    return params


def _method_to_lower(methods: set[str]) -> list[str]:
    """Return HTTP methods as lowercase, excluding HEAD and OPTIONS."""
    skip = {"HEAD", "OPTIONS"}
    return sorted(m.lower() for m in methods if m not in skip)


# ---------------------------------------------------------------------------
# Tag descriptions
# ---------------------------------------------------------------------------

_TAG_DESCRIPTIONS: list[dict[str, str]] = [
    {"name": "auth", "description": "Authentication — register, login, JWT refresh, OAuth, email verification"},
    {"name": "sessions", "description": "Session CRUD — upload, list, detail, update, delete"},
    {"name": "telemetry-data", "description": "Chart data — speed traces, GPS, G-G diagrams, scores, corners"},
    {"name": "coaching", "description": "AI coaching — session debrief, focus areas, practice drills, goals"},
    {"name": "predictions", "description": "Predictive models — lap time estimation, improvement potential"},
    {"name": "compare", "description": "Session and driver comparison endpoints"},
    {"name": "dashboard", "description": "Dashboard aggregate statistics"},
    {"name": "export", "description": "Data export — reports, CSV downloads"},
    {"name": "teams", "description": "Team management — create teams, invite/remove members, roles"},
    {"name": "workspaces", "description": "Multi-tenant workspace context"},
    {"name": "account", "description": "User profile, preferences, and GDPR data operations"},
    {"name": "billing", "description": "Stripe billing — checkout, portal, webhooks"},
    {"name": "tracks", "description": "Track management and detection"},
    {"name": "drivers", "description": "Driver profiles and progression"},
    {"name": "leaderboard", "description": "Track leaderboards and rankings"},
    {"name": "health", "description": "System health and readiness checks"},
    {"name": "jobs", "description": "Background job status polling"},
]


# ---------------------------------------------------------------------------
# Spec generator
# ---------------------------------------------------------------------------

def generate_openapi_spec(app: Flask) -> dict[str, Any]:
    """Build a comprehensive OpenAPI 3.0.3 spec from Flask routes + metadata."""
    paths: dict[str, Any] = {}
    pydantic_schemas = _collect_pydantic_schemas()

    for rule in app.url_map.iter_rules():
        # Include /api/ routes and /healthz
        if not (rule.rule.startswith("/api/") or rule.rule == "/healthz"):
            continue
        if rule.rule.endswith("/openapi.json") or rule.rule.endswith("/docs"):
            continue

        openapi_path = _flask_rule_to_openapi_path(rule.rule)
        path_params = _extract_path_params(rule.rule)

        if openapi_path not in paths:
            paths[openapi_path] = {}

        view_func = app.view_functions.get(rule.endpoint)
        docstring = (view_func.__doc__ or "").strip() if view_func else ""
        doc_lines = docstring.split("\n", 1)
        doc_summary = doc_lines[0].strip() if doc_lines else ""
        doc_description = doc_lines[1].strip() if len(doc_lines) > 1 else ""

        for method in _method_to_lower(rule.methods):
            meta_key = (method, openapi_path)
            meta = _ROUTE_META.get(meta_key, {})

            summary = meta.get("summary", doc_summary) or rule.endpoint.replace("_", " ").title()
            description = meta.get("description", doc_description)

            # Tag: prefer meta, then derive from path
            tag = meta.get("tag")
            if not tag:
                parts = openapi_path.strip("/").split("/")
                tag = parts[2] if len(parts) >= 3 else "default"

            # Build responses
            responses: dict[str, Any] = {
                "200": {
                    "description": "Success",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ApiEnvelope"},
                        },
                    },
                },
            }
            # Add rate-limit headers to all API responses
            responses["200"]["headers"] = {
                "X-Request-Id": {
                    "description": "Unique request identifier for tracing",
                    "schema": {"type": "string", "format": "uuid"},
                },
            }
            responses["429"] = {
                "description": "Rate limit exceeded",
                "headers": {
                    "Retry-After": {
                        "description": "Seconds until the rate limit window resets",
                        "schema": {"type": "integer"},
                    },
                },
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                    },
                },
            }
            # Merge extra response codes from meta
            for code, desc in meta.get("responses", {}).items():
                if code not in responses:
                    responses[code] = {"description": desc}

            if "404" not in responses and "{" in openapi_path:
                responses["404"] = {"description": "Resource not found"}
            if "422" not in responses and method in ("post", "put", "patch"):
                responses["422"] = {
                    "description": "Validation error",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ValidationError"},
                        },
                    },
                }

            operation: dict[str, Any] = {
                "summary": summary,
                "operationId": f"{method}_{rule.endpoint}",
                "tags": [tag],
                "responses": responses,
            }
            if description:
                operation["description"] = description

            # Parameters: path + query
            params = list(path_params)
            for qp in meta.get("query_params", []):
                param = {
                    "name": qp["name"],
                    "in": "query",
                    "required": qp.get("required", False),
                    "schema": qp.get("schema", {"type": "string"}),
                }
                if "description" in qp:
                    param["description"] = qp["description"]
                params.append(param)
            if params:
                operation["parameters"] = params

            # Request body
            if method in ("post", "put", "patch"):
                content_type = meta.get("request_body_content", "application/json")
                if content_type == "multipart/form-data":
                    operation["requestBody"] = {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["file"],
                                    "properties": {
                                        "file": {
                                            "type": "string",
                                            "format": "binary",
                                            "description": "CSV telemetry file (RaceChrono/RaceBox format)",
                                        },
                                    },
                                },
                            },
                        },
                    }
                elif "request_schema" in meta:
                    schema_name = meta["request_schema"]
                    if schema_name in pydantic_schemas:
                        operation["requestBody"] = {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": f"#/components/schemas/{schema_name}"},
                                },
                            },
                        }
                    else:
                        operation["requestBody"] = {
                            "required": True,
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                elif "request_body_schema" in meta:
                    operation["requestBody"] = {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": meta["request_body_schema"],
                            },
                        },
                    }
                else:
                    operation["requestBody"] = {
                        "required": True,
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }

            # Auth: mark unauthenticated endpoints
            if meta.get("no_auth"):
                operation["security"] = []

            paths[openapi_path][method] = operation

    # ── Assemble full spec ────────────────────────────────────
    component_schemas: dict[str, Any] = {
        "ApiEnvelope": {
            "type": "object",
            "description": "Standard API response wrapper used by all endpoints.",
            "properties": {
                "ok": {"type": "boolean", "description": "Whether the request succeeded"},
                "data": {
                    "description": "Response payload (null on error)",
                    "nullable": True,
                },
                "error": {
                    "type": "object",
                    "nullable": True,
                    "description": "Error details (null on success)",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Machine-readable error code",
                            "enum": [
                                "UNAUTHORIZED", "INVALID_CREDENTIALS", "TOKEN_EXPIRED",
                                "FORBIDDEN", "INSUFFICIENT_ROLE", "VALIDATION_ERROR",
                                "NOT_FOUND", "CONFLICT", "QUOTA_EXCEEDED", "RATE_LIMITED",
                                "ANALYSIS_FAILED", "FILE_TOO_LARGE", "UNSUPPORTED_FORMAT",
                                "PLAN_REQUIRED", "IDEMPOTENCY_CONFLICT", "INTERNAL_ERROR",
                            ],
                        },
                        "message": {"type": "string", "description": "Human-readable error message"},
                    },
                },
                "meta": {
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string", "format": "uuid"},
                        "cursor": {
                            "type": "string",
                            "nullable": True,
                            "description": "Next-page cursor for paginated endpoints",
                        },
                    },
                },
            },
            "required": ["ok"],
        },
        "ErrorResponse": {
            "type": "object",
            "description": "Error response (e.g. 429 rate limited, 401 unauthorized).",
            "properties": {
                "ok": {"type": "boolean", "enum": [False]},
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                    },
                    "required": ["code", "message"],
                },
                "meta": {
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string", "format": "uuid"},
                    },
                },
            },
            "required": ["ok", "error"],
        },
        "ValidationError": {
            "type": "object",
            "description": "Validation error with field-level detail.",
            "properties": {
                "ok": {"type": "boolean", "enum": [False]},
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "enum": ["VALIDATION_ERROR"]},
                        "message": {"type": "string"},
                        "details": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field": {"type": "string"},
                                    "message": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
    }

    # Merge Pydantic schemas
    component_schemas.update(pydantic_schemas)

    spec: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": "Lap Coach Telemetry API",
            "version": "1.7.0",
            "description": (
                "Motorsport telemetry analysis API for kart and car racing.\n\n"
                "## Features\n"
                "- **14-stage analysis pipeline** — CSV upload through scoring and coaching\n"
                "- **Multi-tenant** — workspace isolation with row-level security\n"
                "- **Real-time charts** — speed trace, GPS map, G-G diagram, corner coaching\n"
                "- **Team management** — RBAC with viewer/member/admin/owner roles\n\n"
                "## Authentication\n"
                "All endpoints (except auth and health) require a Bearer JWT token.\n"
                "Obtain tokens via `POST /auth/login` or OAuth flows.\n\n"
                "## Rate Limits\n"
                "| Tier | Base Limit | Window |\n"
                "|------|-----------|--------|\n"
                "| auth | 20 req | 60s |\n"
                "| read | 300 req | 60s |\n"
                "| write | 60 req | 60s |\n"
                "| analyze | 5 req | 3600s |\n"
                "| upload | 10 req | 3600s |\n\n"
                "Limits scale with plan tier (Racer 2x, World-Class 5x, B2B 10x).\n"
                "Rate-limited responses include a `Retry-After` header.\n\n"
                "## Response Format\n"
                "All responses use a standard envelope: `{ok, data, error, meta}`.\n"
                "`meta.request_id` is a UUID for tracing.\n"
                "Paginated endpoints return `meta.cursor` for the next page.\n"
            ),
            "contact": {
                "name": "Lap Coach Support",
                "url": "https://lap-coach.racing/support",
            },
        },
        "servers": [
            {"url": "https://api.lap-coach.racing", "description": "Production"},
            {"url": "http://localhost:5000", "description": "Local development"},
        ],
        "tags": _TAG_DESCRIPTIONS,
        "paths": dict(sorted(paths.items())),
        "components": {
            "schemas": component_schemas,
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": (
                        "JWT access token obtained from POST /auth/login. "
                        "Include as `Authorization: Bearer <token>`. "
                        "Tokens expire after 15 minutes; use POST /auth/refresh to renew."
                    ),
                },
            },
        },
        "security": [{"bearerAuth": []}],
    }
    return spec


# ---------------------------------------------------------------------------
# Swagger UI HTML
# ---------------------------------------------------------------------------

_SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Lap Coach API Documentation</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>
    body { margin: 0; background: #fafafa; }
    .topbar { display: none !important; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: '/api/v1/openapi.json',
      dom_id: '#swagger-ui',
      deepLinking: true,
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: 'BaseLayout',
    });
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_openapi(app: Flask) -> None:
    """Register the OpenAPI JSON endpoint and Swagger UI."""

    @app.route("/api/v1/openapi.json")
    def openapi_spec():
        """Serve the OpenAPI 3.0.3 specification."""
        return jsonify(generate_openapi_spec(app))

    @app.route("/api/v1/docs")
    def openapi_docs():
        """Serve Swagger UI for interactive API exploration."""
        resp = make_response(_SWAGGER_UI_HTML)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return resp
