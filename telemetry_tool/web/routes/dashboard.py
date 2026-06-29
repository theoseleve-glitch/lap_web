"""API service root.

In the SaaS the UI is the Next.js webapp and this Flask app is the JSON API.
The legacy server-rendered dashboard referenced stale url_for endpoints
(analysis.analyze_form, sessions.session_list) and 500'd on every GET / hit
(monitors flagged it as a 5xx spike). The root now returns a 200 status payload.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    """Service root - 200 JSON, no template render."""
    return jsonify({"service": "lap-api", "status": "ok"})
