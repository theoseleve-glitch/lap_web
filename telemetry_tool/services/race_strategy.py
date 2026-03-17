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


def _pg_bool(val, default=False) -> bool:
    """Convert 0/1/None to Python bool for PG boolean columns."""
    if val is None:
        return default
    return bool(int(val))

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


def _compute_elapsed_s(race_start_ts: str | None, race: dict | None = None) -> int:
    """Compute seconds elapsed since race start, accounting for pauses.

    Subtracts ``total_paused_s`` from wall-clock elapsed.
    If race is currently paused (``paused_at_ts`` set), freezes at the pause point.
    """
    if not race_start_ts:
        return 0
    try:
        start = datetime.fromisoformat(race_start_ts.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        wall_elapsed = max(0, int((datetime.now(timezone.utc) - start).total_seconds()))

        total_paused = 0
        paused_at = None
        if race:
            total_paused = race.get("total_paused_s") or 0
            paused_at = race.get("paused_at_ts")

        if paused_at:
            # Currently paused: freeze at the moment we paused
            try:
                pause_start = datetime.fromisoformat(paused_at.replace("Z", "+00:00"))
                if pause_start.tzinfo is None:
                    pause_start = pause_start.replace(tzinfo=timezone.utc)
                wall_elapsed = max(0, int((pause_start - start).total_seconds()))
            except Exception:
                pass

        return max(0, wall_elapsed - total_paused)
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
                com_channel, color_hex, allow_double_stint, avg_lap_time_s
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                _pg_bool(d.get("allow_double_stint", 0)),
                d.get("avg_lap_time_s"),
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


def _save_sleep_windows(conn, race_id: int, driver_id_map: dict[int, int],
                        sleep_windows: list[dict]) -> None:
    """Persist sleep windows for a race. Deletes existing first."""
    try:
        conn.execute("DELETE FROM race_sleep_windows WHERE race_id = ?", (race_id,))
    except Exception:
        # Table may not exist if migration 038 hasn't been applied
        logger.warning("race_sleep_windows table not found — skipping sleep windows")
        return
    for sw in sleep_windows:
        start = sw.get("start_s")
        end = sw.get("end_s")
        if start is None or end is None or end <= start:
            continue
        raw_did = sw.get("driver_id")
        driver_id = driver_id_map.get(raw_did, raw_did) if driver_id_map else raw_did
        if driver_id is None:
            continue
        conn.execute(
            "INSERT INTO race_sleep_windows "
            "(race_id, driver_id, start_s, end_s, label, status) "
            "VALUES (?,?,?,?,?,?)",
            (race_id, driver_id, start, end,
             sw.get("label"), sw.get("status", "planned")),
        )


def _build_driver_id_map(conn, race_id: int) -> dict[int, int]:
    """Build a map from 0-based driver index to DB driver id.

    The frontend sends ``driver_id`` as the 0-based index into the drivers
    array.  This function queries the saved drivers (ordered by driver_order)
    and returns ``{0: db_id_1, 1: db_id_2, ...}``.
    """
    rows = conn.execute(
        "SELECT id FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
        (race_id,),
    ).fetchall()
    return {i: (r["id"] if isinstance(r, dict) else r[0]) for i, r in enumerate(rows)}


def _get_sleep_windows(conn, race_id: int) -> list[dict]:
    """Fetch all sleep windows for a race, ordered by start time."""
    try:
        return _rows_to_list(conn.execute(
            "SELECT sw.*, d.driver_name FROM race_sleep_windows sw "
            "JOIN race_drivers d ON sw.driver_id = d.id "
            "WHERE sw.race_id = ? ORDER BY sw.start_s",
            (race_id,),
        ).fetchall())
    except Exception:
        return []  # Table may not exist if migration 038 not applied


def _compute_driver_sleep_status(
    sleep_windows: list[dict], elapsed_s: int
) -> dict[int, dict]:
    """Compute current sleep status for each driver.

    Returns dict keyed by driver_id:
      sleeping=True: until_s, remaining_s, window_id, label
      sleeping=False: next_sleep_s (if upcoming window exists)
    """
    status: dict[int, dict] = {}
    for sw in sleep_windows:
        did = sw["driver_id"]
        effective_end = sw.get("actual_wake_s") or sw["end_s"]
        if sw["start_s"] <= elapsed_s < effective_end and sw.get("actual_wake_s") is None:
            status[did] = {
                "sleeping": True,
                "until_s": sw["end_s"],
                "remaining_s": max(0, sw["end_s"] - elapsed_s),
                "window_id": sw["id"],
                "label": sw.get("label"),
            }
        elif did not in status:
            if sw["start_s"] > elapsed_s and sw.get("actual_wake_s") is None:
                status[did] = {"sleeping": False, "next_sleep_s": sw["start_s"]}
            else:
                status[did] = {"sleeping": False}
    return status



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

    sleep_windows = _get_sleep_windows(conn, race_id)

    # Compute estimated laps and pit lap from driver avg_lap_time_s
    driver_avg = {d["id"]: d.get("avg_lap_time_s") for d in drivers}
    cumulative_laps = 0
    for s in stints:
        avg = driver_avg.get(s["driver_id"])
        dur = s.get("planned_duration_s") or 0
        if avg and avg > 0:
            est = int(dur / avg)
            s["estimated_laps"] = est
            s["pit_at_lap"] = cumulative_laps + est
            cumulative_laps += est
        else:
            s["estimated_laps"] = None
            s["pit_at_lap"] = None

    return {
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "windows": windows,
        "sleep_windows": sleep_windows,
    }


def create_race(conn, data: dict, *, max_duration_s: int | None = None) -> int:
    """Create a new race configuration with drivers and windows.

    Parameters
    ----------
    conn : DB connection
    data : dict
        Must contain ``race`` (config fields), ``drivers`` (list[dict]),
        and optionally ``windows`` (list[dict]).
    max_duration_s : int | None
        Optional plan-based maximum race duration in seconds.
        Raises ValueError if the race duration exceeds this limit.

    Returns
    -------
    int
        The new race_id.
    """
    race = data.get("race", data)  # accept flat or nested

    # Enforce plan-based duration limit
    duration = race.get("race_duration_s", 10800)
    if max_duration_s is not None and duration > max_duration_s:
        limit_h = max_duration_s / 3600
        raise ValueError(
            f"Race duration exceeds your plan's {limit_h:.0f}-hour limit. "
            f"Upgrade to Racer for unlimited race duration."
        )

    drivers = data.get("drivers", [])
    windows = data.get("windows", [])
    sleep_windows = data.get("sleep_windows", [])

    cur = conn.execute(
        """INSERT INTO race_configs (
            race_name, track_name, team_name, race_duration_s,
            reference_weight_kg, desired_stints, fuel_autonomy_s,
            min_pit_stop_s, pit_speed_kmh, quick_pit_stop_s, pit_open_s, pit_close_s,
            blackout_start_min, blackout_end_min,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed, quick_change_enabled,
            optimization_mode,
            tech_stop_enabled, tech_stop_duration_s,
            tech_stop_window_start_s, tech_stop_window_end_s,
            status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft')
        RETURNING race_id""",
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
            race.get("blackout_start_min"),
            race.get("blackout_end_min"),
            race.get("empty_kart_kg"),
            race.get("full_tank_kg"),
            race.get("min_total_kart_kg"),
            _pg_bool(race.get("weigh_on_pit_exit", 0)),
            race.get("qualifying_duration_s"),
            _pg_bool(race.get("refuel_after_quali", 0)),
            _pg_bool(race.get("mandatory_driver_change", 1), default=True),
            _pg_bool(race.get("refueling_allowed", 1), default=True),
            _pg_bool(race.get("quick_change_enabled", 0)),
            race.get("optimization_mode", "equal"),
            _pg_bool(race.get("tech_stop_enabled", 0)),
            race.get("tech_stop_duration_s", 360),
            race.get("tech_stop_window_start_s"),
            race.get("tech_stop_window_end_s"),
        ),
    )
    _row = cur.fetchone()
    if _row is None:
        raise RuntimeError("INSERT RETURNING race_id returned no row")
    race_id = _row[0] if not isinstance(_row, dict) else _row.get("race_id")

    if drivers:
        _save_drivers(conn, race_id, drivers)
    if windows:
        _save_windows(conn, race_id, windows)
    if sleep_windows:
        # Build index→DB id map: frontend sends 0-based driver_index as driver_id
        driver_id_map = _build_driver_id_map(conn, race_id)
        _save_sleep_windows(conn, race_id, driver_id_map, sleep_windows)

    conn.commit()
    return race_id


def update_race(conn, race_id: int, data: dict, *, max_duration_s: int | None = None) -> bool:
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
    max_duration_s : int | None
        Optional plan-based maximum race duration in seconds.
        Raises ValueError if the race duration exceeds this limit.

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

    # Enforce plan-based duration limit
    duration = cfg.get("race_duration_s", race.get("race_duration_s"))
    if max_duration_s is not None and duration and duration > max_duration_s:
        limit_h = max_duration_s / 3600
        raise ValueError(
            f"Race duration exceeds your plan's {limit_h:.0f}-hour limit. "
            f"Upgrade to Racer for unlimited race duration."
        )

    drivers = data.get("drivers", [])
    windows = data.get("windows", [])
    sleep_windows = data.get("sleep_windows", [])

    conn.execute(
        """UPDATE race_configs SET
            race_name=?, track_name=?, team_name=?, race_duration_s=?,
            reference_weight_kg=?, desired_stints=?, fuel_autonomy_s=?,
            min_pit_stop_s=?, pit_speed_kmh=?, quick_pit_stop_s=?,
            pit_open_s=?, pit_close_s=?,
            blackout_start_min=?, blackout_end_min=?,
            empty_kart_kg=?, full_tank_kg=?, min_total_kart_kg=?,
            weigh_on_pit_exit=?, qualifying_duration_s=?, refuel_after_quali=?,
            mandatory_driver_change=?, refueling_allowed=?, quick_change_enabled=?,
            optimization_mode=?,
            tech_stop_enabled=?, tech_stop_duration_s=?,
            tech_stop_window_start_s=?, tech_stop_window_end_s=?,
            updated_at=CURRENT_TIMESTAMP, status='draft'
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
            cfg.get("blackout_start_min", race.get("blackout_start_min")),
            cfg.get("blackout_end_min", race.get("blackout_end_min")),
            cfg.get("empty_kart_kg", race.get("empty_kart_kg")),
            cfg.get("full_tank_kg", race.get("full_tank_kg")),
            cfg.get("min_total_kart_kg", race.get("min_total_kart_kg")),
            _pg_bool(cfg.get("weigh_on_pit_exit", race.get("weigh_on_pit_exit", 0))),
            cfg.get("qualifying_duration_s", race.get("qualifying_duration_s")),
            _pg_bool(cfg.get("refuel_after_quali", race.get("refuel_after_quali", 0))),
            _pg_bool(cfg.get("mandatory_driver_change", race.get("mandatory_driver_change", 1)), default=True),
            _pg_bool(cfg.get("refueling_allowed", race.get("refueling_allowed", 1)), default=True),
            _pg_bool(cfg.get("quick_change_enabled", race.get("quick_change_enabled", 0))),
            cfg.get("optimization_mode", race.get("optimization_mode", "equal")),
            _pg_bool(cfg.get("tech_stop_enabled", race.get("tech_stop_enabled", 0))),
            cfg.get("tech_stop_duration_s", race.get("tech_stop_duration_s", 360)),
            cfg.get("tech_stop_window_start_s", race.get("tech_stop_window_start_s")),
            cfg.get("tech_stop_window_end_s", race.get("tech_stop_window_end_s")),
            race_id,
        ),
    )

    # Clear and re-save drivers + windows
    conn.execute("DELETE FROM race_drivers WHERE race_id = ?", (race_id,))
    if drivers:
        _save_drivers(conn, race_id, drivers)
    if windows:
        _save_windows(conn, race_id, windows)

    try:
        conn.execute("DELETE FROM race_sleep_windows WHERE race_id = ?", (race_id,))
    except Exception:
        logger.warning("race_sleep_windows table not found — skipping")
    if sleep_windows:
        driver_id_map = _build_driver_id_map(conn, race_id)
        _save_sleep_windows(conn, race_id, driver_id_map, sleep_windows)

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

    Explicitly removes child rows before the parent to avoid FK constraint
    issues when PostgreSQL RLS policies interfere with ON DELETE CASCADE.

    Returns True if a row was deleted, False otherwise.
    """
    # Check existence first
    row = conn.execute(
        "SELECT race_id FROM race_configs WHERE race_id = ?", (race_id,)
    ).fetchone()
    if not row:
        return False

    # Delete children in dependency order (deepest first)
    child_tables = [
        "race_rival_events",
        "race_alerts",
        "race_compound_models",
        "race_strategies",
        "race_rivals",
        "race_neutralizations",
        "race_messages",
        "race_sleep_windows",
        "race_windows",
        "race_pit_stops",
        "race_stints",
        "race_drivers",
    ]
    for table in child_tables:
        conn.execute(f"DELETE FROM {table} WHERE race_id = ?", (race_id,))

    conn.execute("DELETE FROM race_configs WHERE race_id = ?", (race_id,))
    conn.commit()
    return True


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

    sleep_windows = _get_sleep_windows(conn, race_id)
    result = optimize_stints(race, drivers, sleep_windows=sleep_windows)

    # Wrap in engine for fuel/ballast cascade
    engine = RaceStateEngine(race, drivers, result["stints"], result["pit_stops"])
    engine.save(conn, race_id)

    # Update status
    new_status = "ready" if result["feasible"] else "draft"
    conn.execute(
        "UPDATE race_configs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE race_id = ?",
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
        "updated_at = CURRENT_TIMESTAMP WHERE race_id = ?",
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

    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)

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
        "UPDATE race_configs SET status = 'finished', updated_at = CURRENT_TIMESTAMP "
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

    # Auto-activate first planned stint if race is live (not paused) but no active stint
    if not active_stint and race["status"] == "live" and not race.get("paused_at_ts"):
        first_planned = conn.execute(
            "SELECT stint_id FROM race_stints "
            "WHERE race_id = ? AND status = 'planned' ORDER BY stint_order LIMIT 1",
            (race_id,),
        ).fetchone()
        if first_planned:
            elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
            conn.execute(
                "UPDATE race_stints SET status = 'active', actual_start_s = ? "
                "WHERE stint_id = ?",
                (elapsed, first_planned["stint_id"] if isinstance(first_planned, dict) else first_planned[0]),
            )
            conn.commit()
            # Re-read stints
            stints = _rows_to_list(conn.execute(
                "SELECT s.*, d.driver_name, d.weight_kg as driver_weight_kg "
                "FROM race_stints s "
                "JOIN race_drivers d ON s.driver_id = d.id "
                "WHERE s.race_id = ? ORDER BY s.stint_order",
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
        elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
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

    # Optional enrichment — weather alerts
    weather_alerts: list = []
    try:
        from meteo_service import get_weather_forecast

        # Weather enrichment requires track coordinates (lat/lon)
        # Currently not available in race_configs — skip for now
        # Future: add lat/lon to race_configs or resolve from track_name
    except ImportError:
        pass
    except Exception:
        logger.debug("Weather enrichment failed for race %d", race_id)

    # Optional enrichment — race intelligence
    intelligence: dict = {}
    try:
        from race_intelligence import analyze_race
        elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
        intelligence = analyze_race(conn, race_id, elapsed) or {}
    except ImportError:
        pass
    except Exception:
        logger.debug("Intelligence enrichment failed for race %d", race_id)

    # Sleep windows + live status
    sleep_windows = _get_sleep_windows(conn, race_id)
    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    driver_sleep_status = _compute_driver_sleep_status(sleep_windows, elapsed)

    # Auto-update sleep window statuses in DB
    for sw in sleep_windows:
        effective_end = sw.get("actual_wake_s") or sw["end_s"]
        if sw["status"] == "planned" and sw["start_s"] <= elapsed:
            conn.execute(
                "UPDATE race_sleep_windows SET status = 'active' WHERE id = ?",
                (sw["id"],),
            )
            sw["status"] = "active"
        elif sw["status"] == "active" and elapsed >= effective_end:
            conn.execute(
                "UPDATE race_sleep_windows SET status = 'completed' WHERE id = ?",
                (sw["id"],),
            )
            sw["status"] = "completed"
    conn.commit()

    # Pit state
    pit_in_at = race.get("pit_in_at_s")
    in_pit = pit_in_at is not None
    pit_elapsed = (elapsed - pit_in_at) if in_pit else 0

    # Penalties
    try:
        from services.race_strategy_penalty import get_penalties, get_active_passage
        penalties = get_penalties(conn, race_id)
        active_passage = get_active_passage(conn, race_id)
    except Exception:
        penalties = []
        active_passage = None

    return {
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "messages": messages,
        "active_stint": active_stint,
        "next_stint": next_stint,
        "in_pit": in_pit,
        "pit_elapsed_s": pit_elapsed,
        "driver_cumulative": driver_cumulative,
        "weather_alerts": weather_alerts,
        "intelligence": intelligence,
        "sleep_windows": sleep_windows,
        "driver_sleep_status": driver_sleep_status,
        "penalties": penalties,
        "active_passage": active_passage,
        "total_penalty_laps": sum(p.get("laps_deducted", 0) for p in penalties),
        **engine_data,
    }


def end_stint(
    conn,
    race_id: int,
    *,
    driver_change: bool = True,
    refueled: bool = False,
    notes: str | None = None,
    actual_laps: int | None = None,
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

    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    actual_duration = elapsed - (active["actual_start_s"] or 0)

    # Convert total race laps to stint laps by subtracting completed stints
    stint_laps = actual_laps
    if actual_laps is not None:
        prev_laps = conn.execute(
            "SELECT COALESCE(SUM(actual_laps), 0) FROM race_stints "
            "WHERE race_id = ? AND status = 'completed'",
            (race_id,),
        ).fetchone()
        prev_total = prev_laps[0] if prev_laps else 0
        stint_laps = max(0, actual_laps - prev_total)

    conn.execute(
        "UPDATE race_stints SET status = 'completed', actual_end_s = ?, "
        "actual_duration_s = ?, actual_laps = ? WHERE stint_id = ?",
        (elapsed, actual_duration, stint_laps, active["stint_id"]),
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
            bool(driver_change),
            bool(refueled),
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


def pit_in(
    conn,
    race_id: int,
    *,
    actual_laps: int | None = None,
    notes: str | None = None,
) -> dict | None:
    """Car enters pit — end current stint, record pit entry time.

    Does NOT start the next stint. The race enters 'in pit' state
    until ``pit_out`` is called.
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

    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    actual_duration = elapsed - (active["actual_start_s"] or 0)

    # Convert total race laps to stint laps
    stint_laps = actual_laps
    if actual_laps is not None:
        prev_laps = conn.execute(
            "SELECT COALESCE(SUM(actual_laps), 0) FROM race_stints "
            "WHERE race_id = ? AND status = 'completed'",
            (race_id,),
        ).fetchone()
        prev_total = prev_laps[0] if prev_laps else 0
        stint_laps = max(0, actual_laps - prev_total)

    # Complete the stint
    conn.execute(
        "UPDATE race_stints SET status = 'completed', actual_end_s = ?, "
        "actual_duration_s = ?, actual_laps = ? WHERE stint_id = ?",
        (elapsed, actual_duration, stint_laps, active["stint_id"]),
    )

    # Record pit entry time on race config
    conn.execute(
        "UPDATE race_configs SET pit_in_at_s = ? WHERE race_id = ?",
        (elapsed, race_id),
    )

    conn.commit()
    return {"ok": True, "elapsed_s": elapsed, "in_pit": True}


def pit_out(
    conn,
    race_id: int,
    *,
    driver_change: bool = True,
    refueled: bool = False,
    notes: str | None = None,
    kart_number: str | None = None,
) -> dict | None:
    """Car exits pit — record pit stop duration, start next stint.

    Pit duration = elapsed_now - pit_in_at_s. This time is NOT counted
    toward any driver's total.
    """
    race = get_race(conn, race_id)
    if not race:
        return None

    pit_in_at = race.get("pit_in_at_s")
    if pit_in_at is None:
        return None  # not in pit

    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    pit_duration = max(0, elapsed - pit_in_at)

    # Find the last completed stint to link the pit stop
    last_completed = conn.execute(
        "SELECT stint_id FROM race_stints "
        "WHERE race_id = ? AND status = 'completed' ORDER BY stint_order DESC LIMIT 1",
        (race_id,),
    ).fetchone()
    stint_id = (last_completed["stint_id"] if isinstance(last_completed, dict) else last_completed[0]) if last_completed else None

    # Log pit stop with actual duration
    conn.execute(
        """INSERT INTO race_pit_stops
           (race_id, stint_id, actual_at_s, duration_s, driver_change, refueled, notes)
        VALUES (?,?,?,?,?,?,?)""",
        (race_id, stint_id, pit_in_at, pit_duration,
         bool(driver_change), bool(refueled), notes),
    )

    # Start next stint
    next_stint = conn.execute(
        "SELECT stint_id FROM race_stints "
        "WHERE race_id = ? AND status = 'planned' ORDER BY stint_order LIMIT 1",
        (race_id,),
    ).fetchone()
    if next_stint:
        next_stint_id = next_stint["stint_id"] if isinstance(next_stint, dict) else next_stint[0]
        conn.execute(
            "UPDATE race_stints SET status = 'active', actual_start_s = ? "
            "WHERE stint_id = ?",
            (elapsed, next_stint_id),
        )
        if kart_number:
            conn.execute(
                "UPDATE race_stints SET kart_number = ? WHERE stint_id = ?",
                (kart_number, next_stint_id),
            )

    # Clear pit state
    conn.execute(
        "UPDATE race_configs SET pit_in_at_s = NULL WHERE race_id = ?",
        (race_id,),
    )

    conn.commit()
    return {"ok": True, "elapsed_s": elapsed, "pit_duration_s": pit_duration, "in_pit": False}


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
    conn.commit()
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
    conn.commit()
    return engine.snapshot()


def set_stint_driver(conn, race_id: int, stint_order: int, driver_id: int) -> dict | None:
    """Change the driver for a stint and re-cascade.

    Returns the engine snapshot, or None on failure.
    """
    try:
        engine = RaceStateEngine.load(conn, race_id)
    except Exception:
        return None
    engine.set_driver(stint_order, driver_id)
    engine.save(conn, race_id)
    conn.commit()
    return engine.snapshot()


def set_stint_duration(conn, race_id: int, stint_order: int, duration_s: int) -> dict | None:
    """Change the planned duration for a stint and rebuild timeline.

    Returns the engine snapshot, or None on failure.
    """
    try:
        engine = RaceStateEngine.load(conn, race_id)
    except Exception:
        return None
    engine.set_duration(stint_order, duration_s)
    engine.save(conn, race_id)
    conn.commit()
    return engine.snapshot()


def wake_driver(conn, race_id: int, driver_id: int) -> dict | None:
    """Wake a driver early by setting actual_wake_s on their active sleep window.

    Returns {"ok": True, "elapsed_s": <int>} on success, or None if no
    active sleep window found for this driver.
    """
    race = get_race(conn, race_id)
    if not race:
        return None

    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)

    active_window = conn.execute(
        "SELECT id FROM race_sleep_windows "
        "WHERE race_id = ? AND driver_id = ? AND status = 'active' "
        "AND actual_wake_s IS NULL LIMIT 1",
        (race_id, driver_id),
    ).fetchone()
    if not active_window:
        return None

    conn.execute(
        "UPDATE race_sleep_windows SET actual_wake_s = ?, status = 'completed' "
        "WHERE id = ?",
        (elapsed, active_window["id"]),
    )
    conn.commit()
    return {"ok": True, "elapsed_s": elapsed}


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

    # Include both completed AND active stints as "fixed" — don't re-plan them
    fixed_stints = _rows_to_list(conn.execute(
        "SELECT * FROM race_stints WHERE race_id = ? AND status IN ('completed', 'active') "
        "ORDER BY stint_order",
        (race_id,),
    ).fetchall())

    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    sleep_windows = _get_sleep_windows(conn, race_id)
    result = reoptimize_remaining(race, drivers, fixed_stints, elapsed, sleep_windows=sleep_windows)

    # Clear planned stints only (active + completed stay)
    conn.execute(
        "DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'",
        (race_id,),
    )
    # Also clean up orphan pit stops for deleted planned stints
    conn.execute(
        "DELETE FROM race_pit_stops WHERE race_id = ? AND stint_id NOT IN "
        "(SELECT stint_id FROM race_stints WHERE race_id = ?)",
        (race_id, race_id),
    )

    # Wrap in engine for fuel/ballast cascade on new stints
    all_stints = fixed_stints + result["stints"]
    engine = RaceStateEngine(race, drivers, all_stints, result["pit_stops"])

    # Save only the NEW planned stints (fixed stints already in DB)
    for s in engine.stints:
        if s.stint_order > len(fixed_stints):
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
    sleep_windows = _rows_to_list(conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ? ORDER BY start_s",
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
        "sleep_windows": sleep_windows,
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
            blackout_start_min, blackout_end_min,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed, optimization_mode,
            tech_stop_enabled, tech_stop_duration_s,
            tech_stop_window_start_s, tech_stop_window_end_s,
            status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft')
        RETURNING race_id""",
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
            race.get("blackout_start_min"),
            race.get("blackout_end_min"),
            race.get("empty_kart_kg"),
            race.get("full_tank_kg"),
            race.get("min_total_kart_kg"),
            _pg_bool(race.get("weigh_on_pit_exit", 0)),
            race.get("qualifying_duration_s"),
            _pg_bool(race.get("refuel_after_quali", 0)),
            _pg_bool(race.get("mandatory_driver_change", 1), default=True),
            _pg_bool(race.get("refueling_allowed", 1), default=True),
            race.get("optimization_mode", "equal"),
            _pg_bool(race.get("tech_stop_enabled", 0)),
            race.get("tech_stop_duration_s", 360),
            race.get("tech_stop_window_start_s"),
            race.get("tech_stop_window_end_s"),
        ),
    )
    _row = cur.fetchone()
    if _row is None:
        raise RuntimeError("INSERT RETURNING race_id returned no row")
    new_race_id = _row[0] if not isinstance(_row, dict) else _row.get("race_id")

    # Insert drivers, building old_id -> new_id map
    id_map: dict[int, int] = {}
    for d in data.get("drivers", []):
        old_id = d.get("id")
        dcur = conn.execute(
            """INSERT INTO race_drivers (
                race_id, driver_name, driver_order, min_stint_s, max_stint_s,
                min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg,
                com_channel, color_hex
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            RETURNING id""",
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
        _drow = dcur.fetchone()
        if _drow is None:
            continue
        new_driver_id = _drow[0] if not isinstance(_drow, dict) else _drow.get("id")
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

    # Import sleep windows
    for sw in data.get("sleep_windows", []):
        old_driver_id = sw.get("driver_id")
        new_driver_id = id_map.get(old_driver_id, old_driver_id)
        conn.execute(
            "INSERT INTO race_sleep_windows "
            "(race_id, driver_id, start_s, end_s, label, status) "
            "VALUES (?,?,?,?,?,?)",
            (new_race_id, new_driver_id,
             sw.get("start_s", 0), sw.get("end_s", 0),
             sw.get("label"), sw.get("status", "planned")),
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
            blackout_start_min, blackout_end_min,
            empty_kart_kg, full_tank_kg, min_total_kart_kg,
            weigh_on_pit_exit, qualifying_duration_s, refuel_after_quali,
            mandatory_driver_change, refueling_allowed, optimization_mode, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft')
        RETURNING race_id""",
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
            r.get("blackout_start_min"),
            r.get("blackout_end_min"),
            r["empty_kart_kg"],
            r["full_tank_kg"],
            r["min_total_kart_kg"],
            _pg_bool(r["weigh_on_pit_exit"]),
            r["qualifying_duration_s"],
            _pg_bool(r["refuel_after_quali"]),
            _pg_bool(r["mandatory_driver_change"], default=True),
            _pg_bool(r["refueling_allowed"], default=True),
            r.get("optimization_mode", "equal"),
        ),
    )
    _row = cur.fetchone()
    if _row is None:
        return None
    new_id = _row[0] if not isinstance(_row, dict) else _row.get("race_id")

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

    # Copy sleep windows
    old_sleep = conn.execute(
        "SELECT * FROM race_sleep_windows WHERE race_id = ?", (race_id,)
    ).fetchall()
    new_drivers_list = conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
        (new_id,),
    ).fetchall()
    sleep_id_map = {}
    for old_d, new_d in zip(old_drivers, new_drivers_list):
        sleep_id_map[_row_to_dict(old_d)["id"]] = _row_to_dict(new_d)["id"]
    for sw in old_sleep:
        swd = _row_to_dict(sw)
        new_did = sleep_id_map.get(swd["driver_id"], swd["driver_id"])
        conn.execute(
            "INSERT INTO race_sleep_windows "
            "(race_id, driver_id, start_s, end_s, label, status) "
            "VALUES (?,?,?,?,?,?)",
            (new_id, new_did, swd["start_s"], swd["end_s"],
             swd.get("label"), "planned"),
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
