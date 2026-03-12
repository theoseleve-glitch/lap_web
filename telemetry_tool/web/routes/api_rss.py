"""RSS feed — public activity feed for driver sessions.

Endpoint: GET /api/v1/rss/sessions

Returns an RSS 2.0 XML feed of the most recent sessions (public,
non-archived, non-deleted). Useful for coaches or team pages to
embed a live activity stream.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from flask import Blueprint, Response, request

bp = Blueprint("api_rss", __name__)

_MAX_ITEMS = 50


@bp.route("/api/v1/rss/sessions", methods=["GET"])
def rss_sessions():
    """Return RSS 2.0 feed of recent sessions."""
    from web.app import get_db_connection
    from web import models

    conn = get_db_connection()
    try:
        limit = min(int(request.args.get("limit", 20)), _MAX_ITEMS)
    except (ValueError, TypeError):
        limit = 20
    sessions = models.get_sessions(conn, limit=limit, offset=0)

    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    items_xml = []
    for s in sessions:
        sid = s.get("session_id", "")
        title = escape(f"{s.get('driver_name', 'Driver')} at {s.get('track_name', 'Track')}")
        date_str = s.get("session_date", "")
        grade = s.get("grade", "")
        score = s.get("total_score")
        score_str = f" — Score: {score:.1f} ({grade})" if score is not None else ""
        desc = escape(
            f"Session on {date_str}. "
            f"Laps: {s.get('n_laps', '?')}. "
            f"Best lap: {_fmt_time(s.get('best_lap_time_s'))}"
            f"{score_str}"
        )
        pub_date = _to_rfc822(date_str)
        items_xml.append(
            f"    <item>\n"
            f"      <title>{title}</title>\n"
            f"      <description>{desc}</description>\n"
            f"      <guid isPermaLink=\"false\">{escape(sid)}</guid>\n"
            f"      <pubDate>{pub_date}</pubDate>\n"
            f"    </item>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        "    <title>LAP Coach — Recent Sessions</title>\n"
        "    <description>Latest telemetry analysis sessions</description>\n"
        "    <link>https://lap-coach.racing</link>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        + "\n".join(items_xml)
        + "\n  </channel>\n"
        "</rss>"
    )

    return Response(xml, mimetype="application/rss+xml; charset=utf-8")


def _fmt_time(seconds) -> str:
    if seconds is None:
        return "—"
    m, s = divmod(float(seconds), 60)
    return f"{int(m)}:{s:06.3f}"


def _to_rfc822(date_str: str) -> str:
    """Convert YYYY-MM-DD to RFC 822 format."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
