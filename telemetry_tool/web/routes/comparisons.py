"""Comparison routes — head-to-head session and driver comparisons."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request

from web.db import get_db_connection
from web.models import (
    get_driver_profile,
    get_driver_progression,
    get_driving_style,
    get_gps_trace,
    get_laps_for_session,
    get_score_details,
    get_session_by_id,
)

bp = Blueprint("comparisons", __name__, url_prefix="/compare")


def _session_summary(conn, session_id: str) -> dict | None:
    """Build a rich session dict for comparison."""
    session = get_session_by_id(conn, session_id)
    if session is None:
        return None
    laps = get_laps_for_session(conn, session_id)
    score = get_score_details(conn, session_id)

    best_lap_num = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap_num = lap["lap_number"]
            break

    style = None
    if session.get("driver_id"):
        style = get_driving_style(conn, session["driver_id"], session_id)

    return {
        **session,
        "laps": laps,
        "score": score,
        "best_lap_number": best_lap_num,
        "driving_style": style,
    }


def _driver_summary(conn, driver_id: int) -> dict | None:
    """Build a rich driver dict for head-to-head comparison.

    Returns five core metrics: pace, consistency, avg_score, total_laps,
    progression_rate — plus supporting data for the scorecard UI.
    """
    row = conn.execute(
        "SELECT * FROM drivers WHERE driver_id = :did",
        {"did": driver_id},
    ).fetchone()
    if row is None:
        return None
    driver = dict(row)
    profile = get_driver_profile(conn, driver_id)
    progression = get_driver_progression(conn, driver_id)

    # Session stats
    stats = conn.execute(
        "SELECT COUNT(*) as n_sessions, "
        "COALESCE(SUM(s.n_laps), 0) as total_laps, "
        "MIN(s.best_lap_time_s) as best_time, "
        "AVG(s.total_score) as avg_score, "
        "MAX(s.total_score) as best_score "
        "FROM sessions s WHERE s.driver_id = :did",
        {"did": driver_id},
    ).fetchone()

    # Progression rate: linear slope of total_score over sessions
    progression_rate = None
    scored = [p for p in progression if p.get("total_score") is not None]
    if len(scored) >= 2:
        scores = [p["total_score"] for p in scored]
        n = len(scores)
        x_mean = (n - 1) / 2.0
        y_mean = sum(scores) / n
        num = sum((i - x_mean) * (s - y_mean) for i, s in enumerate(scores))
        den = sum((i - x_mean) ** 2 for i in range(n))
        if den > 0:
            progression_rate = round(num / den, 2)

    # Consistency: use CV% from profile, or compute from recent sessions
    consistency_cv = None
    if profile and profile.get("consistency_rating") is not None:
        consistency_cv = profile["consistency_rating"]
    else:
        # Fallback: compute from last 10 session scores
        recent_scores = [
            p["total_score"] for p in scored[-10:]
            if p.get("total_score") is not None
        ]
        if len(recent_scores) >= 3:
            import statistics
            mean = statistics.mean(recent_scores)
            if mean > 0:
                consistency_cv = round(
                    (statistics.stdev(recent_scores) / mean) * 100, 1
                )

    return {
        **driver,
        "profile": profile,
        "progression": progression,
        "stats": dict(stats) if stats else {},
        "metrics": {
            "pace": dict(stats).get("best_time") if stats else None,
            "consistency_cv": consistency_cv,
            "avg_score": dict(stats).get("avg_score") if stats else None,
            "best_score": dict(stats).get("best_score") if stats else None,
            "total_laps": dict(stats).get("total_laps") or 0 if stats else 0,
            "n_sessions": dict(stats).get("n_sessions") or 0 if stats else 0,
            "progression_rate": progression_rate,
        },
    }


def _build_h2h(drv_a: dict, drv_b: dict) -> list[dict]:
    """Build head-to-head metric rows for the scorecard.

    Each row: {key, label, val_a, val_b, winner, fmt_a, fmt_b, note}.
    winner is 'a', 'b', or 'tie'.
    """
    ma, mb = drv_a["metrics"], drv_b["metrics"]
    rows = []

    def _add(key, label, va, vb, lower_is_better=False, fmt="%.1f", suffix="",
             note=""):
        if va is None and vb is None:
            winner = "tie"
            fa = fb = "—"
        elif va is None:
            winner = "b"
            fa, fb = "—", (fmt % vb) + suffix
        elif vb is None:
            winner = "a"
            fa, fb = (fmt % va) + suffix, "—"
        else:
            fa, fb = (fmt % va) + suffix, (fmt % vb) + suffix
            if lower_is_better:
                winner = "a" if va < vb else ("b" if vb < va else "tie")
            else:
                winner = "a" if va > vb else ("b" if vb > va else "tie")
        rows.append({
            "key": key, "label": label,
            "val_a": va, "val_b": vb,
            "winner": winner, "fmt_a": fa, "fmt_b": fb,
            "note": note,
        })

    _add("pace", "Pace (Best Lap)", ma["pace"], mb["pace"],
         lower_is_better=True, fmt="%.3f", suffix="s",
         note="Personal best lap time")
    _add("consistency", "Consistency (CV%)", ma["consistency_cv"],
         mb["consistency_cv"], lower_is_better=True, fmt="%.1f", suffix="%",
         note="Lower is more consistent")
    _add("avg_score", "Avg Score", ma["avg_score"], mb["avg_score"],
         fmt="%.1f", suffix="/100",
         note="Average session score")
    _add("total_laps", "Total Laps", ma["total_laps"], mb["total_laps"],
         fmt="%.0f",
         note="Track experience")
    _add("progression", "Progression Rate", ma["progression_rate"],
         mb["progression_rate"], fmt="%+.2f", suffix=" pts/session",
         note="Score improvement trend")

    return rows


@bp.route("/")
def compare_form():
    """Show comparison selector form."""
    conn = get_db_connection()
    sessions = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, "
        "d.driver_name, t.track_name "
        "FROM sessions s "
        "JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "ORDER BY s.session_date DESC LIMIT 100"
    ).fetchall()
    sessions = [dict(r) for r in sessions]

    drivers = conn.execute(
        "SELECT d.driver_id, d.driver_name, COUNT(s.session_id) as n_sessions "
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id "
        "GROUP BY d.driver_id ORDER BY d.driver_name"
    ).fetchall()
    drivers = [dict(r) for r in drivers]

    return render_template(
        "compare.html",
        sessions=sessions,
        drivers=drivers,
    )


@bp.route("/sessions")
def compare_sessions():
    """Side-by-side session comparison."""
    conn = get_db_connection()
    sid_a = request.args.get("a", "")
    sid_b = request.args.get("b", "")

    if not sid_a or not sid_b:
        return render_template("compare.html",
                               sessions=[], drivers=[],
                               error="Select two sessions to compare.")

    sum_a = _session_summary(conn, sid_a)
    sum_b = _session_summary(conn, sid_b)

    if sum_a is None or sum_b is None:
        abort(404)

    return render_template(
        "compare_sessions.html",
        session_a=sum_a,
        session_b=sum_b,
    )


@bp.route("/drivers")
def compare_drivers():
    """Side-by-side driver comparison."""
    conn = get_db_connection()
    did_a = request.args.get("a", 0, type=int)
    did_b = request.args.get("b", 0, type=int)

    if not did_a or not did_b:
        return render_template("compare.html",
                               sessions=[], drivers=[],
                               error="Select two drivers to compare.")

    drv_a = _driver_summary(conn, did_a)
    drv_b = _driver_summary(conn, did_b)

    if drv_a is None or drv_b is None:
        abort(404)

    h2h = _build_h2h(drv_a, drv_b)
    wins_a = sum(1 for r in h2h if r["winner"] == "a")
    wins_b = sum(1 for r in h2h if r["winner"] == "b")

    return render_template(
        "compare_drivers.html",
        driver_a=drv_a,
        driver_b=drv_b,
        h2h=h2h,
        wins_a=wins_a,
        wins_b=wins_b,
    )


@bp.route("/api/session_pair")
def session_pair_api():
    """Return speed traces for two sessions (for overlay chart)."""
    conn = get_db_connection()
    sid_a = request.args.get("a", "")
    sid_b = request.args.get("b", "")

    traces = {}
    for sid, label_suffix in [(sid_a, "A"), (sid_b, "B")]:
        if not sid:
            continue
        session = get_session_by_id(conn, sid)
        if session is None:
            continue
        laps = get_laps_for_session(conn, sid)
        best_lap = None
        for lap in laps:
            if lap.get("is_best"):
                best_lap = lap["lap_number"]
                break
        if best_lap:
            gps = get_gps_trace(conn, sid, best_lap)
            if gps:
                traces[sid] = {
                    "label": f"{session.get('session_date', '?')} - {session.get('driver_name', '?')} ({label_suffix})",
                    "distances": gps["distances"],
                    "speeds": gps["speeds"],
                }

    return jsonify({"traces": traces})
