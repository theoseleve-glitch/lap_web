# Race Strategy Port — Phase A Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port the endurance race strategy tool from Flask/Jinja2 to a REST API + Next.js frontend, replacing the current sprint-race stub.

**Architecture:** New `/api/v1/race-strategy/` Flask blueprint wraps existing `RaceStateEngine` + `optimize_stints()` logic with proper auth/RLS. Frontend is 5 React pages using TanStack Query for data fetching — list, config (new/edit), detail, live dashboard, summary.

**Tech Stack:** Flask (Blueprint, api_utils envelope), PostgreSQL 16 (existing tables + RLS), Next.js 14, TanStack React Query, Tailwind CSS, Zustand

---

### Task 1: Extract Service Layer from race_strategy_v2.py

The existing Flask routes at `telemetry_tool/web/routes/race_strategy_v2.py` mix HTTP concerns (render_template, redirect, request parsing) with business logic (DB queries, optimization calls, engine loading). We need a service module that the new API blueprint can call without duplicating logic.

**Files:**
- Create: `telemetry_tool/services/race_strategy.py`
- Reference: `telemetry_tool/web/routes/race_strategy_v2.py` (lines 160-1350)
- Reference: `telemetry_tool/race_state_engine.py` (RaceStateEngine class)

**Step 1: Create the service module**

Create `telemetry_tool/services/race_strategy.py` with these functions extracted from `race_strategy_v2.py`. The service layer accepts a DB connection and returns dicts — no Flask imports.

```python
"""Race strategy service layer.

Pure business logic for endurance race management. No Flask imports —
accepts a DB connection and returns plain dicts.

Used by both the legacy Jinja2 routes (race_strategy_v2.py) and the
new API blueprint (api_v1_race_strategy.py).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────

def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    return dict(row)


def _rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


def _compute_elapsed_s(race_start_ts: str | None) -> int:
    """Compute elapsed seconds since race start timestamp."""
    if not race_start_ts:
        return 0
    try:
        start = datetime.fromisoformat(race_start_ts.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - start).total_seconds()))
    except Exception:
        return 0


# ── Core Operations ─────────────────────────────

def list_races(conn) -> list[dict]:
    """Return all races, newest first."""
    rows = conn.execute(
        "SELECT * FROM race_configs ORDER BY race_id DESC"
    ).fetchall()
    return _rows_to_list(rows)


def get_race(conn, race_id: int) -> dict | None:
    """Return a single race config or None."""
    row = conn.execute(
        "SELECT * FROM race_configs WHERE race_id = :race_id",
        {"race_id": race_id},
    ).fetchone()
    return _row_to_dict(row) if row else None


def get_race_detail(conn, race_id: int) -> dict | None:
    """Return full race detail: config + drivers + stints + pit_stops + windows."""
    race = get_race(conn, race_id)
    if not race:
        return None
    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = :rid ORDER BY driver_order",
        {"rid": race_id},
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name, d.weight_kg as driver_weight_kg "
        "FROM race_stints s JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = :rid ORDER BY s.stint_order",
        {"rid": race_id},
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = :rid ORDER BY planned_at_s",
        {"rid": race_id},
    ).fetchall())
    windows = _rows_to_list(conn.execute(
        "SELECT * FROM race_windows WHERE race_id = :rid ORDER BY window_order",
        {"rid": race_id},
    ).fetchall())
    return {
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "windows": windows,
    }


def create_race(conn, data: dict) -> int:
    """Insert race config + drivers + windows. Return race_id."""
    race = data["race"]
    cur = conn.execute(
        """INSERT INTO race_configs (
            race_name, track_name, team_name, race_duration_s, desired_stints,
            fuel_autonomy_s, min_pit_stop_s, pit_speed_kmh, pit_open_s, pit_close_s,
            empty_kart_kg, full_tank_kg, min_total_kart_kg, weigh_on_pit_exit,
            qualifying_duration_s, refuel_after_quali, mandatory_driver_change,
            refueling_allowed, quick_pit_stop_s, reference_weight_kg, status
        ) VALUES (
            :race_name, :track_name, :team_name, :race_duration_s, :desired_stints,
            :fuel_autonomy_s, :min_pit_stop_s, :pit_speed_kmh, :pit_open_s, :pit_close_s,
            :empty_kart_kg, :full_tank_kg, :min_total_kart_kg, :weigh_on_pit_exit,
            :qualifying_duration_s, :refuel_after_quali, :mandatory_driver_change,
            :refueling_allowed, :quick_pit_stop_s, :reference_weight_kg, 'draft'
        )""",
        race,
    )
    race_id = cur.lastrowid
    # In PG mode, use RETURNING — handled by sql_compat or explicit query
    if race_id is None:
        row = conn.execute("SELECT lastval()").fetchone()
        race_id = row[0] if row else None

    _save_drivers(conn, race_id, data.get("drivers", []))
    _save_windows(conn, race_id, data.get("windows", []))
    conn.commit()
    return race_id


def update_race(conn, race_id: int, data: dict) -> bool:
    """Update race config + drivers + windows. Return True if found."""
    race = get_race(conn, race_id)
    if not race:
        return False

    fields = data.get("race", {})
    if fields:
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["race_id"] = race_id
        conn.execute(
            f"UPDATE race_configs SET {set_clause}, updated_at = datetime('now') "
            f"WHERE race_id = :race_id",
            fields,
        )

    if "drivers" in data:
        conn.execute("DELETE FROM race_drivers WHERE race_id = :rid", {"rid": race_id})
        _save_drivers(conn, race_id, data["drivers"])

    if "windows" in data:
        conn.execute("DELETE FROM race_windows WHERE race_id = :rid", {"rid": race_id})
        _save_windows(conn, race_id, data["windows"])

    conn.commit()
    return True


def delete_race(conn, race_id: int) -> bool:
    """Delete race and all related data (FK CASCADE). Return True if found."""
    race = get_race(conn, race_id)
    if not race:
        return False
    conn.execute("DELETE FROM race_configs WHERE race_id = :rid", {"rid": race_id})
    conn.commit()
    return True


def run_optimization(conn, race_id: int) -> dict:
    """Run stint optimization and save results via RaceStateEngine."""
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from race_strategy_v2 import optimize_stints
    from race_state_engine import RaceStateEngine

    race = get_race(conn, race_id)
    if not race:
        raise ValueError(f"Race {race_id} not found")

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = :rid ORDER BY driver_order",
        {"rid": race_id},
    ).fetchall())

    result = optimize_stints(race, drivers)
    engine = RaceStateEngine(race, drivers, result["stints"], result["pit_stops"])
    engine.save(conn, race_id)

    new_status = "ready" if result["feasible"] else "draft"
    conn.execute(
        "UPDATE race_configs SET status = :status, updated_at = datetime('now') "
        "WHERE race_id = :rid",
        {"status": new_status, "rid": race_id},
    )
    conn.commit()
    return {"stints": result["stints"], "pit_stops": result["pit_stops"],
            "feasible": result["feasible"]}


def go_live(conn, race_id: int) -> bool:
    """Transition race from 'ready' to 'live'. Start the first stint."""
    race = get_race(conn, race_id)
    if not race or race["status"] != "ready":
        return False

    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE race_configs SET status = 'live', race_start_ts = :ts, "
        "updated_at = datetime('now') WHERE race_id = :rid",
        {"ts": now_iso, "rid": race_id},
    )
    first = conn.execute(
        "SELECT stint_id FROM race_stints WHERE race_id = :rid "
        "ORDER BY stint_order LIMIT 1",
        {"rid": race_id},
    ).fetchone()
    if first:
        conn.execute(
            "UPDATE race_stints SET status = 'active', actual_start_s = 0 "
            "WHERE stint_id = :sid",
            {"sid": first["stint_id"]},
        )
    conn.commit()
    return True


def finish_race(conn, race_id: int) -> bool:
    """End the race — mark remaining stints skipped, set status to finished."""
    race = get_race(conn, race_id)
    if not race or race["status"] not in ("live", "ready"):
        return False

    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    # Complete active stint
    conn.execute(
        "UPDATE race_stints SET status = 'completed', actual_end_s = :elapsed "
        "WHERE race_id = :rid AND status = 'active'",
        {"elapsed": elapsed, "rid": race_id},
    )
    # Skip remaining planned stints
    conn.execute(
        "UPDATE race_stints SET status = 'skipped' "
        "WHERE race_id = :rid AND status = 'planned'",
        {"rid": race_id},
    )
    conn.execute(
        "UPDATE race_configs SET status = 'finished', updated_at = datetime('now') "
        "WHERE race_id = :rid",
        {"rid": race_id},
    )
    conn.commit()
    return True


def get_live_state(conn, race_id: int) -> dict | None:
    """Return full live state for dashboard polling."""
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)

    race = get_race(conn, race_id)
    if not race:
        return None

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = :rid ORDER BY driver_order",
        {"rid": race_id},
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT s.*, d.driver_name, d.weight_kg as driver_weight_kg "
        "FROM race_stints s JOIN race_drivers d ON s.driver_id = d.id "
        "WHERE s.race_id = :rid ORDER BY s.stint_order",
        {"rid": race_id},
    ).fetchall())
    pit_stops = _rows_to_list(conn.execute(
        "SELECT * FROM race_pit_stops WHERE race_id = :rid ORDER BY planned_at_s",
        {"rid": race_id},
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

    # Engine-computed data
    engine_data = {}
    try:
        from race_state_engine import RaceStateEngine
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
        logger.debug("Engine load failed for race %d", race_id)

    return {
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "active_stint": active_stint,
        "next_stint": next_stint,
        "driver_cumulative": driver_cumulative,
        **engine_data,
    }


def end_stint(conn, race_id: int, **kwargs) -> dict | None:
    """End the active stint and start the next one."""
    race = get_race(conn, race_id)
    if not race:
        return None

    active = conn.execute(
        "SELECT * FROM race_stints WHERE race_id = :rid AND status = 'active'",
        {"rid": race_id},
    ).fetchone()
    if not active:
        return None

    elapsed = _compute_elapsed_s(race.get("race_start_ts"))
    actual_duration = elapsed - (dict(active).get("actual_start_s") or 0)

    conn.execute(
        "UPDATE race_stints SET status = 'completed', actual_end_s = :elapsed, "
        "actual_duration_s = :dur WHERE stint_id = :sid",
        {"elapsed": elapsed, "dur": actual_duration, "sid": active["stint_id"]},
    )
    # Log pit stop
    conn.execute(
        "INSERT INTO race_pit_stops (race_id, stint_id, actual_at_s, "
        "driver_change, refueled, notes) VALUES (:rid, :sid, :at, :dc, :rf, :notes)",
        {
            "rid": race_id, "sid": active["stint_id"], "at": elapsed,
            "dc": 1 if kwargs.get("driver_change", True) else 0,
            "rf": 1 if kwargs.get("refueled", False) else 0,
            "notes": kwargs.get("notes"),
        },
    )
    # Start next stint
    next_stint = conn.execute(
        "SELECT stint_id FROM race_stints WHERE race_id = :rid AND status = 'planned' "
        "ORDER BY stint_order LIMIT 1",
        {"rid": race_id},
    ).fetchone()
    if next_stint:
        conn.execute(
            "UPDATE race_stints SET status = 'active', actual_start_s = :elapsed "
            "WHERE stint_id = :sid",
            {"elapsed": elapsed, "sid": next_stint["stint_id"]},
        )
    conn.commit()
    return {"ok": True, "elapsed_s": elapsed}


def toggle_fuel(conn, race_id: int, stint_order: int) -> dict | None:
    """Toggle refuel on a stint. Returns updated snapshot."""
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from race_state_engine import RaceStateEngine

    engine = RaceStateEngine.load(conn, race_id)
    engine.toggle_fuel(stint_order)
    engine.save(conn, race_id)
    conn.commit()
    return engine.snapshot()


def set_pit_type(conn, race_id: int, stint_order: int, pit_type: str) -> dict | None:
    """Set pit type (full/quick). Returns updated snapshot."""
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from race_state_engine import RaceStateEngine

    engine = RaceStateEngine.load(conn, race_id)
    engine.set_pit_type(stint_order, pit_type)
    engine.save(conn, race_id)
    conn.commit()
    return engine.snapshot()


def reoptimize(conn, race_id: int) -> dict:
    """Re-optimize remaining stints mid-race."""
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from race_strategy_v2 import optimize_stints
    from race_state_engine import RaceStateEngine

    race = get_race(conn, race_id)
    if not race:
        raise ValueError(f"Race {race_id} not found")

    elapsed = _compute_elapsed_s(race.get("race_start_ts"))

    drivers = _rows_to_list(conn.execute(
        "SELECT * FROM race_drivers WHERE race_id = :rid ORDER BY driver_order",
        {"rid": race_id},
    ).fetchall())
    stints = _rows_to_list(conn.execute(
        "SELECT * FROM race_stints WHERE race_id = :rid ORDER BY stint_order",
        {"rid": race_id},
    ).fetchall())

    completed = [s for s in stints if s["status"] in ("completed", "active")]
    active = next((s for s in stints if s["status"] == "active"), None)

    remaining_s = race["race_duration_s"] - elapsed
    if remaining_s <= 0:
        return {"stints": [], "pit_stops": []}

    reopt_config = dict(race)
    reopt_config["race_duration_s"] = remaining_s

    # Build cumulative times for constraint checks
    driver_cumulative = {}
    for s in completed:
        did = s["driver_id"]
        dur = s.get("actual_duration_s") or s.get("planned_duration_s") or 0
        driver_cumulative[did] = driver_cumulative.get(did, 0) + dur

    result = optimize_stints(reopt_config, drivers)

    # Delete planned stints and merge
    conn.execute(
        "DELETE FROM race_stints WHERE race_id = :rid AND status = 'planned'",
        {"rid": race_id},
    )
    max_order = max((s["stint_order"] for s in completed), default=0)
    for i, s in enumerate(result["stints"]):
        s["stint_order"] = max_order + i + 1
        s["planned_start_s"] = elapsed + s.get("planned_start_s", 0)
        s["planned_end_s"] = elapsed + s.get("planned_end_s", 0)

    # Save via engine
    all_stints = completed + result["stints"]
    engine = RaceStateEngine(race, drivers, all_stints, result.get("pit_stops", []))
    engine.save(conn, race_id)
    conn.commit()
    return result


def export_race(conn, race_id: int) -> dict | None:
    """Export full race as JSON dict."""
    detail = get_race_detail(conn, race_id)
    if not detail:
        return None
    return detail


def import_race(conn, data: dict) -> int:
    """Import a race from JSON dict. Returns new race_id."""
    return create_race(conn, data)


def duplicate_race(conn, race_id: int) -> int | None:
    """Duplicate a race config + drivers + windows. Returns new race_id."""
    detail = get_race_detail(conn, race_id)
    if not detail:
        return None
    import_data = {
        "race": {**detail["race"], "race_name": detail["race"]["race_name"] + " (copy)"},
        "drivers": detail["drivers"],
        "windows": detail["windows"],
    }
    # Remove IDs so they get auto-generated
    for key in ("race_id", "created_at", "updated_at", "race_start_ts", "status"):
        import_data["race"].pop(key, None)
    for d in import_data["drivers"]:
        d.pop("id", None)
    for w in import_data["windows"]:
        w.pop("id", None)
    return create_race(conn, import_data)


def get_summary(conn, race_id: int) -> dict | None:
    """Post-race summary stats."""
    detail = get_race_detail(conn, race_id)
    if not detail:
        return None

    race = detail["race"]
    stints = detail["stints"]
    pit_stops = detail["pit_stops"]
    drivers = detail["drivers"]

    completed_stints = [s for s in stints if s["status"] == "completed"]
    total_drive_s = sum(s.get("actual_duration_s") or s.get("planned_duration_s") or 0
                        for s in completed_stints)
    total_pit_s = sum(s.get("duration_s") or 0 for s in pit_stops)

    # Per-driver stats
    driver_stats = {}
    for s in completed_stints:
        did = s["driver_id"]
        dur = s.get("actual_duration_s") or s.get("planned_duration_s") or 0
        if did not in driver_stats:
            driver_stats[did] = {
                "driver_name": s.get("driver_name", "?"),
                "total_drive_s": 0,
                "stint_count": 0,
                "longest_s": 0,
                "shortest_s": float("inf"),
            }
        ds = driver_stats[did]
        ds["total_drive_s"] += dur
        ds["stint_count"] += 1
        ds["longest_s"] = max(ds["longest_s"], dur)
        ds["shortest_s"] = min(ds["shortest_s"], dur)

    for ds in driver_stats.values():
        if ds["shortest_s"] == float("inf"):
            ds["shortest_s"] = 0

    return {
        **detail,
        "total_drive_s": total_drive_s,
        "total_pit_s": total_pit_s,
        "stint_count": len(completed_stints),
        "pit_stop_count": len(pit_stops),
        "driver_count": len(drivers),
        "driver_stats": driver_stats,
    }


# ── Private Helpers ─────────────────────────────

def _save_drivers(conn, race_id: int, drivers: list[dict]) -> None:
    for i, d in enumerate(drivers):
        conn.execute(
            """INSERT INTO race_drivers (
                race_id, driver_name, driver_order, min_stint_s, max_stint_s,
                min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg,
                com_channel, color_hex
            ) VALUES (
                :race_id, :driver_name, :driver_order, :min_stint_s, :max_stint_s,
                :min_cumulative_s, :max_cumulative_s, :min_rest_s, :weight_kg,
                :com_channel, :color_hex
            )""",
            {
                "race_id": race_id,
                "driver_name": d.get("driver_name", f"Driver {i+1}"),
                "driver_order": d.get("driver_order", i + 1),
                "min_stint_s": d.get("min_stint_s"),
                "max_stint_s": d.get("max_stint_s"),
                "min_cumulative_s": d.get("min_cumulative_s"),
                "max_cumulative_s": d.get("max_cumulative_s"),
                "min_rest_s": d.get("min_rest_s", 0),
                "weight_kg": d.get("weight_kg"),
                "com_channel": d.get("com_channel"),
                "color_hex": d.get("color_hex"),
            },
        )


def _save_windows(conn, race_id: int, windows: list[dict]) -> None:
    for i, w in enumerate(windows):
        conn.execute(
            """INSERT INTO race_windows (
                race_id, window_type, label, start_s, end_s,
                refuel_allowed, driver_change_allowed, window_order
            ) VALUES (
                :race_id, :window_type, :label, :start_s, :end_s,
                :refuel_allowed, :driver_change_allowed, :window_order
            )""",
            {
                "race_id": race_id,
                "window_type": w.get("window_type", "pitlane"),
                "label": w.get("label"),
                "start_s": w.get("start_s", 0),
                "end_s": w.get("end_s", 0),
                "refuel_allowed": w.get("refuel_allowed", 1),
                "driver_change_allowed": w.get("driver_change_allowed", 1),
                "window_order": w.get("window_order", i + 1),
            },
        )
```

**Step 2: Create `__init__.py` if needed**

Run: `ls telemetry_tool/services/`

If the directory doesn't exist:
```bash
mkdir -p telemetry_tool/services
touch telemetry_tool/services/__init__.py
```

**Step 3: Commit**

```bash
git add telemetry_tool/services/race_strategy.py telemetry_tool/services/__init__.py
git commit -m "refactor: extract race strategy service layer from v2 routes"
```

---

### Task 2: Create API Blueprint

New REST API blueprint at `/api/v1/race-strategy/` that wraps the service layer with auth/RLS envelope responses.

**Files:**
- Create: `telemetry_tool/web/routes/api_v1_race_strategy.py`
- Reference: `telemetry_tool/web/routes/api_v1_account.py` (pattern)
- Reference: `telemetry_tool/web/api_utils.py` (api_response, api_error, ErrorCode)

**Step 1: Create the API blueprint**

```python
"""V1 race strategy API — endurance race management.

Blueprint: ``/api/v1/race-strategy/`` — CRUD, optimization, live race,
import/export, duplication, and post-race summary.
"""
from __future__ import annotations

import json
import logging

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, api_error, api_response

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1_race_strategy", __name__, url_prefix="/api/v1/race-strategy")

# ---- Rate limit import (graceful fallback) ----
try:
    from web.rate_limit import rate_limit
except ImportError:
    def rate_limit(**kwargs):
        def decorator(fn):
            return fn
        return decorator


def _get_conn():
    """Get DB connection — PG with RLS context already set by tenant middleware."""
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _get_service():
    """Lazy import to avoid circular imports."""
    from services.race_strategy import (
        list_races, get_race, get_race_detail, create_race, update_race,
        delete_race, run_optimization, go_live, finish_race, get_live_state,
        end_stint, toggle_fuel, set_pit_type, reoptimize, export_race,
        import_race, duplicate_race, get_summary,
    )
    return {
        "list_races": list_races,
        "get_race": get_race,
        "get_race_detail": get_race_detail,
        "create_race": create_race,
        "update_race": update_race,
        "delete_race": delete_race,
        "run_optimization": run_optimization,
        "go_live": go_live,
        "finish_race": finish_race,
        "get_live_state": get_live_state,
        "end_stint": end_stint,
        "toggle_fuel": toggle_fuel,
        "set_pit_type": set_pit_type,
        "reoptimize": reoptimize,
        "export_race": export_race,
        "import_race": import_race,
        "duplicate_race": duplicate_race,
        "get_summary": get_summary,
    }


# ── CRUD ─────────────────────────────────────────

@bp.route("/", methods=["GET"])
@rate_limit(tier="read")
def list_all():
    """List all races for current workspace."""
    svc = _get_service()
    conn = _get_conn()
    races = svc["list_races"](conn)
    return api_response({"races": races})


@bp.route("/", methods=["POST"])
@rate_limit(tier="write")
def create():
    """Create a new race config with drivers and windows."""
    svc = _get_service()
    conn = _get_conn()
    data = request.get_json(silent=True)
    if not data:
        return api_error(ErrorCode.VALIDATION_ERROR, "JSON body required", status=400)
    try:
        race_id = svc["create_race"](conn, data)
        return api_response({"race_id": race_id}, status=201)
    except Exception as exc:
        logger.exception("Failed to create race")
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


@bp.route("/<int:race_id>", methods=["GET"])
@rate_limit(tier="read")
def get_detail(race_id: int):
    """Get full race detail."""
    svc = _get_service()
    conn = _get_conn()
    detail = svc["get_race_detail"](conn, race_id)
    if not detail:
        return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
    return api_response(detail)


@bp.route("/<int:race_id>", methods=["PUT"])
@rate_limit(tier="write")
def update(race_id: int):
    """Update race config, drivers, and/or windows."""
    svc = _get_service()
    conn = _get_conn()
    data = request.get_json(silent=True)
    if not data:
        return api_error(ErrorCode.VALIDATION_ERROR, "JSON body required", status=400)
    ok = svc["update_race"](conn, race_id, data)
    if not ok:
        return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
    return api_response({"ok": True})


@bp.route("/<int:race_id>", methods=["DELETE"])
@rate_limit(tier="write")
def delete(race_id: int):
    """Delete a race and all related data."""
    svc = _get_service()
    conn = _get_conn()
    ok = svc["delete_race"](conn, race_id)
    if not ok:
        return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
    return api_response({"ok": True})


# ── Optimization ──────────────────────────────────

@bp.route("/<int:race_id>/optimize", methods=["POST"])
@rate_limit(tier="write")
def optimize(race_id: int):
    """Run stint optimizer and save results."""
    svc = _get_service()
    conn = _get_conn()
    try:
        result = svc["run_optimization"](conn, race_id)
        return api_response(result)
    except ValueError as exc:
        return api_error(ErrorCode.NOT_FOUND, str(exc), status=404)
    except Exception as exc:
        logger.exception("Optimization failed for race %d", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


# ── Live Race ─────────────────────────────────────

@bp.route("/<int:race_id>/go-live", methods=["POST"])
@rate_limit(tier="write")
def race_go_live(race_id: int):
    """Start the race (transition from ready to live)."""
    svc = _get_service()
    conn = _get_conn()
    ok = svc["go_live"](conn, race_id)
    if not ok:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "Race must be in 'ready' status", status=400)
    return api_response({"ok": True})


@bp.route("/<int:race_id>/finish", methods=["POST"])
@rate_limit(tier="write")
def race_finish(race_id: int):
    """End the race."""
    svc = _get_service()
    conn = _get_conn()
    ok = svc["finish_race"](conn, race_id)
    if not ok:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "Race must be live or ready", status=400)
    return api_response({"ok": True})


@bp.route("/<int:race_id>/state", methods=["GET"])
@rate_limit(tier="read")
def live_state(race_id: int):
    """Full live state for dashboard polling (2s interval)."""
    svc = _get_service()
    conn = _get_conn()
    state = svc["get_live_state"](conn, race_id)
    if not state:
        return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
    return api_response(state)


@bp.route("/<int:race_id>/end-stint", methods=["POST"])
@rate_limit(tier="write")
def stint_end(race_id: int):
    """End the current active stint."""
    svc = _get_service()
    conn = _get_conn()
    data = request.get_json(silent=True) or {}
    result = svc["end_stint"](conn, race_id, **data)
    if not result:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "No active stint to end", status=400)
    return api_response(result)


@bp.route("/<int:race_id>/toggle-fuel", methods=["POST"])
@rate_limit(tier="write")
def fuel_toggle(race_id: int):
    """Toggle refuel on a pit stop."""
    svc = _get_service()
    conn = _get_conn()
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    if stint_order is None:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "stint_order required", status=400)
    try:
        snapshot = svc["toggle_fuel"](conn, race_id, stint_order)
        return api_response(snapshot)
    except Exception as exc:
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


@bp.route("/<int:race_id>/set-pit-type", methods=["POST"])
@rate_limit(tier="write")
def pit_type_set(race_id: int):
    """Set pit stop type (full/quick)."""
    svc = _get_service()
    conn = _get_conn()
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    pit_type = data.get("pit_type")
    if stint_order is None or pit_type not in ("full", "quick"):
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "stint_order and pit_type (full/quick) required", status=400)
    try:
        snapshot = svc["set_pit_type"](conn, race_id, stint_order, pit_type)
        return api_response(snapshot)
    except Exception as exc:
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


@bp.route("/<int:race_id>/reoptimize", methods=["POST"])
@rate_limit(tier="write")
def race_reoptimize(race_id: int):
    """Re-optimize remaining stints mid-race."""
    svc = _get_service()
    conn = _get_conn()
    try:
        result = svc["reoptimize"](conn, race_id)
        return api_response(result)
    except Exception as exc:
        logger.exception("Reoptimize failed for race %d", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


# ── Import / Export / Duplicate ───────────────────

@bp.route("/<int:race_id>/export", methods=["GET"])
@rate_limit(tier="read")
def race_export(race_id: int):
    """Export full race as JSON."""
    svc = _get_service()
    conn = _get_conn()
    data = svc["export_race"](conn, race_id)
    if not data:
        return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
    return api_response(data)


@bp.route("/import", methods=["POST"])
@rate_limit(tier="write")
def race_import():
    """Import race from JSON upload."""
    svc = _get_service()
    conn = _get_conn()
    # Accept either JSON body or file upload
    if request.content_type and "multipart" in request.content_type:
        f = request.files.get("file")
        if not f:
            return api_error(ErrorCode.VALIDATION_ERROR, "No file uploaded", status=400)
        try:
            data = json.loads(f.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return api_error(ErrorCode.VALIDATION_ERROR, "Invalid JSON file", status=400)
    else:
        data = request.get_json(silent=True)
        if not data:
            return api_error(ErrorCode.VALIDATION_ERROR, "JSON body required", status=400)
    try:
        race_id = svc["import_race"](conn, data)
        return api_response({"race_id": race_id}, status=201)
    except Exception as exc:
        logger.exception("Import failed")
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


@bp.route("/<int:race_id>/duplicate", methods=["POST"])
@rate_limit(tier="write")
def race_duplicate(race_id: int):
    """Clone a race config."""
    svc = _get_service()
    conn = _get_conn()
    new_id = svc["duplicate_race"](conn, race_id)
    if new_id is None:
        return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
    return api_response({"race_id": new_id}, status=201)


# ── Summary ───────────────────────────────────────

@bp.route("/<int:race_id>/summary", methods=["GET"])
@rate_limit(tier="read")
def race_summary(race_id: int):
    """Post-race statistics."""
    svc = _get_service()
    conn = _get_conn()
    data = svc["get_summary"](conn, race_id)
    if not data:
        return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
    return api_response(data)
```

**Step 2: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_race_strategy.py
git commit -m "feat: add /api/v1/race-strategy/ REST API blueprint"
```

---

### Task 3: Register Blueprint in app.py

Wire the new API blueprint into the Flask app factory, inside the `if cfg.USE_PG:` block alongside the other `/api/v1/` blueprints.

**Files:**
- Modify: `telemetry_tool/web/app.py:279-289` (inside `if cfg.USE_PG:` block, after Phase 4 v1 blueprints)

**Step 1: Add registration**

After line 284 (`logger.debug("Registered Phase 4 v1 blueprints (api_v1_data, api_v1_account)")`), add:

```python
            # Race strategy v1 API
            from .routes.api_v1_race_strategy import bp as api_v1_race_strategy_bp
            app.register_blueprint(api_v1_race_strategy_bp)
            logger.debug("Registered api_v1_race_strategy blueprint")
```

**Step 2: Commit**

```bash
git add telemetry_tool/web/app.py
git commit -m "feat: register race strategy API blueprint in Flask app factory"
```

---

### Task 4: Delete Existing Frontend Stub

Remove the sprint-race model pages that will be replaced with endurance model pages.

**Files:**
- Delete: `lap-website/src/app/app/race-strategy/page.tsx`
- Delete: `lap-website/src/app/app/race-strategy/new/page.tsx`
- Delete: `lap-website/src/app/app/race-strategy/[id]/page.tsx`
- Delete: `lap-website/src/app/app/race-strategy/[id]/live/page.tsx`
- Delete: `lap-website/src/app/app/race-strategy/[id]/summary/page.tsx`

**Step 1: Delete files**

```bash
cd lap-website
rm -rf src/app/app/race-strategy/
mkdir -p src/app/app/race-strategy/new
mkdir -p src/app/app/race-strategy/\[id\]/edit
mkdir -p src/app/app/race-strategy/\[id\]/live
mkdir -p src/app/app/race-strategy/\[id\]/summary
```

**Step 2: Commit**

```bash
git add -A src/app/app/race-strategy/
git commit -m "chore: delete sprint-race strategy stub pages"
```

---

### Task 5: Frontend — Race List Page

The entry point for race strategy. Shows all races with status badges.

**Files:**
- Create: `lap-website/src/app/app/race-strategy/page.tsx`
- Reference: `lap-website/src/app/app/sessions/page.tsx` (page pattern)
- Reference: `lap-website/src/lib/api-client.ts` (api.get)

**Step 1: Create the list page**

```tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface RaceRow {
  race_id: number;
  race_name: string;
  track_name: string | null;
  team_name: string | null;
  race_duration_s: number;
  desired_stints: number;
  status: 'draft' | 'ready' | 'live' | 'finished';
  created_at: string;
}

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h${m.toString().padStart(2, '0')}` : `${m}m`;
}

const statusConfig: Record<string, { label: string; className: string }> = {
  draft: { label: 'Draft', className: 'text-steel bg-steel/10' },
  ready: { label: 'Ready', className: 'text-marshal-yellow bg-marshal-yellow/10' },
  live: { label: 'LIVE', className: 'text-acid-green bg-acid-green/10 animate-pulse' },
  finished: { label: 'Finished', className: 'text-chalk bg-chalk/10' },
};

export default function RaceStrategyListPage() {
  const router = useRouter();

  const { data, isLoading } = useQuery({
    queryKey: ['race-strategy'],
    queryFn: () => api.get<{ races: RaceRow[] }>('/race-strategy/'),
  });

  const races = data?.races ?? [];

  const columns = [
    { key: 'race_name', header: 'Race', sortable: true },
    { key: 'track_name', header: 'Track', sortable: true,
      render: (v: string | null) => v || '—' },
    { key: 'team_name', header: 'Team',
      render: (v: string | null) => v || '—' },
    { key: 'race_duration_s', header: 'Duration',
      render: (v: number) => formatDuration(v) },
    { key: 'desired_stints', header: 'Stints' },
    { key: 'status', header: 'Status',
      render: (v: string) => {
        const cfg = statusConfig[v] || statusConfig.draft;
        return (
          <span className={`inline-flex px-2 py-0.5 text-xs font-telemetry tracking-wider uppercase ${cfg.className}`}>
            {cfg.label}
          </span>
        );
      },
    },
  ];

  return (
    <div>
      <PageHeader
        title="Race Strategy"
        subtitle="Endurance race management — plan, optimize, and run"
        actions={
          <div className="flex gap-2">
            <Link
              href="/app/race-strategy/new"
              className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm hover:bg-pit-orange/80 transition-colors"
            >
              + New Race
            </Link>
          </div>
        }
      />
      <DataTable
        columns={columns}
        data={races}
        isLoading={isLoading}
        onRowClick={(row: RaceRow) => {
          if (row.status === 'live') {
            router.push(`/app/race-strategy/${row.race_id}/live`);
          } else if (row.status === 'finished') {
            router.push(`/app/race-strategy/${row.race_id}/summary`);
          } else {
            router.push(`/app/race-strategy/${row.race_id}`);
          }
        }}
        emptyMessage="No races yet. Create your first endurance race strategy."
      />
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd lap-website && npx next build --no-lint 2>&1 | tail -5`

Expected: Build succeeds (page may show warnings about missing DataTable props — that's fine for now).

**Step 3: Commit**

```bash
git add src/app/app/race-strategy/page.tsx
git commit -m "feat: add race strategy list page (endurance model)"
```

---

### Task 6: Frontend — Race Config Page (New + Edit)

Multi-section form for creating and editing race configurations. Matches the Flask `config.html` form.

**Files:**
- Create: `lap-website/src/app/app/race-strategy/new/page.tsx`
- Create: `lap-website/src/app/app/race-strategy/[id]/edit/page.tsx`

**Step 1: Create the config form component**

Create `new/page.tsx` with a comprehensive form covering:
- Race Details: name, team, track, duration (hours + minutes picker), desired stints
- Drivers: dynamic rows with name, weight, COM channel, color, constraints (min/max stint, cumulative, rest)
- Pit Strategy: min pit stop duration, pit speed, quick pit stop, mandatory driver change, refueling
- Pit Windows: dynamic rows with type (pitlane/refuel/tech_stop), label, start/end times
- Fuel & Weight: fuel autonomy, empty kart, full tank, min total, reference weight, weigh on exit
- Qualifying: duration, refuel after (collapsible)

The form should:
- POST to `/race-strategy/` on create, PUT to `/race-strategy/<id>` on edit
- Use `useMutation` from React Query for submit
- Navigate to detail page on success
- Show validation errors inline

The edit page (`[id]/edit/page.tsx`) loads existing data via `useQuery` and renders the same form pre-filled.

Since this is a large form, the exact implementation should follow these field mappings from the SQLite schema:

| Section | Fields | Schema Columns |
|---------|--------|----------------|
| Race Details | name, team, track, duration, stints | race_name, team_name, track_name, race_duration_s, desired_stints |
| Drivers | name, weight, COM, color, constraints | driver_name, weight_kg, com_channel, color_hex, min/max_stint_s, min/max_cumulative_s, min_rest_s |
| Pit Strategy | min stop, speed, quick stop, mandatory change, refueling | min_pit_stop_s, pit_speed_kmh, quick_pit_stop_s, mandatory_driver_change, refueling_allowed |
| Pit Windows | type, label, start, end, rules | window_type, label, start_s, end_s, refuel_allowed, driver_change_allowed |
| Fuel & Weight | autonomy, empty, full, min total, reference, weigh | fuel_autonomy_s, empty_kart_kg, full_tank_kg, min_total_kart_kg, reference_weight_kg, weigh_on_pit_exit |
| Qualifying | duration, refuel after | qualifying_duration_s, refuel_after_quali |

**Step 2: Create the edit page wrapper**

`[id]/edit/page.tsx` fetches existing data and renders the same form:

```tsx
'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter, useParams } from 'next/navigation';
import { api } from '@/lib/api-client';
// Import the form component or inline it

export default function EditRacePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ['race-strategy', id],
    queryFn: () => api.get<RaceDetail>(`/race-strategy/${id}`),
  });

  const mutation = useMutation({
    mutationFn: (formData: RaceFormData) =>
      api.put(`/race-strategy/${id}`, formData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['race-strategy'] });
      router.push(`/app/race-strategy/${id}`);
    },
  });

  if (isLoading) return <div className="p-8 text-steel">Loading...</div>;
  if (!data) return <div className="p-8 text-safety-red">Race not found</div>;

  return <RaceConfigForm initialData={data} onSubmit={mutation.mutateAsync} isEdit />;
}
```

**Step 3: Commit**

```bash
git add src/app/app/race-strategy/new/page.tsx src/app/app/race-strategy/\[id\]/edit/page.tsx
git commit -m "feat: add race config form pages (new + edit)"
```

---

### Task 7: Frontend — Race Detail Page

Shows config summary, driver roster, stint timeline, and action buttons.

**Files:**
- Create: `lap-website/src/app/app/race-strategy/[id]/page.tsx`

**Step 1: Create the detail page**

Key sections:
1. **Config summary cards** — race name, track, team, duration, fuel autonomy, status badge
2. **Driver roster table** — name, weight, COM channel, color dot, constraints
3. **Stint plan timeline** — horizontal bar colored by driver, with time labels
4. **Stint table** — order, driver, start, end, duration, fuel start/end, ballast, pit type
5. **Action buttons**:
   - Optimize (POST `/race-strategy/<id>/optimize`) — only when draft/ready
   - Go Live (POST `/race-strategy/<id>/go-live`) — only when ready
   - Edit (link to edit page) — only when draft/ready
   - Export (GET `/race-strategy/<id>/export`)
   - Duplicate (POST `/race-strategy/<id>/duplicate`)
   - Delete (DELETE `/race-strategy/<id>`) — with confirmation

The stint timeline bar should:
- Show each stint as a segment proportional to its duration
- Color each segment by driver's `color_hex`
- Show pit stops as thin separators between segments
- Label driver name + duration inside each segment

**Step 2: Commit**

```bash
git add src/app/app/race-strategy/\[id\]/page.tsx
git commit -m "feat: add race detail page with stint timeline"
```

---

### Task 8: Frontend — Live Dashboard Page

Real-time race monitoring with 2-second polling.

**Files:**
- Create: `lap-website/src/app/app/race-strategy/[id]/live/page.tsx`

**Step 1: Create the live dashboard**

Polls `GET /race-strategy/<id>/state` every 2 seconds via React Query `refetchInterval`.

Key sections:
1. **Race timer** — elapsed / remaining with color-coded progress bar (green → yellow → red)
2. **Fuel gauge** — current fuel kg, burn rate, autonomy countdown (time until empty)
3. **Current driver card** — name, color, stint elapsed bar, COM channel badge
4. **Next driver card** — name, color, planned stint duration
5. **Stint log table** — all stints with planned vs actual, delta column, status badges
6. **Stint timeline bar** — same as detail page but with active stint highlighted
7. **Pit window status** — 3 cards (pitlane, refuel, tech stop) showing open/closed/upcoming
8. **Action buttons**:
   - End Stint (POST `/race-strategy/<id>/end-stint`)
   - Re-Optimize (POST `/race-strategy/<id>/reoptimize`)
   - Finish Race (POST `/race-strategy/<id>/finish`) — with confirmation

```tsx
// Key polling pattern:
const { data: state } = useQuery({
  queryKey: ['race-strategy', id, 'state'],
  queryFn: () => api.get<LiveState>(`/race-strategy/${id}/state`),
  refetchInterval: 2000,
  refetchIntervalInBackground: true,
});
```

Timer computation:
```tsx
// Elapsed seconds from race_start_ts
const elapsed = state?.race?.race_start_ts
  ? Math.floor((Date.now() - new Date(state.race.race_start_ts).getTime()) / 1000)
  : 0;
const remaining = (state?.race?.race_duration_s ?? 0) - elapsed;
const progress = elapsed / (state?.race?.race_duration_s || 1);
```

**Step 2: Commit**

```bash
git add src/app/app/race-strategy/\[id\]/live/page.tsx
git commit -m "feat: add live race dashboard with 2s polling"
```

---

### Task 9: Frontend — Summary Page

Post-race statistics and analysis.

**Files:**
- Create: `lap-website/src/app/app/race-strategy/[id]/summary/page.tsx`

**Step 1: Create the summary page**

Fetches `GET /race-strategy/<id>/summary`.

Key sections:
1. **Top-level stats** — total race time, drive time, pit time, stint count, pit stop count, driver count
2. **Stint timeline bar** — colored by driver (same component as detail page)
3. **Driver stats** — per-driver: total drive time, stint count, longest stint, shortest stint (table + optional bar chart)
4. **Stint log** — planned vs actual with delta highlighting (green if under, red if over)
5. **Pit stops table** — pit time, fuel added, driver change, pit type
6. **Actions**: Export, Duplicate, View Config (link to detail)

**Step 2: Commit**

```bash
git add src/app/app/race-strategy/\[id\]/summary/page.tsx
git commit -m "feat: add post-race summary page"
```

---

### Task 10: Build Verification and Smoke Test

Verify the full stack compiles and the frontend builds cleanly.

**Files:**
- All files created in Tasks 1-9

**Step 1: Run frontend lint**

```bash
cd lap-website && npm run lint
```

Expected: No errors (warnings OK).

**Step 2: Run frontend build**

```bash
npm run build
```

Expected: Build succeeds with all race-strategy pages listed.

**Step 3: Run frontend tests**

```bash
npm run test
```

Expected: All existing tests pass. No new tests yet (those would be Phase B or a follow-up).

**Step 4: Verify backend imports**

```bash
cd .. && python -c "from services.race_strategy import list_races; print('Service OK')"
python -c "from web.routes.api_v1_race_strategy import bp; print('Blueprint OK:', bp.url_prefix)"
```

Expected: Both print success messages.

**Step 5: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: resolve build issues from race strategy port"
```

---

## Phase B (Deferred)

The following will be implemented in a separate plan after Phase A is validated:

- **B1:** TeamTalk chat panel + API endpoints
- **B2:** Weather integration (Open-Meteo + RainViewer)
- **B3:** Safety car / neutralization controls
- **B4:** Rival tracker panel
- **B5:** Alert manager (toasts + audio + browser notifications)
- **B6:** Layout modes (grid / vertical / pit wall)

---

## Notes for Implementer

1. **SQL Compatibility**: The service layer uses `:name` parameter style. The `sql_compat.py` module auto-translates this to `%(name)s` for PostgreSQL at call time. Both SQLite and PG work.

2. **RLS Context**: The tenant middleware (`web/middleware/tenant.py`) sets `SET LOCAL app.current_workspace_id` before each request. All race strategy tables already have RLS policies (migration 007). No additional RLS work needed.

3. **Auth**: The auth middleware (`web/middleware/auth.py`) enforces JWT on all `/api/v1/` paths. The new blueprint at `/api/v1/race-strategy/` is automatically protected.

4. **Import Paths**: Backend modules are accessed via `from services.race_strategy import ...` and `from web.routes.api_v1_race_strategy import bp`. The `conftest.py` files add project root to `sys.path`.

5. **Frontend API Client**: Use `api.get<T>('/race-strategy/...')` — the `/api/v1` prefix is added automatically by `apiFetch()`. The JWT token is attached from the in-memory auth store.

6. **Existing race_state_engine.py**: Located at `telemetry_tool/race_state_engine.py` (project root, not in a package). Service layer imports it via `sys.path.insert()` — same pattern used by the existing v2 routes.

7. **optimize_stints()**: Located in `telemetry_tool/race_strategy_v2.py` (the module, not the web route). This is the standalone optimizer function that the route imports.

8. **DataTable component**: Located at `lap-website/src/components/app/DataTable.tsx`. Accepts `columns`, `data`, `isLoading`, `onRowClick`, `emptyMessage` props. Check the actual interface before using.

9. **PageHeader component**: Located at `lap-website/src/components/app/PageHeader.tsx`. Accepts `title`, `subtitle`, `actions` props.
