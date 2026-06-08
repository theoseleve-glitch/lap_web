# web/routes/consent.py
"""Consent blueprint — server-side consent of record.

POST /api/v1/consent  — upsert user_consent + write an audit_log row.
The webapp's lib/consent.ts posts here whenever a logged-in user changes
their cookie consent, so the backend gate (events ingest) tracks the cookie.
"""
from __future__ import annotations

import json
import logging

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, api_error, api_response

logger = logging.getLogger(__name__)

bp = Blueprint("consent", __name__, url_prefix="/api/v1")


def _get_conn():
    try:
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    except Exception:
        from web.db import get_db_connection
        return get_db_connection()


@bp.route("/consent", methods=["POST"])
def post_consent():
    """Upsert the authenticated user's consent state and audit the change."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    body = request.get_json(silent=True) or {}
    analytics = body.get("analytics")
    marketing = body.get("marketing")
    version = body.get("version")

    if not isinstance(analytics, bool) or not isinstance(marketing, bool):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "analytics and marketing must be booleans",
            details=[{"field": "analytics", "message": "must be a boolean"}],
            status=422,
        )
    if not isinstance(version, int) or isinstance(version, bool):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "version must be an integer",
            details=[{"field": "version", "message": "must be an integer"}],
            status=422,
        )

    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO user_consent (user_id, analytics, marketing, version, updated_at)
        VALUES (%(uid)s, %(a)s, %(m)s, %(v)s, now())
        ON CONFLICT (user_id) DO UPDATE
            SET analytics = EXCLUDED.analytics,
                marketing = EXCLUDED.marketing,
                version = EXCLUDED.version,
                updated_at = now()
        """,
        {"uid": user_id, "a": analytics, "m": marketing, "v": version},
    )
    conn.execute(
        """
        INSERT INTO audit_log (user_id, workspace_id, action, details)
        VALUES (%(uid)s, %(wid)s, %(action)s, %(details)s)
        """,
        {
            "uid": user_id,
            "wid": getattr(g, "workspace_id", None),
            "action": "consent_changed",
            "details": json.dumps(
                {"analytics": analytics, "marketing": marketing, "version": version}
            ),
        },
    )
    conn.commit()

    return api_response({"analytics": analytics, "marketing": marketing, "version": version})
