"""tasks/onboarding_tasks.py
----------------------------
Celery task ``draft_and_notify`` -- Phase 1, Task 10 of the Track Onboarding
Loop.

Runs when ``onboarding.service.record_missing_geometry`` enqueues a fresh (or
retried ``draft_failed``) request: auto-drafts the track boundary (SAM2, else
the GPS-only fallback), persists the draft, mints a one-time signed annotator
link, and emails the operator EXACTLY ONCE.

Must be idempotent under Celery's at-least-once delivery + retries. Two
independent guards make that so:

  1. ``repo.claim_for_drafting`` is a compare-and-set gate (only a row in
     ``requested``/``draft_failed`` can be claimed, and it flips to
     ``drafting`` atomically) -- a second concurrent or redelivered call for
     the same ``request_id`` sees ``False`` and returns immediately: no
     double draft, no double save, no double mint, no double email.
  2. The email send is separately guarded by re-reading the row's
     ``emailed_at`` right before sending -- an already-``emailed_at``-set
     row is never re-emailed, even on a call that (for whatever reason)
     reaches this point a second time.

Registration idiom copied EXACTLY from ``tasks/email_tasks.py``: try the real
Celery app, fall back to a plain function when it's absent (Celery not
installed/configured, e.g. under pytest) so the task is directly callable
without a broker:

    _USE_CELERY = False
    try:
        from celery_app import celery as _celery_app
        _USE_CELERY = True
    except Exception:
        _celery_app = None

    if _USE_CELERY and _celery_app is not None:
        @_celery_app.task(...)
        def draft_and_notify(request_id): ...
    else:
        def draft_and_notify(request_id): ...  # type: ignore[misc]

Dedicated queue: this task is registered directly with ``queue="onboarding"``
in the decorator -- the same mechanism ``tasks/racing_line_tasks.py`` uses
for its ``"pipeline"`` queue (a queue set on the task itself, independent of
``celery_app.py``'s ``task_routes`` dict). ``celery_app.py`` is NOT modified
by this task: it is not added to that module's ``include=[...]`` list,
mirroring how Task 9's ``onboarding/reprocess.py`` (a plain function, not a
Celery task) also left ``celery_app.py`` untouched. Wiring this task's module
into the worker's ``include`` list (so a real worker process discovers it)
is worker-deployment plumbing, not part of this task's scope, and is called
out in the task report.

The real logic lives in :func:`_run_draft_and_notify`, a plain function
taking an already-open connection, so tests can call it directly without a
Celery broker or a live Postgres connection.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from onboarding import repo, tokens
from onboarding.draft import (
    DraftError,
    gps_only_draft,
    sam2_draft,
    save_draft,
    validate_bbox,
)
from tasks.email_tasks import send_email_async

logger = logging.getLogger(__name__)

__all__ = ["draft_and_notify"]

_MAX_RETRIES = 3
_EMAIL_TEMPLATE = "onboarding_task"

# ---------------------------------------------------------------------------
# Celery app import (graceful fallback for testing) -- copied from
# tasks/email_tasks.py's exact idiom.
# ---------------------------------------------------------------------------

_USE_CELERY = False
try:
    from celery_app import celery as _celery_app
    _USE_CELERY = True
except Exception:
    _celery_app = None


def _centerline_from_row(row: dict) -> list:
    """Driven-lap centerline (``[[lon, lat], ...]``) for the drafters.

    Migration 081's ``draft_centerline`` column (Task 13) is the first-class
    home for this: a downsampled lon/lat polyline of one driven lap, written
    at request-creation time (``onboarding.service.record_missing_geometry``
    -> ``repo.upsert_open_request``) and threaded straight through to this
    row. Falls back to an empty list when absent (e.g. a request created
    before Task 13, or a caller that never supplied one) -- ``gps_only_draft``
    raises ``DraftError`` on an empty centerline (caught above as an
    unexpected drafting failure) and ``sam2_draft`` just returns ``None``,
    falling through to the GPS-only path.
    """
    centerline = row.get("draft_centerline")
    if isinstance(centerline, list):
        return centerline
    return []


def _run_draft_and_notify(request_id: str, conn: Any) -> dict:
    """Plain, Celery-free implementation of the draft-and-notify flow.

    See the module docstring for the two idempotency guards this relies on.
    Never raises: every foreseeable failure mode (lost claim race, invalid
    bbox, drafting error) is turned into a ``draft_failed`` status write and
    a normal return, so a Celery worker never crashes on this task.
    """
    if not repo.claim_for_drafting(conn, request_id):
        logger.info(
            "draft_and_notify: request_id=%s not claimable (already drafting/"
            "past that stage) -- idempotent no-op",
            request_id,
        )
        return {"ok": True, "skipped": "already_claimed"}

    row = repo.get(conn, request_id)
    if row is None:
        logger.error(
            "draft_and_notify: request_id=%s claimed but row missing", request_id
        )
        return {"ok": False, "error": "row_not_found"}

    bbox = row.get("bbox")
    try:
        validate_bbox(bbox)
    except DraftError as exc:
        logger.warning(
            "draft_and_notify: invalid bbox for request_id=%s: %s", request_id, exc
        )
        repo.set_status(conn, request_id, "draft_failed", error=str(exc)[:500])
        return {"ok": False, "error": "invalid_bbox"}

    centerline = _centerline_from_row(row)
    try:
        geojson = sam2_draft(bbox, centerline)
        if geojson is not None:
            draft_kind, drafted_status = "sam2", "drafted"
        else:
            geojson = gps_only_draft(centerline)
            draft_kind, drafted_status = "gps_only", "drafted_gps_only"
    except Exception as exc:  # noqa: BLE001 -- must never crash the worker
        logger.exception(
            "draft_and_notify: drafting failed for request_id=%s", request_id
        )
        repo.set_status(conn, request_id, "draft_failed", error=str(exc)[:500])
        return {"ok": False, "error": "draft_failed"}

    draft_path = save_draft(request_id, geojson)
    repo.set_status(
        conn, request_id, drafted_status,
        draft_path=draft_path, draft_status=draft_kind,
    )

    raw_token, jti = tokens.mint(request_id)
    repo.set_status(conn, request_id, drafted_status, token_jti=jti)

    row = repo.get(conn, request_id)
    if row is not None and row.get("emailed_at") is None:
        annotator_host = os.environ["ANNOTATOR_HOST"]
        operator_email = os.environ["ONBOARDING_OPERATOR_EMAIL"]
        # Token in the URL FRAGMENT (never the query string) so it never
        # lands in server access logs or Referer headers.
        annotator_url = f"{annotator_host}/?req={request_id}#token={raw_token}"
        send_email_async.delay(
            _EMAIL_TEMPLATE,
            operator_email,
            {
                "track_label": row.get("track_label"),
                "track_key": row.get("track_key"),
                "annotator_url": annotator_url,
            },
        )
        repo.set_status(
            conn, request_id, "emailed", emailed_at=datetime.now(timezone.utc)
        )
    else:
        logger.info(
            "draft_and_notify: request_id=%s already emailed -- skipping resend",
            request_id,
        )

    return {"ok": True, "status": drafted_status}


def _dispatch(request_id: str) -> dict:
    """Open a maint connection, run the flow, commit, always return it."""
    from web.db_pg import get_maint_connection, return_pg_connection

    conn = get_maint_connection()
    try:
        result = _run_draft_and_notify(request_id, conn)
        conn.commit()
        return result
    finally:
        return_pg_connection(conn)


if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(
        name="tasks.onboarding_tasks.draft_and_notify",
        queue="onboarding",
        acks_late=True,
        max_retries=_MAX_RETRIES,
    )
    def draft_and_notify(request_id: str) -> dict:
        return _dispatch(request_id)
else:
    def draft_and_notify(request_id: str) -> dict:  # type: ignore[misc]
        return _dispatch(request_id)
