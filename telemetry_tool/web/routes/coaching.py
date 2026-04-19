"""
Coaching API — prescriptive coaching endpoint.

Exposes the ``track_surface.prescriptive`` engine as a stateless HTTP
endpoint. The caller supplies upstream evidence (corner_packets) and
weakness records (from DevelopmentIntelligence); the endpoint returns a
versioned ``CoachingSheet`` JSON dict (the same shape embedded under
``prescriptive_coaching`` in ``track-surface-ok-data.json``).

Stateless by design — no DB writes, no workspace filtering, no caching.
This keeps the endpoint trivially testable and isolates the engine from
session-storage concerns while the Phase 3 migration is in flight.

Auth — when ``AUTH_REQUIRED=1`` this endpoint sits behind the standard
JWT middleware (no allowlist entry needed). Local/desktop mode bypasses
auth per the global policy.
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, request

from track_surface.prescriptive import (
    generate_coaching_sheet,
    to_json_dict,
)
from web.api_utils import ErrorCode, api_error, api_response

logger = logging.getLogger(__name__)

bp = Blueprint("coaching", __name__, url_prefix="/api/v1/coaching")


@bp.route("/prescriptive", methods=["POST"])
def post_prescriptive() -> tuple:
    """Compute a prescriptive coaching sheet from upstream evidence.

    Request body (application/json)::

        {
            "corner_packets":    [ {...}, ... ],
            "weaknesses":        [ {...}, ... ],
            "sessions_analyzed": int,
            "laps_analyzed":     int
        }

    Responses:
        200  — standard envelope, ``data`` is the CoachingSheet JSON dict.
        422  — request body validation failed (missing fields, wrong types,
               malformed weakness/packet — e.g., missing ``behavior_id``).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Request body must be a JSON object",
            status=422,
        )

    errors = _validate_shape(payload)
    if errors:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Request body failed validation",
            details=errors,
            status=422,
        )

    try:
        sheet = generate_coaching_sheet(
            corner_packets=payload["corner_packets"],
            weaknesses=payload["weaknesses"],
            sessions_analyzed=int(payload["sessions_analyzed"]),
            laps_analyzed=int(payload["laps_analyzed"]),
        )
    except KeyError as e:
        # Missing required upstream key (e.g., behavior_id on a weakness,
        # corner_id on a packet) — structured 422, not a 500.
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Upstream record missing required key: {e}",
            status=422,
        )
    except (TypeError, ValueError) as e:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Upstream record failed type coercion: {e}",
            status=422,
        )

    return api_response(to_json_dict(sheet), status=200)


# ── validation ──────────────────────────────────────────────────

_REQUIRED_FIELDS = {
    "corner_packets": list,
    "weaknesses": list,
    "sessions_analyzed": int,
    "laps_analyzed": int,
}


def _validate_shape(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Return a list of {field, message} entries describing any top-level
    shape violations. Empty list means the payload is structurally sound;
    deeper validation happens inside the engine/adapters."""
    errs: list[dict[str, str]] = []
    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in payload:
            errs.append({"field": field, "message": "missing required field"})
            continue
        value = payload[field]
        # Accept bool as int? No — booleans are their own error shape.
        if expected_type is int:
            if not isinstance(value, int) or isinstance(value, bool):
                errs.append({"field": field, "message": "must be an integer"})
        elif not isinstance(value, expected_type):
            errs.append({
                "field": field,
                "message": f"must be a {expected_type.__name__}",
            })
    return errs
