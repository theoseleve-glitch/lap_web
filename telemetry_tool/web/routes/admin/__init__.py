"""Admin blueprint package — Race Control operational dashboard.

Registers all admin sub-blueprints under /api/v1/admin/*.
The before_request hook loads admin user info and enforces
superadmin + 2FA requirements.
"""
from flask import Blueprint

from .middleware import admin_before_request  # noqa: E402

admin_bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")
admin_bp.before_request(admin_before_request)

# Re-export as `bp` for backward compat with app.py registration
bp = admin_bp

# Import and register legacy endpoints
from .legacy import legacy_bp  # noqa: E402

admin_bp.register_blueprint(legacy_bp)

# Register 2FA auth sub-blueprint
from .auth_admin import bp as auth_admin_bp  # noqa: E402

admin_bp.register_blueprint(auth_admin_bp)

# Register Race Control sub-blueprints
from .health import bp as health_bp  # noqa: E402
from .users import bp as users_bp  # noqa: E402
from .jobs import bp as jobs_bp  # noqa: E402
from .billing import bp as billing_admin_bp  # noqa: E402
from .entitlements import bp as entitlements_bp  # noqa: E402
from .email import bp as email_bp  # noqa: E402
from .security import bp as security_bp  # noqa: E402
from .infra import bp as infra_bp  # noqa: E402

for _sub_bp in [health_bp, users_bp, jobs_bp, billing_admin_bp,
                entitlements_bp, email_bp, security_bp, infra_bp]:
    admin_bp.register_blueprint(_sub_bp)

# Re-export endpoint functions for backward compat with tests/imports
from .legacy import (  # noqa: E402, F401
    list_users,
    get_user_detail,
    suspend_user,
    unsuspend_user,
    create_override,
    impersonate_user,
    list_workspaces,
    list_audit_log,
    billing_overview,
    storage_stats,
)
