"""V1 race strategy API endpoints — CRUD, optimization, and live-race ops.

Blueprint: ``/api/v1/race-strategy/`` — provides REST endpoints for race
strategy configuration, optimization, live-race management, import/export,
and post-race summary.

Auth middleware automatically enforces JWT on ``/api/v1/`` paths.
Tenant middleware sets RLS context automatically.

Usage::

    from web.routes.api_v1_race_strategy import bp as api_v1_race_strategy_bp
    app.register_blueprint(api_v1_race_strategy_bp)
"""
from __future__ import annotations

import json
import logging

from flask import Blueprint, request

from web.repos.delete_cascade import delete_entity_cascade, get_delete_impact
from services.race_strategy import (
    create_race,
    duplicate_race,
    end_stint,
    pit_in,
    pit_out,
    export_race,
    finish_race,
    get_live_state,
    get_race_detail,
    get_summary,
    go_live,
    import_race,
    list_races,
    reoptimize,
    reorder_stints,
    run_optimization,
    set_pit_type,
    set_stint_driver,
    set_stint_duration,
    toggle_fuel,
    update_race,
    wake_driver,
)
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


# ---- PG connection ----
def get_pg_connection():
    """Get PostgreSQL connection. Tests patch this."""
    from web.db_pg import get_pg_connection as _get_pg
    return _get_pg()


# ---------------------------------------------------------------------------
# GET / — list all races
# ---------------------------------------------------------------------------

@bp.route("/", methods=["GET"])
@rate_limit(tier="read")
def list_races_endpoint():
    """Return all races for the current workspace.

    Returns:
        200 with ``{"races": [...]}``
    """
    try:
        conn = get_pg_connection()
        races = list_races(conn)
        return api_response({"races": races})
    except Exception as exc:
        logger.exception("Failed to list races")
        return api_error(ErrorCode.INTERNAL_ERROR, f"list_races: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST / — create a new race
# ---------------------------------------------------------------------------

@bp.route("/", methods=["POST"])
@rate_limit(tier="write")
def create_race_endpoint():
    """Create a new race configuration.

    Expects a JSON body with ``race``, ``drivers``, and optionally ``windows``.

    Returns:
        201 with ``{"race_id": N}``
        400 if JSON body is missing or invalid.
    """
    data = request.get_json(silent=True)
    if not data:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "JSON body is required",
            status=400,
        )

    try:
        conn = get_pg_connection()

        # Resolve plan limits from entitlements
        max_dur = None
        allowed_modes = None
        try:
            from flask import g

            from auth.entitlements import get_plan_entitlements, normalize_tier
            user_id = getattr(g, "current_user_id", None)
            ws_id = getattr(g, "workspace_id", None)
            if user_id is not None:
                from auth.entitlements import get_user_entitlements
                ent = get_user_entitlements(conn, user_id, ws_id)
                max_dur = ent.get("race_strategy_max_duration_s")
                # Resolve optimizer mode restriction from plan
                tier = normalize_tier(ent.get("plan_tier"))
                plan_ent = get_plan_entitlements(tier)
                allowed_modes = plan_ent.get("optimizer_modes")
        except Exception:
            pass  # Fail open — don't block on entitlement resolution errors

        race_id = create_race(conn, data, max_duration_s=max_dur,
                              allowed_optimizer_modes=allowed_modes)
        return api_response({"race_id": race_id}, status=201)
    except ValueError as ve:
        return api_error(ErrorCode.VALIDATION_ERROR, str(ve), status=400)
    except Exception as exc:
        logger.exception("Failed to create race")
        return api_error(ErrorCode.INTERNAL_ERROR, f"create_race: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# GET /<race_id> — get full race detail
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>", methods=["GET"])
@rate_limit(tier="read")
def get_race_detail_endpoint(race_id: int):
    """Return full race detail: config + drivers + stints + pit_stops + windows.

    Returns:
        200 with race detail dict.
        404 if race not found.
    """
    try:
        conn = get_pg_connection()
        detail = get_race_detail(conn, race_id)
        if detail is None:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response(detail)
    except Exception as exc:
        logger.exception("Failed to get race detail for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"get_race_detail: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# PUT /<race_id> — update race configuration
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>", methods=["PUT"])
@rate_limit(tier="write")
def update_race_endpoint(race_id: int):
    """Update an existing race configuration.

    Only allowed when status is ``'draft'`` or ``'ready'``.

    Returns:
        200 with ``{"ok": true}``
        400 if JSON body is missing or update not allowed.
        404 if race not found.
    """
    data = request.get_json(silent=True)
    if not data:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "JSON body is required",
            status=400,
        )

    try:
        conn = get_pg_connection()

        # Resolve plan limits from entitlements
        max_dur = None
        allowed_modes = None
        try:
            from flask import g

            from auth.entitlements import get_plan_entitlements, normalize_tier
            user_id = getattr(g, "current_user_id", None)
            ws_id = getattr(g, "workspace_id", None)
            if user_id is not None:
                from auth.entitlements import get_user_entitlements
                ent = get_user_entitlements(conn, user_id, ws_id)
                max_dur = ent.get("race_strategy_max_duration_s")
                tier = normalize_tier(ent.get("plan_tier"))
                plan_ent = get_plan_entitlements(tier)
                allowed_modes = plan_ent.get("optimizer_modes")
        except Exception:
            pass  # Fail open — don't block on entitlement resolution errors

        success = update_race(conn, race_id, data, max_duration_s=max_dur,
                              allowed_optimizer_modes=allowed_modes)
        if not success:
            # Could be not found or wrong status
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Race not found or cannot be updated in current status",
                status=400,
            )
        return api_response({"ok": True})
    except ValueError as ve:
        return api_error(ErrorCode.VALIDATION_ERROR, str(ve), status=400)
    except Exception as exc:
        logger.exception("Failed to update race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"update_race: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# DELETE /<race_id> — delete race
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>", methods=["DELETE"])
@rate_limit(tier="write")
def delete_race_endpoint(race_id: int):
    """Delete a race and all associated data via cascade.

    Returns:
        200 with ``{"ok": true, "impact": {...}}``
        404 if race not found.
    """
    try:
        conn = get_pg_connection()
        # Verify race exists first
        row = conn.execute(
            "SELECT race_id FROM race_configs WHERE race_id = %(race_id)s",
            {"race_id": race_id},
        ).fetchone()
        if not row:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        result = delete_entity_cascade(conn, "race_strategy", race_id)
        conn.commit()
        return api_response(result)
    except Exception as exc:
        logger.exception("Failed to delete race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"delete_race: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# GET /<race_id>/delete-impact — preview cascade impact
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/delete-impact", methods=["GET"])
@rate_limit(tier="read")
def delete_impact_endpoint(race_id: int):
    """Preview what would be deleted without actually deleting."""
    try:
        conn = get_pg_connection()
        row = conn.execute(
            "SELECT race_id FROM race_configs WHERE race_id = %(race_id)s",
            {"race_id": race_id},
        ).fetchone()
        if not row:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        result = get_delete_impact(conn, "race_strategy", race_id)
        return api_response(result)
    except Exception as exc:
        logger.exception("Failed to get delete impact for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"delete_impact: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/optimize — run stint optimizer
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/optimize", methods=["POST"])
@rate_limit(tier="write")
def optimize_endpoint(race_id: int):
    """Run the stint optimizer and persist results.

    Returns:
        200 with optimization snapshot.
        404 if race not found.
        500 on optimization failure.
    """
    try:
        conn = get_pg_connection()
        logger.info("OPTIMIZE called for race_id=%s", race_id)
        result = run_optimization(conn, race_id)
        logger.info("OPTIMIZE result for race_id=%s: stints=%s feasible=%s",
                     race_id, len(result.get("stints", [])), result.get("feasible"))
        if result.get("error") == "not found":
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response(result)
    except Exception as exc:
        logger.exception("Optimization failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"optimize: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/go-live — start the race
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/go-live", methods=["POST"])
@rate_limit(tier="write")
def go_live_endpoint(race_id: int):
    """Start the race: set status to 'live' and activate the first stint.

    Returns:
        200 with ``{"ok": true}``
        400 if race is not in a valid status to go live.
    """
    try:
        conn = get_pg_connection()
        success = go_live(conn, race_id)
        if not success:
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Race not found or not in a valid status to go live",
                status=400,
            )
        return api_response({"ok": True})
    except Exception as exc:
        logger.exception("go_live failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"go_live: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/finish — end the race
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/finish", methods=["POST"])
@rate_limit(tier="write")
def finish_race_endpoint(race_id: int):
    """End the race: complete any active stint and set status to 'finished'.

    Returns:
        200 with ``{"ok": true}``
        400 if race not found.
    """
    try:
        conn = get_pg_connection()
        success = finish_race(conn, race_id)
        if not success:
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Race not found",
                status=400,
            )
        return api_response({"ok": True})
    except Exception as exc:
        logger.exception("finish_race failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"finish_race: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# GET /<race_id>/state — full live state for dashboard polling
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/state", methods=["GET"])
@rate_limit(tier="read")
def get_live_state_endpoint(race_id: int):
    """Return the full live state for dashboard 2s polling.

    Returns:
        200 with live state dict.
        404 if race not found.
    """
    try:
        conn = get_pg_connection()
        state = get_live_state(conn, race_id)
        if state is None:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response(state)
    except Exception as exc:
        logger.exception("get_live_state failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"get_live_state: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/end-stint — end current stint
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/end-stint", methods=["POST"])
@rate_limit(tier="write")
def end_stint_endpoint(race_id: int):
    """End the current active stint, log a pit stop, and start the next stint.

    Accepts optional JSON body with ``driver_change``, ``refueled``, ``notes``.

    Returns:
        200 with ``{"ok": true, "elapsed_s": N}``
        400 if no active stint.
    """
    data = request.get_json(silent=True) or {}

    try:
        conn = get_pg_connection()
        actual_laps = data.get("actual_laps")
        if actual_laps is not None:
            actual_laps = int(actual_laps)
        result = end_stint(
            conn,
            race_id,
            driver_change=data.get("driver_change", True),
            refueled=data.get("refueled", False),
            notes=data.get("notes"),
            actual_laps=actual_laps,
        )
        if result is None:
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Race not found or no active stint",
                status=400,
            )
        return api_response(result)
    except Exception as exc:
        logger.exception("end_stint failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"end_stint: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/pit-in — car enters pit
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/pit-in", methods=["POST"])
@rate_limit(tier="write")
def pit_in_endpoint(race_id: int):
    """Car enters pit — end current stint, start pit timer."""
    data = request.get_json(silent=True) or {}
    try:
        conn = get_pg_connection()
        actual_laps = data.get("actual_laps")
        if actual_laps is not None:
            actual_laps = int(actual_laps)
        result = pit_in(conn, race_id, actual_laps=actual_laps, notes=data.get("notes"))
        if result is None:
            return api_error(ErrorCode.VALIDATION_ERROR, "Race not found or no active stint", status=400)
        return api_response(result)
    except Exception as exc:
        logger.exception("pit_in failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"pit_in: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/pit-out — car exits pit
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/pit-out", methods=["POST"])
@rate_limit(tier="write")
def pit_out_endpoint(race_id: int):
    """Car exits pit — record pit duration, start next stint."""
    data = request.get_json(silent=True) or {}
    try:
        conn = get_pg_connection()
        result = pit_out(
            conn, race_id,
            driver_change=data.get("driver_change", True),
            refueled=data.get("refueled", False),
            notes=data.get("notes"),
            kart_number=data.get("kart_number"),
        )
        if result is None:
            return api_error(ErrorCode.VALIDATION_ERROR, "Race not found or not in pit", status=400)
        return api_response(result)
    except Exception as exc:
        logger.exception("pit_out failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"pit_out: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/toggle-fuel — toggle refuel on a pit stop
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/toggle-fuel", methods=["POST"])
@rate_limit(tier="write")
def toggle_fuel_endpoint(race_id: int):
    """Toggle refuel on a pit stop and re-cascade via RaceStateEngine.

    Requires ``stint_order`` in JSON body.

    Returns:
        200 with engine snapshot.
        400 if stint_order is missing or toggle fails.
    """
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    if stint_order is None:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "stint_order is required",
            status=400,
        )

    try:
        conn = get_pg_connection()
        result = toggle_fuel(conn, race_id, stint_order)
        if result is None:
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Failed to toggle fuel — race not found or engine load failed",
                status=400,
            )
        return api_response(result)
    except Exception as exc:
        logger.exception("toggle_fuel failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"toggle_fuel: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/set-pit-type — set pit stop type (full/quick)
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/set-pit-type", methods=["POST"])
@rate_limit(tier="write")
def set_pit_type_endpoint(race_id: int):
    """Set pit stop type ('full' or 'quick') and re-cascade.

    Requires ``stint_order`` and ``pit_type`` in JSON body.

    Returns:
        200 with engine snapshot.
        400 if required fields missing or invalid pit_type.
    """
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    pit_type = data.get("pit_type")

    if stint_order is None:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "stint_order is required",
            status=400,
        )
    if pit_type not in ("full", "quick"):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "pit_type must be 'full' or 'quick'",
            status=400,
        )

    try:
        conn = get_pg_connection()
        result = set_pit_type(conn, race_id, stint_order, pit_type)
        if result is None:
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Failed to set pit type — race not found or engine load failed",
                status=400,
            )
        return api_response(result)
    except Exception as exc:
        logger.exception("set_pit_type failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"set_pit_type: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/reoptimize — re-optimize remaining stints mid-race
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/reoptimize", methods=["POST"])
@rate_limit(tier="write")
def reoptimize_endpoint(race_id: int):
    """Re-optimize remaining stints mid-race.

    Keeps completed and active stints, replaces planned stints.

    Returns:
        200 with engine snapshot.
        404 if race not found.
        500 on optimization failure.
    """
    try:
        conn = get_pg_connection()

        # If body contains rain context, create a temporary weather window
        data = request.get_json(silent=True) or {}
        wet_lap_time = data.get("wet_lap_time_s")
        rain_duration_min = data.get("rain_duration_min")
        if wet_lap_time and rain_duration_min:
            from services.race_strategy import get_race, _compute_elapsed_s
            race = get_race(conn, race_id)
            if race:
                elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
                rain_end = elapsed + int(rain_duration_min) * 60
                from services.race_strategy_weather import add_weather_window, get_weather_windows
                # Remove old temporary windows and add the new one
                existing = get_weather_windows(conn, race_id)
                for w in existing:
                    if w.get("start_s", 0) >= elapsed:
                        conn.execute(
                            "DELETE FROM race_weather_windows WHERE id = ?",
                            (w["id"],),
                        )
                add_weather_window(conn, race_id, elapsed, rain_end,
                                   race.get("current_condition") or "wet", 100)

        result = reoptimize(conn, race_id)
        if result.get("error") == "not found":
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response(result)
    except Exception as exc:
        logger.exception("reoptimize failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"reoptimize: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/apply-strategy — apply a specific strategy plan
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/apply-strategy", methods=["POST"])
@rate_limit(tier="write")
def apply_strategy_endpoint(race_id: int):
    """Apply a specific strategy's stints to the race.

    Expects JSON body with ``stints`` list (from /strategies response)
    and optional ``approach`` name for logging.

    Replaces all planned stints with the strategy's stints.
    Completed/active stints are kept.
    """
    data = request.get_json(silent=True) or {}
    strategy_stints = data.get("stints")
    if not strategy_stints or not isinstance(strategy_stints, list):
        return api_error(ErrorCode.VALIDATION_ERROR, "stints list is required", status=400)

    try:
        conn = get_pg_connection()
        from services.race_strategy import (
            get_race, _compute_elapsed_s, _rows_to_list, _get_sleep_windows,
        )
        from race_state_engine import RaceStateEngine

        race = get_race(conn, race_id)
        if not race:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)

        drivers = _rows_to_list(conn.execute(
            "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
            (race_id,),
        ).fetchall())

        # Keep completed/active stints
        fixed_stints = _rows_to_list(conn.execute(
            "SELECT * FROM race_stints WHERE race_id = ? AND status IN ('completed', 'active') "
            "ORDER BY stint_order",
            (race_id,),
        ).fetchall())
        n_fixed = len(fixed_stints)

        # Build new planned stints from the strategy
        new_stints = []
        for i, st in enumerate(strategy_stints):
            order = n_fixed + i + 1
            start_s = st.get("start_s", 0)
            dur = st.get("duration_s", 0)
            new_stints.append({
                "stint_order": order,
                "driver_id": st["driver_id"],
                "driver_name": st.get("driver_name", ""),
                "planned_start_s": start_s,
                "planned_end_s": start_s + dur,
                "planned_duration_s": dur,
            })

        # Build pit stops between stints
        pit_time = race.get("min_pit_stop_s") or 120
        pit_stops = []
        for i in range(len(new_stints) - 1):
            curr = new_stints[i]
            nxt = new_stints[i + 1]
            pit_stops.append({
                "after_stint": curr["stint_order"],
                "at_s": curr["planned_end_s"],
                "duration_s": pit_time,
                "refuel": True,
                "driver_change": curr["driver_id"] != nxt["driver_id"],
            })

        # Clear planned stints
        conn.execute(
            "DELETE FROM race_stints WHERE race_id = ? AND status = 'planned'",
            (race_id,),
        )
        conn.execute(
            "DELETE FROM race_pit_stops WHERE race_id = ? AND stint_id NOT IN "
            "(SELECT stint_id FROM race_stints WHERE race_id = ?)",
            (race_id, race_id),
        )

        # Wrap in engine for fuel/ballast cascade
        all_stints = fixed_stints + new_stints
        engine = RaceStateEngine(race, drivers, all_stints, pit_stops)

        # Save new planned stints
        for s in engine.stints:
            if s.stint_order > n_fixed:
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
        snapshot = engine.snapshot()
        return api_response(snapshot)
    except Exception as exc:
        logger.exception("apply_strategy failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"apply_strategy: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# GET /<race_id>/export — export race as JSON
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/export", methods=["GET"])
@rate_limit(tier="read")
def export_race_endpoint(race_id: int):
    """Export the full race data as JSON.

    Returns:
        200 with export dict.
        404 if race not found.
    """
    try:
        conn = get_pg_connection()
        data = export_race(conn, race_id)
        if data is None:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response(data)
    except Exception as exc:
        logger.exception("export_race failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"export_race: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /import — import race from JSON body or multipart file upload
# ---------------------------------------------------------------------------

@bp.route("/import", methods=["POST"])
@rate_limit(tier="write")
def import_race_endpoint():
    """Import a race from an export dict.

    Accepts either:
    1. JSON body (Content-Type: application/json)
    2. Multipart file upload (Content-Type: multipart/form-data) with field "file"

    Returns:
        201 with ``{"race_id": N}``
        400 if input is invalid or required fields are missing.
    """
    data = None

    # Try JSON body first
    if request.is_json:
        data = request.get_json(silent=True)
    # Fall back to multipart file upload
    elif request.files.get("file"):
        uploaded = request.files["file"]
        try:
            raw = uploaded.read()
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                f"Invalid JSON in uploaded file: {exc}",
                status=400,
            )

    if not data:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "JSON body or file upload with field 'file' is required",
            status=400,
        )

    try:
        conn = get_pg_connection()
        race_id = import_race(conn, data)
        return api_response({"race_id": race_id}, status=201)
    except ValueError as exc:
        return api_error(ErrorCode.VALIDATION_ERROR, str(exc), status=400)
    except Exception as exc:
        logger.exception("import_race failed")
        return api_error(ErrorCode.INTERNAL_ERROR, f"import_race: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/duplicate — clone a race configuration
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/duplicate", methods=["POST"])
@rate_limit(tier="write")
def duplicate_race_endpoint(race_id: int):
    """Clone a race configuration with drivers and windows (no stints).

    Returns:
        201 with ``{"race_id": N}``
        404 if source race not found.
    """
    try:
        conn = get_pg_connection()
        new_race_id = duplicate_race(conn, race_id)
        if new_race_id is None:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response({"race_id": new_race_id}, status=201)
    except Exception as exc:
        logger.exception("duplicate_race failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"duplicate_race: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# GET /<race_id>/summary — post-race summary stats
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/summary", methods=["GET"])
@rate_limit(tier="read")
def get_summary_endpoint(race_id: int):
    """Return post-race summary statistics.

    Returns:
        200 with summary dict.
        404 if race not found.
    """
    try:
        conn = get_pg_connection()
        summary = get_summary(conn, race_id)
        if summary is None:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response(summary)
    except Exception as exc:
        logger.exception("get_summary failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"get_summary: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/wake-driver — wake a sleeping driver early
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/wake-driver", methods=["POST"])
@rate_limit(tier="write")
def wake_driver_endpoint(race_id: int):
    """Wake a sleeping driver early during an endurance race.

    Requires ``driver_id`` in JSON body.

    Returns:
        200 with wake result.
        400 if driver_id is missing.
        404 if no active sleep window for this driver.
    """
    data = request.get_json(silent=True) or {}
    driver_id = data.get("driver_id")
    if not driver_id:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "driver_id is required",
            status=400,
        )

    try:
        conn = get_pg_connection()
        result = wake_driver(conn, race_id, int(driver_id))
        if result is None:
            return api_error(
                ErrorCode.NOT_FOUND,
                "No active sleep window for this driver",
                status=404,
            )
        return api_response(result)
    except (ValueError, TypeError):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "driver_id must be an integer",
            status=400,
        )
    except Exception as exc:
        logger.exception("wake_driver failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"wake_driver: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/set-driver — change stint driver
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/set-driver", methods=["POST"])
@rate_limit(tier="write")
def set_driver_endpoint(race_id: int):
    """Change the driver for a stint and re-cascade."""
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    driver_id = data.get("driver_id")
    if stint_order is None or driver_id is None:
        return api_error(ErrorCode.VALIDATION_ERROR, "stint_order and driver_id are required", status=400)
    try:
        conn = get_pg_connection()
        result = set_stint_driver(conn, race_id, int(stint_order), int(driver_id))
        if result is None:
            return api_error(ErrorCode.VALIDATION_ERROR, "Failed — race or stint not found", status=400)
        return api_response(result)
    except Exception as exc:
        logger.exception("set_driver failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"set_driver: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/set-duration — change stint duration
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/set-duration", methods=["POST"])
@rate_limit(tier="write")
def set_duration_endpoint(race_id: int):
    """Change the planned duration for a stint and rebuild timeline."""
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    duration_s = data.get("duration_s")
    if stint_order is None or duration_s is None:
        return api_error(ErrorCode.VALIDATION_ERROR, "stint_order and duration_s are required", status=400)
    if int(duration_s) < 0:
        return api_error(ErrorCode.VALIDATION_ERROR, "duration_s must be non-negative", status=400)
    try:
        conn = get_pg_connection()
        result = set_stint_duration(conn, race_id, int(stint_order), int(duration_s))
        if result is None:
            return api_error(ErrorCode.VALIDATION_ERROR, "Failed — race or stint not found", status=400)
        return api_response(result)
    except Exception as exc:
        logger.exception("set_duration failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"set_duration: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/reorder-stints — swap two adjacent stints
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/reorder-stints", methods=["POST"])
@rate_limit(tier="write")
def reorder_stints_endpoint(race_id: int):
    """Swap two adjacent stints and re-cascade fuel/ballast/pit stops."""
    data = request.get_json(silent=True) or {}
    stint_order = data.get("stint_order")
    direction = data.get("direction")
    if stint_order is None or direction not in ("up", "down"):
        return api_error(ErrorCode.VALIDATION_ERROR, "stint_order and direction (up/down) are required", status=400)
    try:
        conn = get_pg_connection()
        result = reorder_stints(conn, race_id, int(stint_order), direction)
        if result is None:
            return api_error(ErrorCode.VALIDATION_ERROR, "Cannot move stint in that direction", status=400)
        return api_response(result)
    except Exception as exc:
        logger.exception("reorder_stints failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"reorder_stints: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/pause — start neutralization (pause race)
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/pause", methods=["POST"])
@rate_limit(tier="write")
def pause_race_endpoint(race_id: int):
    """Pause the race — freezes the clock entirely."""
    try:
        conn = get_pg_connection()
        from services.race_strategy import get_race
        from datetime import datetime, timezone
        race = get_race(conn, race_id)
        if not race:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        if race.get("paused_at_ts"):
            return api_response({"ok": True, "paused": True})  # already paused
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE race_configs SET paused_at_ts = ? WHERE race_id = ?",
            (now_iso, race_id),
        )
        conn.commit()
        return api_response({"ok": True, "paused": True})
    except Exception as exc:
        logger.exception("pause failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"pause: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/resume — end neutralization (resume race)
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/resume", methods=["POST"])
@rate_limit(tier="write")
def resume_race_endpoint(race_id: int):
    """Resume the race — unfreezes the clock and accumulates paused time."""
    try:
        conn = get_pg_connection()
        from services.race_strategy import get_race
        from datetime import datetime, timezone
        race = get_race(conn, race_id)
        if not race:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        paused_at = race.get("paused_at_ts")
        if not paused_at:
            return api_response({"ok": True, "paused": False})
        try:
            pause_start = datetime.fromisoformat(paused_at.replace("Z", "+00:00"))
            if pause_start.tzinfo is None:
                pause_start = pause_start.replace(tzinfo=timezone.utc)
            pause_duration = max(0, int((datetime.now(timezone.utc) - pause_start).total_seconds()))
        except Exception:
            pause_duration = 0
        total_paused = (race.get("total_paused_s") or 0) + pause_duration
        conn.execute(
            "UPDATE race_configs SET paused_at_ts = NULL, total_paused_s = ? WHERE race_id = ?",
            (total_paused, race_id),
        )
        conn.commit()
        return api_response({"ok": True, "paused": False, "total_paused_s": total_paused})
    except Exception as exc:
        logger.exception("resume failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"resume: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/tech-stop-in — car enters tech stop
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/tech-stop-in", methods=["POST"])
@rate_limit(tier="write")
def tech_stop_in_endpoint(race_id: int):
    """Car enters tech stop — does NOT end the active stint."""
    try:
        conn = get_pg_connection()
        from services.race_strategy_tech import tech_stop_in
        result = tech_stop_in(conn, race_id)
        if result is None:
            return api_error(ErrorCode.VALIDATION_ERROR, "Race not found or already in pit", status=400)
        return api_response(result)
    except Exception as exc:
        logger.exception("tech_stop_in failed")
        return api_error(ErrorCode.INTERNAL_ERROR, f"tech_stop_in: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/tech-stop-out — car exits tech stop
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/tech-stop-out", methods=["POST"])
@rate_limit(tier="write")
def tech_stop_out_endpoint(race_id: int):
    """Car exits tech stop — validates minimum duration, records pit stop."""
    try:
        conn = get_pg_connection()
        from services.race_strategy_tech import tech_stop_out
        result = tech_stop_out(conn, race_id)
        if result is None:
            return api_error(ErrorCode.VALIDATION_ERROR, "Race not found or not in tech stop", status=400)
        if result.get("error") == "too_early":
            return api_error(ErrorCode.VALIDATION_ERROR, f"Tech stop minimum not reached, {result['remaining_s']}s remaining", status=400)
        return api_response(result)
    except Exception as exc:
        logger.exception("tech_stop_out failed")
        return api_error(ErrorCode.INTERNAL_ERROR, f"tech_stop_out: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/weather-window — add a weather forecast window
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/weather-window", methods=["POST"])
@rate_limit(tier="write")
def add_weather_window_endpoint(race_id: int):
    """Add a weather forecast window to a race.

    Expects JSON body with ``start_s``, ``end_s``, ``condition``, optional ``confidence_pct``.

    Returns:
        200 with ``{"ok": true}``
        400 if JSON body is missing or required fields absent.
        404 if race not found.
    """
    data = request.get_json(silent=True) or {}
    start_s = data.get("start_s")
    end_s = data.get("end_s")
    condition = data.get("condition")
    if start_s is None or end_s is None or not condition:
        return api_error(ErrorCode.VALIDATION_ERROR, "start_s, end_s, and condition are required", status=400)

    try:
        conn = get_pg_connection()
        from services.race_strategy_weather import add_weather_window
        result = add_weather_window(conn, race_id, int(start_s), int(end_s), condition, int(data.get("confidence_pct", 100)))
        if result is None:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response(result)
    except Exception as exc:
        logger.exception("add_weather_window failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"add_weather_window: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# PUT /<race_id>/weather-window/<window_id> — update a weather window
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/weather-window/<int:window_id>", methods=["PUT"])
@rate_limit(tier="write")
def update_weather_window_endpoint(race_id: int, window_id: int):
    """Update fields on an existing weather forecast window.

    Accepts any subset of ``start_s``, ``end_s``, ``condition``, ``confidence_pct``.

    Returns:
        200 with ``{"ok": true}``
        400 if no updatable fields provided.
    """
    data = request.get_json(silent=True) or {}
    fields = {}
    for k in ("start_s", "end_s", "condition", "confidence_pct"):
        if k in data:
            fields[k] = data[k]

    try:
        conn = get_pg_connection()
        from services.race_strategy_weather import update_weather_window
        result = update_weather_window(conn, race_id, window_id, **fields)
        if result is None:
            return api_error(ErrorCode.VALIDATION_ERROR, "No updatable fields provided", status=400)
        return api_response(result)
    except Exception as exc:
        logger.exception("update_weather_window failed for race_id=%s window_id=%s", race_id, window_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"update_weather_window: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# DELETE /<race_id>/weather-window/<window_id> — delete a weather window
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/weather-window/<int:window_id>", methods=["DELETE"])
@rate_limit(tier="write")
def delete_weather_window_endpoint(race_id: int, window_id: int):
    """Delete a weather forecast window.

    Returns:
        200 with ``{"ok": true}``
    """
    try:
        conn = get_pg_connection()
        from services.race_strategy_weather import delete_weather_window
        result = delete_weather_window(conn, race_id, window_id)
        return api_response(result)
    except Exception as exc:
        logger.exception("delete_weather_window failed for race_id=%s window_id=%s", race_id, window_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"delete_weather_window: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# GET /<race_id>/weather-windows — list weather windows
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/weather-windows", methods=["GET"])
@rate_limit(tier="read")
def get_weather_windows_endpoint(race_id: int):
    """Return all weather forecast windows for a race.

    Returns:
        200 with ``{"windows": [...]}``
    """
    try:
        conn = get_pg_connection()
        from services.race_strategy_weather import get_weather_windows
        windows = get_weather_windows(conn, race_id)
        return api_response({"windows": windows})
    except Exception as exc:
        logger.exception("get_weather_windows failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"get_weather_windows: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/condition — set current weather condition
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/condition", methods=["POST"])
@rate_limit(tier="write")
def set_condition_endpoint(race_id: int):
    """Set the current weather condition on the race.

    Expects JSON body with ``condition`` (one of ``dry``, ``damp``, ``wet``).

    Returns:
        200 with ``{"ok": true, "condition": "..."}``
        400 if condition is invalid.
    """
    data = request.get_json(silent=True) or {}
    condition = data.get("condition")
    if condition not in ("dry", "damp", "wet"):
        return api_error(ErrorCode.VALIDATION_ERROR, "condition must be 'dry', 'damp', or 'wet'", status=400)

    try:
        conn = get_pg_connection()
        from services.race_strategy_weather import set_current_condition
        result = set_current_condition(conn, race_id, condition)
        if result is None:
            return api_error(ErrorCode.VALIDATION_ERROR, "Invalid condition value", status=400)
        return api_response(result)
    except Exception as exc:
        logger.exception("set_condition failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"set_condition: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/strategies — generate ranked weather strategies
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/strategies", methods=["POST"])
@rate_limit(tier="write")
def generate_strategies_endpoint(race_id: int):
    """Generate multiple optimizer strategies for weather conditions."""
    data = request.get_json(silent=True) or {}
    try:
        conn = get_pg_connection()
        from services.race_strategy import get_race, _compute_elapsed_s, _get_sleep_windows
        race = get_race(conn, race_id)
        if not race:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)

        drivers_rows = conn.execute(
            "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
            (race_id,),
        ).fetchall()
        drivers = [dict(r) for r in drivers_rows]

        elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)

        # Build weather windows in SOLVER-RELATIVE time (0 = now)
        # The solver operates on [0, remaining_time], not absolute race clock.
        wet_lap_time = data.get("wet_lap_time_s")
        rain_duration_min = data.get("rain_duration_min")
        weather_windows = []
        if wet_lap_time and rain_duration_min:
            # User says "rain for X minutes starting now" → relative [0, X*60]
            weather_windows = [{
                "start_s": 0,
                "end_s": int(rain_duration_min) * 60,
                "condition": race.get("current_condition") or "wet",
                "confidence_pct": 100,
            }]
        else:
            # Use stored weather windows — convert absolute → relative
            try:
                from services.race_strategy_weather import get_weather_windows
                stored = get_weather_windows(conn, race_id)
                for w in stored:
                    ws = max(0, w.get("start_s", 0) - elapsed)
                    we = max(0, w.get("end_s", 0) - elapsed)
                    if we > ws:
                        weather_windows.append({
                            "start_s": ws,
                            "end_s": we,
                            "condition": w.get("condition", "dry"),
                        })
            except Exception:
                pass

        # Build solver config for remaining race
        remaining_time = race["race_duration_s"] - elapsed
        sleep_windows = _get_sleep_windows(conn, race_id)

        from optimizer.csp_solver import SolverConfig, DriverConstraints
        from optimizer.multi_strategy import generate_strategies

        pit_time = race.get("min_pit_stop_s") or 120
        fuel_autonomy = race.get("fuel_autonomy_s") or 0
        empty_kart = race.get("empty_kart_kg") or 0.0
        full_tank_cfg = race.get("full_tank_kg") or 0.0
        fuel_capacity = full_tank_cfg if full_tank_cfg <= empty_kart or empty_kart == 0 else full_tank_cfg - empty_kart
        burn_rate = fuel_capacity / fuel_autonomy if fuel_autonomy > 0 else 0.0

        # Count remaining stints
        completed = conn.execute(
            "SELECT COUNT(*) as cnt FROM race_stints WHERE race_id = ? AND status IN ('completed', 'active')",
            (race_id,),
        ).fetchone()
        completed_count = (completed["cnt"] if isinstance(completed, dict) else completed[0]) if completed else 0
        remaining_stints = max(1, (race.get("desired_stints") or 20) - completed_count)

        solver_config = SolverConfig(
            race_duration_s=remaining_time,
            n_stints=remaining_stints,
            pit_time_s=pit_time,
            fuel_capacity_kg=fuel_capacity,
            fuel_burn_rate_kgs=burn_rate,
            blackout_start_s=0,
            blackout_end_s=(race.get("blackout_end_min") or 0) * 60,
            quick_change=bool(race.get("quick_change_enabled")),
            optimization_mode=race.get("optimization_mode", "equal"),
            weather_windows=weather_windows,
        )

        solver_drivers = []
        for d in sorted(drivers, key=lambda x: x.get("driver_order", 0)):
            sw = []
            if sleep_windows:
                for s in sleep_windows:
                    if s.get("driver_id") == d["id"]:
                        sw.append((s.get("start_s", 0), s.get("end_s", 0)))
            solver_drivers.append(DriverConstraints(
                id=d["id"],
                name=d.get("driver_name", ""),
                avg_lap_time_s=d.get("avg_lap_time_s") or 65.0,
                weight_kg=d.get("weight_kg") or 70.0,
                wet_confidence=d.get("wet_confidence") or 0.5,
                max_stint_s=d.get("max_stint_s"),
                min_stint_s=d.get("min_stint_s"),
                max_cumulative_s=d.get("max_cumulative_s"),
                min_cumulative_s=d.get("min_cumulative_s"),
                min_rest_s=d.get("min_rest_s") or 0,
                allow_double_stint=bool(d.get("allow_double_stint")),
                sleep_windows=sw,
            ))

        strategies = generate_strategies(solver_config, solver_drivers)

        # Serialize for API response
        response = []
        for strat in strategies:
            m = strat.metrics
            stints_data = [{
                "stint_order": s.stint_order,
                "driver_id": s.driver_id,
                "driver_name": s.driver_name,
                "start_s": s.start_s + elapsed,
                "duration_s": s.duration_s,
            } for s in strat.result.stints]

            response.append({
                "name": strat.name,
                "description": strat.description,
                "approach": strat.approach,
                "score": round(strat.score, 1),
                "stints": stints_data,
                "metrics": {
                    "pits_in_rain": m.pits_in_rain,
                    "pits_in_dry": m.pits_in_dry,
                    "rain_drive_s": m.rain_drive_s,
                    "dry_drive_s": m.dry_drive_s,
                    "driver_transitions": m.driver_transitions,
                    "min_stint_s": m.min_stint_s,
                    "max_stint_s": m.max_stint_s,
                    "flexibility_score": round(m.flexibility_score, 2),
                    "risk_score": round(m.risk_score, 2),
                    "total_pit_s": m.total_pit_s,
                },
            })

        return api_response({"strategies": response})

    except Exception as exc:
        logger.exception("strategies failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"strategies: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# GET /<race_id>/planned-vs-actual — planned vs actual comparison
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/planned-vs-actual", methods=["GET"])
@rate_limit(tier="read")
def planned_vs_actual_endpoint(race_id: int):
    """Return planned-vs-actual stint comparison for a retrospective race.

    Returns:
        200 with comparison dict.
        404 if race not found.
    """
    try:
        conn = get_pg_connection()
        from services.race_strategy_bridge import get_planned_vs_actual
        result = get_planned_vs_actual(conn, race_id)
        if result is None:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response(result)
    except Exception as exc:
        logger.exception("planned_vs_actual failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, "Internal server error", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/penalty — add a penalty
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/penalty", methods=["POST"])
@rate_limit(tier="write")
def add_penalty_endpoint(race_id: int):
    """Add a penalty to a race (passage, time, laps deducted)."""
    data = request.get_json(silent=True) or {}
    penalty_type = data.get("penalty_type")
    if not penalty_type:
        return api_error(ErrorCode.VALIDATION_ERROR, "penalty_type is required", status=400)
    try:
        conn = get_pg_connection()
        from services.race_strategy_penalty import add_penalty
        result = add_penalty(
            conn, race_id,
            penalty_type=penalty_type,
            laps_deducted=data.get("laps_deducted", 0),
            reason=data.get("reason"),
            passage_duration_s=data.get("passage_duration_s"),
        )
        if result is None:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response(result)
    except Exception as exc:
        logger.exception("add_penalty failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"add_penalty: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# POST /<race_id>/penalty/<penalty_id>/clear — clear a penalty
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/penalty/<int:penalty_id>/clear", methods=["POST"])
@rate_limit(tier="write")
def clear_penalty_endpoint(race_id: int, penalty_id: int):
    """Mark a penalty as cleared (e.g. passage served)."""
    try:
        conn = get_pg_connection()
        from services.race_strategy_penalty import clear_penalty
        result = clear_penalty(conn, race_id, penalty_id)
        if result is None:
            return api_error(ErrorCode.NOT_FOUND, "Penalty not found", status=404)
        return api_response(result)
    except Exception as exc:
        logger.exception("clear_penalty failed for race_id=%s penalty_id=%s", race_id, penalty_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"clear_penalty: {type(exc).__name__}: {exc}", status=500)


# ---------------------------------------------------------------------------
# GET /<race_id>/penalties — list all penalties for a race
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>/penalties", methods=["GET"])
@rate_limit(tier="read")
def get_penalties_endpoint(race_id: int):
    """Return all penalties for a race."""
    try:
        conn = get_pg_connection()
        from services.race_strategy_penalty import get_penalties
        penalties = get_penalties(conn, race_id)
        return api_response({"penalties": penalties})
    except Exception as exc:
        logger.exception("get_penalties failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"get_penalties: {type(exc).__name__}: {exc}", status=500)
