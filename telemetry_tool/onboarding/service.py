"""
onboarding/service.py
----------------------
``record_missing_geometry`` -- the entry point the in-session build path
(the GT-miss detection hook, a later task) calls when an operator analyses
a session for a track with no ground-truth limits.

It dedups via ``onboarding/repo.py`` (Task 4, atomic upsert on the partial
unique index) and enqueues the async draft job (``tasks.onboarding_tasks``,
Task 10 -- not built yet) only for a genuinely new or previously-failed
request. It refuses to onboard outright in several cases -- see the
docstring below.

Connection pattern: mirrors ``tasks/racing_line_tasks.py``
(``get_maint_connection`` / ``return_pg_connection``, standalone, explicit
close in ``finally``) rather than ``tasks/email_tasks._get_pg`` (Flask-``g``
cached). ``track_onboarding_requests`` is a global, non-RLS table (migration
081, same footing as 078/079) and this function may run from a Celery
pipeline task as easily as from a Flask request, so a connection that does
not depend on Flask app context is the safer default here.
"""
from __future__ import annotations

import logging

from onboarding import repo
from track_surface.gt_loader import load_gt
from web.db_pg import get_maint_connection, return_pg_connection

logger = logging.getLogger(__name__)

__all__ = ["record_missing_geometry"]

# track_key values that must never be onboarded under -- caller-side
# "no match"/"low confidence" sentinels, not real track identities.
_BOGUS_TRACK_KEYS = {"", None, "unknown_track"}

# Existing-row statuses for which a repeat miss should retry the enqueue
# (the previous draft attempt errored out; nothing else will retry it).
_RETRYABLE_STATUSES = {"draft_failed"}


def record_missing_geometry(
    *,
    track_key: str | None,
    track_label: str | None,
    fingerprint: dict | None,
    bbox: dict | None,
    session_ref: str,
    is_operator_run: bool,
    draft_centerline: list | None = None,
    vehicle_classes: list | None = None,
) -> str | None:
    """Dedup + enqueue an onboarding draft for a real GT gap.

    Refuses to onboard (returns ``None``, logs at INFO/DEBUG) when:
      1. ``is_operator_run`` is false -- end-user uploads never onboard.
      2. ``track_key`` is ``""``, ``None``, or ``"unknown_track"`` -- never
         write GT under a bogus key.
      3. ``gt_loader.load_gt(track_key)`` is not ``None`` -- GT already
         exists; re-confirmed here rather than trusting the caller's
         (possibly stale) "gt is None" check.

    ``draft_centerline`` (a downsampled lon/lat polyline of the driven lap,
    migration 081) is forwarded as-is to ``repo.upsert_open_request``, which
    applies first-non-null-wins semantics on conflict -- this function does
    not otherwise inspect or validate it.

    ``vehicle_classes`` (final-review finding I2) is forwarded as-is to
    ``repo.upsert_open_request``, which merges it into the request's
    deduped ``vehicle_classes`` union on conflict. This is what lets
    ``onboarding/reprocess.py::reprocess_after_bless`` enqueue the 30-min
    fast-path ``compute_racing_lines`` for every vehicle class actually
    seen while the track was unmapped, not just ``"generic"``.

    Otherwise, atomically upserts the single open request for
    ``track_key`` (``repo.upsert_open_request``). The async draft job is
    enqueued only when the row was just created, or when the pre-existing
    row's status is ``"draft_failed"`` (retryable) -- attaching to any
    other already in-flight/emailed row does not re-enqueue or re-email.

    Returns the request id, or ``None`` if skipped.
    """
    if not is_operator_run:
        logger.debug(
            "record_missing_geometry: skip (not an operator run) track_key=%s",
            track_key,
        )
        return None

    if track_key in _BOGUS_TRACK_KEYS:
        logger.info(
            "record_missing_geometry: skip (bogus track_key=%r)", track_key
        )
        return None

    if load_gt(track_key) is not None:
        logger.info(
            "record_missing_geometry: skip (GT already present) track_key=%s",
            track_key,
        )
        return None

    conn = get_maint_connection()
    try:
        request_id, created = repo.upsert_open_request(
            conn,
            track_key=track_key,
            track_label=track_label,
            fingerprint=fingerprint,
            bbox=bbox,
            session_ref=session_ref,
            draft_centerline=draft_centerline,
            vehicle_classes=vehicle_classes,
        )
        conn.commit()

        should_enqueue = created
        if not created:
            existing = repo.get(conn, request_id)
            if existing is not None and existing.get("status") in _RETRYABLE_STATUSES:
                should_enqueue = True

        if should_enqueue:
            _enqueue_draft(request_id)

        return request_id
    finally:
        return_pg_connection(conn)


def _enqueue_draft(request_id: str) -> None:
    """Best-effort enqueue of ``draft_and_notify`` (Task 10).

    Lazily imported at call time: ``tasks.onboarding_tasks`` does not exist
    yet in this repo state, so a module-level import would break
    ``import service`` for every caller until Task 10 lands. Any failure
    here (``ImportError`` today; a transient broker error later) is logged,
    never raised -- the open request row is already durably written, so a
    failed enqueue just means drafting is retried out-of-band rather than
    the whole detection hook blowing up.
    """
    try:
        from tasks.onboarding_tasks import draft_and_notify
    except ImportError:
        logger.warning(
            "record_missing_geometry: draft_and_notify not available yet "
            "(Task 10 pending) -- skipping enqueue for request_id=%s",
            request_id,
        )
        return

    try:
        draft_and_notify.delay(request_id)
    except Exception:
        logger.exception(
            "record_missing_geometry: failed to enqueue draft_and_notify "
            "for request_id=%s",
            request_id,
        )
