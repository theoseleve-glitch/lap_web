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

from web.api_utils import ErrorCode, api_error, api_response

from services.race_strategy import (
    list_races,
    get_race_detail,
    create_race,
    update_race,
    delete_race,
    run_optimization,
    go_live,
    finish_race,
    get_live_state,
    end_stint,
    toggle_fuel,
    set_pit_type,
    reoptimize,
    export_race,
    import_race,
    duplicate_race,
    get_summary,
)

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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
                if ent.get("race_strategy_limit") == "limited_3h":
                    max_dur = 10800
        except Exception:
            pass  # Fail open — don't block on entitlement resolution errors

        race_id = create_race(conn, data, max_duration_s=max_dur)
        return api_response({"race_id": race_id}, status=201)
    except ValueError as ve:
        return api_error(ErrorCode.VALIDATION_ERROR, str(ve), status=400)
    except Exception as exc:
        logger.exception("Failed to create race")
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
                if ent.get("race_strategy_limit") == "limited_3h":
                    max_dur = 10800
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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


# ---------------------------------------------------------------------------
# DELETE /<race_id> — delete race
# ---------------------------------------------------------------------------

@bp.route("/<int:race_id>", methods=["DELETE"])
@rate_limit(tier="write")
def delete_race_endpoint(race_id: int):
    """Delete a race and all associated data.

    Returns:
        200 with ``{"ok": true}``
        404 if race not found.
    """
    try:
        conn = get_pg_connection()
        deleted = delete_race(conn, race_id)
        if not deleted:
            return api_error(ErrorCode.NOT_FOUND, "Race not found", status=404)
        return api_response({"ok": True})
    except Exception as exc:
        logger.exception("Failed to delete race_id=%s", race_id)
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        result = end_stint(
            conn,
            race_id,
            driver_change=data.get("driver_change", True),
            refueled=data.get("refueled", False),
            notes=data.get("notes"),
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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


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
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)
