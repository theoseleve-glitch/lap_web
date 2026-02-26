"""Role-based access control — permission matrix + decorators."""
from __future__ import annotations

from functools import wraps

from flask import g, jsonify

# Role hierarchy: higher index = more permissions.
ROLE_LEVELS = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}

# Permission matrix: minimum role required for each action.
PERMISSIONS = {
    # Viewing
    "view_sessions": "viewer",
    "view_tracks": "viewer",
    "view_drivers": "viewer",
    "view_analytics": "viewer",

    # Creating / uploading
    "upload_csv": "member",
    "create_annotations": "member",
    "create_race_strategy": "member",
    "manage_own_drivers": "member",

    # Editing others' data
    "edit_any_session": "admin",
    "delete_sessions": "admin",
    "delete_tracks": "admin",

    # Team management
    "manage_members": "admin",
    "invite_members": "admin",
    "change_roles": "admin",

    # Destructive / billing
    "delete_workspace": "owner",
    "billing": "owner",
    "gdpr_export": "owner",
}


def has_permission(role: str, action: str) -> bool:
    """Check if a role has permission for a given action."""
    required_role = PERMISSIONS.get(action)
    if required_role is None:
        return False  # Unknown action — deny by default
    return ROLE_LEVELS.get(role, -1) >= ROLE_LEVELS.get(required_role, 999)


def require_role(minimum_role: str):
    """Decorator: endpoint requires at least the given role in the current workspace.

    Expects ``g.workspace_role`` to be set by the tenant middleware.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user_role = getattr(g, "workspace_role", None)
            if user_role is None:
                return jsonify({
                    "ok": False,
                    "error": {"code": "FORBIDDEN", "message": "No workspace role"},
                    "meta": {},
                }), 403

            if ROLE_LEVELS.get(user_role, -1) < ROLE_LEVELS.get(minimum_role, 999):
                return jsonify({
                    "ok": False,
                    "error": {"code": "FORBIDDEN",
                              "message": f"Requires {minimum_role} role or higher"},
                    "meta": {},
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


def require_permission(action: str):
    """Decorator: endpoint requires a specific permission."""
    min_role = PERMISSIONS.get(action, "owner")
    return require_role(min_role)
