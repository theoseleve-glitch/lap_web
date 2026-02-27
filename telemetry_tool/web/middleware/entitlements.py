"""Entitlement middleware/decorators for quota and feature enforcement."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps

from flask import current_app, g, request

from auth.entitlements import get_user_entitlements, get_plan_entitlements
from web.api_utils import ErrorCode, api_error


def _get_conn():
    if current_app.config.get("USE_PG"):
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    from web.db import get_db_connection
    return get_db_connection()


def _identity() -> tuple[int | None, int | None]:
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        user_id = getattr(g, "user_id", None)
    workspace_id = getattr(g, "workspace_id", None)
    return user_id, workspace_id


def entitlement_snapshot() -> dict:
    """Resolve entitlement snapshot from request context."""
    user_id, workspace_id = _identity()
    if workspace_id is None:
        workspace_id = current_app.config.get("DEFAULT_WORKSPACE_ID", 1)
    conn = _get_conn()
    return get_user_entitlements(conn, user_id=user_id, workspace_id=workspace_id)


def require_api_access(fn):
    """Deny access when current tier does not include API access."""

    @wraps(fn)
    def _wrapped(*args, **kwargs):
        snapshot = entitlement_snapshot()
        if not snapshot.get("api_access", False):
            return api_error(
                ErrorCode.FORBIDDEN,
                "API access is not enabled for your tier.",
                status=403,
            )
        g.entitlement_snapshot = snapshot
        return fn(*args, **kwargs)

    return _wrapped


def require_feature(feature_name: str):
    """Gate a route behind a boolean feature flag from entitlement snapshot."""

    def _decorator(fn):
        @wraps(fn)
        def _wrapped(*args, **kwargs):
            snapshot = entitlement_snapshot()
            if not snapshot.get(feature_name, False):
                return api_error(
                    ErrorCode.FORBIDDEN,
                    f"Feature '{feature_name}' is not enabled for your tier.",
                    status=403,
                )
            g.entitlement_snapshot = snapshot
            return fn(*args, **kwargs)

        return _wrapped

    return _decorator


def require_report_quota(fn):
    """Check monthly report/export quota before allowing report generation."""

    @wraps(fn)
    def _wrapped(*args, **kwargs):
        snapshot = entitlement_snapshot()
        user_id, _ = _identity()
        conn = _get_conn()

        reports_used = 0
        if user_id is not None:
            month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM data_exports "
                "WHERE user_id = %(uid)s AND created_at >= %(month_start)s",
                {"uid": user_id, "month_start": month_start},
            ).fetchone()
            reports_used = int((dict(row) if row else {"cnt": 0}).get("cnt", 0))

        policy = get_plan_entitlements(snapshot.get("plan_tier", "demo"))
        limit = policy.get("reports_per_month", 0)
        remaining = max(0, limit - reports_used) if limit != -1 else 999
        if remaining <= 0:
            return api_error(
                ErrorCode.QUOTA_EXCEEDED,
                "Monthly report quota exceeded.",
                status=429,
            )

        snapshot["reports_used"] = reports_used
        snapshot["reports_remaining"] = remaining
        g.entitlement_snapshot = snapshot
        return fn(*args, **kwargs)

    return _wrapped


def require_upload_size(max_field_name: str = "file"):
    """Check upload request size against current entitlement tier limits."""

    def _decorator(fn):
        @wraps(fn)
        def _wrapped(*args, **kwargs):
            snapshot = entitlement_snapshot()
            max_bytes = int(snapshot.get("max_upload_size_mb", 0) * 1024 * 1024)

            uploaded = request.files.get(max_field_name)
            if uploaded and getattr(uploaded, "stream", None) is not None:
                stream = uploaded.stream
                pos = stream.tell()
                stream.seek(0, 2)
                actual_size = int(stream.tell())
                stream.seek(pos)
            elif uploaded and hasattr(uploaded, "content_length") and uploaded.content_length:
                actual_size = int(uploaded.content_length)
            else:
                actual_size = int(request.content_length or 0)

            if max_bytes > 0 and actual_size > max_bytes:
                return api_error(
                    ErrorCode.FILE_TOO_LARGE,
                    f"Upload exceeds your tier limit of {snapshot['max_upload_size_mb']} MB.",
                    status=413,
                )

            g.entitlement_snapshot = snapshot
            return fn(*args, **kwargs)

        return _wrapped

    return _decorator
