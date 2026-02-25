"""Endurance race strategy blueprint — config, live dashboard, summary."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from web.db import get_db_connection

logger = logging.getLogger(__name__)

bp = Blueprint(
    "race_strategy_v2",
    __name__,
    url_prefix="/race-strategy",
)


def _row_to_dict(row) -> dict:
    """Convert sqlite3.Row to dict."""
    if row is None:
        return {}
    return dict(row)


def _rows_to_list(rows) -> list[dict]:
    """Convert list of sqlite3.Row to list of dict."""
    return [dict(r) for r in rows]


@bp.route("/")
def index():
    """List all saved races, with any live race promoted to hero card."""
    conn = get_db_connection()
    races = _rows_to_list(conn.execute(
        "SELECT * FROM race_configs ORDER BY "
        "CASE status WHEN 'live' THEN 0 ELSE 1 END, created_at DESC"
    ).fetchall())

    live_race = None
    for r in races:
        if r["status"] == "live":
            live_race = r
            break

    return render_template(
        "race_strategy/index.html",
        races=races,
        live_race=live_race,
    )
