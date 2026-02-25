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


# ── Import / Export ──────────────────────────────

@bp.route("/<int:race_id>/export")
def export(race_id: int):
    """Export race as JSON file download."""
    import re

    from flask import Response

    conn = get_db_connection()
    race = conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
    if not race:
        abort(404)

    data = _build_export_dict(conn, race_id)
    payload = json.dumps(data, indent=2, default=str)

    slug = re.sub(r'[^a-z0-9]+', '-', race["race_name"].lower()).strip('-')
    date = (race["created_at"] or "")[:10]
    filename = f"race-{slug}-{date}.json"

    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/import", methods=["POST"])
def import_race():
    """Import race from JSON file upload."""
    from flask import flash

    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("race_strategy_v2.index"))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        flash("Invalid JSON file.", "error")
        return redirect(url_for("race_strategy_v2.index"))

    conn = get_db_connection()
    try:
        race_id = _import_race_from_dict(conn, data)
        conn.commit()
    except ValueError as e:
        flash(f"Import failed: {e}", "error")
        return redirect(url_for("race_strategy_v2.index"))

    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))


def _build_export_dict(conn, race_id: int) -> dict:
    """Build the full export dictionary for a race."""
    from datetime import datetime, timezone

    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? ORDER BY stint_order", (race_id,)
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY pit_id", (race_id,)
    ).fetchall())

    messages = _rows_to_list(conn.execute(
        "SELECT * FROM race_messages WHERE race_id = ? ORDER BY msg_id", (race_id,)
    ).fetchall())

    windows = _rows_to_list(conn.execute(
        "SELECT * FROM race_windows WHERE race_id = ? ORDER BY window_order", (race_id,)
    ).fetchall())

    return {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "messages": messages,
        "windows": windows,
    }


def _import_race_from_dict(conn, data: dict) -> int:
    """Import a race from an export dict. Returns new race_id."""
    race = data.get("race", {})
    if not race.get("race_name"):
        raise ValueError("Missing required field: race_name")
    if not race.get("race_duration_s"):
        raise ValueError("Missing required field: race_duration_s")

    cur = conn.execute(
        """INSERT INTO race_configs (
            race_name, track_name, team_name, race_duration_s,
            reference_weight_kg, desired_stints, fuel_autonomy_s,
            min_pit_stop_s, pit_speed_kmh, quick_pit_stop_s, pit_open_s, pit_close_s,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft')""",
        (
            race.get("race_name"), race.get("track_name"), race.get("team_name"),
            race["race_duration_s"], race.get("reference_weight_kg"),
            race.get("desired_stints", 4), race.get("fuel_autonomy_s"),
            race.get("min_pit_stop_s", 60), race.get("pit_speed_kmh"),
            race.get("quick_pit_stop_s"),
            race.get("pit_open_s"), race.get("pit_close_s"),
            race.get("empty_kart_kg"), race.get("full_tank_kg"),
            race.get("min_total_kart_kg"), race.get("weigh_on_pit_exit", 0),
            race.get("qualifying_duration_s"), race.get("refuel_after_quali", 0),
            race.get("mandatory_driver_change", 1), race.get("refueling_allowed", 1),
        ),
    )
    new_race_id = cur.lastrowid

    # Insert drivers, building old_id -> new_id map
    id_map = {}
    for d in data.get("drivers", []):
        old_id = d.get("id")
        cur = conn.execute(
            """INSERT INTO race_drivers (
                race_id, driver_name, driver_order, min_stint_s, max_stint_s,
                min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg, com_channel, color_hex
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_race_id, d["driver_name"], d.get("driver_order", 1),
                d.get("min_stint_s"), d.get("max_stint_s"),
                d.get("min_cumulative_s"), d.get("max_cumulative_s"),
                d.get("min_rest_s", 0), d.get("weight_kg"), d.get("com_channel"),
                d.get("color_hex"),
            ),
        )
        if old_id is not None:
            id_map[old_id] = cur.lastrowid

    # Insert stints with remapped driver IDs
    for s in data.get("stints", []):
        old_driver_id = s.get("driver_id")
        new_driver_id = id_map.get(old_driver_id, old_driver_id)
        conn.execute(
            """INSERT INTO race_stints (
                race_id, stint_order, driver_id, planned_start_s, planned_end_s,
                planned_duration_s, actual_start_s, actual_end_s, actual_duration_s,
                ballast_kg, notes, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_race_id, s.get("stint_order", 1), new_driver_id,
                s.get("planned_start_s"), s.get("planned_end_s"),
                s.get("planned_duration_s"), s.get("actual_start_s"),
                s.get("actual_end_s"), s.get("actual_duration_s"),
                s.get("ballast_kg", 0), s.get("notes"), s.get("status", "planned"),
            ),
        )

    # Insert pit stops
    for p in data.get("pit_stops", []):
        conn.execute(
            """INSERT INTO race_pit_stops (
                race_id, planned_at_s, actual_at_s, duration_s,
                driver_change, refueled, fuel_added_kg, ballast_changed, notes
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                new_race_id, p.get("planned_at_s"), p.get("actual_at_s"),
                p.get("duration_s"), p.get("driver_change", 1),
                p.get("refueled", 0), p.get("fuel_added_kg"),
                p.get("ballast_changed", 0), p.get("notes"),
            ),
        )

    # Insert messages
    for m in data.get("messages", []):
        conn.execute(
            "INSERT INTO race_messages (race_id, author, message, category) VALUES (?,?,?,?)",
            (new_race_id, m.get("author", ""), m.get("message", ""), m.get("category", "general")),
        )

    # Import windows
    for w in data.get("windows", []):
        conn.execute(
            "INSERT INTO race_windows (race_id, window_type, label, start_s, end_s, "
            "refuel_allowed, driver_change_allowed, window_order) VALUES (?,?,?,?,?,?,?,?)",
            (
                new_race_id, w.get("window_type", "pitlane"), w.get("label"),
                w.get("start_s", 0), w.get("end_s", 0),
                w.get("refuel_allowed", 1), w.get("driver_change_allowed", 1),
                w.get("window_order", 1),
            ),
        )

    return new_race_id


# ── Config Form (New / Edit / CRUD) ──────────────────────

@bp.route("/new", methods=["GET", "POST"])
def new_race():
    """Create a new race configuration."""
    if request.method == "GET":
        conn = get_db_connection()
        tracks = _rows_to_list(conn.execute("SELECT track_id, track_name FROM tracks ORDER BY track_name").fetchall())
        drivers = _rows_to_list(conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall())
        return render_template("race_strategy/config.html", race=None, race_drivers=[], race_windows=[],
                               tracks=tracks, drivers=drivers)

    # POST: save new race
    conn = get_db_connection()
    cur = conn.execute(
        """INSERT INTO race_configs (
            race_name, track_name, team_name, race_duration_s,
            reference_weight_kg, desired_stints, fuel_autonomy_s,
            min_pit_stop_s, pit_speed_kmh, quick_pit_stop_s, pit_open_s, pit_close_s,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            _parse_int(request.form.get("quick_pit_stop_s"), None),
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

    # Save drivers and windows
    _save_drivers(conn, race_id, request.form)
    _save_windows(conn, race_id, request.form)

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
            min_pit_stop_s=?, pit_speed_kmh=?, quick_pit_stop_s=?, pit_open_s=?, pit_close_s=?,
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
            _parse_int(request.form.get("quick_pit_stop_s"), None),
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

    # Clear and re-save drivers + windows
    conn.execute("DELETE FROM race_drivers WHERE race_id = ?", (race_id,))
    _save_drivers(conn, race_id, request.form)
    _save_windows(conn, race_id, request.form)

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
    race_windows = _rows_to_list(conn.execute(
        "SELECT * FROM race_windows WHERE race_id = ? ORDER BY window_order", (race_id,)
    ).fetchall())
    tracks = _rows_to_list(conn.execute("SELECT track_id, track_name FROM tracks ORDER BY track_name").fetchall())
    drivers = _rows_to_list(conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall())
    return render_template("race_strategy/config.html", race=race, race_drivers=race_drivers,
                           race_windows=race_windows, tracks=tracks, drivers=drivers)


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
            min_pit_stop_s, pit_speed_kmh, quick_pit_stop_s, pit_open_s, pit_close_s,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft')""",
        (r["race_name"] + " (copy)", r["track_name"], r["team_name"],
         r["race_duration_s"], r["reference_weight_kg"], r["desired_stints"],
         r["fuel_autonomy_s"], r["min_pit_stop_s"], r["pit_speed_kmh"],
         r.get("quick_pit_stop_s"), r["pit_open_s"], r["pit_close_s"],
         r["empty_kart_kg"], r["full_tank_kg"], r["min_total_kart_kg"],
         r["weigh_on_pit_exit"], r["qualifying_duration_s"],
         r["refuel_after_quali"], r["mandatory_driver_change"],
         r["refueling_allowed"]),
    )
    new_id = cur.lastrowid
    # Copy drivers
    old_drivers = conn.execute("SELECT * FROM race_drivers WHERE race_id = ?", (race_id,)).fetchall()
    for d in old_drivers:
        dd = dict(d)
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, min_stint_s, max_stint_s, "
            "min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg, com_channel) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (new_id, dd["driver_name"], dd["driver_order"], dd["min_stint_s"],
             dd["max_stint_s"], dd["min_cumulative_s"], dd["max_cumulative_s"],
             dd["min_rest_s"], dd["weight_kg"], dd.get("com_channel")),
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
    """Run optimizer and save planned stints with fuel-aware ballast."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_strategy_v2 import optimize_stints
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())

    result = optimize_stints(race, drivers)

    # Wrap in engine for fuel/ballast cascade
    engine = RaceStateEngine(race, drivers, result["stints"], result["pit_stops"])
    engine.save(conn, race_id)

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
    messages = _rows_to_list(conn.execute(
        "SELECT * FROM race_messages WHERE race_id = ? ORDER BY msg_id", (race_id,)
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

    # Engine-computed real-time data (fuel, ballast, fuel model)
    engine_data = {}
    try:
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
        from race_state_engine import RaceStateEngine
        from race_intelligence import analyze_race
        engine = RaceStateEngine.load(conn, race_id)
        elapsed = _compute_elapsed_s(race.get("race_start_ts"))
        snapshot = engine.snapshot()
        engine_data = {
            "current_fuel_kg": round(engine.current_fuel_kg(elapsed), 4),
            "current_ballast": engine.current_ballast(elapsed),
            "fuel_model": snapshot["fuel_model"],
            "window_status": engine.window_status(elapsed),
            "neutralizations": snapshot.get("neutralizations", []),
            "is_neutralized": snapshot.get("is_neutralized", False),
        }
        # Intelligence analysis
        try:
            rivals_db = _rows_to_list(conn.execute(
                "SELECT * FROM race_rivals WHERE race_id = ? ORDER BY id", (race_id,)
            ).fetchall())
            rival_events_db = _rows_to_list(conn.execute(
                "SELECT * FROM race_rival_events WHERE race_id = ? ORDER BY at_s", (race_id,)
            ).fetchall())
            fm = snapshot["fuel_model"]
            engine_data["intelligence"] = analyze_race(
                race_duration_s=race.get("race_duration_s", 0),
                elapsed_s=elapsed,
                race_start_ts=race.get("race_start_ts"),
                stints=stints,
                active_stint=active_stint,
                drivers=drivers,
                neutralizations=snapshot.get("neutralizations", []),
                current_fuel_kg=engine.current_fuel_kg(elapsed),
                burn_rate_kgs=fm.get("burn_rate_kgs", 0) if isinstance(fm, dict) else getattr(fm, "burn_rate_kgs", 0),
                active_stint_end_s=active_stint.get("planned_end_s", 0) if active_stint else 0,
                next_planned_pit_s=next_stint.get("planned_start_s") if next_stint else None,
                rivals=rivals_db,
                rival_events=rival_events_db,
            )
        except Exception as exc:
            logger.debug("Intelligence analysis failed for race %d: %s", race_id, exc)
            engine_data["intelligence"] = {}
    except Exception:
        logger.debug("Engine load failed for race %d, returning basic state", race_id)

    return jsonify({
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "messages": messages,
        "active_stint": active_stint,
        "next_stint": next_stint,
        "driver_cumulative": driver_cumulative,
        **engine_data,
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
    from race_state_engine import RaceStateEngine

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

    # Clear planned stints only
    conn.execute("DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'", (race_id,))

    # Wrap in engine for fuel/ballast cascade on new stints
    all_stints = completed + result["stints"]
    engine = RaceStateEngine(race, drivers, all_stints, result["pit_stops"])

    # Save only the NEW planned stints (completed already in DB)
    for s in engine.stints:
        if s.stint_order > len(completed):
            conn.execute(
                """INSERT INTO race_stints (race_id, stint_order, driver_id,
                    planned_start_s, planned_end_s, planned_duration_s,
                    fuel_at_start, fuel_at_end, ballast_kg,
                    ballast_base_kg, ballast_fuel_offset_kg, fuel_burn_rate_kgs,
                    status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'planned')""",
                (race_id, s.stint_order, s.driver_id,
                 s.planned_start_s, s.planned_end_s, s.planned_duration_s,
                 round(s.fuel_at_start_kg, 4), round(s.fuel_at_end_kg, 4),
                 s.ballast_kg, s.ballast_base_kg, s.ballast_fuel_offset_kg,
                 engine.fuel_model.burn_rate_kgs),
            )
    conn.commit()
    return jsonify({"ok": True, "result": engine.snapshot()})


@bp.route("/<int:race_id>/api/messages", methods=["GET", "POST"])
def api_messages(race_id: int):
    """Get or post race messages."""
    conn = get_db_connection()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        author = data.get("author", "").strip()
        message = data.get("message", "").strip()
        category = data.get("category", "general")
        if not author or not message:
            return jsonify({"error": "author and message required"}), 400
        conn.execute(
            "INSERT INTO race_messages (race_id, author, message, category) VALUES (?,?,?,?)",
            (race_id, author, message, category),
        )
        conn.commit()
        return jsonify({"ok": True})

    # GET: return all messages
    msgs = _rows_to_list(conn.execute(
        "SELECT * FROM race_messages WHERE race_id = ? ORDER BY msg_id", (race_id,)
    ).fetchall())
    return jsonify({"messages": msgs})


@bp.route("/<int:race_id>/api/weather")
def api_weather(race_id: int):
    """Current weather + forecast + pace estimate for race track."""
    conn = get_db_connection()
    race = _row_to_dict(
        conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone()
    )
    if not race:
        return jsonify({"error": "not found"}), 404

    track_name = race.get("track_name")
    if not track_name:
        return jsonify({"error": "no track configured"}), 400

    try:
        import sys as _sys
        from pathlib import Path as _Path
        _root = str(_Path(__file__).resolve().parents[2])
        if _root not in _sys.path:
            _sys.path.insert(0, _root)

        from meteo_service import (
            get_known_tracks, fetch_current_weather,
            get_weather_forecast, estimate_track_conditions,
        )

        tracks = get_known_tracks(conn)
        track = next(
            (t for t in tracks if t.get("track_name", "").lower() == track_name.lower()),
            None,
        )
        if not track or not track.get("lat") or not track.get("lon"):
            return jsonify({"error": "track coordinates not found"}), 400

        lat, lon = track["lat"], track["lon"]

        # Current conditions
        current = fetch_current_weather(lat, lon)
        conditions = estimate_track_conditions(current) if current else {}

        # Forecast
        race_hours = max(1, (race.get("race_duration_s") or 3600) // 3600 + 1)
        forecast = get_weather_forecast(lat, lon, hours=race_hours)

        # Fuel adjustment based on grip
        fuel_autonomy = race.get("fuel_autonomy_s")
        adjusted_autonomy = None
        if fuel_autonomy and conditions.get("grip_score"):
            from wet_physics import get_grip_factor
            grip = get_grip_factor(conditions.get("track_state", "dry"))
            adjusted_autonomy = int(fuel_autonomy * grip)

        return jsonify({
            "current": current,
            "conditions": conditions,
            "forecast": forecast,
            "fuel_autonomy_adjusted_s": adjusted_autonomy,
            "lat": lat,
            "lon": lon,
        })
    except Exception as exc:
        logger.warning("Weather fetch failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── Stint Plan Export / Import ────────────────────

@bp.route("/<int:race_id>/export-plan")
def export_plan(race_id: int):
    """Export stint plan only (lightweight) as JSON download."""
    import re
    import sys
    from flask import Response
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)
    try:
        engine = RaceStateEngine.load(conn, race_id)
    except Exception:
        abort(400)
    data = engine.stint_plan_export(race.get("race_name", ""))
    payload = json.dumps(data, indent=2, default=str)
    slug = re.sub(r'[^a-z0-9]+', '-', race["race_name"].lower()).strip('-')
    filename = f"stint-plan-{slug}.json"
    return Response(payload, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@bp.route("/<int:race_id>/import-plan", methods=["POST"])
def import_plan(race_id: int):
    """Import stint plan into existing race. Matches drivers by name."""
    import sys
    from flask import flash
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine

    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        abort(404)

    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("race_strategy_v2.detail", race_id=race_id))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        flash("Invalid JSON file.", "error")
        return redirect(url_for("race_strategy_v2.detail", race_id=race_id))

    if data.get("format") != "stint-plan-v1":
        flash("Unsupported plan format.", "error")
        return redirect(url_for("race_strategy_v2.detail", race_id=race_id))

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order", (race_id,)
    ).fetchall())
    name_to_id = {d["driver_name"].lower(): d["id"] for d in drivers}

    raw_stints = []
    warnings = []
    for s in data.get("stints", []):
        driver_name = s.get("driver_name", "")
        driver_id = name_to_id.get(driver_name.lower())
        if not driver_id:
            warnings.append(f"Driver '{driver_name}' not found in race")
            driver_id = drivers[0]["id"] if drivers else None
        if driver_id:
            raw_stints.append({
                "stint_order": s["stint_order"],
                "driver_id": driver_id,
                "driver_name": driver_name,
                "planned_duration_s": s["planned_duration_s"],
                "planned_start_s": 0,
                "planned_end_s": 0,
            })

    # Rebuild timeline
    pit_time = race.get("min_pit_stop_s") or 60
    pit_stops = []
    clock = 0
    for i, s in enumerate(raw_stints):
        s["planned_start_s"] = clock
        s["planned_end_s"] = clock + s["planned_duration_s"]
        clock += s["planned_duration_s"]
        if i < len(raw_stints) - 1:
            ps_list = data.get("pit_stops", [])
            p = ps_list[i] if i < len(ps_list) else {}
            pit_stops.append({
                "after_stint": i + 1,
                "at_s": clock,
                "duration_s": p.get("duration_s", pit_time),
                "driver_change": p.get("driver_change", True),
                "refuel": p.get("refueled", True),
                "pit_type": p.get("pit_type", "full"),
            })
            clock += p.get("duration_s", pit_time)

    engine = RaceStateEngine(race, drivers, raw_stints, pit_stops)
    engine.save(conn, race_id)

    for w in warnings:
        flash(w, "warning")

    return redirect(url_for("race_strategy_v2.detail", race_id=race_id))


# ── Cascade Mutation APIs ────────────────────────

@bp.route("/<int:race_id>/api/toggle-fuel", methods=["POST"])
def api_toggle_fuel(race_id: int):
    """Toggle refuel on a pit stop. Triggers cascade."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    if not stint_order:
        return jsonify({"error": "stint_order required"}), 400
    engine = RaceStateEngine.load(conn, race_id)
    engine.toggle_fuel(stint_order)
    engine.save(conn, race_id)
    return jsonify({"ok": True, "snapshot": engine.snapshot()})


@bp.route("/<int:race_id>/api/set-pit-type", methods=["POST"])
def api_set_pit_type(race_id: int):
    """Set pit stop type (full/quick). Triggers cascade."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    pit_type = data.get("pit_type", "full")
    if not stint_order or pit_type not in ("full", "quick"):
        return jsonify({"error": "stint_order and valid pit_type required"}), 400
    engine = RaceStateEngine.load(conn, race_id)
    engine.set_pit_type(stint_order, pit_type)
    engine.save(conn, race_id)
    return jsonify({"ok": True, "snapshot": engine.snapshot()})


@bp.route("/<int:race_id>/api/set-driver", methods=["POST"])
def api_set_driver(race_id: int):
    """Change driver on a stint. Triggers cascade."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    driver_id = data.get("driver_id")
    if not stint_order or not driver_id:
        return jsonify({"error": "stint_order and driver_id required"}), 400
    engine = RaceStateEngine.load(conn, race_id)
    engine.set_driver(stint_order, driver_id)
    engine.save(conn, race_id)
    return jsonify({"ok": True, "snapshot": engine.snapshot()})


@bp.route("/<int:race_id>/api/set-duration", methods=["POST"])
def api_set_duration(race_id: int):
    """Edit stint duration. Triggers cascade."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    duration_s = data.get("duration_s")
    if not stint_order or duration_s is None:
        return jsonify({"error": "stint_order and duration_s required"}), 400
    engine = RaceStateEngine.load(conn, race_id)
    engine.set_duration(stint_order, int(duration_s))
    engine.save(conn, race_id)
    return jsonify({"ok": True, "snapshot": engine.snapshot()})


# ── Rival Tracker + Neutralization APIs ──────────


@bp.route("/<int:race_id>/api/rivals")
def api_list_rivals(race_id: int):
    """List all rivals for a race with their events."""
    conn = get_db_connection()
    rivals = _rows_to_list(conn.execute(
        "SELECT * FROM race_rivals WHERE race_id = ? ORDER BY id", (race_id,)
    ).fetchall())
    events = _rows_to_list(conn.execute(
        "SELECT * FROM race_rival_events WHERE race_id = ? ORDER BY at_s", (race_id,)
    ).fetchall())
    # Attach events to each rival
    for r in rivals:
        r["events"] = [e for e in events if e["rival_id"] == r["id"]]
    return jsonify({"rivals": rivals})


@bp.route("/<int:race_id>/api/rivals", methods=["POST"])
def api_add_rival(race_id: int):
    """Add a rival team."""
    data = request.get_json(silent=True) or {}
    team_name = (data.get("team_name") or "").strip()
    if not team_name:
        return jsonify({"error": "team_name required"}), 400
    car_number = (data.get("car_number") or "").strip()
    notes = (data.get("notes") or "").strip()
    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO race_rivals (race_id, team_name, car_number, notes) VALUES (?,?,?,?)",
        (race_id, team_name, car_number or None, notes or None),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM race_rivals WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row))


@bp.route("/<int:race_id>/api/rivals/<int:rival_id>/event", methods=["POST"])
def api_add_rival_event(race_id: int, rival_id: int):
    """Log a rival event (pit_in, pit_out, driver_change, penalty, note)."""
    _VALID_EVENT_TYPES = {"pit_in", "pit_out", "driver_change", "penalty", "note"}
    data = request.get_json(silent=True) or {}
    event_type = data.get("event_type", "note")
    if event_type not in _VALID_EVENT_TYPES:
        return jsonify({"error": f"event_type must be one of: {', '.join(sorted(_VALID_EVENT_TYPES))}"}), 400
    detail = data.get("detail")
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    try:
        at_s = int(data.get("at_s", elapsed))
    except (ValueError, TypeError):
        at_s = elapsed
    conn.execute(
        "INSERT INTO race_rival_events (race_id, rival_id, event_type, at_s, detail) VALUES (?,?,?,?,?)",
        (race_id, rival_id, event_type, at_s, detail),
    )
    conn.commit()
    return jsonify({"ok": True, "at_s": at_s})


@bp.route("/<int:race_id>/api/rivals/<int:rival_id>", methods=["DELETE"])
def api_delete_rival(race_id: int, rival_id: int):
    """Delete a rival and their events."""
    conn = get_db_connection()
    conn.execute("DELETE FROM race_rival_events WHERE rival_id = ? AND race_id = ?", (rival_id, race_id))
    conn.execute("DELETE FROM race_rivals WHERE id = ? AND race_id = ?", (rival_id, race_id))
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/<int:race_id>/api/neutralization/start", methods=["POST"])
def api_neutralization_start(race_id: int):
    """Start a neutralization (safety car) period."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "safety_car")
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        return jsonify({"error": "not found"}), 404
    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    engine = RaceStateEngine.load(conn, race_id)
    engine.start_neutralization(elapsed, reason)
    engine.save(conn, race_id)
    return jsonify({"ok": True, "is_neutralized": engine.is_neutralized, "elapsed_s": elapsed})


@bp.route("/<int:race_id>/api/neutralization/end", methods=["POST"])
def api_neutralization_end(race_id: int):
    """End the active neutralization period (green flag)."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    from race_state_engine import RaceStateEngine
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        return jsonify({"error": "not found"}), 404
    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    engine = RaceStateEngine.load(conn, race_id)
    engine.end_neutralization(elapsed)
    engine.save(conn, race_id)
    return jsonify({"ok": True, "is_neutralized": engine.is_neutralized, "elapsed_s": elapsed})


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
                min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg, com_channel, color_hex
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
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
                form.get(f"driver_com_{i}") or None,
                form.get(f"driver_color_{i}") or None,
            ),
        )
        i += 1


def _save_windows(conn, race_id: int, form):
    """Save race windows from form data. Expects window_type_N, window_start_N, etc."""
    conn.execute("DELETE FROM race_windows WHERE race_id = ?", (race_id,))
    i = 0
    while True:
        wtype = form.get(f"window_type_{i}")
        if wtype is None:
            break
        start_raw = form.get(f"window_start_{i}")
        end_raw = form.get(f"window_end_{i}")
        start = _parse_duration(start_raw) if start_raw else None
        end = _parse_duration(end_raw) if end_raw else None
        if start is None and end is None:
            i += 1
            continue
        conn.execute(
            "INSERT INTO race_windows (race_id, window_type, label, start_s, end_s, "
            "refuel_allowed, driver_change_allowed, window_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                race_id, wtype,
                form.get(f"window_label_{i}") or None,
                start or 0, end or 0,
                1 if form.get(f"window_refuel_{i}") else 0,
                1 if form.get(f"window_driver_change_{i}") else 0,
                i + 1,
            ),
        )
        i += 1
