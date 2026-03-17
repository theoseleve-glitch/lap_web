"""
Race strategy bridge service — links endurance sessions to race strategy.

Creates retrospective race configs from detected endurance stints,
populates actuals from real stint data, and provides planned-vs-actual
comparison.

No Flask imports — accepts a DB connection as first argument and returns
plain dicts.  SQL uses ``?`` positional parameters; the ``sql_compat``
layer auto-translates to ``%(name)s`` / ``%s`` for PostgreSQL at call
time.
"""
from __future__ import annotations

import logging
import statistics
import sys
from pathlib import Path
from typing import Any

_parent = str(Path(__file__).resolve().parents[1])  # telemetry_tool/
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from endurance_scoring import compute_stint_scores  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    """Convert a DB row to a plain dict."""
    if row is None:
        return {}
    return dict(row)


def _rows_to_list(rows) -> list[dict]:
    """Convert a list of DB rows to a list of plain dicts."""
    return [dict(r) for r in rows]


def _get_laps_for_session(conn, session_id: str) -> list[dict]:
    """Read all laps for a session."""
    rows = conn.execute(
        "SELECT * FROM laps WHERE session_id = :sid ORDER BY lap_number",
        {"sid": session_id},
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_race_from_session(
    conn,
    session_id: str,
    race_meta: dict[str, Any],
    driver_map: dict[int, str],
    *,
    max_duration_s: int | None = None,
) -> int:
    """Create a retrospective race config from an endurance session.

    1. Read endurance_stints for session_id
    2. Validate: at least 2 stints exist, driver_map covers all stint_numbers
    3. Build race config from race_meta + detected stint data
    4. Call services.race_strategy.create_race() to persist
    5. Run optimizer via services.race_strategy.run_optimization()
    6. Populate race_actuals from real stint data
    7. Compute delta_duration_s per stint
    8. Return race_id

    Parameters
    ----------
    conn : DB connection
    session_id : str
        The telemetry session to bridge from.
    race_meta : dict
        Race config overrides: race_name, track_name, team_name, etc.
    driver_map : dict[int, str]
        Maps stint_number (1-based) to driver_name.
    max_duration_s : int | None
        Optional plan-based duration limit.

    Returns
    -------
    int
        The new race_id.

    Raises
    ------
    ValueError
        If validation fails (too few stints, missing drivers, etc.).
    """
    from web.repos.endurance_repo import get_stints  # noqa: E402
    from services.race_strategy import create_race, run_optimization  # noqa: E402

    # 1. Read stints
    stints = get_stints(conn, session_id)
    if len(stints) < 2:
        raise ValueError(
            f"Need at least 2 stints for a race bridge, found {len(stints)}"
        )

    # 2. Validate driver_map covers all stint_numbers
    stint_numbers = {s["stint_number"] for s in stints}
    missing = stint_numbers - set(driver_map.keys())
    if missing:
        raise ValueError(
            f"driver_map missing stint numbers: {sorted(missing)}"
        )

    # Compute total race duration from stints
    all_laps = _get_laps_for_session(conn, session_id)
    lap_times = {}
    for lap in all_laps:
        ln = lap.get("lap_number")
        lt = lap.get("lap_time_s")
        if ln is not None and lt is not None and lt > 0:
            lap_times[ln] = lt

    # Total time = sum of all valid lap times across all stints
    total_time_s = 0
    for stint in stints:
        for ln in range(stint["start_lap"], stint["end_lap"] + 1):
            if ln in lap_times:
                total_time_s += lap_times[ln]
        # Include pit lap time if present
        if stint.get("pit_lap_time_s"):
            total_time_s += stint["pit_lap_time_s"]

    total_time_s = int(total_time_s)

    # 3. Build race config payload
    # Unique driver names from the map
    unique_drivers = list(dict.fromkeys(driver_map.values()))
    drivers_payload = []
    for i, name in enumerate(unique_drivers):
        drivers_payload.append({
            "driver_name": name,
            "driver_order": i + 1,
        })

    race_config = {
        "race_name": race_meta.get("race_name", f"Endurance session {session_id[:8]}"),
        "track_name": race_meta.get("track_name"),
        "team_name": race_meta.get("team_name"),
        "race_duration_s": race_meta.get("race_duration_s", total_time_s),
        "desired_stints": len(stints),
        "min_pit_stop_s": race_meta.get("min_pit_stop_s", 60),
        "fuel_autonomy_s": race_meta.get("fuel_autonomy_s"),
        "empty_kart_kg": race_meta.get("empty_kart_kg"),
        "full_tank_kg": race_meta.get("full_tank_kg"),
        "min_total_kart_kg": race_meta.get("min_total_kart_kg"),
    }

    data = {
        "race": race_config,
        "drivers": drivers_payload,
        "windows": race_meta.get("windows", []),
    }

    # 4. Create race
    race_id = create_race(conn, data, max_duration_s=max_duration_s)

    # Link session and mark as retrospective
    conn.execute(
        "UPDATE race_configs SET session_id = ?, is_retrospective = true "
        "WHERE race_id = ?",
        (session_id, race_id),
    )
    # 5. Run optimizer (generates planned stints)
    run_optimization(conn, race_id)

    # 6. Populate race_actuals from real stint data
    _populate_actuals(conn, race_id, stints, all_laps, driver_map, lap_times)

    return race_id


def _populate_actuals(
    conn,
    race_id: int,
    stints: list[dict],
    all_laps: list[dict],
    driver_map: dict[int, str],
    lap_times: dict[int, float],
) -> None:
    """Insert race_actuals rows from real stint data.

    Also computes delta_duration_s by comparing to planned stints.
    """
    # Read planned stints for delta computation
    planned_rows = conn.execute(
        "SELECT stint_order, planned_duration_s FROM race_stints "
        "WHERE race_id = ? ORDER BY stint_order",
        (race_id,),
    ).fetchall()
    planned_by_order = {
        r["stint_order"]: r["planned_duration_s"]
        for r in planned_rows
    }

    # Compute cumulative start time for each stint
    clock_s = 0
    for stint_idx, stint in enumerate(stints):
        stint_num = stint["stint_number"]

        # Compute stint metrics from laps
        stint_lap_times = []
        for ln in range(stint["start_lap"], stint["end_lap"] + 1):
            if ln in lap_times:
                stint_lap_times.append(lap_times[ln])

        actual_duration_s = int(sum(stint_lap_times)) if stint_lap_times else 0
        actual_lap_count = len(stint_lap_times)
        actual_best = round(min(stint_lap_times), 3) if stint_lap_times else None
        actual_mean = round(statistics.mean(stint_lap_times), 3) if stint_lap_times else None

        # Consistency CV
        cv = None
        if len(stint_lap_times) > 1 and actual_mean and actual_mean > 0:
            std = statistics.stdev(stint_lap_times)
            cv = round(std / actual_mean * 100, 2)

        # Pace fade
        pace_fade = None
        if len(stint_lap_times) >= 3:
            third = max(1, len(stint_lap_times) // 3)
            early = statistics.mean(stint_lap_times[:third])
            late = statistics.mean(stint_lap_times[-third:])
            if early > 0:
                pace_fade = round((late - early) / early * 100, 2)

        actual_start_s = int(clock_s)
        actual_end_s = int(clock_s + actual_duration_s)

        # Delta vs planned — match by position (index), not stint_number,
        # because the optimizer may assign different stint_order values
        planned_dur = planned_by_order.get(stint_idx + 1)  # optimizer uses 1-based stint_order
        delta = (actual_duration_s - planned_dur) if planned_dur is not None else None

        conn.execute(
            "INSERT INTO race_actuals "
            "(race_id, stint_order, actual_start_s, actual_end_s, "
            " actual_duration_s, actual_lap_count, actual_best_lap_s, "
            " actual_mean_lap_s, actual_consistency_cv_pct, actual_pace_fade_pct, "
            " delta_duration_s) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                race_id, stint_idx + 1, actual_start_s, actual_end_s,
                actual_duration_s, actual_lap_count, actual_best,
                actual_mean, cv, pace_fade, delta,
            ),
        )

        # Advance clock (include pit lap if present)
        clock_s += actual_duration_s
        if stint.get("pit_lap_time_s"):
            clock_s += stint["pit_lap_time_s"]


def get_planned_vs_actual(conn, race_id: int) -> dict | None:
    """Return planned-vs-actual comparison for a race.

    Queries race_stints (planned) and race_actuals, then builds a per-stint
    comparison with summary totals and per-driver deltas.

    Parameters
    ----------
    conn : DB connection
    race_id : int

    Returns
    -------
    dict | None
        ``{race, stints: [{planned, actual, delta}], summary}``
        Returns None if race not found.
    """
    # Get race config
    race_row = conn.execute(
        "SELECT * FROM race_configs WHERE race_id = ?", (race_id,)
    ).fetchone()
    if not race_row:
        return None
    race = _row_to_dict(race_row)

    # Get planned stints
    planned_rows = conn.execute(
        "SELECT rs.*, rd.driver_name FROM race_stints rs "
        "LEFT JOIN race_drivers rd ON rs.driver_id = rd.id "
        "WHERE rs.race_id = ? ORDER BY rs.stint_order",
        (race_id,),
    ).fetchall()
    planned = _rows_to_list(planned_rows)

    # Get actuals
    actual_rows = conn.execute(
        "SELECT * FROM race_actuals WHERE race_id = ? ORDER BY stint_order",
        (race_id,),
    ).fetchall()
    actual_by_order = {r["stint_order"]: _row_to_dict(r) for r in actual_rows}

    # Build per-stint comparison
    stints_comparison = []
    total_planned_s = 0
    total_actual_s = 0
    driver_deltas: dict[str, dict[str, Any]] = {}

    for p in planned:
        stint_order = p["stint_order"]
        driver_name = p.get("driver_name", "Unknown")
        a = actual_by_order.get(stint_order, {})

        planned_dur = p.get("planned_duration_s", 0)
        actual_dur = a.get("actual_duration_s")
        delta_dur = a.get("delta_duration_s")

        total_planned_s += planned_dur or 0
        total_actual_s += actual_dur or 0

        stints_comparison.append({
            "stint_order": stint_order,
            "driver_name": driver_name,
            "planned": {
                "start_s": p.get("planned_start_s"),
                "end_s": p.get("planned_end_s"),
                "duration_s": planned_dur,
            },
            "actual": {
                "start_s": a.get("actual_start_s"),
                "end_s": a.get("actual_end_s"),
                "duration_s": actual_dur,
                "lap_count": a.get("actual_lap_count"),
                "best_lap_s": a.get("actual_best_lap_s"),
                "mean_lap_s": a.get("actual_mean_lap_s"),
                "consistency_cv_pct": a.get("actual_consistency_cv_pct"),
                "pace_fade_pct": a.get("actual_pace_fade_pct"),
            },
            "delta_duration_s": delta_dur,
        })

        # Accumulate per-driver deltas
        if driver_name not in driver_deltas:
            driver_deltas[driver_name] = {
                "planned_s": 0,
                "actual_s": 0,
                "delta_s": 0,
                "stint_count": 0,
            }
        dd = driver_deltas[driver_name]
        dd["planned_s"] += planned_dur or 0
        dd["actual_s"] += actual_dur or 0
        dd["delta_s"] += delta_dur or 0
        dd["stint_count"] += 1

    return {
        "race": {
            "race_id": race.get("race_id"),
            "race_name": race.get("race_name"),
            "session_id": race.get("session_id"),
            "is_retrospective": bool(race.get("is_retrospective")),
            "race_duration_s": race.get("race_duration_s"),
            "status": race.get("status"),
        },
        "stints": stints_comparison,
        "summary": {
            "total_planned_s": total_planned_s,
            "total_actual_s": total_actual_s,
            "delta_s": total_actual_s - total_planned_s,
            "driver_deltas": driver_deltas,
        },
    }
