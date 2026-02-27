"""
Race strategy service layer.

Pure business logic for race strategy CRUD, optimization, and live-race
operations.  No Flask imports -- accepts a DB connection as first argument
and returns plain dicts.

SQL uses ``?`` positional parameters; the ``sql_compat`` layer
auto-translates to ``%(name)s`` / ``%s`` for PostgreSQL at call time.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# sys.path manipulation for sibling-module imports (same pattern used in the
# existing routes -- see race_strategy_v2.py routes, line 602-605)
# ---------------------------------------------------------------------------
_root = str(Path(__file__).resolve().parents[1])  # telemetry_tool/
if _root not in sys.path:
    sys.path.insert(0, _root)

from race_state_engine import RaceStateEngine  # noqa: E402
from race_strategy_v2 import optimize_stints, reoptimize_remaining  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    """Convert a DB row (sqlite3.Row or psycopg2 DictRow) to a plain dict."""
    if row is None:
        return {}
    return dict(row)


def _rows_to_list(rows) -> list[dict]:
    """Convert a list of DB rows to a list of plain dicts."""
    return [dict(r) for r in rows]


def _compute_elapsed_s(race_start_ts: str | None) -> int:
    """Compute seconds elapsed since race start.

    Handles ISO-8601 timestamps with or without timezone info.
    Returns 0 when *race_start_ts* is falsy or unparseable.
    """
    if not race_start_ts:
        return 0
    try:
        start = datetime.fromisoformat(race_start_ts.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - start).total_seconds()))
    except Exception:
        return 0


def _save_drivers(conn, race_id: int, drivers: list[dict]) -> None:
    """Persist a list of driver dicts for a given race.

    Each dict should contain at minimum ``driver_name`` plus any optional
    constraint fields (min_stint_s, max_stint_s, weight_kg, etc.).
    """
    for i, d in enumerate(drivers):
        name = (d.get("driver_name") or "").strip()
        if not name:
            continue
        conn.execute(
            """INSERT INTO race_drivers (
                race_id, driver_name, driver_order, min_stint_s, max_stint_s,
                min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg,
                com_channel, color_hex
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                race_id,
                name,
                d.get("driver_order", i + 1),
                d.get("min_stint_s"),
                d.get("max_stint_s"),
                d.get("min_cumulative_s"),
                d.get("max_cumulative_s"),
                d.get("min_rest_s", 0),
                d.get("weight_kg"),
                d.get("com_channel"),
                d.get("color_hex"),
            ),
        )


def _save_windows(conn, race_id: int, windows: list[dict]) -> None:
    """Persist a list of race-window dicts for a given race.

    Deletes any existing windows for the race first.
    """
    conn.execute("DELETE FROM race_windows WHERE race_id = ?", (race_id,))
    for i, w in enumerate(windows):
        start = w.get("start_s")
        end = w.get("end_s")
        if start is None and end is None:
            continue
        conn.execute(
            "INSERT INTO race_windows (race_id, window_type, label, start_s, end_s, "
            "refuel_allowed, driver_change_allowed, window_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                race_id,
                w.get("window_type", "pitlane"),
                w.get("label"),
                start or 0,
                end or 0,
                w.get("refuel_allowed", 1),
                w.get("driver_change_allowed", 1),
                w.get("window_order", i + 1),
            ),
        )


def _get_last_insert_id(conn, cur, table: str, pk_col: str) -> int | None:
    """Get the ID of the last inserted row.

    Works for both SQLite (``cur.lastrowid``) and PostgreSQL (``currval``).
    """
    race_id = cur.lastrowid
    if race_id is None or race_id == 0:
        # PG mode: lastrowid not set, need explicit query
        row = conn.execute(
            "SELECT currval(pg_get_serial_sequence(?, ?))",
            (table, pk_col),
        ).fetchone()
        race_id = row[0] if row else None
    return race_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_races(conn) -> list[dict]:
    """Return all races, live races sorted first, then by created_at DESC."""
    rows = conn.execute(
        "SELECT * FROM race_configs ORDER BY "
        "CASE status WHEN 'live' THEN 0 ELSE 1 END, created_at DESC"
    ).fetchall()
    return _rows_to_list(rows)


def get_race(conn, race_id: int) -> dict | None:
    """Return a single race config by ID, or None if not found."""
    row = conn.execute(
        "SELECT * FROM race_configs WHERE race_id = ?", (race_id,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def get_race_detail(conn, race_id: int) -> dict | None:
    """Return full race detail: config + drivers + stints + pit_stops + windows.

    Returns None if the race does not exist.
    """
    race = get_race(conn, race_id)
    if not race:
        return None

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
        (race_id,),
    ).fetchall())

    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name FROM race_stints s "
        "JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = ? ORDER BY s.stint_order",
        (race_id,),
    ).fetchall())

    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY planned_at_s",
        (race_id,),
    ).fetchall())

    windows = _rows_to_list(conn.execute(
        "SELECT * FROM race_windows WHERE race_id = ? ORDER BY window_order",
        (race_id,),
    ).fetchall())

    return {
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "windows": windows,
    }


def create_race(conn, data: dict) -> int:
    """Create a new race configuration with drivers and windows.

    Parameters
    ----------
    conn : DB connection
    data : dict
        Must contain ``race`` (config fields), ``drivers`` (list[dict]),
        and optionally ``windows`` (list[dict]).

    Returns
    -------
    int
        The new race_id.
    """
    race = data.get("race", data)  # accept flat or nested
    drivers = data.get("drivers", [])
    windows = data.get("windows", [])

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
            race.get("race_name", "Untitled Race"),
            race.get("track_name"),
            race.get("team_name"),
            race.get("race_duration_s", 10800),
            race.get("reference_weight_kg"),
            race.get("desired_stints", 4),
            race.get("fuel_autonomy_s"),
            race.get("min_pit_stop_s", 60),
            race.get("pit_speed_kmh"),
            race.get("quick_pit_stop_s"),
            race.get("pit_open_s"),
            race.get("pit_close_s"),
            race.get("empty_kart_kg"),
            race.get("full_tank_kg"),
            race.get("min_total_kart_kg"),
            race.get("weigh_on_pit_exit", 0),
            race.get("qualifying_duration_s"),
            race.get("refuel_after_quali", 0),
            race.get("mandatory_driver_change", 1),
            race.get("refueling_allowed", 1),
        ),
    )
    race_id = _get_last_insert_id(conn, cur, "race_configs", "race_id")

    if drivers:
        _save_drivers(conn, race_id, drivers)
    if windows:
        _save_windows(conn, race_id, windows)

    conn.commit()
    return race_id


def update_race(conn, race_id: int, data: dict) -> bool:
    """Update an existing race configuration.

    Only allowed when status is ``'draft'`` or ``'ready'``.
    Clears planned stints and pit stops (requires re-optimization).

    Parameters
    ----------
    conn : DB connection
    race_id : int
    data : dict
        ``race`` (config fields), ``drivers`` (list[dict]),
        optionally ``windows`` (list[dict]).

    Returns
    -------
    bool
        True if update succeeded, False if race not found or wrong status.
    """
    race = get_race(conn, race_id)
    if not race:
        return False
    if race["status"] not in ("draft", "ready"):
        return False

    cfg = data.get("race", data)
    drivers = data.get("drivers", [])
    windows = data.get("windows", [])

    conn.execute(
        """UPDATE race_configs SET
            race_name=?, track_name=?, team_name=?, race_duration_s=?,
            reference_weight_kg=?, desired_stints=?, fuel_autonomy_s=?,
            min_pit_stop_s=?, pit_speed_kmh=?, quick_pit_stop_s=?,
            pit_open_s=?, pit_close_s=?,
            empty_kart_kg=?, full_tank_kg=?, min_total_kart_kg=?,
            weigh_on_pit_exit=?, qualifying_duration_s=?, refuel_after_quali=?,
            mandatory_driver_change=?, refueling_allowed=?,
            updated_at=datetime('now'), status='draft'
        WHERE race_id=?""",
        (
            cfg.get("race_name", race.get("race_name", "Untitled Race")),
            cfg.get("track_name", race.get("track_name")),
            cfg.get("team_name", race.get("team_name")),
            cfg.get("race_duration_s", race.get("race_duration_s")),
            cfg.get("reference_weight_kg", race.get("reference_weight_kg")),
            cfg.get("desired_stints", race.get("desired_stints", 4)),
            cfg.get("fuel_autonomy_s", race.get("fuel_autonomy_s")),
            cfg.get("min_pit_stop_s", race.get("min_pit_stop_s", 60)),
            cfg.get("pit_speed_kmh", race.get("pit_speed_kmh")),
            cfg.get("quick_pit_stop_s", race.get("quick_pit_stop_s")),
            cfg.get("pit_open_s", race.get("pit_open_s")),
            cfg.get("pit_close_s", race.get("pit_close_s")),
            cfg.get("empty_kart_kg", race.get("empty_kart_kg")),
            cfg.get("full_tank_kg", race.get("full_tank_kg")),
            cfg.get("min_total_kart_kg", race.get("min_total_kart_kg")),
            cfg.get("weigh_on_pit_exit", race.get("weigh_on_pit_exit", 0)),
            cfg.get("qualifying_duration_s", race.get("qualifying_duration_s")),
            cfg.get("refuel_after_quali", race.get("refuel_after_quali", 0)),
            cfg.get("mandatory_driver_change", race.get("mandatory_driver_change", 1)),
            cfg.get("refueling_allowed", race.get("refueling_allowed", 1)),
            race_id,
        ),
    )

    # Clear and re-save drivers + windows
    conn.execute("DELETE FROM race_drivers WHERE race_id = ?", (race_id,))
    if drivers:
        _save_drivers(conn, race_id, drivers)
    if windows:
        _save_windows(conn, race_id, windows)

    # Clear planned stints (will need re-optimize)
    conn.execute(
        "DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'",
        (race_id,),
    )
    conn.execute("DELETE FROM race_pit_stops WHERE race_id = ?", (race_id,))

    conn.commit()
    return True


def delete_race(conn, race_id: int) -> bool:
    """Delete a race and all associated data.

    Returns True if a row was deleted, False otherwise.
    """
    cur = conn.execute(
        "DELETE FROM race_configs WHERE race_id = ?", (race_id,)
    )
    conn.commit()
    # rowcount is reliable on both SQLite and psycopg2
    return (getattr(cur, "rowcount", 0) or 0) > 0


def run_optimization(conn, race_id: int) -> dict:
    """Run the stint optimizer and persist results via RaceStateEngine.

    Returns the engine snapshot dict.  Updates race status to ``'ready'``
    if the result is feasible, otherwise keeps ``'draft'``.
    """
    race = get_race(conn, race_id)
    if not race:
        return {"error": "not found"}

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
        (race_id,),
    ).fetchall())

    result = optimize_stints(race, drivers)

    # Wrap in engine for fuel/ballast cascade
    engine = RaceStateEngine(race, drivers, result["stints"], result["pit_stops"])
    engine.save(conn, race_id)

    # Update status
    new_status = "ready" if result["feasible"] else "draft"
    conn.execute(
        "UPDATE race_configs SET status = ?, updated_at = datetime('now') WHERE race_id = ?",
        (new_status, race_id),
    )
    conn.commit()

    snapshot = engine.snapshot()
    snapshot["feasible"] = result["feasible"]
    snapshot["violations"] = result.get("violations", [])
    snapshot["warnings"] = result.get("warnings", [])
    snapshot["driver_summary"] = result.get("driver_summary", {})
    snapshot["total_pit_time_s"] = result.get("total_pit_time_s", 0)
    snapshot["total_drive_time_s"] = result.get("total_drive_time_s", 0)
    return snapshot


def go_live(conn, race_id: int) -> bool:
    """Start the race: set status to ``'live'`` and activate the first stint.

    Returns False if the race is not in ``'ready'`` or ``'draft'`` status.
    """
    race_row = conn.execute(
        "SELECT * FROM race_configs WHERE race_id = ?", (race_id,)
    ).fetchone()
    if not race_row:
        return False
    race = _row_to_dict(race_row)
    if race["status"] not in ("ready", "draft"):
        return False

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE race_configs SET status = 'live', race_start_ts = ?, "
        "updated_at = datetime('now') WHERE race_id = ?",
        (now, race_id),
    )

    # Set first planned stint to active
    first_stint = conn.execute(
        "SELECT stint_id FROM race_stints "
        "WHERE race_id = ? AND status = 'planned' ORDER BY stint_order LIMIT 1",
        (race_id,),
    ).fetchone()
    if first_stint:
        conn.execute(
            "UPDATE race_stints SET status = 'active', actual_start_s = 0 "
            "WHERE stint_id = ?",
            (first_stint["stint_id"],),
        )

    conn.commit()
    return True


def finish_race(conn, race_id: int) -> bool:
    """End the race: complete any active stint and set status to ``'finished'``.

    Returns False if the race is not found.
    """
    race = get_race(conn, race_id)
    if not race:
        return False

    elapsed = _compute_elapsed_s(race.get("race_start_ts"))

    # Complete any active stint with actual times
    active = conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? AND status = 'active'",
        (race_id,),
    ).fetchone()
    if active:
        actual_duration = elapsed - (active["actual_start_s"] or 0)
        conn.execute(
            "UPDATE race_stints SET status = 'completed', actual_end_s = ?, "
            "actual_duration_s = ? WHERE stint_id = ?",
            (elapsed, actual_duration, active["stint_id"]),
        )

    conn.execute(
        "UPDATE race_configs SET status = 'finished', updated_at = datetime('now') "
        "WHERE race_id = ?",
        (race_id,),
    )
    conn.commit()
    return True


def get_live_state(conn, race_id: int) -> dict | None:
    """Return the full live state for dashboard polling.

    Includes race config, drivers, stints, pit stops, messages,
    active/next stint, driver cumulative times, and engine-computed
    real-time data (fuel, ballast, fuel model, window status).

    Returns None if the race is not found.
    """
    race = get_race(conn, race_id)
    if not race:
        return None

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
        (race_id,),
    ).fetchall())

    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name, d.weight_kg as driver_weight_kg "
        "FROM race_stints s "
        "JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = ? ORDER BY s.stint_order",
        (race_id,),
    ).fetchall())

    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY planned_at_s",
        (race_id,),
    ).fetchall())

    messages = _rows_to_list(conn.execute(
        "SELECT * FROM race_messages WHERE race_id = ? ORDER BY msg_id",
        (race_id,),
    ).fetchall())

    active_stint = next((s for s in stints if s["status"] == "active"), None)
    next_stint = next((s for s in stints if s["status"] == "planned"), None)

    # Driver cumulative times
    driver_cumulative: dict[int, int] = {}
    for s in stints:
        if s["status"] == "completed":
            did = s["driver_id"]
            dur = s.get("actual_duration_s") or s.get("planned_duration_s") or 0
            driver_cumulative[did] = driver_cumulative.get(did, 0) + dur

    # Engine-computed real-time data (fuel, ballast, fuel model)
    engine_data: dict[str, Any] = {}
    try:
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
    except Exception:
        logger.debug("Engine load failed for race %d, returning basic state", race_id)

    return {
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "messages": messages,
        "active_stint": active_stint,
        "next_stint": next_stint,
        "driver_cumulative": driver_cumulative,
        **engine_data,
    }


def end_stint(
    conn,
    race_id: int,
    *,
    driver_change: bool = True,
    refueled: bool = False,
    notes: str | None = None,
) -> dict | None:
    """End the current active stint, log a pit stop, and start the next stint.

    Returns a dict with ``ok`` and ``elapsed_s`` on success, or None if
    there is no active stint.
    """
    race = get_race(conn, race_id)
    if not race:
        return None

    active = conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? AND status = 'active'",
        (race_id,),
    ).fetchone()
    if not active:
        return None

    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    actual_duration = elapsed - (active["actual_start_s"] or 0)

    conn.execute(
        "UPDATE race_stints SET status = 'completed', actual_end_s = ?, "
        "actual_duration_s = ? WHERE stint_id = ?",
        (elapsed, actual_duration, active["stint_id"]),
    )

    # Log pit stop
    conn.execute(
        """INSERT INTO race_pit_stops
           (race_id, stint_id, actual_at_s, driver_change, refueled, notes)
        VALUES (?,?,?,?,?,?)""",
        (
            race_id,
            active["stint_id"],
            elapsed,
            1 if driver_change else 0,
            1 if refueled else 0,
            notes,
        ),
    )

    # Start next stint
    next_stint = conn.execute(
        "SELECT stint_id FROM race_stints "
        "WHERE race_id = ? AND status = 'planned' ORDER BY stint_order LIMIT 1",
        (race_id,),
    ).fetchone()
    if next_stint:
        conn.execute(
            "UPDATE race_stints SET status = 'active', actual_start_s = ? "
            "WHERE stint_id = ?",
            (elapsed, next_stint["stint_id"]),
        )

    conn.commit()
    return {"ok": True, "elapsed_s": elapsed}


def toggle_fuel(conn, race_id: int, stint_order: int) -> dict | None:
    """Toggle refuel on a pit stop and re-cascade via RaceStateEngine.

    Returns the engine snapshot, or None on failure.
    """
    try:
        engine = RaceStateEngine.load(conn, race_id)
    except Exception:
        return None
    engine.toggle_fuel(stint_order)
    engine.save(conn, race_id)
    return engine.snapshot()


def set_pit_type(
    conn, race_id: int, stint_order: int, pit_type: str
) -> dict | None:
    """Set pit stop type (``'full'`` / ``'quick'``) and re-cascade.

    Returns the engine snapshot, or None on failure.
    """
    if pit_type not in ("full", "quick"):
        return None
    try:
        engine = RaceStateEngine.load(conn, race_id)
    except Exception:
        return None
    engine.set_pit_type(stint_order, pit_type)
    engine.save(conn, race_id)
    return engine.snapshot()


def reoptimize(conn, race_id: int) -> dict:
    """Re-optimize remaining stints mid-race.

    Keeps completed and active stints, replaces planned stints with a
    fresh optimization result wrapped through RaceStateEngine for
    fuel/ballast cascade.

    Returns the engine snapshot dict with ``ok: True``.
    """
    race = get_race(conn, race_id)
    if not race:
        return {"error": "not found"}

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
        (race_id,),
    ).fetchall())

    completed = _rows_to_list(conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? AND status = 'completed' "
        "ORDER BY stint_order",
        (race_id,),
    ).fetchall())

    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    result = reoptimize_remaining(race, drivers, completed, elapsed)

    # Clear planned stints only
    conn.execute(
        "DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'",
        (race_id,),
    )

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
                (
                    race_id,
                    s.stint_order,
                    s.driver_id,
                    s.planned_start_s,
                    s.planned_end_s,
                    s.planned_duration_s,
                    round(s.fuel_at_start_kg, 4),
                    round(s.fuel_at_end_kg, 4),
                    s.ballast_kg,
                    s.ballast_base_kg,
                    s.ballast_fuel_offset_kg,
                    engine.fuel_model.burn_rate_kgs,
                ),
            )

    conn.commit()
    return {"ok": True, "result": engine.snapshot()}


def export_race(conn, race_id: int) -> dict | None:
    """Build the full export dictionary for a race.

    Returns None if the race does not exist.
    """
    race = get_race(conn, race_id)
    if not race:
        return None

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
        (race_id,),
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? ORDER BY stint_order",
        (race_id,),
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY pit_id",
        (race_id,),
    ).fetchall())
    messages = _rows_to_list(conn.execute(
        "SELECT * FROM race_messages WHERE race_id = ? ORDER BY msg_id",
        (race_id,),
    ).fetchall())
    windows = _rows_to_list(conn.execute(
        "SELECT * FROM race_windows WHERE race_id = ? ORDER BY window_order",
        (race_id,),
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


def import_race(conn, data: dict) -> int:
    """Import a race from an export dict (version 1 format).

    Remaps driver IDs so the imported copy has fresh, self-consistent
    foreign keys.

    Returns the new race_id.

    Raises
    ------
    ValueError
        If required fields are missing.
    """
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
            race.get("race_name"),
            race.get("track_name"),
            race.get("team_name"),
            race["race_duration_s"],
            race.get("reference_weight_kg"),
            race.get("desired_stints", 4),
            race.get("fuel_autonomy_s"),
            race.get("min_pit_stop_s", 60),
            race.get("pit_speed_kmh"),
            race.get("quick_pit_stop_s"),
            race.get("pit_open_s"),
            race.get("pit_close_s"),
            race.get("empty_kart_kg"),
            race.get("full_tank_kg"),
            race.get("min_total_kart_kg"),
            race.get("weigh_on_pit_exit", 0),
            race.get("qualifying_duration_s"),
            race.get("refuel_after_quali", 0),
            race.get("mandatory_driver_change", 1),
            race.get("refueling_allowed", 1),
        ),
    )
    new_race_id = _get_last_insert_id(conn, cur, "race_configs", "race_id")

    # Insert drivers, building old_id -> new_id map
    id_map: dict[int, int] = {}
    for d in data.get("drivers", []):
        old_id = d.get("id")
        dcur = conn.execute(
            """INSERT INTO race_drivers (
                race_id, driver_name, driver_order, min_stint_s, max_stint_s,
                min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg,
                com_channel, color_hex
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_race_id,
                d["driver_name"],
                d.get("driver_order", 1),
                d.get("min_stint_s"),
                d.get("max_stint_s"),
                d.get("min_cumulative_s"),
                d.get("max_cumulative_s"),
                d.get("min_rest_s", 0),
                d.get("weight_kg"),
                d.get("com_channel"),
                d.get("color_hex"),
            ),
        )
        new_driver_id = _get_last_insert_id(
            conn, dcur, "race_drivers", "id"
        )
        if old_id is not None and new_driver_id is not None:
            id_map[old_id] = new_driver_id

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
                new_race_id,
                s.get("stint_order", 1),
                new_driver_id,
                s.get("planned_start_s"),
                s.get("planned_end_s"),
                s.get("planned_duration_s"),
                s.get("actual_start_s"),
                s.get("actual_end_s"),
                s.get("actual_duration_s"),
                s.get("ballast_kg", 0),
                s.get("notes"),
                s.get("status", "planned"),
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
                new_race_id,
                p.get("planned_at_s"),
                p.get("actual_at_s"),
                p.get("duration_s"),
                p.get("driver_change", 1),
                p.get("refueled", 0),
                p.get("fuel_added_kg"),
                p.get("ballast_changed", 0),
                p.get("notes"),
            ),
        )

    # Insert messages
    for m in data.get("messages", []):
        conn.execute(
            "INSERT INTO race_messages (race_id, author, message, category) "
            "VALUES (?,?,?,?)",
            (
                new_race_id,
                m.get("author", ""),
                m.get("message", ""),
                m.get("category", "general"),
            ),
        )

    # Import windows
    for w in data.get("windows", []):
        conn.execute(
            "INSERT INTO race_windows (race_id, window_type, label, start_s, end_s, "
            "refuel_allowed, driver_change_allowed, window_order) VALUES (?,?,?,?,?,?,?,?)",
            (
                new_race_id,
                w.get("window_type", "pitlane"),
                w.get("label"),
                w.get("start_s", 0),
                w.get("end_s", 0),
                w.get("refuel_allowed", 1),
                w.get("driver_change_allowed", 1),
                w.get("window_order", 1),
            ),
        )

    conn.commit()
    return new_race_id


def duplicate_race(conn, race_id: int) -> int | None:
    """Clone a race configuration with its drivers and windows.

    Stints and pit stops are NOT copied (the clone starts in ``'draft'``
    status and needs a fresh optimization).

    Returns the new race_id, or None if the source race was not found.
    """
    race_row = conn.execute(
        "SELECT * FROM race_configs WHERE race_id = ?", (race_id,)
    ).fetchone()
    if not race_row:
        return None
    r = _row_to_dict(race_row)

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
            r["race_name"] + " (copy)",
            r["track_name"],
            r["team_name"],
            r["race_duration_s"],
            r["reference_weight_kg"],
            r["desired_stints"],
            r["fuel_autonomy_s"],
            r["min_pit_stop_s"],
            r["pit_speed_kmh"],
            r.get("quick_pit_stop_s"),
            r["pit_open_s"],
            r["pit_close_s"],
            r["empty_kart_kg"],
            r["full_tank_kg"],
            r["min_total_kart_kg"],
            r["weigh_on_pit_exit"],
            r["qualifying_duration_s"],
            r["refuel_after_quali"],
            r["mandatory_driver_change"],
            r["refueling_allowed"],
        ),
    )
    new_id = _get_last_insert_id(conn, cur, "race_configs", "race_id")

    # Copy drivers
    old_drivers = conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ?", (race_id,)
    ).fetchall()
    for d in old_drivers:
        dd = _row_to_dict(d)
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, "
            "min_stint_s, max_stint_s, min_cumulative_s, max_cumulative_s, "
            "min_rest_s, weight_kg, com_channel) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                new_id,
                dd["driver_name"],
                dd["driver_order"],
                dd["min_stint_s"],
                dd["max_stint_s"],
                dd["min_cumulative_s"],
                dd["max_cumulative_s"],
                dd["min_rest_s"],
                dd["weight_kg"],
                dd.get("com_channel"),
            ),
        )

    # Copy windows
    old_windows = conn.execute(
        "SELECT * FROM race_windows WHERE race_id = ? ORDER BY window_order",
        (race_id,),
    ).fetchall()
    for w in old_windows:
        wd = _row_to_dict(w)
        conn.execute(
            "INSERT INTO race_windows (race_id, window_type, label, start_s, end_s, "
            "refuel_allowed, driver_change_allowed, window_order) VALUES (?,?,?,?,?,?,?,?)",
            (
                new_id,
                wd.get("window_type", "pitlane"),
                wd.get("label"),
                wd.get("start_s", 0),
                wd.get("end_s", 0),
                wd.get("refuel_allowed", 1),
                wd.get("driver_change_allowed", 1),
                wd.get("window_order", 1),
            ),
        )

    conn.commit()
    return new_id


def get_summary(conn, race_id: int) -> dict | None:
    """Build the post-race summary data.

    Returns a dict with race, drivers, stints, pit_stops, per-driver stats,
    total_drive_s, and total_pit_s.  Returns None if the race is not found.
    """
    race = get_race(conn, race_id)
    if not race:
        return None

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
        (race_id,),
    ).fetchall())

    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name FROM race_stints s "
        "JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = ? ORDER BY s.stint_order",
        (race_id,),
    ).fetchall())

    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY actual_at_s",
        (race_id,),
    ).fetchall())

    # Compute per-driver stats
    driver_stats: dict[int, dict] = {}
    for d in drivers:
        d_stints = [s for s in stints if s["driver_id"] == d["id"]]
        durations = [
            s.get("actual_duration_s") or s.get("planned_duration_s") or 0
            for s in d_stints
        ]
        total_time = sum(durations)
        driver_stats[d["id"]] = {
            "name": d["driver_name"],
            "total_drive_s": total_time,
            "n_stints": len(d_stints),
            "longest_stint_s": max(durations) if durations else 0,
            "shortest_stint_s": min(durations) if durations else 0,
        }

    total_actual_drive = sum(
        s.get("actual_duration_s") or s.get("planned_duration_s") or 0
        for s in stints
    )
    total_pit = sum(p.get("duration_s") or 0 for p in pit_stops)

    return {
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "driver_stats": driver_stats,
        "total_drive_s": total_actual_drive,
        "total_pit_s": total_pit,
    }
