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
