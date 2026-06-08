# web/routes/marketing.py
"""Marketing collector blueprint — anonymous, public event ingest.

POST /api/v1/marketing-events  (PUBLIC — see auth allowlist; CORS via the
global allowlist). Mirrors the marketing site's conversion + pageview events
into the global, RLS-free `marketing_events` table.

HARD anonymity: the server NEVER persists the client IP, User-Agent, or any
identifier. Only (event_type, path, PII-scrubbed properties) are stored.
"""
from __future__ import annotations

import json
import logging

from flask import Blueprint, request

from web.api_utils import ErrorCode, api_error, api_response
from web.pii_guard import scrub_properties
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("marketing", __name__, url_prefix="/api/v1")

_MAX_BATCH = 50
_MAX_EVENT_TYPE_LEN = 128
_MAX_PATH_LEN = 512


def _get_conn():
    try:
        from web.db_pg import get_pg_connection
        return get_pg_connection()
    except Exception:
        from web.db import get_db_connection
        return get_db_connection()


def _insert_marketing_events(rows: list[dict]) -> None:
    """Insert anonymous rows into marketing_events. Never persists identity.

    Fails soft — a dropped analytics row must never surface to the public
    caller — but records a counter so silent loss is observable.
    """
    if not rows:
        return
    try:
        conn = _get_conn()
        params = [
            (r["event"], r["path"], json.dumps(r["properties"]))
            for r in rows
        ]
        conn.executemany(
            """
            INSERT INTO marketing_events (event_type, path, properties)
            VALUES (%s, %s, %s::jsonb)
            """,
            params,
        )
        conn.commit()
    except Exception:
        logger.warning("Failed to insert marketing events", exc_info=True)
        try:
            from web.metrics import incr_counter
            incr_counter("marketing_events_insert_failed")
        except Exception:
            pass


@bp.route("/marketing-events", methods=["POST"])
@rate_limit(tier="marketing")
def post_marketing_events():
    """Receive a batch of anonymous marketing events."""
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

    rows: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict) or not ev.get("event"):
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Each event must have an 'event' string field",
                status=400,
            )
        rows.append({
            "event": str(ev["event"])[:_MAX_EVENT_TYPE_LEN],
            "path": str(ev.get("path", ""))[:_MAX_PATH_LEN],
            "properties": scrub_properties(ev.get("properties")),
        })

    _insert_marketing_events(rows)
    return api_response({"accepted": len(rows)})
