"""Blueprint for advanced analytics pages: weather, trends, rival comparison."""

from __future__ import annotations

import logging
from flask import Blueprint, render_template, request
from web.db import get_db_connection

logger = logging.getLogger(__name__)

bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@bp.route("/")
def analytics_index():
    """Analytics landing page — lists all available analytics tools."""
    return render_template(
        "analytics_index.html",
        tools=[
            {"name": "Weather Correlation", "url": "/analytics/weather",
             "desc": "Analyse how weather conditions affect lap times"},
            {"name": "Pace Trends", "url": "/analytics/trends",
             "desc": "Track pace improvement over multiple sessions"},
            {"name": "Live Meteo", "url": "/analytics/meteo",
             "desc": "Current & forecast weather at track locations"},
            {"name": "Race Strategy", "url": "/predictions/race-strategy",
             "desc": "Pit stop and tire strategy planner with fuel model"},
            {"name": "Weight Simulator", "url": "/predictions/weight-simulator",
             "desc": "Simulate weight change impact on lap times"},
        ],
    )


@bp.route("/weather")
def weather_analysis():
    """Weather correlation analysis page."""
    conn = get_db_connection()
    # Get tracks for dropdown
    tracks = conn.execute(
        "SELECT track_id, track_name FROM tracks ORDER BY track_name"
    ).fetchall()
    track_id = request.args.get("track_id")
    driver_id = request.args.get("driver_id", type=int)

    # Get drivers for dropdown
    drivers = conn.execute(
        "SELECT driver_id, driver_name FROM drivers ORDER BY driver_name"
    ).fetchall()

    return render_template(
        "weather_analysis.html",
        tracks=[dict(t) for t in tracks],
        drivers=[dict(d) for d in drivers],
        selected_track=track_id,
        selected_driver=driver_id,
    )


@bp.route("/trends")
def trend_analysis():
    """Multi-session trend analysis page."""
    conn = get_db_connection()
    drivers = conn.execute(
        "SELECT driver_id, driver_name FROM drivers ORDER BY driver_name"
    ).fetchall()
    tracks = conn.execute(
        "SELECT track_id, track_name FROM tracks ORDER BY track_name"
    ).fetchall()

    driver_id = request.args.get("driver_id", type=int)
    track_id = request.args.get("track_id")

    return render_template(
        "trend_analysis.html",
        drivers=[dict(d) for d in drivers],
        tracks=[dict(t) for t in tracks],
        selected_driver=driver_id,
        selected_track=track_id,
    )


# Rival comparison removed per audit
# @bp.route("/rivals")
# def rival_comparison(): ...


@bp.route("/meteo")
def meteo_page():
    """Live and historical meteo dashboard."""
    conn = get_db_connection()
    drivers = conn.execute(
        "SELECT driver_id, driver_name FROM drivers ORDER BY driver_name"
    ).fetchall()
    return render_template("meteo_dashboard.html", drivers=[dict(d) for d in drivers])


