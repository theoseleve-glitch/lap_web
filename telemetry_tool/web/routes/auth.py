"""Auth routes -- register, login, refresh, logout, me."""
from flask import Blueprint, request, jsonify, current_app, g

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _get_conn():
    """Get DB connection (PG in SaaS mode)."""
    from web.db import get_db_connection
    return get_db_connection()


def _json_response(data=None, error=None, status=200):
    """Consistent response envelope."""
    if error:
        return jsonify({"ok": False, "error": error, "meta": {}}), status
    return jsonify({"ok": True, "data": data, "meta": {}}), status


@bp.route("/register", methods=["POST"])
def register():
    from auth.service import register_user, login_user, AuthError

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    display_name = (body.get("display_name") or "").strip()

    if not email or not password:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Email and password required"},
            status=400,
        )

    if len(password) < 8:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Password must be at least 8 characters"},
            status=400,
        )

    conn = _get_conn()
    try:
        user = register_user(conn, email, password, display_name or email.split("@")[0])
        # Auto-login after registration
        secret = current_app.config.get("JWT_SECRET", "jwt-dev-secret")
        result = login_user(conn, email, password, secret)
        return _json_response(data=result, status=201)
    except AuthError as e:
        status = 409 if e.code == "CONFLICT" else 400
        return _json_response(error={"code": e.code, "message": str(e)}, status=status)


@bp.route("/login", methods=["POST"])
def login():
    from auth.service import login_user, AuthError

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return _json_response(
            error={"code": "VALIDATION_ERROR", "message": "Email and password required"},
            status=400,
        )

    conn = _get_conn()
    secret = current_app.config.get("JWT_SECRET", "jwt-dev-secret")
    try:
        result = login_user(conn, email, password, secret)
        return _json_response(data=result)
    except AuthError as e:
        return _json_response(
            error={"code": e.code, "message": str(e)}, status=401,
        )


@bp.route("/logout", methods=["POST"])
def logout():
    from auth.service import hash_refresh_token

    body = request.get_json(silent=True) or {}
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        return _json_response(data={"message": "Logged out"})

    conn = _get_conn()
    token_hash = hash_refresh_token(refresh_token)
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = NOW() WHERE token_hash = %(token_hash)s",
        {"token_hash": token_hash},
    )
    conn.commit()
    return _json_response(data={"message": "Logged out"})


# ---------------------------------------------------------------------------
# /api/v1/me — separate blueprint for authenticated API routes
# ---------------------------------------------------------------------------

api_v1_bp = Blueprint("api_v1_auth", __name__, url_prefix="/api/v1")


@api_v1_bp.route("/me", methods=["GET"])
def me():
    """Return current user profile. Requires auth."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return _json_response(
            error={"code": "UNAUTHORIZED", "message": "Authentication required"},
            status=401,
        )

    conn = _get_conn()
    cur = conn.execute(
        "SELECT id, email, display_name, created_at FROM users WHERE id = %(user_id)s",
        {"user_id": user_id},
    )
    user = cur.fetchone()
    if user is None:
        return _json_response(
            error={"code": "NOT_FOUND", "message": "User not found"}, status=404,
        )
    return _json_response(data=dict(user))
