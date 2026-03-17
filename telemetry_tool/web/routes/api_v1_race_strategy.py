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

        # Resolve duration limit from entitlements
        max_dur = None
        try:
            from flask import g

            from auth.entitlements import get_user_entitlements
            user_id = getattr(g, "current_user_id", None)
            ws_id = getattr(g, "workspace_id", None)
            if user_id is not None:
                ent = get_user_entitlements(conn, user_id, ws_id)
                max_dur = ent.get("race_strategy_max_duration_s")
        except Exception:
            pass  # Fail open — don't block on entitlement resolution errors

        race_id = create_race(conn, data, max_duration_s=max_dur)
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

        # Resolve duration limit from entitlements
        max_dur = None
        try:
            from flask import g

            from auth.entitlements import get_user_entitlements
            user_id = getattr(g, "current_user_id", None)
            ws_id = getattr(g, "workspace_id", None)
            if user_id is not None:
                ent = get_user_entitlements(conn, user_id, ws_id)
                max_dur = ent.get("race_strategy_max_duration_s")
        except Exception:
            pass  # Fail open — don't block on entitlement resolution errors

        success = update_race(conn, race_id, data, max_duration_s=max_dur)
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
        result = run_optimization(conn, race_id)
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
        result = reoptimize(conn, race_id)
        if result.get("error") == "not found":
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response(result)
    except Exception as exc:
        logger.exception("reoptimize failed for race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, f"reoptimize: {type(exc).__name__}: {exc}", status=500)


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
