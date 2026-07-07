"""web/routes/onboarding_routes.py
--------------------------------
Track Onboarding Loop (Phase 1, Task 12): the two token-authorized HTTP
endpoints an operator's emailed annotator link drives.

SECURITY: these are the ONLY two ``/api/v1/*`` routes exempt from the normal
JWT ``auth_middleware`` (see ``web/middleware/auth.py``'s
``_AUTH_PUBLIC_PATHS`` -- an exact-path match, not a prefix). In its place, a
signed, single-use, request_id-scoped token (``onboarding.tokens``) is the
SOLE authorization. Every token failure -- missing, malformed, expired,
tampered, wrong request_id, or a ``jti`` that no longer matches the row
(already consumed/rotated by a prior save) -- returns the SAME generic 401,
so a caller can never learn *which* check failed (``onboarding.tokens``'s own
module docstring states the identical requirement for ``verify``).

  GET  /api/v1/onboarding/draft?req=<id>  -- fetch the auto-drafted geojson
       for the annotator to render and let the operator correct.
  POST /api/v1/onboarding/save            -- submit the corrected geojson;
       runs it through the same fail-closed gates as the CLI bless
       (``onboarding.bless_service.bless_geometry``, ``force=False`` --
       including its own "did you actually edit the draft?" check, given
       the stored auto-draft) and, on success, revokes the token (so the
       one-shot link can never be replayed) and best-effort kicks off
       ``onboarding.reprocess.reprocess_after_bless``.

``canonical_id``/``track_key``/``session_refs`` are ALWAYS read from the row
fetched via the token-verified ``request_id`` -- NEVER from the request body
-- so a client can never retarget a bless at an arbitrary canonical_id
(Global Constraint: "reviewed_by and canonical_id are server-derived, client
values ignored"). Migration 081's ``track_onboarding_requests`` table has no
separate ``canonical_id`` column: ``track_key`` already IS the canonical id
at this stage of the loop (the plan's Task 13 interfaces note calls the
trigger's ``track_key`` "canonical" outright), so both `bless_geometry` and
`reprocess_after_bless` are called with ``canonical_id = row["track_key"]``.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, g, request

from onboarding import repo
from onboarding.bless_service import bless_geometry
from onboarding.draft import DraftError, load_draft
from onboarding.reprocess import reprocess_after_bless
from onboarding.tokens import TokenError, verify
from web.api_utils import ErrorCode, api_error, api_response
from web.db_pg import get_maint_connection, return_pg_connection
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("onboarding", __name__, url_prefix="/api/v1/onboarding")

__all__ = ["bp"]

# Generic, detail-free message for every auth failure (see module docstring).
_GENERIC_AUTH_ERROR = "Invalid or expired onboarding link"

# Strictest existing rate-limit tier (RATE_TIERS in web/rate_limit.py):
# ties with "device_pair" at 5 requests/3600s -- "analyze" is used here as
# the closer semantic fit for a server-gated operator action.
_RATE_TIER = "analyze"


def _extract_token(*, allow_query: bool = False) -> str | None:
    """Bearer header preferred; ``?token=`` query-string fallback for the
    annotator's plain ``fetch`` call (plan: "prefer header") -- but ONLY for
    the read-only ``GET /draft`` route. The write route (``POST /save``)
    must be header-only: a query-string token can leak via proxy/access
    logs, browser history, or ``Referer`` headers in a way a header never
    does, and that risk is only acceptable for the read of an already-public
    auto-draft, never for blessing a geometry."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    if allow_query:
        return request.args.get("token") or None
    return None


def _auth_deny():
    return api_error(ErrorCode.UNAUTHORIZED, _GENERIC_AUTH_ERROR, status=401)


def _authorize(request_id: str | None, token: str | None, conn) -> dict | None:
    """Verify token + jti-match; return the row dict on success, else None.

    Every failure path -- missing request_id/token, malformed/expired/
    tampered/wrong-scope/wrong-request_id token, unknown request_id, or a
    jti that no longer matches the row (already consumed by a prior save,
    or rotated) -- collapses to ``None`` uniformly so the route emits one
    generic 401 without leaking which check failed.
    """
    if not request_id or not token:
        return None
    try:
        claims = verify(token, request_id)
    except TokenError:
        return None
    row = repo.get(conn, request_id)
    if row is None:
        return None
    if claims.get("jti") != row.get("token_jti"):
        return None
    return row


def _scoped_rate_limit(fn):
    """Outer decorator: set ``g.workspace_id`` to the client IP alone BEFORE
    ``@rate_limit`` computes its scope key, and short-circuit CORS preflight
    entirely (no auth, no quota consumed).

    ``web/rate_limit.py``'s ``rate_limit()`` decorator prefers
    ``g.workspace_id`` over ``g.current_user_id``/IP when building its Redis
    key -- there is no logged-in user on these token-authed routes, so
    stuffing the IP into ``g.workspace_id`` reuses the existing sliding-
    window limiter for this route's strict tier without duplicating the
    Lua/Redis machinery.

    IMPORTANT: the key is IP-ONLY -- it must NOT include ``request_id``.
    ``request_id`` is read from the query string / JSON body *before* any
    auth check runs, so it is fully attacker-controlled; keying the bucket
    on it would let a caller mint an unlimited number of fresh buckets (one
    per guessed/forged request_id) and the rate limit would never engage.
    All requests from one IP share a single bucket regardless of request_id.

    Must be the OUTER decorator (listed above ``@rate_limit`` in the stack)
    so it runs first, before ``rate_limit`` reads ``g.workspace_id``.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            # Browsers never attach auth headers to preflight, and CORS
            # response headers are added globally by the after_request
            # hook in web/middleware/cors.py regardless of body.
            return "", 204
        ip = request.remote_addr or "unknown"
        g.workspace_id = f"onboarding:{ip}"
        return fn(*args, **kwargs)
    return wrapper


@bp.route("/draft", methods=["GET", "OPTIONS"])
@_scoped_rate_limit
@rate_limit(_RATE_TIER)
def get_draft():
    """``GET /api/v1/onboarding/draft?req=<id>`` -- fetch the auto-draft.

    The draft file path is derived ONLY from ``request_id`` (via
    ``draft.load_draft``'s own sanitizer) -- never from client input.
    """
    request_id = request.args.get("req")
    token = _extract_token(allow_query=True)

    conn = get_maint_connection()
    try:
        row = _authorize(request_id, token, conn)
    finally:
        return_pg_connection(conn)

    if row is None:
        return _auth_deny()

    try:
        draft = load_draft(request_id)
    except DraftError:
        logger.warning(
            "onboarding draft: no draft on disk for request_id=%s", request_id
        )
        return api_error(ErrorCode.NOT_FOUND, "Draft not found", status=404)

    return api_response(draft)


@bp.route("/save", methods=["POST", "OPTIONS"])
@_scoped_rate_limit
@rate_limit(_RATE_TIER)
def save_geometry():
    """``POST /api/v1/onboarding/save`` -- submit the corrected geojson.

    ``canonical_id``/``track_key``/``session_refs`` are ALWAYS read off the
    row (never the body) -- see module docstring. The "did the operator
    actually edit this?" check is ``bless_geometry``'s own job (Task 8):
    passing it the stored auto-draft makes it reject an unchanged
    resubmission with ``failures=["unreviewed_draft"]``, surfaced below via
    the same generic ``ok=False`` -> 422 path as any other gate failure.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    request_id = body.get("request_id")
    geometry = body.get("geometry")
    token = _extract_token(allow_query=False)  # header-only: see _extract_token docstring

    conn = get_maint_connection()
    try:
        row = _authorize(request_id, token, conn)
        if row is None:
            return _auth_deny()

        if not isinstance(geometry, dict):
            return api_error(ErrorCode.VALIDATION_ERROR, "geometry is required", status=400)

        # Required deploy-config: the reviewer attestation is derived from
        # this. Degrade to a clean 503 rather than KeyError->500 when unset
        # (deny-safe: nothing is blessed). See runbook env table.
        operator_email = os.environ.get("ONBOARDING_OPERATOR_EMAIL")
        if not operator_email:
            logger.error(
                "onboarding save: ONBOARDING_OPERATOR_EMAIL unset -- cannot "
                "derive reviewer attestation; refusing bless"
            )
            return api_error(
                ErrorCode.INTERNAL_ERROR,
                "Onboarding is not configured",
                status=503,
            )

        # Server-derived, never from the body (attacker-controlled fields
        # in the request JSON are silently ignored).
        canonical_id = row.get("track_key")
        track_key = row.get("track_key")
        session_refs = row.get("session_refs") or []
        vehicle_classes = row.get("vehicle_classes") or []

        try:
            auto_draft = load_draft(request_id)
        except DraftError:
            # A valid, pending request ALWAYS has a draft on disk (it's
            # written before the token is ever emailed out) -- its absence
            # is a server-side fault, not a legitimate "no draft to compare
            # against" case. Falling back to ``auto_draft=None`` here would
            # silently disable bless_geometry's unreviewed-draft gate (it
            # only runs that check when given a draft to diff against),
            # letting an unedited auto-draft slip through as if reviewed.
            # Reject and let the operator retry once the draft is restored
            # -- do NOT revoke the token, this isn't the operator's fault.
            logger.warning(
                "onboarding save: draft missing for request_id=%s -- "
                "refusing to bypass unreviewed-draft gate", request_id,
            )
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Geometry rejected",
                details=[{"failure": "draft_missing"}],
                status=422,
            )

        with tempfile.TemporaryDirectory(prefix="onboarding_save_") as tmp_dir:
            tmp_path = Path(tmp_dir) / f"{request_id}.geojson"
            tmp_path.write_text(json.dumps(geometry), encoding="utf-8")

            result = bless_geometry(
                geojson_path=tmp_path,
                canonical_id=canonical_id,
                reviewed_by=f"onboarding:{operator_email}",
                auto_draft_geojson=auto_draft,
                conn=conn,
            )

        if not result.ok:
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "Geometry rejected",
                details=[{"failure": f} for f in result.failures],
                status=422,
            )

        # Revoke the token (single-use) in the SAME commit as the status
        # flip -- a bless can never succeed twice off the same link.
        updated = repo.set_status(
            conn, request_id, "blessed",
            blessed_at=datetime.now(timezone.utc), token_jti=None,
        )
        conn.commit()

        if not updated:
            # ``set_status``'s ``WHERE status <> 'blessed'`` guard returned
            # rowcount 0 -- either a concurrent/duplicate save already
            # blessed (and revoked the token for) this request, or the row
            # is gone. Either way the geometry IS blessed; it just wasn't
            # THIS request that did it, so don't re-run token revocation
            # bookkeeping or reprocessing (the winning request already did,
            # or will). Report success idempotently rather than implying
            # this call performed the bless.
            logger.warning(
                "onboarding save: set_status no-op for request_id=%s -- "
                "already blessed by a concurrent/duplicate save (or row gone)",
                request_id,
            )
            return api_response({"status": "blessed"})

        try:
            reprocess_after_bless(
                track_key=track_key,
                canonical_id=canonical_id,
                session_refs=session_refs,
                vehicle_classes=vehicle_classes,
                conn=conn,
            )
        except Exception:
            # Best-effort (module docstring / Task 9): a reprocess hiccup
            # must never turn an already-committed bless into a failed
            # response.
            logger.exception(
                "onboarding save: reprocess_after_bless failed for "
                "request_id=%s canonical_id=%s -- bless already committed",
                request_id, canonical_id,
            )

        return api_response({"status": "blessed"})
    finally:
        return_pg_connection(conn)
