"""onboarding/reprocess.py
--------------------------
``reprocess_after_bless`` -- the F3/F4 upgrade path for the Track Onboarding
Loop (Phase 1, Task 9). Called once ``onboarding/bless_service.bless_geometry``
(Task 8) has durably installed a human-corrected GT geojson: the sessions
that were WAITING on that track_key must be routed onto the new GT and
re-anchored, and the racing-line solve must re-run against the corrected
geometry.

Why a plain ``compute_racing_lines`` is not enough on its own: the blessed
GT is only consumed at BUILD time -- ``track_surface.builder.build_track_
surface`` calls ``resolve_canonical_via_pg`` + ``load_gt(canonical_id)``
during the pipeline's analyze stage (``pipeline/stages/s10d_surface.py``
``run_surface_build``), and THAT is what re-anchors the session's boundaries
and persists the sidecar with ``boundary_source`` (Task 1). Racing lines are
solved from the persisted sidecar (``track_surface.store.load_track_model``)
-- so racing lines must be recomputed only AFTER the affected sessions have
rebuilt, or they will simply re-solve against the stale (pre-bless) sidecar.

Three responsibilities, run in order, each best-effort (an exception in one
session/class must never abort the rest -- see the module docstring's
"Best-effort" note repeated on every helper below):

  F4  ``tracks.canonical_id`` mapping -- for every ``session_ref``, resolve
      its ``tracks.track_id`` (via the ``sessions`` table) and UPDATE
      ``tracks.canonical_id`` to point at the newly-blessed ``canonical_id``
      (idempotent -- a no-op UPDATE if already correct), so
      ``resolve_canonical_via_pg`` returns the right id the next time this
      track builds. This is NOT skipped just because ``track_key`` already
      equals ``canonical_id`` -- the mapping row is the thing that matters,
      not string equality between the two identifiers.

  F3  Build-reprocess -- per ``session_ref``, re-run the FULL ingest ->
      analyze -> finalize pipeline chain (verified real entrypoint:
      ``tasks.pipeline_tasks.build_pipeline_chain(job_id).apply_async()``,
      the same one ``web/routes/jobs.py``'s ``retry()`` endpoint dispatches
      for a from-scratch rerun of an existing upload). This is genuinely
      the only place ``build_track_surface``/``load_gt`` re-executes; there
      is no lighter "resurface this session" entrypoint in this codebase
      (verified -- ``run_surface_build`` is only ever called from inside
      the pipeline's analyze stage).

  Racing lines -- exactly ONE ``tasks.racing_line_tasks.compute_racing_
      lines`` enqueue per distinct ``(track_key, vehicle_class)`` pair
      (deduped -- never N per session), delayed via ``countdown`` so the
      (async, multi-minute) builds above get a head start. See
      ``_RACING_LINE_REPROCESS_DELAY_S`` for why this is a heuristic, not a
      guarantee, and what backstops it.

Connection pattern mirrors ``onboarding/service.py`` / ``tasks/racing_line_
tasks.py``: ``web.db_pg.get_maint_connection`` / ``return_pg_connection``,
standalone (no Flask ``g``) since this runs from a Celery task as easily as
a route. A caller-supplied ``conn`` (e.g. one already open in the caller's
transaction) is honored as-is and never closed here.
"""
from __future__ import annotations

import logging
import uuid

from pipeline_context import PipelineContext
from tasks.pipeline_tasks import build_pipeline_chain
from tasks.racing_line_tasks import compute_racing_lines
from web.db_pg import get_maint_connection, return_pg_connection

logger = logging.getLogger(__name__)

__all__ = ["reprocess_after_bless"]

# Head-start given to the racing-line recompute over the (async, unbounded --
# 900s soft_time_limit per session in the verified ops/reprocess_day13_*
# precedent) build-reprocess chains above. Unlike ``pipeline/orchestrator.
# py``'s ``_RACING_LINE_DEBOUNCE_S`` (30s -- tuned for a build that finishes
# synchronously within the SAME task before the debounce fires), a bless
# reprocess build can take minutes, so this window is a best-effort
# heuristic, not a guarantee -- see ``reprocess_after_bless`` docstring.
_RACING_LINE_REPROCESS_DELAY_S = 1800  # 30 minutes


def reprocess_after_bless(
    *,
    track_key: str,
    canonical_id: str,
    session_refs: list[str],
    vehicle_classes: list[str],
    conn=None,
) -> None:
    """Re-anchor the given sessions onto a newly-blessed GT and re-solve.

    Ordering guarantee actually provided: the canonical-id mapping (F4) is
    applied synchronously, in-process, before any build is enqueued, so by
    the time the FIRST build-reprocess task starts running,
    ``resolve_canonical_via_pg`` already returns ``canonical_id`` for every
    affected track. Build-reprocess (F3) is dispatched next, one Celery
    chain per ``session_ref`` -- these run independently and asynchronously,
    with no cross-session ordering promised or needed (each session's build
    only touches its own sidecar).

    What is NOT strictly guaranteed: that every build-reprocess chain has
    FINISHED before the racing-line recompute (below) runs. There is no
    chaining primitive available that spans an unknown number of independent,
    unknown-duration Celery chains without fragile chain-concatenation (celery
    ``chain()`` composes task *signatures*, not already-built sub-chains, and
    naively concatenating ``build_pipeline_chain`` instances risks the next
    session's ``pipeline_ingest.s(job_id)`` receiving the previous chain's
    return value as a spurious extra argument -- untested and unverifiable
    against a live broker here, so deliberately not attempted). Instead, the
    racing-line enqueue is delayed by ``_RACING_LINE_REPROCESS_DELAY_S`` --
    a best-effort head start -- and real correctness is backstopped at the
    worker/beat level by ``tasks.racing_line_tasks.compute_all_racing_lines``
    (the nightly beat task), which re-solves every track with surface data
    and is idempotent (skips a condition whose grip hash hasn't changed).
    If the delayed compute races ahead of a slow build, the next nightly
    beat run corrects it. This caveat is deliberate, not an oversight, and
    real end-to-end ordering is deferred to the deploy gate.

    Every enqueue/DB step below is independently wrapped: an exception in
    one session's canonical-id update, one session's build dispatch, or one
    class's racing-line enqueue is logged and does not prevent the rest
    from being attempted.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_maint_connection()

    try:
        _apply_canonical_mapping(conn, session_refs=session_refs, canonical_id=canonical_id)
        _dispatch_builds(conn, session_refs=session_refs)
        _enqueue_racing_lines(track_key=track_key, vehicle_classes=vehicle_classes)
    finally:
        if owns_conn:
            return_pg_connection(conn)


# ---------------------------------------------------------------------------
# F4 -- tracks.canonical_id mapping
# ---------------------------------------------------------------------------


def _resolve_track_id_for_session(conn, session_ref: str) -> str | None:
    """Bridge a session_ref to its ``tracks.track_id`` via the ``sessions``
    table (``sessions.session_id`` -> ``sessions.track_id`` -- the same
    column pair every session-scoped repo in this codebase keys on, e.g.
    ``web/repos/session_repo.py``, ``db/queries.py``). Returns ``None`` if
    the session is unknown or has no track_id recorded -- caller treats
    that as "nothing to map" rather than an error.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT track_id FROM sessions WHERE session_id = %(session_id)s",
            {"session_id": session_ref},
        )
        row = cur.fetchone()
    finally:
        cur.close()
    if row is None:
        return None
    val = row.get("track_id") if hasattr(row, "get") else row[0]
    return str(val) if val else None


def _set_canonical_id(conn, track_id: str, canonical_id: str) -> None:
    """Idempotent ``UPDATE tracks SET canonical_id = ...`` for one track_id.

    Same raw-cursor + explicit commit pattern as ``track_surface.gt_loader.
    resolve_canonical_via_pg`` (the reader half of this same bridge column,
    added in migration 060) and ``onboarding.bless_service._write_audit``.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE tracks SET canonical_id = %(canonical_id)s WHERE track_id = %(track_id)s",
            {"canonical_id": canonical_id, "track_id": track_id},
        )
    finally:
        cur.close()
    conn.commit()


def _apply_canonical_mapping(conn, *, session_refs: list[str], canonical_id: str) -> None:
    """F4: set ``tracks.canonical_id`` for every session's track.

    One resolve + UPDATE attempt per ``session_ref`` -- not deduped by
    track_id, since the UPDATE is idempotent (a second identical UPDATE for
    the same track_id is a no-op) and per-session accounting keeps the
    "canonical set once per session" test assertion simple and direct.
    """
    for session_ref in session_refs:
        try:
            track_id = _resolve_track_id_for_session(conn, session_ref)
            if not track_id:
                logger.info(
                    "reprocess_after_bless: no track_id for session_ref=%s -- "
                    "skipping canonical_id mapping for this session",
                    session_ref,
                )
                continue
            _set_canonical_id(conn, track_id, canonical_id)
        except Exception:
            logger.exception(
                "reprocess_after_bless: failed to set canonical_id "
                "(session_ref=%s, canonical_id=%s) -- continuing",
                session_ref, canonical_id,
            )


# ---------------------------------------------------------------------------
# F3 -- build-reprocess per session
# ---------------------------------------------------------------------------


def _get_redis():
    """Create a Redis client from the app config.

    Same 2-line helper as ``web/routes/jobs.py``/``tasks/pipeline_tasks.py``
    (duplicated rather than importing a private module attribute across
    package boundaries -- consistent with the existing duplication between
    those two modules).
    """
    import redis

    from web.config import Config

    return redis.Redis.from_url(Config.REDIS_URL)


def _load_ingestion_job(conn, job_id: str) -> dict | None:
    """Fetch ``(workspace_id, file_path)`` for an existing ``ingestion_jobs``
    row by ``job_id`` alone (no workspace filter -- this runs from an
    operator/admin-triggered maintenance connection, not a tenant-scoped web
    request, so there is no ``g.workspace_id`` to filter by; the workspace_id
    needed for ``PipelineContext.create`` is read directly off the row).
    """
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT workspace_id, file_path FROM ingestion_jobs WHERE job_id = %(job_id)s",
            {"job_id": job_id},
        )
        row = cur.fetchone()
    finally:
        cur.close()
    if row is None:
        return None
    if hasattr(row, "get"):
        return {"workspace_id": row.get("workspace_id"), "file_path": row.get("file_path")}
    return {"workspace_id": row[0], "file_path": row[1]}


def _copy_ingestion_job_row(conn, *, old_job_id: str, new_job_id: str) -> None:
    """INSERT a fresh ``ingestion_jobs`` row for ``new_job_id``, copying the
    original's ``workspace_id``/``file_path``/``file_size``/``sha256_partial``.

    Verbatim pattern lifted from ``web/routes/jobs.py``'s ``retry()``
    endpoint (the one other verified "rerun an existing session end-to-end"
    entrypoint in this codebase) -- ``_update_job_progress`` (called by
    ``pipeline_ingest``) UPDATEs an existing row rather than upserting one,
    so a row must exist for ``new_job_id`` before the chain is dispatched.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO ingestion_jobs "
            "  (job_id, workspace_id, file_path, file_size, sha256_partial, "
            "   status, stage_name, stage_index, stage_total, updated_at) "
            "SELECT %(new_id)s, workspace_id, file_path, file_size, "
            "  COALESCE(sha256_partial, ''), "
            "  'pending', 'onboarding_reprocess_queued', 0, 15, now() "
            "FROM ingestion_jobs WHERE job_id = %(old_id)s",
            {"new_id": new_job_id, "old_id": old_job_id},
        )
    finally:
        cur.close()
    conn.commit()


def _dispatch_build_reprocess(conn, session_ref: str) -> None:
    """The verified build/reprocess entrypoint for ONE session.

    Mirrors ``web/routes/jobs.py::retry(job_id)`` (a from-scratch rerun of
    an existing upload, dispatched the identical way the real upload path
    does): look up the original job's ``workspace_id``/``file_path``, mint a
    fresh ``job_id``, copy the ``ingestion_jobs`` row, seed a
    ``PipelineContext`` (+ copy any ``pipeline:meta:{job_id}`` redis blob),
    then dispatch ``tasks.pipeline_tasks.build_pipeline_chain(new_job_id).
    apply_async()`` -- the ingest -> analyze -> finalize chain that re-runs
    ``track_surface.builder.build_track_surface`` (and therefore
    ``load_gt(canonical_id)``) for this session, re-anchoring it onto the
    just-blessed GT and re-persisting its sidecar with ``boundary_source``.

    Raises on failure (missing job row, redis/dispatch error) -- the caller
    (``_dispatch_builds``) is what swallows + logs, one call per session_ref.
    """
    job = _load_ingestion_job(conn, session_ref)
    if job is None:
        raise RuntimeError(
            f"no ingestion_jobs row found for session_ref={session_ref!r} -- "
            "cannot build-reprocess (unknown session)"
        )

    new_job_id = uuid.uuid4().hex
    _copy_ingestion_job_row(conn, old_job_id=session_ref, new_job_id=new_job_id)

    redis_client = _get_redis()
    PipelineContext.create(
        redis_client=redis_client,
        job_id=new_job_id,
        workspace_id=str(job["workspace_id"]),
        session_id=new_job_id,
        file_path=job["file_path"],
    )
    try:
        original_meta = redis_client.get(f"pipeline:meta:{session_ref}")
        if original_meta:
            redis_client.set(f"pipeline:meta:{new_job_id}", original_meta, ex=7200)
    except Exception:
        logger.warning(
            "reprocess_after_bless: failed to copy pipeline:meta for "
            "session_ref=%s -> new_job_id=%s (build will use pipeline "
            "defaults)", session_ref, new_job_id,
        )

    build_pipeline_chain(new_job_id).apply_async()
    logger.info(
        "reprocess_after_bless: dispatched build-reprocess session_ref=%s "
        "-> new_job_id=%s", session_ref, new_job_id,
    )


def _dispatch_builds(conn, *, session_refs: list[str]) -> None:
    """F3: enqueue one build-reprocess per ``session_ref``, best-effort."""
    for session_ref in session_refs:
        try:
            _dispatch_build_reprocess(conn, session_ref)
        except Exception:
            logger.exception(
                "reprocess_after_bless: build-reprocess dispatch failed for "
                "session_ref=%s -- continuing with remaining sessions",
                session_ref,
            )


# ---------------------------------------------------------------------------
# Racing lines -- deduped enqueue
# ---------------------------------------------------------------------------


def _enqueue_racing_lines(*, track_key: str, vehicle_classes: list[str]) -> None:
    """Enqueue exactly one ``compute_racing_lines`` per distinct
    ``(track_key, vehicle_class)`` pair -- deduped so N sessions for the same
    track/class never enqueue more than one solve.
    """
    seen: set[str] = set()
    for vehicle_class in vehicle_classes:
        if vehicle_class in seen:
            continue
        seen.add(vehicle_class)
        try:
            compute_racing_lines.apply_async(
                (track_key, vehicle_class),
                countdown=_RACING_LINE_REPROCESS_DELAY_S,
            )
            logger.info(
                "reprocess_after_bless: enqueued compute_racing_lines "
                "(track_key=%s, vehicle_class=%s) in %ds",
                track_key, vehicle_class, _RACING_LINE_REPROCESS_DELAY_S,
            )
        except Exception:
            logger.exception(
                "reprocess_after_bless: compute_racing_lines enqueue failed "
                "(track_key=%s, vehicle_class=%s) -- continuing",
                track_key, vehicle_class,
            )
