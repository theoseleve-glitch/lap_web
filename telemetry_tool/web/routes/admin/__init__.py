"""Admin blueprint package — Race Control operational dashboard.

Registers all admin sub-blueprints under /api/v1/admin/*.
The before_request hook loads admin user info and enforces
superadmin + 2FA requirements.
"""
from flask import Blueprint

from .middleware import admin_before_request  # noqa: E402

admin_bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")
admin_bp.before_request(admin_before_request)


@admin_bp.after_request
def _no_cache_admin(response):
    """Prevent caching of admin responses — sensitive operational data."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response

# Re-export as `bp` for backward compat with app.py registration
bp = admin_bp

# Import and register legacy endpoints
from .legacy import legacy_bp  # noqa: E402

admin_bp.register_blueprint(legacy_bp)

# Register 2FA auth sub-blueprint
from .auth_admin import bp as auth_admin_bp  # noqa: E402

admin_bp.register_blueprint(auth_admin_bp)

from .billing import bp as billing_admin_bp  # noqa: E402
from .email import bp as email_bp  # noqa: E402
from .entitlements import bp as entitlements_bp  # noqa: E402

# Register Race Control sub-blueprints
from .health import bp as health_bp  # noqa: E402
from .infra import bp as infra_bp  # noqa: E402
from .jobs import bp as jobs_bp  # noqa: E402
from .monitoring import bp as monitoring_bp  # noqa: E402
from .security import bp as security_bp  # noqa: E402
from .training import bp as training_bp  # noqa: E402
from .users import bp as users_bp  # noqa: E402
from .analytics import bp as analytics_bp  # noqa: E402
from .user_detail import bp as user_detail_bp  # noqa: E402
from .overview import bp as overview_bp  # noqa: E402

for _sub_bp in [health_bp, users_bp, jobs_bp, billing_admin_bp,
                entitlements_bp, email_bp, security_bp, infra_bp,
                training_bp, monitoring_bp, analytics_bp, user_detail_bp,
                overview_bp]:
    admin_bp.register_blueprint(_sub_bp)

# Re-export endpoint functions for backward compat with tests/imports
from .legacy import (  # noqa: E402, F401
    billing_overview,
    create_override,
    get_user_detail,
    impersonate_user,
    list_audit_log,
    list_users,
    list_workspaces,
    storage_stats,
    suspend_user,
    unsuspend_user,
)
