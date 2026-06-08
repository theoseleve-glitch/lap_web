"""Events blueprint — engagement tracking and usage dashboard.

Endpoints:
    POST /api/v1/events             — Receive batched engagement events from frontend
    GET  /api/v1/usage              — Current usage snapshot for workspace
    GET  /api/v1/analytics/engagement — 30-day engagement summary
"""
from __future__ import annotations

import json
import logging

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, api_error, api_response
from web.pii_guard import scrub_properties

logger = logging.getLogger(__name__)

bp = Blueprint("events", __name__, url_prefix="/api/v1")

# Allowed event-type prefixes — events with other prefixes are silently dropped.
_ALLOWED_PREFIXES = (
    "page.",
    "session.",
    "chart.",
    "report.",
    "compare.",
    "corner.",
    "track.",
    "weekend.",
    "search.",
    "export.",
    "limit.",
)

_MAX_BATCH = 50
_MAX_EVENT_TYPE_LEN = 128
_MAX_PATH_LEN = 512


def _get_conn():
    """Return an active DB connection (PG preferred, SQLite fallback)."""
    try:
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    except Exception:
        from web.db import get_db_connection
        return get_db_connection()


def entitlement_snapshot() -> dict:
    """Lazy-import wrapper so circular imports are avoided at module level."""
    from web.middleware.entitlements import entitlement_snapshot as _snap
    return _snap()


def analytics_consent_granted(user_id: int) -> bool:
    """Return True only when user_consent.analytics is explicitly true.

    Default-deny: no row, false row, or any DB error → no consent.
    """
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT analytics FROM user_consent WHERE user_id = %(uid)s",
            {"uid": user_id},
        ).fetchone()
    except Exception:
        logger.warning("Consent lookup failed for user %s — denying", user_id, exc_info=True)
        return False
    if row is None:
        return False
    analytics = row["analytics"] if isinstance(row, dict) else row[0]
    return bool(analytics)


def _insert_events(events: list[dict], user_id: int, workspace_id: int) -> None:
    """Bulk-insert engagement events into app_events table.

    Fails silently — tracking must never break the UX.
    """
    if not events:
        return
    try:
        conn = _get_conn()
        rows = [
            (
                workspace_id,
                user_id,
                ev["event"],
                ev.get("path", ""),
                json.dumps(ev.get("properties") or {}),
            )
            for ev in events
        ]
        conn.executemany(
            """
            INSERT INTO app_events
                (workspace_id, user_id, event_type, path, properties)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            rows,
        )
        conn.commit()
    except Exception:
        logger.warning("Failed to insert events", exc_info=True)
        try:
            from web.metrics import incr_counter
            incr_counter("app_events_insert_failed")
        except Exception:
            pass


@bp.route("/events", methods=["POST"])
def post_events():
    """Receive batched engagement events from the frontend.

    Auth required: g.current_user_id and g.workspace_id must be set.
    Silently drops events with unknown prefixes.
    """
    user_id = getattr(g, "current_user_id", None)
    workspace_id = getattr(g, "workspace_id", None)

    if user_id is None or workspace_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    body = request.get_json(silent=True) or {}
    events = body.get("events")

    if not isinstance(events, list) or len(events) == 0:
        return api_error(ErrorCode.VALIDATION_ERROR, "events must be a non-empty array", status=400)

    if len(events) > _MAX_BATCH:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Batch too large — maximum {_MAX_BATCH} events per request",
            status=400,
        )

    # Validate each event has the required `event` field.
    for ev in events:
        if not isinstance(ev, dict) or not ev.get("event"):
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Each event must have an 'event' string field",
                status=400,
            )

    # Consent gate (default-deny): drop the whole batch if analytics
    # consent is not granted. Never error the UX (HTTP 200).
    if not analytics_consent_granted(user_id):
        return api_response({"accepted": 0, "reason": "no_consent"})

    # Filter + normalise + PII-scrub events.
    accepted: list[dict] = []
    for ev in events:
        event_type = str(ev["event"])
        if not any(event_type.startswith(pfx) for pfx in _ALLOWED_PREFIXES):
            # Silently drop unknown prefixes.
            continue
        accepted.append(
            {
                "event": event_type[:_MAX_EVENT_TYPE_LEN],
                "path": str(ev.get("path", ""))[:_MAX_PATH_LEN],
                "properties": scrub_properties(ev.get("properties")),
            }
        )

    _insert_events(accepted, user_id, workspace_id)
    return api_response({"accepted": len(accepted)})


@bp.route("/usage", methods=["GET"])
def get_usage():
    """Return the current usage snapshot for the authenticated workspace.

    Auth required: g.current_user_id must be set.
    """
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    try:
        snapshot = entitlement_snapshot()
        return api_response(
            {
                "plan_tier": snapshot.get("plan_tier"),
                "analyses_used": snapshot.get("analyses_used", 0),
                "analyses_limit": snapshot.get("analyses_per_month"),
                "max_upload_size_mb": snapshot.get("max_upload_size_mb"),
            }
        )
    except Exception:
        logger.warning("Failed to fetch entitlement snapshot", exc_info=True)
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to load usage data", status=500)


@bp.route("/analytics/engagement", methods=["GET"])
def get_engagement():
    """Return a 30-day engagement summary for the authenticated workspace.

    Auth required: g.workspace_id must be set.
    Fails gracefully — returns zeros on DB errors.
    """
    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    try:
        conn = _get_conn()

        # Top 10 features by event count over the last 30 days.
        top_features_rows = conn.execute(
            """
            SELECT event_type, COUNT(*) AS cnt
            FROM app_events
            WHERE workspace_id = %(wid)s
              AND created_at >= NOW() - INTERVAL '30 days'
            GROUP BY event_type
            ORDER BY cnt DESC
            LIMIT 10
            """,
            {"wid": workspace_id},
        ).fetchall()

        # Distinct active users over the last 30 days.
        active_users_row = conn.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS active_users
            FROM app_events
            WHERE workspace_id = %(wid)s
              AND created_at >= NOW() - INTERVAL '30 days'
            """,
            {"wid": workspace_id},
        ).fetchone()

        # Total events over the last 30 days.
        total_row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM app_events
            WHERE workspace_id = %(wid)s
              AND created_at >= NOW() - INTERVAL '30 days'
            """,
            {"wid": workspace_id},
        ).fetchone()

        def _row_val(row, key: str, default=0):
            if row is None:
                return default
            if isinstance(row, dict):
                return row.get(key, default)
            try:
                return row[key]
            except (KeyError, IndexError, TypeError):
                return default

        top_features = [
            {"event_type": r["event_type"] if isinstance(r, dict) else r[0],
             "count": r["cnt"] if isinstance(r, dict) else r[1]}
            for r in (top_features_rows or [])
        ]

        return api_response(
            {
                "top_features": top_features,
                "active_users": _row_val(active_users_row, "active_users", 0),
                "total_events": _row_val(total_row, "total", 0),
            }
        )
    except Exception:
        logger.warning("Failed to fetch engagement data", exc_info=True)
        return api_response(
            {
                "top_features": [],
                "active_users": 0,
                "total_events": 0,
            }
        )
