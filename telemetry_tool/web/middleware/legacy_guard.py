"""Legacy route guard — blocks Jinja2 HTML routes in production.

When AUTH_REQUIRED is True (production SaaS), legacy routes that bypass
multi-tenant middleware are blocked with 404. These routes are only used
by the desktop/CLI Jinja2 frontend, not the Next.js production UI.
"""
from flask import request

from web.api_utils import ErrorCode, api_error

# Routes used ONLY by the legacy Jinja2 frontend.
# These bypass tenant middleware and RLS — must not be exposed in production.
_LEGACY_PREFIXES = (
    "/sessions",
    "/drivers",
    "/compare",
    "/visualize",
    "/analysis",
    "/dashboard",
    "/weekends",
    "/race-strategy",
    "/annotations",
    "/predictions",
    "/dev-plans",
    "/karts",
    "/analytics",
    "/leaderboard",
    "/tracks",
    # web/routes/ingest.py (old streaming-ingest SSE/polling blueprint) is
    # fully superseded by the workspace-scoped /api/v1/jobs blueprint
    # (web/routes/jobs.py + tasks/job_registry.py) and has no known caller.
    # It was reachable with no auth at all (outside /api/v1/, see
    # web/middleware/auth.py) and its JobStore queried ingestion_jobs with
    # no workspace predicate — a confirmed cross-tenant IDOR. Blocked
    # outright in production rather than kept alive as a second, harder to
    # audit code path. auth/tenant middleware + JobStore now scope it too
    # (defense in depth) in case this guard is ever relaxed.
    "/api/ingest",
)


def init_legacy_guard(app):
    """Register before_request hook that blocks legacy routes in prod.

    Only active when AUTH_REQUIRED is truthy in app config.
    Desktop/CLI mode (AUTH_REQUIRED=False) is unaffected.
    """
    if not app.config.get("AUTH_REQUIRED"):
        return

    @app.before_request
    def _block_legacy_routes():
        path = request.path
        if any(path.startswith(prefix) for prefix in _LEGACY_PREFIXES):
            return api_error(ErrorCode.NOT_FOUND, "Not found", status=404)
