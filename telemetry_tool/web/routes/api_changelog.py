"""API changelog — serves a machine-readable changelog of API changes.

Endpoint: GET /api/v1/changelog

Returns a JSON array of changelog entries, newest first.
Each entry has: version, date, changes[] (with type, description).
"""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("api_changelog", __name__)

# Changelog entries — append new entries at the TOP.
_CHANGELOG = [
    {
        "version": "1.13.0",
        "date": "2026-03-09",
        "changes": [
            {"type": "added", "description": "GET /api/v1/sessions/<id>/export?format=aim|motec — AiM/MoTeC CSV export"},
            {"type": "added", "description": "POST /api/v1/sessions/<id>/archive — session archive/unarchive"},
            {"type": "added", "description": "GET /api/v1/changelog — machine-readable API changelog"},
            {"type": "added", "description": "Chart color themes (Default, Neon, Pastel, High Contrast, Colorblind-safe)"},
            {"type": "added", "description": "Session list column customization with localStorage persistence"},
            {"type": "added", "description": "GG plot time-animation mode (play button)"},
            {"type": "added", "description": "Session grouping by event/weekend view"},
            {"type": "added", "description": "Chart annotation tool (double-click to add notes)"},
            {"type": "added", "description": "Scoring radar chart for session comparison"},
            {"type": "added", "description": "Custom scoring weight configuration (client-side)"},
            {"type": "added", "description": "Critical CSS inlining for faster first paint"},
        ],
    },
    {
        "version": "1.12.0",
        "date": "2026-03-09",
        "changes": [
            {"type": "added", "description": "GET /api/v1/driver/achievements — career milestone badges"},
            {"type": "added", "description": "GET /api/v1/sessions/<id>/corners/per-lap — per-lap corner metrics"},
            {"type": "added", "description": "GET /api/v1/sessions/<id>/speed-trace?avg=1 — average pace line"},
            {"type": "added", "description": "Dead letter queue for failed Celery tasks (migration 037)"},
        ],
    },
    {
        "version": "1.11.0",
        "date": "2026-03-08",
        "changes": [
            {"type": "added", "description": "GET /api/v1/sessions/<id>/endurance — endurance analysis data"},
            {"type": "added", "description": "GET /api/v1/sessions/<id>/channels — available data channel inventory"},
            {"type": "added", "description": "Session soft-delete with DELETE /api/v1/sessions/<id>"},
            {"type": "added", "description": "Domain check constraints (migration 036)"},
        ],
    },
    {
        "version": "1.10.0",
        "date": "2026-03-07",
        "changes": [
            {"type": "added", "description": "Rollup materialized views for dashboard stats (migration 028)"},
            {"type": "added", "description": "Composite indexes for query performance (migration 027)"},
            {"type": "added", "description": "Export templates (migration 026)"},
            {"type": "changed", "description": "Session analysis results now stored as JSONB (migration 025)"},
        ],
    },
    {
        "version": "1.9.0",
        "date": "2026-03-06",
        "changes": [
            {"type": "added", "description": "POST /api/v1/sessions/upload — synchronous upload with pipeline analysis"},
            {"type": "added", "description": "12 data-serving endpoints in sessions_v2 / data_v2"},
            {"type": "removed", "description": "Legacy route files (api_data, analysis, comparisons, etc.)"},
        ],
    },
    {
        "version": "1.8.0",
        "date": "2026-03-04",
        "changes": [
            {"type": "added", "description": "Tiered data retention with enforce_telemetry_retention task"},
            {"type": "added", "description": "Billing profile management with Stripe integration"},
            {"type": "added", "description": "Webhook retry mechanism with exponential backoff"},
        ],
    },
    {
        "version": "1.7.0",
        "date": "2026-03-02",
        "changes": [
            {"type": "added", "description": "Race control data model (flags, penalties, race results)"},
            {"type": "added", "description": "Community features (email verification, social profiles)"},
            {"type": "added", "description": "Account security (2FA columns, login history, API keys)"},
        ],
    },
    {
        "version": "1.6.0",
        "date": "2026-02-28",
        "changes": [
            {"type": "added", "description": "Workspace-based multi-tenancy with RLS policies"},
            {"type": "added", "description": "RBAC with 4 roles and 17 permissions"},
            {"type": "added", "description": "OAuth (Google OIDC + GitHub) authentication"},
            {"type": "added", "description": "JWT auth with refresh token rotation"},
        ],
    },
    {
        "version": "1.0.0",
        "date": "2026-02-20",
        "changes": [
            {"type": "added", "description": "Initial API — session upload, 14-stage pipeline, scoring, reports"},
            {"type": "added", "description": "PostgreSQL backend with Alembic migrations"},
            {"type": "added", "description": "Redis-backed rate limiting and idempotency"},
        ],
    },
]


@bp.route("/api/v1/changelog", methods=["GET"])
def get_changelog():
    """Return the API changelog as JSON."""
    return {"ok": True, "data": {"entries": _CHANGELOG, "total": len(_CHANGELOG)}}
