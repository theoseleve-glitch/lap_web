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


# ── Config Form (New / Edit / CRUD) ──────────────────────

@bp.route("/new", methods=["GET", "POST"])
def new_race():
    """Create a new race configuration."""
    if request.method == "GET":
        conn = get_db_connection()
        tracks = _rows_to_list(conn.execute("SELECT track_id, track_name FROM tracks ORDER BY track_name").fetchall())
        drivers = _rows_to_list(conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall())
        return render_template("race_strategy/config.html", race=None, race_drivers=[], tracks=tracks, drivers=drivers)

    # POST: save new race
    conn = get_db_connection()
    cur = conn.execute(
        """INSERT INTO race_configs (
            race_name, track_name, team_name, race_duration_s,
            reference_weight_kg, desired_stints, fuel_autonomy_s,
            min_pit_stop_s, pit_speed_kmh, pit_open_s, pit_close_s,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            request.form.get("race_name", "Untitled Race"),
            request.form.get("track_name") or None,
            request.form.get("team_name") or None,
            _parse_duration(request.form.get("race_duration", "3:00")),
            _parse_float(request.form.get("reference_weight_kg")),
            _parse_int(request.form.get("desired_stints"), 4),
            _parse_duration(request.form.get("fuel_autonomy")) if request.form.get("fuel_autonomy") else None,
            _parse_int(request.form.get("min_pit_stop_s"), 60),
            _parse_float(request.form.get("pit_speed_kmh")),
            _parse_duration(request.form.get("pit_open")) if request.form.get("pit_open") else None,
            _parse_duration(request.form.get("pit_close")) if request.form.get("pit_close") else None,
            _parse_float(request.form.get("empty_kart_kg")),
            _parse_float(request.form.get("full_tank_kg")),
            _parse_float(request.form.get("min_total_kart_kg")),
            1 if request.form.get("weigh_on_pit_exit") else 0,
            _parse_duration(request.form.get("qualifying_duration")) if request.form.get("qualifying_duration") else None,
            1 if request.form.get("refuel_after_quali") else 0,
            1 if request.form.get("mandatory_driver_change") else 0,
            1 if request.form.get("refueling_allowed") else 0,
        ),
    )
    race_id = cur.lastrowid

    # Save drivers
    _save_drivers(conn, race_id, request.form)

    conn.commit()
    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))


@bp.route("/<int:race_id>/update", methods=["POST"])
def update_race(race_id: int):
    """Update existing race configuration."""
    conn = get_db_connection()
    race = conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
    if not race:
        abort(404)
    if race["status"] not in ("draft", "ready"):
        abort(400)

    conn.execute(
        """UPDATE race_configs SET
            race_name=?, track_name=?, team_name=?, race_duration_s=?,
            reference_weight_kg=?, desired_stints=?, fuel_autonomy_s=?,
            min_pit_stop_s=?, pit_speed_kmh=?, pit_open_s=?, pit_close_s=?,
            empty_kart_kg=?, full_tank_kg=?, min_total_kart_kg=?,
            weigh_on_pit_exit=?, qualifying_duration_s=?, refuel_after_quali=?,
            mandatory_driver_change=?, refueling_allowed=?,
            updated_at=datetime('now'), status='draft'
        WHERE race_id=?""",
        (
            request.form.get("race_name", "Untitled Race"),
            request.form.get("track_name") or None,
            request.form.get("team_name") or None,
            _parse_duration(request.form.get("race_duration", "3:00")),
            _parse_float(request.form.get("reference_weight_kg")),
            _parse_int(request.form.get("desired_stints"), 4),
            _parse_duration(request.form.get("fuel_autonomy")) if request.form.get("fuel_autonomy") else None,
            _parse_int(request.form.get("min_pit_stop_s"), 60),
            _parse_float(request.form.get("pit_speed_kmh")),
            _parse_duration(request.form.get("pit_open")) if request.form.get("pit_open") else None,
            _parse_duration(request.form.get("pit_close")) if request.form.get("pit_close") else None,
            _parse_float(request.form.get("empty_kart_kg")),
            _parse_float(request.form.get("full_tank_kg")),
            _parse_float(request.form.get("min_total_kart_kg")),
            1 if request.form.get("weigh_on_pit_exit") else 0,
            _parse_duration(request.form.get("qualifying_duration")) if request.form.get("qualifying_duration") else None,
            1 if request.form.get("refuel_after_quali") else 0,
            1 if request.form.get("mandatory_driver_change") else 0,
            1 if request.form.get("refueling_allowed") else 0,
            race_id,
        ),
    )

    # Clear and re-save drivers
    conn.execute("DELETE FROM race_drivers WHERE race_id = ?", (race_id,))
    _save_drivers(conn, race_id, request.form)

    # Clear planned stints (will need re-optimize)
    conn.execute("DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'", (race_id,))
    conn.execute("DELETE FROM race_pit_stops WHERE race_id = ?", (race_id,))

    conn.commit()
    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))


@bp.route("/<int:race_id>/edit")
def edit_race(race_id: int):
    """Edit an existing race configuration."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)
    race_drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    tracks = _rows_to_list(conn.execute("SELECT track_id, track_name FROM tracks ORDER BY track_name").fetchall())
    drivers = _rows_to_list(conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall())
    return render_template("race_strategy/config.html", race=race, race_drivers=race_drivers,
                           tracks=tracks, drivers=drivers)


@bp.route("/<int:race_id>/duplicate", methods=["POST"])
def duplicate(race_id: int):
    """Duplicate a race configuration."""
    conn = get_db_connection()
    race = conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
    if not race:
        abort(404)
    r = dict(race)
    cur = conn.execute(
        """INSERT INTO race_configs (
            race_name, track_name, team_name, race_duration_s,
            reference_weight_kg, desired_stints, fuel_autonomy_s,
            min_pit_stop_s, pit_speed_kmh, pit_open_s, pit_close_s,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft')""",
        (r["race_name"] + " (copy)", r["track_name"], r["team_name"],
         r["race_duration_s"], r["reference_weight_kg"], r["desired_stints"],
         r["fuel_autonomy_s"], r["min_pit_stop_s"], r["pit_speed_kmh"],
         r["pit_open_s"], r["pit_close_s"], r["empty_kart_kg"],
         r["full_tank_kg"], r["min_total_kart_kg"], r["weigh_on_pit_exit"],
         r["qualifying_duration_s"], r["refuel_after_quali"],
         r["mandatory_driver_change"], r["refueling_allowed"]),
    )
    new_id = cur.lastrowid
    # Copy drivers
    old_drivers = conn.execute("SELECT * FROM race_drivers WHERE race_id = ?", (race_id,)).fetchall()
    for d in old_drivers:
        dd = dict(d)
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, min_stint_s, max_stint_s, "
            "min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg) VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id, dd["driver_name"], dd["driver_order"], dd["min_stint_s"],
             dd["max_stint_s"], dd["min_cumulative_s"], dd["max_cumulative_s"],
             dd["min_rest_s"], dd["weight_kg"]),
        )
    conn.commit()
    return redirect(url_for("race_strategy_v2.detail", race_id=new_id))


@bp.route("/<int:race_id>/delete", methods=["POST"])
def delete(race_id: int):
    """Delete a race configuration."""
    conn = get_db_connection()
    conn.execute("DELETE FROM race_configs WHERE race_id = ?", (race_id,))
    conn.commit()
    return redirect(url_for("race_strategy_v2.index"))


# ── Detail Page + Optimizer ───────────────────────────────

@bp.route("/<int:race_id>")
def detail(race_id: int):
    """Race detail: review config, optimize, and go-live."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)
    race_drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name FROM race_stints s "
        "JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = ? ORDER BY s.stint_order", (race_id,)
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY planned_at_s", (race_id,)
    ).fetchall())

    return render_template("race_strategy/detail.html",
                           race=race, drivers=race_drivers,
                           stints=stints, pit_stops=pit_stops)


@bp.route("/<int:race_id>/optimize", methods=["POST"])
def optimize(race_id: int):
    """Run optimizer and save planned stints."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_strategy_v2 import optimize_stints

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())

    result = optimize_stints(race, drivers)

    # Clear existing planned stints
    conn.execute("DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'", (race_id,))
    conn.execute("DELETE FROM race_pit_stops WHERE race_id = ?", (race_id,))

    # Save new stints
    for s in result["stints"]:
        conn.execute(
            """INSERT INTO race_stints (race_id, stint_order, driver_id,
                planned_start_s, planned_end_s, planned_duration_s, ballast_kg, status)
            VALUES (?,?,?,?,?,?,?,'planned')""",
            (race_id, s["stint_order"], s["driver_id"],
             s["planned_start_s"], s["planned_end_s"],
             s["planned_duration_s"], s.get("ballast_kg", 0)),
        )

    # Save pit stops
    for p in result["pit_stops"]:
        conn.execute(
            """INSERT INTO race_pit_stops (race_id, planned_at_s, duration_s,
                driver_change, refueled)
            VALUES (?,?,?,?,?)""",
            (race_id, p["at_s"], p["duration_s"],
             1 if p["driver_change"] else 0, 1 if p["refuel"] else 0),
        )

    # Update status to ready if feasible
    new_status = "ready" if result["feasible"] else "draft"
    conn.execute("UPDATE race_configs SET status = ?, updated_at = datetime('now') WHERE race_id = ?",
                 (new_status, race_id))
    conn.commit()

    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))


# ── Live Dashboard + API ─────────────────────────────────

@bp.route("/<int:race_id>/go-live", methods=["POST"])
def go_live(race_id: int):
    """Start the race — set status to live and record start timestamp."""
    conn = get_db_connection()
    race = conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
    if not race or race["status"] not in ("ready", "draft"):
        abort(400)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "UPDATE race_configs SET status = 'live', race_start_ts = ?, updated_at = datetime('now') WHERE race_id = ?",
        (now, race_id),
    )

    # Set first stint to active
    first_stint = conn.execute(
        "SELECT stint_id FROM race_stints WHERE race_id = ? AND status = 'planned' ORDER BY stint_order LIMIT 1",
        (race_id,),
    ).fetchone()
    if first_stint:
        conn.execute("UPDATE race_stints SET status = 'active', actual_start_s = 0 WHERE stint_id = ?",
                      (first_stint["stint_id"],))

    conn.commit()
    return redirect(url_for("race_strategy_v2.live", race_id=race_id))


@bp.route("/<int:race_id>/live")
def live(race_id: int):
    """Live dashboard page."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)
    return render_template("race_strategy/live.html", race=race)


@bp.route("/<int:race_id>/finish", methods=["POST"])
def finish(race_id: int):
    """End the race."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())

    # Compute final elapsed time for active stint
    elapsed = _compute_elapsed_s(race.get("race_start_ts"))

    # Complete any active stint with actual times
    active = conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? AND status = 'active'", (race_id,)
    ).fetchone()
    if active:
        actual_duration = elapsed - (active["actual_start_s"] or 0)
        conn.execute(
            "UPDATE race_stints SET status = 'completed', actual_end_s = ?, actual_duration_s = ? WHERE stint_id = ?",
            (elapsed, actual_duration, active["stint_id"]),
        )

    conn.execute(
        "UPDATE race_configs SET status = 'finished', updated_at = datetime('now') WHERE race_id = ?",
        (race_id,),
    )
    conn.commit()
    return redirect(url_for("race_strategy_v2.summary", race_id=race_id))


# ── Post-Race Summary ────────────────────────────────────

@bp.route("/<int:race_id>/summary")
def summary(race_id: int):
    """Post-race summary — read-only view of completed race."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)
    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name FROM race_stints s "
        "JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = ? ORDER BY s.stint_order", (race_id,)
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY actual_at_s", (race_id,)
    ).fetchall())

    # Compute per-driver stats
    driver_stats = {}
    for d in drivers:
        d_stints = [s for s in stints if s["driver_id"] == d["id"]]
        total_time = sum(s.get("actual_duration_s") or s.get("planned_duration_s") or 0 for s in d_stints)
        durations = [s.get("actual_duration_s") or s.get("planned_duration_s") or 0 for s in d_stints]
        driver_stats[d["id"]] = {
            "name": d["driver_name"],
            "total_drive_s": total_time,
            "n_stints": len(d_stints),
            "longest_stint_s": max(durations) if durations else 0,
            "shortest_stint_s": min(durations) if durations else 0,
        }

    total_actual_drive = sum(s.get("actual_duration_s") or s.get("planned_duration_s") or 0 for s in stints)
    total_pit = sum(p.get("duration_s") or 0 for p in pit_stops)

    return render_template("race_strategy/summary.html",
                           race=race, drivers=drivers, stints=stints,
                           pit_stops=pit_stops, driver_stats=driver_stats,
                           total_drive_s=total_actual_drive, total_pit_s=total_pit)


# ── API Routes (JSON, for live dashboard polling) ────────

@bp.route("/<int:race_id>/api/state")
def api_state(race_id: int):
    """Full race state for live dashboard polling."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        return jsonify({"error": "not found"}), 404

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name, d.weight_kg as driver_weight_kg FROM race_stints s "
        "JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = ? ORDER BY s.stint_order", (race_id,)
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY planned_at_s", (race_id,)
    ).fetchall())

    active_stint = next((s for s in stints if s["status"] == "active"), None)
    next_stint = next((s for s in stints if s["status"] == "planned"), None)

    # Driver cumulative times
    driver_cumulative = {}
    for s in stints:
        if s["status"] == "completed":
            did = s["driver_id"]
            dur = s.get("actual_duration_s") or s.get("planned_duration_s") or 0
            driver_cumulative[did] = driver_cumulative.get(did, 0) + dur

    return jsonify({
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "active_stint": active_stint,
        "next_stint": next_stint,
        "driver_cumulative": driver_cumulative,
    })


@bp.route("/<int:race_id>/api/stint/end", methods=["POST"])
def api_stint_end(race_id: int):
    """End the current active stint."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())

    active = conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? AND status = 'active'", (race_id,)
    ).fetchone()
    if not active:
        return jsonify({"error": "no active stint"}), 400

    # Compute elapsed since race start
    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    actual_duration = elapsed - (active["actual_start_s"] or 0)

    conn.execute(
        "UPDATE race_stints SET status = 'completed', actual_end_s = ?, actual_duration_s = ? WHERE stint_id = ?",
        (elapsed, actual_duration, active["stint_id"]),
    )

    # Log pit stop
    data = request.get_json(silent=True) or {}
    conn.execute(
        """INSERT INTO race_pit_stops (race_id, stint_id, actual_at_s, driver_change, refueled, notes)
        VALUES (?,?,?,?,?,?)""",
        (race_id, active["stint_id"], elapsed,
         1 if data.get("driver_change", True) else 0,
         1 if data.get("refueled", False) else 0,
         data.get("notes")),
    )

    # Start next stint
    next_stint = conn.execute(
        "SELECT stint_id FROM race_stints WHERE race_id = ? AND status = 'planned' ORDER BY stint_order LIMIT 1",
        (race_id,),
    ).fetchone()
    if next_stint:
        conn.execute(
            "UPDATE race_stints SET status = 'active', actual_start_s = ? WHERE stint_id = ?",
            (elapsed, next_stint["stint_id"]),
        )

    conn.commit()
    return jsonify({"ok": True, "elapsed_s": elapsed})


@bp.route("/<int:race_id>/api/stint/note", methods=["POST"])
def api_stint_note(race_id: int):
    """Update notes on a stint."""
    data = request.get_json(silent=True) or {}
    stint_id = data.get("stint_id")
    notes = data.get("notes", "")
    conn = get_db_connection()
    conn.execute("UPDATE race_stints SET notes = ? WHERE stint_id = ? AND race_id = ?",
                 (notes, stint_id, race_id))
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/<int:race_id>/api/reoptimize", methods=["POST"])
def api_reoptimize(race_id: int):
    """Re-optimize remaining stints mid-race."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_strategy_v2 import reoptimize_remaining

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    completed = _rows_to_list(conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? AND status = 'completed' ORDER BY stint_order",
        (race_id,),
    ).fetchall())

    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    result = reoptimize_remaining(race, drivers, completed, elapsed)

    # Replace planned stints
    conn.execute("DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'", (race_id,))
    for s in result["stints"]:
        conn.execute(
            """INSERT INTO race_stints (race_id, stint_order, driver_id,
                planned_start_s, planned_end_s, planned_duration_s, ballast_kg, status)
            VALUES (?,?,?,?,?,?,?,'planned')""",
            (race_id, s["stint_order"], s["driver_id"],
             s["planned_start_s"], s["planned_end_s"],
             s["planned_duration_s"], s.get("ballast_kg", 0)),
        )
    conn.commit()

    return jsonify({"ok": True, "result": result})


# ── Helpers ──────────────────────────────────────

def _compute_elapsed_s(race_start_ts: str | None) -> int:
    """Compute seconds elapsed since race start."""
    if not race_start_ts:
        return 0
    from datetime import datetime, timezone
    try:
        start = datetime.fromisoformat(race_start_ts)
        now = datetime.now(timezone.utc)
        return max(0, int((now - start).total_seconds()))
    except (ValueError, TypeError):
        return 0


def _parse_duration(val: str | None) -> int:
    """Parse 'H:MM' or 'H:MM:SS' or plain minutes to seconds."""
    if not val:
        return 0
    val = val.strip()
    parts = val.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 3600 + int(parts[1]) * 60
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            return int(float(val) * 60)  # Plain number = minutes
    except (ValueError, TypeError):
        return 0


def _parse_duration_mmss(val: str | None) -> int | None:
    """Parse 'MM:SS' to seconds."""
    if not val or not val.strip():
        return None
    parts = val.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(val)
    except (ValueError, TypeError):
        return None


def _parse_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_int(val: str | None, default: int = 0) -> int:
    if not val:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _save_drivers(conn, race_id: int, form):
    """Save drivers from form data. Expects driver_name_N, driver_order_N, etc."""
    i = 0
    while True:
        name = form.get(f"driver_name_{i}")
        if name is None:
            break
        if not name.strip():
            i += 1
            continue
        conn.execute(
            """INSERT INTO race_drivers (
                race_id, driver_name, driver_order, min_stint_s, max_stint_s,
                min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                race_id,
                name.strip(),
                _parse_int(form.get(f"driver_order_{i}"), i + 1),
                _parse_duration_mmss(form.get(f"driver_min_stint_{i}")),
                _parse_duration_mmss(form.get(f"driver_max_stint_{i}")),
                _parse_duration_mmss(form.get(f"driver_min_cumulative_{i}")),
                _parse_duration_mmss(form.get(f"driver_max_cumulative_{i}")),
                _parse_duration_mmss(form.get(f"driver_min_rest_{i}")) or 0,
                _parse_float(form.get(f"driver_weight_{i}")),
            ),
        )
        i += 1
