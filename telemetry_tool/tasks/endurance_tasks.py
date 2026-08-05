"""Celery tasks for per-stint endurance processing."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from celery_app import celery as celery_app
from tasks.concurrency import _ACQUIRE_LOCK_LUA, _RELEASE_LOCK_LUA

logger = logging.getLogger(__name__)

# ── Per-task time limits (own `endurance` queue — routed in celery_app.py) ──
# Root cause of the original starvation bug: this task used to declare only
# soft_time_limit=3600 with no explicit hard time_limit. Celery then fell
# back to the WORKER's blanket --time-limit for the hard kill, and on the
# shared `pipeline` queue that was 2100s (35 min) — well under this task's
# own 60-minute soft limit, so the hard SIGKILL always fired first and the
# soft limit's graceful-failure path never got a chance to run. Both limits
# are now explicit here (hard > soft) and mirrored by the dedicated
# `celery-endurance` worker's --soft-time-limit/--time-limit flags in
# docker-compose.prod.yml / docker-compose.staging.yml.
ENDURANCE_SOFT_TIME_LIMIT_S = 3600  # 60 min — generous per-stint pipeline runs
ENDURANCE_HARD_TIME_LIMIT_S = 3900  # 65 min — same 300s cleanup-margin
                                     # convention as tasks.pipeline_tasks.HARD_LIMIT_MARGIN_S

# Lock TTL must outlive the hard limit (plus headroom for the failure-path
# publish to run) so a genuinely still-running job keeps its lock at least
# as long as Celery would let it run anyway.
_JOB_LOCK_TTL_S = ENDURANCE_HARD_TIME_LIMIT_S + 60

# ── customer-readiness fixes #2/#4/#6 (2c5f508 follow-up) ──────────────────
# 2c5f508 isolated endurance jobs onto their own Celery queue so a long
# analysis could never stall ordinary customers' uploads, but it also moved
# ALL endurance job state into Redis-only bookkeeping (runlock + status),
# completely invisible to every PG-backed safety net:
#   #2 the shared per-tier compute budget (web.compute_budget) only scans
#      ingestion_jobs/exports/analysis_runs, so it never counted endurance
#      jobs — the concurrency cap was a no-op for this queue.
#   #4 there is no endurance analogue of alerting_tasks._reconcile_stuck_jobs,
#      so a hard-killed job (SIGKILL from the task's own time_limit) is never
#      un-stuck: its `finally: _release_job_lock` cannot run under SIGKILL,
#      so the run-lock is held and the status is left non-terminal forever.
#   #6 with task_reject_on_worker_lost + acks_late, that SAME hard-killed
#      message gets requeued by the broker once visibility_timeout elapses.
#      `self.request.id` is unchanged across redeliveries of one message, so
#      the re-entrant run-lock re-grants immediately and the (still
#      non-terminal) status doesn't trip the existing terminal-skip either —
#      the job loops forever, pinning the sole --concurrency=1 worker.
#
# All three fixes below share ONE notion of job identity/state, entirely in
# Redis, keyed by job_id:
#   endurance:active:{workspace_id}  — SET of in-flight job_ids (fix #2's
#                                       countable signal for
#                                       web.compute_budget.count_active_compute_jobs)
#   endurance:dispatch:{job_id}      — {workspace_id, dispatched_at} written
#                                       once at submit/enqueue time — used to
#                                       recover workspace_id during the sweep
#                                       and as a generous TTL backstop; NOT
#                                       used to age the job anymore (see next).
#   endurance:started:{job_id}       — RUN-START timestamp, written the
#                                       instant the job acquires its run-lock
#                                       and actually starts executing (HIGH
#                                       fix, customer-readiness follow-up).
#                                       fix #4's reconciler ages jobs off THIS
#                                       marker, not dispatched_at — a job
#                                       queued behind another on the
#                                       single-concurrency worker has no
#                                       started marker yet and must NEVER be
#                                       force-failed for merely waiting.
#   endurance:attempts:{job_id}      — INCR'd on every delivery, INDEPENDENT
#                                       of the Celery/broker message id (fix
#                                       #6's redelivery bound)
# The pre-existing endurance:status:{job_id} terminal check (below) is what
# stops any of the three paths from double-handling the same job once
# another has already reached a terminal state — see
# tests/test_endurance_robustness.py::TestCrossFixComposition.
ENDURANCE_MAX_DELIVERY_ATTEMPTS = 3  # allow up to 3 real run attempts of the
                                     # SAME job_id; the 4th delivery is forced
                                     # to 'failed' instead of running again.
_ATTEMPTS_KEY_TTL_S = _JOB_LOCK_TTL_S  # outlives one full run attempt

# Mirrors tasks.pipeline_tasks.HARD_LIMIT_MARGIN_S (300s / 5min). By design
# this equals celery_app.py's broker_transport_options visibility_timeout
# (4200s) — see reconcile_stuck_endurance_jobs docstring for why that's safe.
_RECONCILE_MARGIN_S = 300
_RECONCILE_CEILING_S = ENDURANCE_HARD_TIME_LIMIT_S + _RECONCILE_MARGIN_S


def _active_set_key(workspace_id) -> str:
    return f"endurance:active:{workspace_id}"


def _dispatch_key(job_id: str) -> str:
    return f"endurance:dispatch:{job_id}"


def _started_key(job_id: str) -> str:
    return f"endurance:started:{job_id}"


def _attempts_key(job_id: str) -> str:
    return f"endurance:attempts:{job_id}"


def mark_endurance_dispatched(redis_client, job_id: str, workspace_id) -> None:
    """Record a NEW endurance submission: SADD into the per-workspace active
    set (the countable signal ``web.compute_budget.count_active_compute_jobs``
    reads) and stamp a dispatch timestamp the reconciler ages against.

    Called from ``web.routes.endurance_upload.process_stints`` BEFORE
    ``.delay()`` so the concurrency cap reflects this submission immediately,
    even before any worker has picked it up.
    """
    redis_client.sadd(_active_set_key(workspace_id), job_id)
    redis_client.set(
        _dispatch_key(job_id),
        json.dumps({"workspace_id": str(workspace_id), "dispatched_at": time.time()}),
        # Generous — the reconciler is the real cleanup path; this TTL is
        # just a backstop so a leaked key can't live forever.
        ex=_RECONCILE_CEILING_S + 3600,
    )


def mark_endurance_started(redis_client, job_id: str) -> None:
    """Record the RUN-START instant for ``job_id`` (HIGH fix, customer-
    readiness follow-up): the stuck-job reconciler below must age a job from
    when it actually STARTS RUNNING, not from when it was enqueued.

    On the single-concurrency endurance worker, a healthy job can legitimately
    sit queued behind another long-running job for well over the reconcile
    ceiling before it ever gets a worker slot. Aging off ``dispatched_at``
    (set at enqueue time, see ``mark_endurance_dispatched``) meant the sweep
    could force-fail a job just minutes into its REAL run, simply because the
    QUEUE wait pushed its total dispatched-age past the ceiling — publishing a
    customer-facing failure to a healthy running job, releasing its still-held
    run-lock (opening a duplicate-concurrent-run window), and clearing its
    active-set slot.

    Called from ``process_endurance_session`` immediately AFTER
    ``_acquire_job_lock`` succeeds — the exact instant a job stops being
    merely "dispatched" and starts being "running". A job with NO started
    marker is therefore still queued (or has already finished and had its
    bookkeeping cleared by ``_clear_endurance_active``) — either way, the
    reconciler must never force-fail it.

    TTL is generous — comfortably above the hard time limit — purely as a
    backstop so a leaked key can't live forever; the reconciler is the real
    cleanup path.
    """
    redis_client.set(
        _started_key(job_id), time.time(),
        ex=_RECONCILE_CEILING_S + 3600,
    )


def _clear_endurance_active(redis_client, job_id: str, workspace_id) -> None:
    """Remove a job from the countable active-job signal on any terminal
    transition (success, soft-timeout failure, redelivery-exhaustion failure,
    or a forced reconciler failure). Safe to call more than once — SREM of an
    absent member and DEL of an absent key are both no-ops.
    """
    try:
        redis_client.srem(_active_set_key(workspace_id), job_id)
        redis_client.delete(_dispatch_key(job_id))
        redis_client.delete(_started_key(job_id))
    except Exception:
        logger.debug("Endurance active-set cleanup skipped for %s", job_id, exc_info=True)


def _force_release_job_lock(redis_client, job_id: str) -> None:
    """Unconditionally clear the run-lock, bypassing the owner-match check
    ``_release_job_lock`` uses for the normal compare-and-delete release.

    Only used by paths that have INDEPENDENTLY proven the original holder can
    no longer be running: the stuck-job reconciler (age past the hard-limit
    ceiling) and the redelivery-exhaustion guard (this exact job_id has
    already been redelivered past ``ENDURANCE_MAX_DELIVERY_ATTEMPTS``). A
    normal release always prefers the compare-and-delete path so a still
    legitimately-running attempt is never unlocked out from under itself.
    """
    redis_client.delete(f"endurance:runlock:{job_id}")


def reconcile_stuck_endurance_jobs(redis_client) -> list[dict]:
    """Beat sweep (fix #4, HIGH-fix follow-up): force-fail any endurance job
    that has actually STARTED RUNNING and stayed non-terminal past the
    hard-limit ceiling, releasing its stale run-lock and active-set
    membership.

    Mirrors ``tasks.alerting_tasks._reconcile_stuck_jobs``'s ingestion_jobs
    sweep, but endurance job state lives entirely in Redis (module docstring
    above). A HARD Celery time_limit SIGKILLs the worker child — no Python
    ``finally`` runs, so nothing marks the job failed or frees its run-lock
    without this sweep. Uses SCAN (not KEYS) so it never blocks Redis even
    with many in-flight jobs.

    HIGH-fix (customer-readiness merge-blocker): this sweep used to age jobs
    off ``dispatched_at`` (enqueue time, ``mark_endurance_dispatched``). On
    the single-concurrency endurance worker, a healthy job can legitimately
    sit QUEUED behind another long-running job for well over the reconcile
    ceiling before it ever starts — ageing off enqueue time force-failed such
    a job just minutes into its real run. The predicate now keys off
    ``endurance:started:{job_id}`` (``mark_endurance_started``, written the
    instant the job actually acquires its run-lock and starts executing):
    a job with NO started marker is either still queued or already finished
    and cleaned up — either way it is NEVER force-failed here, no matter how
    long its dispatch record has existed.

    Deliberately does NOT rely on the attempts-based redelivery bound (fix
    #6) to converge stuck jobs: the broker's own visibility_timeout is 4200s
    (celery_app.py), so a genuinely still-running job's message isn't even
    eligible for redelivery until then. This sweep is the ONLY path that
    reclaims a stuck job/lock before that; the attempts bound only guards
    against repeated redelivery once it starts happening — see
    tests/test_endurance_robustness.py::TestCrossFixComposition for how the
    two compose without double-handling the same job.
    """
    reconciled: list[dict] = []
    now = time.time()

    for raw_key in redis_client.scan_iter(match="endurance:dispatch:*", count=200):
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        job_id = key[len("endurance:dispatch:"):]

        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            dispatch = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        workspace_id = dispatch.get("workspace_id", "1")

        # HIGH fix: age off RUN-START, not enqueue/dispatch time. A job with
        # no started marker is still queued (or already terminal and had its
        # bookkeeping cleared) — never force-fail it here regardless of how
        # long ago it was dispatched.
        started_raw = redis_client.get(_started_key(job_id))
        if not started_raw:
            continue
        try:
            started_at = float(started_raw)
        except (TypeError, ValueError):
            continue
        if (now - started_at) <= _RECONCILE_CEILING_S:
            continue

        status_raw = redis_client.get(f"endurance:status:{job_id}")
        status = None
        if status_raw:
            try:
                status = json.loads(status_raw).get("status")
            except (json.JSONDecodeError, TypeError, AttributeError):
                status = None

        if status in ("completed", "failed"):
            # Already terminal via another path — just clear leftover
            # bookkeeping so this job stops being re-examined every sweep.
            _clear_endurance_active(redis_client, job_id, workspace_id)
            continue

        running_s = int(now - started_at)
        logger.error(
            "Reconciling stuck endurance job %s: non-terminal (%s) after %ds "
            "running (ceiling %ds) — worker was likely hard-killed mid-run",
            job_id, status, running_s, _RECONCILE_CEILING_S,
        )
        _publish(redis_client, job_id, {
            "status": "failed",
            "job_id": job_id,
            "error": (
                "This endurance analysis stalled and was stopped automatically. "
                "Try splitting the session into fewer stints, or contact support "
                "if this keeps happening."
            ),
            "error_class": "reconciled_stuck",
        })
        _force_release_job_lock(redis_client, job_id)
        _clear_endurance_active(redis_client, job_id, workspace_id)
        reconciled.append({"job_id": job_id, "running_seconds": running_s})

    return reconciled


@celery_app.task(name="tasks.endurance_tasks.reconcile_stuck_endurance_jobs_task")
def reconcile_stuck_endurance_jobs_task() -> dict[str, Any]:
    """Celery entry point for the beat schedule — see
    :func:`reconcile_stuck_endurance_jobs` for the actual sweep logic.

    Routed to the `default` queue (celery_app.py beat_schedule), NOT
    `endurance` — if the sole --concurrency=1 endurance worker is the one
    stuck, queuing this sweep behind it would mean it never runs.
    """
    import redis as _redis
    from web.config import Config

    _r = _redis.Redis.from_url(Config.REDIS_URL)
    reconciled = reconcile_stuck_endurance_jobs(_r)
    return {"reconciled_count": len(reconciled), "reconciled": reconciled}


def _acquire_job_lock(redis_client, job_id: str, owner: str, ttl: int = _JOB_LOCK_TTL_S) -> bool:
    """Re-entrant per-job lock (same atomic Lua pattern as tasks.concurrency's
    workspace lock, keyed by job_id instead of workspace_id).

    Prevents a double /process submit or a broker redelivery of the same
    endurance job from running two overlapping analyses concurrently.
    """
    key = f"endurance:runlock:{job_id}"
    result = redis_client.eval(_ACQUIRE_LOCK_LUA, 1, key, owner, str(ttl))  # noqa: S307
    return bool(result)


def _release_job_lock(redis_client, job_id: str, owner: str) -> None:
    """Atomically release the per-job lock only if `owner` still holds it."""
    key = f"endurance:runlock:{job_id}"
    redis_client.eval(_RELEASE_LOCK_LUA, 1, key, owner)  # noqa: S307


@celery_app.task(
    name="tasks.endurance_tasks.process_endurance_session",
    bind=True,
    max_retries=0,
    soft_time_limit=ENDURANCE_SOFT_TIME_LIMIT_S,
    time_limit=ENDURANCE_HARD_TIME_LIMIT_S,
)
def process_endurance_session(
    self,
    job_id: str,
    meta: dict[str, Any],
    stint_configs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Process each stint through the pipeline, then aggregate.

    Routed to the dedicated `endurance` queue (see celery_app.py task_routes)
    so a long-running endurance analysis can never pin the shared `pipeline`
    queue and stall ordinary customers' uploads.
    """
    import redis as _redis
    from web.config import Config

    _r = _redis.Redis.from_url(Config.REDIS_URL)
    lock_owner = self.request.id or job_id
    workspace_id = meta.get("workspace_id", "1")

    # ── Fix #6: bound broker redeliveries by JOB_ID, independent of the
    # Celery message/task id (which stays the SAME across redeliveries of one
    # message — see module docstring). Counted at the very top, before lock
    # acquisition, so every delivery attempt is counted regardless of lock
    # state or which worker picks it up.
    attempts = _r.incr(_attempts_key(job_id))
    if attempts == 1:
        _r.expire(_attempts_key(job_id), _ATTEMPTS_KEY_TTL_S)
    if attempts > ENDURANCE_MAX_DELIVERY_ATTEMPTS:
        # LOW fix (#G): consult the existing terminal status FIRST. Without
        # this, a job already terminal via another path (e.g. the
        # reconciler's more specific "reconciled_stuck") could be relabeled
        # with the less-informative "redelivery_exhausted" just because a
        # stale message for it happens to get redelivered one more time
        # AFTER it was already resolved — pure noise for support/on-call.
        _existing_raw = _r.get(f"endurance:status:{job_id}")
        _existing_status = None
        if _existing_raw:
            try:
                _existing_status = json.loads(_existing_raw).get("status")
            except (json.JSONDecodeError, TypeError, AttributeError):
                _existing_status = None
        if _existing_status in ("completed", "failed"):
            logger.info(
                "Endurance job %s already %s — redelivery-exhausted gate "
                "(attempts=%d) skipping relabel",
                job_id, _existing_status, attempts,
            )
            _force_release_job_lock(_r, job_id)
            _clear_endurance_active(_r, job_id, workspace_id)
            return {
                "job_id": job_id, "skipped": True,
                "reason": f"already_{_existing_status}", "attempts": attempts,
            }

        logger.error(
            "Endurance job %s redelivered %d times (max %d) — forcing failed "
            "instead of re-running (breaks the SIGKILL/requeue loop)",
            job_id, attempts, ENDURANCE_MAX_DELIVERY_ATTEMPTS,
        )
        _publish(_r, job_id, {
            "status": "failed",
            "job_id": job_id,
            "error": (
                "This endurance analysis was interrupted too many times and was "
                "stopped automatically. Please contact support."
            ),
            "error_class": "redelivery_exhausted",
        })
        # This delivery may not even hold the run-lock (it might belong to a
        # dead prior attempt) — force-clear unconditionally, see
        # _force_release_job_lock docstring.
        _force_release_job_lock(_r, job_id)
        _clear_endurance_active(_r, job_id, workspace_id)
        # Return (do not raise) so acks_late acks THIS delivery — the goal is
        # to stop the redelivery loop, not trigger yet another one.
        return {
            "job_id": job_id, "failed": True,
            "error_class": "redelivery_exhausted", "attempts": attempts,
        }

    # Idempotency guard — see _acquire_job_lock docstring.
    if not _acquire_job_lock(_r, job_id, lock_owner):
        logger.warning(
            "Endurance job %s already running (lock held) — skipping duplicate dispatch",
            job_id,
        )
        return {"job_id": job_id, "skipped": True, "reason": "duplicate_run"}

    # HIGH fix: this is the exact instant the job stops being merely
    # "dispatched" (queued) and starts actually running — see
    # mark_endurance_started docstring for why the stuck-job reconciler must
    # age off THIS marker instead of enqueue time.
    mark_endurance_started(_r, job_id)

    try:
        # Also skip outright if a prior attempt already reached a terminal
        # state — handles the rare case where a hard-killed task's message
        # was redelivered after that attempt's lock had already expired (or
        # after the fix #4 reconciler force-failed it and freed the lock).
        existing_raw = _r.get(f"endurance:status:{job_id}")
        existing_status = None
        if existing_raw:
            try:
                existing_status = json.loads(existing_raw).get("status")
            except (json.JSONDecodeError, TypeError, AttributeError):
                existing_status = None
        if existing_status in ("completed", "failed"):
            logger.info(
                "Endurance job %s already %s — skipping redelivered run",
                job_id, existing_status,
            )
            return {"job_id": job_id, "skipped": True, "reason": f"already_{existing_status}"}

        result = _run_endurance_session(_r, job_id, meta, stint_configs)
        return result
    except SoftTimeLimitExceeded:
        logger.error(
            "Endurance job %s exceeded its %ss soft time limit — marking failed",
            job_id, ENDURANCE_SOFT_TIME_LIMIT_S,
        )
        _publish(_r, job_id, {
            "status": "failed",
            "job_id": job_id,
            "error": (
                "This endurance analysis took too long to process and was stopped. "
                "Try splitting the session into fewer stints, or contact support "
                "if this keeps happening."
            ),
            "error_class": "timeout",
        })
        # Deliberately swallowed: returning normally (not re-raising) lets
        # Celery ack the message as done, so acks_late / task_reject_on_worker_lost
        # never get a chance to redeliver a job we've already failed cleanly.
        return {"job_id": job_id, "failed": True, "error_class": "timeout"}
    finally:
        # MEDIUM fix (#B): _clear_endurance_active must run on EVERY exit path
        # from this try block, not just the ones that explicitly called it
        # before (success, terminal-skip, soft-timeout). A plain, non-
        # SoftTimeLimitExceeded exception (e.g. a bug in compute_*_report, or
        # a ZeroDivisionError when total_stints==0) used to propagate past
        # this function WITHOUT clearing the active-set slot — acks_late acks
        # the message (no redelivery), so the slot leaked until the
        # reconciler self-healed ~_RECONCILE_CEILING_S later, eating into the
        # workspace's shared compute-budget pool the whole time. Both calls
        # are idempotent (safe on an absent member/key), so consolidating to
        # one call here — including on the already-handled success/timeout/
        # skip paths above — is harmless.
        _clear_endurance_active(_r, job_id, workspace_id)
        _release_job_lock(_r, job_id, lock_owner)


def _run_endurance_session(
    _r,
    job_id: str,
    meta: dict[str, Any],
    stint_configs: list[dict[str, Any]],
) -> dict[str, Any]:
    """The actual per-stint processing + aggregation body.

    Split out from the task entry point so the idempotency lock and the
    SoftTimeLimitExceeded handler wrap the whole thing from the outside, and
    so tests can exercise this logic without going through Celery's task
    binding machinery.
    """
    file_path = meta["file_path"]
    session_meta = meta.get("session_meta", {})
    total_stints = len(stint_configs)

    _publish(_r, job_id, {"status": "processing", "total_stints": total_stints})

    stint_results = []
    # Track per-stint statuses so frontend can always see the full picture
    stint_statuses: list[dict] = [
        {"stint_number": sc["stint_number"], "driver_name": sc.get("driver_name", ""), "status": "queued"}
        for sc in stint_configs
    ]

    def _publish_full(phase: str, extra: dict | None = None):
        """Publish full status including all stint statuses."""
        payload = {
            "status": phase,
            "total_stints": total_stints,
            "stints": stint_statuses,
            "progress_pct": round(sum(1 for s in stint_statuses if s["status"] == "complete") / total_stints * 100),
            **(extra or {}),
        }
        _publish(_r, job_id, payload)

    for i, stint_cfg in enumerate(stint_configs):
        stint_num = stint_cfg["stint_number"]
        start_lap = stint_cfg["start_lap"]
        end_lap = stint_cfg["end_lap"]
        driver_name = stint_cfg.get("driver_name", f"Driver {stint_num}")
        condition = stint_cfg.get("condition", "dry")
        valid_laps = stint_cfg.get("valid_laps")
        pit_lap_number = stint_cfg.get("pit_lap_number")
        pit_lap_time_s = stint_cfg.get("pit_lap_time_s")
        logger.info("Stint %d: start=%d end=%d valid_laps=%s driver=%s",
                     stint_num, start_lap, end_lap,
                     f"{len(valid_laps)} laps" if valid_laps else "None (using range)",
                     driver_name)

        # Mark this stint as processing
        stint_statuses[i]["status"] = "processing"
        _publish_full("processing_stint")

        try:
            result = _process_single_stint(
                file_path=file_path,
                start_lap=start_lap,
                end_lap=end_lap,
                stint_number=stint_num,
                driver_name=driver_name,
                condition=condition,
                valid_laps=valid_laps,
                session_meta=session_meta,
                workspace_id=meta.get("workspace_id", "1"),
                job_id=job_id,
            )
            # Add pit info from config (not from pipeline)
            result["pit_lap_number"] = pit_lap_number
            result["pit_lap_time_s"] = pit_lap_time_s
            result["pit_duration_s"] = stint_cfg.get("pit_duration_s")
            stint_results.append(result)

            # Mark complete with stats
            stint_statuses[i] = {
                **stint_statuses[i],
                "status": "complete",
                "best_lap_s": result.get("best_lap_s"),
                "lap_count": result.get("lap_count"),
            }
            _publish_full("stint_complete")
        except SoftTimeLimitExceeded:
            # Do NOT swallow this as a per-stint error — that used to let the
            # loop continue to the next stint instead of stopping, so a
            # timed-out job kept burning worker time until the HARD limit
            # SIGKILLed the whole process with no job ever marked failed.
            # Re-raise so the task-level handler in process_endurance_session
            # marks the whole job failed and stops cleanly.
            raise
        except Exception as exc:
            logger.exception("Failed to process stint %d", stint_num)
            stint_statuses[i] = {**stint_statuses[i], "status": "error", "error": str(exc)[:200]}
            _publish_full("stint_error")
            stint_results.append({
                "stint_number": stint_num,
                "driver_name": driver_name,
                "error": str(exc)[:200],
                "lap_count": 0,
            })

    # Aggregate
    _publish_full("processing_drivers")

    from endurance_scoring import compute_driver_report, compute_team_report

    driver_stints: dict[str, list] = {}
    for r in stint_results:
        d = r.get("driver_name", "Unknown")
        if d not in driver_stints:
            driver_stints[d] = []
        driver_stints[d].append(r)

    driver_reports = {}
    for driver, stints in driver_stints.items():
        driver_reports[driver] = compute_driver_report(driver, stints)
        _publish_full("driver_complete", {"driver_name": driver})

    _publish_full("processing_team")

    total_laps = sum(r.get("lap_count", 0) for r in stint_results if not r.get("error"))
    total_time = sum(r.get("total_time_s", 0) for r in stint_results if not r.get("error"))
    team_report = compute_team_report(
        driver_reports, total_laps, total_stints, total_time,
        stint_results=stint_results,
        pit_threshold_s=meta.get("pit_threshold_s", 30),
    )

    full_report = {
        "team": team_report,
        "drivers": driver_reports,
        "stint_results": stint_results,
    }

    _r.set(f"endurance:report:{job_id}", json.dumps(full_report), ex=14400)

    # ── Persist master endurance session to DB ──────────────────
    # Creates a single session entry visible in the sessions list
    master_session_id = None
    try:
        master_session_id = _persist_master_session(
            job_id=job_id,
            meta=meta,
            team_report=team_report,
            driver_reports=driver_reports,
            stint_results=stint_results,
            total_laps=total_laps,
            total_time=total_time,
            workspace_id=meta.get("workspace_id", "1"),
        )
        logger.info("Persisted master endurance session: %s", master_session_id)
    except Exception:
        logger.exception("Failed to persist master endurance session")

    # ── Cleanup temp upload file ──────────────────────────────
    try:
        import shutil
        upload_dir = Path(file_path).parent
        if upload_dir.name.startswith("endurance_"):
            shutil.rmtree(upload_dir, ignore_errors=True)
            logger.info("Cleaned up endurance upload: %s", upload_dir)
    except Exception:
        pass

    _publish(_r, job_id, {
        "status": "completed",
        "job_id": job_id,
        "session_id": master_session_id,
    })
    return {"job_id": job_id, "stints_processed": len(stint_results), "session_id": master_session_id}


def _persist_stint_session(
    summary: dict[str, Any],
    driver_name: str,
    workspace_id: str,
    stint_number: int,
    job_id: str,
) -> str | None:
    """Persist a stint's pipeline results to PG using the same path as normal uploads.

    Mirrors ``pipeline_tasks._persist_session_data`` — connection-scoped SET,
    independent commits per step, graceful degradation on non-critical failures.
    Falls back to s15_persist for SQLite mode.
    """
    if os.environ.get("USE_PG", "0") != "1":
        # SQLite mode: delegate to s15_persist
        from pipeline.stages.s15_persist import run_persist_to_db
        meta = summary.get("session_meta") or {}
        return run_persist_to_db(
            summary, meta,
            summary.get("track_id", ""),
            score_result=summary.get("score_result"),
            driving_style_result=summary.get("driving_style_result"),
            driver_tag=driver_name,
            force_persist=True,
        )

    from web.db_pg import get_pg_connection
    from web.models import (
        insert_corner_metrics,
        insert_gps_traces,
        insert_laps,
        insert_reference_line,
        insert_score_details,
        upsert_driver,
        upsert_session,
        upsert_track,
    )

    conn = get_pg_connection()
    try:
        # Connection-scoped SET survives COMMIT (same as _persist_session_data)
        conn.execute(
            "SET app.current_workspace_id = %(ws)s",
            {"ws": str(workspace_id)},
        )

        # 1. Upsert driver
        driver_id = upsert_driver(conn, driver_name)
        conn.commit()

        # 2. Ensure track exists (FK constraint)
        meta = summary.get("session_meta") or {}
        user_track_name = meta.get("track_name") or meta.get("user_track_name")
        track_match = summary.get("track_match")

        if track_match and isinstance(track_match, dict):
            try:
                upsert_track(conn, track_match)
                conn.commit()
            except Exception:
                conn.rollback()

        # Use user-provided track name when pipeline detection falls back to unknown
        track_id = summary.get("track_id", "unknown_track")
        if user_track_name and track_id == "unknown_track":
            import hashlib
            track_id = hashlib.md5(user_track_name.encode()).hexdigest()[:16]
            summary["track_id"] = track_id

        display_name = user_track_name or (
            track_match.get("track_name") if track_match else track_id
        )
        try:
            conn.execute(
                "INSERT INTO tracks (track_id, track_name, lap_length_m) "
                "VALUES (%(track_id)s, %(track_name)s, %(lap_length_m)s) "
                "ON CONFLICT (track_id) DO NOTHING",
                {"track_id": track_id, "track_name": display_name, "lap_length_m": 0.0},
            )
            conn.commit()
        except Exception:
            conn.rollback()

        # Set kart from session meta (if provided in endurance upload form)
        kart_name = meta.get("kart_name")
        if kart_name and kart_name.strip():
            try:
                from web.models import upsert_kart_by_name
                kart_id = upsert_kart_by_name(conn, kart_name.strip())
                conn.commit()
                meta["kart_id"] = kart_id
            except Exception:
                conn.rollback()

        # 3. Upsert session
        session_id = upsert_session(conn, summary, driver_id)
        conn.commit()
        logger.info("Stint %d: persisted session %s (driver_id=%d)", stint_number, session_id, driver_id)

        # 4. Insert laps
        try:
            n_laps = insert_laps(conn, session_id, summary)
            conn.commit()
            logger.info("Stint %d: inserted %s laps", stint_number, n_laps)
        except Exception:
            logger.warning("Stint %d: laps insert failed", stint_number, exc_info=True)
            conn.rollback()

        # 5. Insert GPS traces
        try:
            n_gps = insert_gps_traces(conn, session_id, summary)
            conn.commit()
            logger.info("Stint %d: inserted %s GPS rows", stint_number, n_gps)
        except Exception:
            logger.warning("Stint %d: GPS insert failed", stint_number, exc_info=True)
            conn.rollback()

        # 6. Insert corner metrics
        try:
            if summary.get("corners"):
                insert_corner_metrics(conn, session_id, summary)
                conn.commit()
        except Exception:
            conn.rollback()

        # 6b. Insert driving events (Phase 2 of driving-pattern-recognition,
        # Task 10). Logged with exc_info=True, unlike the bare except just
        # above (Task 10 brief calls that pattern out by name as the one
        # NOT to repeat here).
        try:
            driving_events = summary.get("driving_events")
            if driving_events:
                from web.repos.events_repo import insert_driving_events
                n = insert_driving_events(conn, session_id, driving_events)
                conn.commit()
                logger.info(
                    "Stint %d: inserted %d driving events", stint_number, n,
                )
        except Exception as exc:
            logger.warning(
                "Stint %d: driving events insert failed: %s", stint_number, exc, exc_info=True,
            )
            conn.rollback()

        # 7. Insert score details
        try:
            if summary.get("score_result"):
                insert_score_details(conn, session_id, summary)
                conn.commit()
        except Exception:
            conn.rollback()

        # 8. Insert reference line
        try:
            if summary.get("reference_line") is not None:
                insert_reference_line(conn, session_id, summary)
                conn.commit()
        except Exception:
            conn.rollback()

        return session_id

    except Exception:
        logger.exception("Stint %d PG persist failed (job %s)", stint_number, job_id)
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _process_single_stint(
    file_path: str,
    start_lap: int,
    end_lap: int,
    stint_number: int,
    driver_name: str,
    condition: str,
    session_meta: dict,
    workspace_id: str,
    job_id: str,
    valid_laps: list[int] | None = None,
) -> dict[str, Any]:
    """Run the pipeline on a single stint's rows.

    Reads only rows belonging to laps [start_lap, end_lap],
    writes a temp CSV, runs pipeline on it.
    """
    csv_path = Path(file_path)

    header_lines: list[str] = []
    stint_lines: list[str] = []
    lap_col_idx: int | None = None

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                header_lines.append(line)
                continue
            lower = stripped.lower()
            if "lap" in lower and ("time" in lower or "speed" in lower):
                header_lines.append(line)
                parts = [c.strip().lower() for c in stripped.split(",")]
                for i, col in enumerate(parts):
                    if col in ("lap #", "lap", "lap number"):
                        lap_col_idx = i
                        break
                break
            header_lines.append(line)

        if lap_col_idx is None:
            raise ValueError("Cannot find Lap # column in CSV header")

        _valid_set = set(valid_laps) if valid_laps else set()
        logger.info("Row filter: valid_set=%s (len=%d), range=%d-%d",
                     _valid_set if len(_valid_set) < 20 else f"{len(_valid_set)} laps",
                     len(_valid_set), start_lap, end_lap)

        for line in f:
            parts = line.split(",")
            if len(parts) <= lap_col_idx:
                continue
            try:
                lap_num = int(float(parts[lap_col_idx].strip()))
            except (ValueError, TypeError):
                continue
            # Use explicit valid_laps list if provided, else fall back to range
            if _valid_set:
                if lap_num not in _valid_set:
                    continue
            elif not (start_lap <= lap_num <= end_lap):
                continue
            stint_lines.append(line)

    if not stint_lines:
        return {
            "stint_number": stint_number,
            "driver_name": driver_name,
            "lap_count": 0,
            "best_lap_s": None,
            "mean_lap_s": None,
            "total_time_s": 0,
            "scores": {"pace": 0, "consistency": 0, "robustness": 0},
        }

    logger.info(
        "Stint %d (%s): %d rows from laps %d-%d",
        stint_number, driver_name, len(stint_lines), start_lap, end_lap,
    )

    # Write stint CSV
    fd, stint_csv_path = tempfile.mkstemp(
        suffix=".csv", prefix=f"endurance_stint{stint_number}_",
    )
    os.close(fd)
    with open(stint_csv_path, "w", encoding="utf-8") as out:
        out.writelines(header_lines)
        out.writelines(stint_lines)

    try:
        from pipeline.orchestrator import run_full_analysis

        summary = run_full_analysis(
            csv_path=stint_csv_path,
            session_meta={
                **session_meta,
                "driver_name": driver_name,
                "session_type": "endurance_stint",
                "track_state": condition,
            },
            enable_report=False,
            # Pin the workspace so the orchestrator's RLS connections work under
            # the telemetry_app cutover and per-stint gamification is attributed
            # to the real workspace (was defaulting to workspace 1).
            # _persist_stint_session does no gamification, so the orchestrator
            # remains the source here (skip_gamification stays False).
            workspace_id=int(workspace_id) if str(workspace_id).isdigit() else None,
        )

        score = summary.get("score_result") or {}
        subs = score.get("sub_scores", {})
        lap_metrics = summary.get("lap_metrics") or []
        valid_times = [
            lm["lap_time_s"] for lm in lap_metrics
            if lm.get("lap_time_s") and lm["lap_time_s"] > 0
        ]

        # Track-evolution-aware pace: if lap times show a clear improvement
        # trend, compare each lap against the running PB instead of the
        # final PB.  Use whichever score is higher (rewards the driver).
        rpb_details = {}
        try:
            from endurance_scoring import running_pb_pace
            rpb_score, rpb_details = running_pb_pace(valid_times, condition=condition)
            if rpb_score is not None:
                scorer_pace = subs.get("pace", {}).get("score", 0)
                if rpb_score > scorer_pace:
                    logger.info(
                        "Stint %d: track evolution detected (slope=%.3f s/lap, R²=%.2f) — "
                        "running-PB pace %.1f > scorer pace %.1f",
                        stint_number, rpb_details.get("slope_s_per_lap", 0),
                        rpb_details.get("r_squared", 0), rpb_score, scorer_pace,
                    )
                    subs.setdefault("pace", {})["score"] = rpb_score
        except Exception:
            pass  # non-fatal — fall back to standard pace

        # Persist stint session to DB (same path as normal uploads)
        stint_session_id = summary.get("db_session_id")
        if not stint_session_id:
            try:
                stint_session_id = _persist_stint_session(
                    summary, driver_name, workspace_id, stint_number, job_id,
                )
                summary["db_session_id"] = stint_session_id
                if stint_session_id:
                    logger.info("Persisted stint %d session: %s", stint_number, stint_session_id)
            except Exception as persist_err:
                logger.warning("Stint %d persist failed (non-fatal): %s", stint_number, persist_err)

        # Traffic time loss: running-PB + degradation cancellation
        from endurance_scoring import compute_traffic_losses
        traffic_losses, traffic_total_s, traffic_count, track_degradation = compute_traffic_losses(valid_times)

        return {
            "stint_number": stint_number,
            "driver_name": driver_name,
            "condition": condition,
            "start_lap": start_lap,
            "end_lap": end_lap,
            "lap_count": len(valid_times),
            "best_lap_s": round(min(valid_times), 3) if valid_times else None,
            "mean_lap_s": round(sum(valid_times) / len(valid_times), 3) if valid_times else None,
            "total_time_s": round(sum(valid_times), 3) if valid_times else 0,
            "traffic_losses": traffic_losses,
            "traffic_total_s": round(traffic_total_s, 3),
            "traffic_count": len(traffic_losses),
            "scores": {
                "pace": round(subs.get("pace", {}).get("score", 0), 1),
                "consistency": round(subs.get("consistency", {}).get("score", 0), 1),
                "robustness": round(subs.get("robustness", {}).get("score", 0), 1),
            },
            "track_evolution": rpb_details if rpb_details.get("trend") else None,
            "track_degradation": track_degradation,
            "session_id": summary.get("db_session_id"),
        }
    finally:
        try:
            os.unlink(stint_csv_path)
        except OSError:
            pass


def _persist_master_session(
    job_id: str,
    meta: dict,
    team_report: dict,
    driver_reports: dict,
    stint_results: list[dict],
    total_laps: int,
    total_time: float,
    workspace_id: str,
) -> str | None:
    """Create a master session entry in the DB for the endurance race.

    This makes the endurance report visible in the sessions list.
    """
    import uuid
    from web.db import get_db_connection

    conn = get_db_connection()
    # Set RLS workspace context
    conn.execute("SET LOCAL app.current_workspace_id = :wid", {"wid": str(workspace_id)})
    session_id = uuid.uuid4().hex
    session_meta = meta.get("session_meta", {})
    drivers = team_report.get("drivers", [])
    driver_label = " + ".join(drivers) if drivers else "Endurance"

    # Find overall best lap across all stints
    best_times = [r["best_lap_s"] for r in stint_results if r.get("best_lap_s")]
    best_lap = min(best_times) if best_times else None
    mean_times = [r["mean_lap_s"] for r in stint_results if r.get("mean_lap_s")]
    mean_lap = sum(t * r.get("lap_count", 1) for t, r in zip(mean_times, stint_results) if r.get("mean_lap_s")) / total_laps if total_laps > 0 else None

    # Team score
    scores = team_report.get("scores", {})
    total_score = sum(scores.values())
    grade = "A+" if total_score >= 90 else "A" if total_score >= 80 else "B" if total_score >= 65 else "C" if total_score >= 50 else "D" if total_score >= 35 else "F"

    # Find or create driver for the team label
    driver_row = conn.execute(
        "SELECT driver_id FROM drivers WHERE driver_name = :dn",
        {"dn": driver_label},
    ).fetchone()
    if driver_row:
        driver_id = driver_row["driver_id"]
    else:
        conn.execute(
            "INSERT INTO drivers (driver_name) VALUES (:dn)",
            {"dn": driver_label},
        )
        driver_row = conn.execute(
            "SELECT driver_id FROM drivers WHERE driver_name = :dn",
            {"dn": driver_label},
        ).fetchone()
        driver_id = driver_row["driver_id"]

    # Find or create track
    track_name = session_meta.get("track_name", "Unknown Track")
    track_row = conn.execute(
        "SELECT track_id FROM tracks WHERE track_name = :tn",
        {"tn": track_name},
    ).fetchone()
    if track_row:
        track_id = track_row["track_id"]
    else:
        import hashlib
        track_id = hashlib.md5(track_name.encode()).hexdigest()[:16]
        conn.execute(
            "INSERT INTO tracks (track_id, track_name) VALUES (:tid, :tn)",
            {"tid": track_id, "tn": track_name},
        )

    conn.execute(
        "INSERT INTO sessions "
        "(session_id, display_name, driver_id, track_id, session_type, track_state, "
        " session_date, best_lap_time_s, mean_lap_time_s, n_laps, total_score, grade, "
        " csv_filename, analysis_json) "
        "VALUES (:sid, :dn, :did, :tid, :st, :ts, :sd, :blt, :mlt, :tl, :tscore, :grade, :fn, :aj)",
        {
            "sid": session_id,
            "dn": driver_label,
            "did": driver_id,
            "tid": track_id,
            "st": "endurance",
            "ts": session_meta.get("track_state", "dry"),
            "sd": session_meta.get("session_date") or datetime.now().strftime("%Y-%m-%d"),
            "blt": best_lap,
            "mlt": mean_lap,
            "tl": total_laps,
            "tscore": round(total_score, 1),
            "grade": grade,
            "fn": meta.get("file_name", "endurance.csv"),
            "aj": json.dumps({
                "endurance_job_id": job_id,
                "endurance_report": {
                    "team": team_report,
                    "drivers": driver_reports,
                    "stint_results": stint_results,
                },
            }),
        },
    )

    # Insert score_details
    conn.execute(
        "INSERT INTO score_details "
        "(session_id, pace_score, pace_max, consistency_score, consistency_max, "
        " execution_score, execution_max, robustness_score, robustness_max, adaptation_score) "
        "VALUES (:sid, :ps, :pm, :cs, :cm, :es, :em, :rs, :rm, :as_)",
        {
            "sid": session_id,
            "ps": scores.get("pace", 0),
            "pm": 25,
            "cs": scores.get("consistency", 0),
            "cm": 25,
            "es": 0,
            "em": 0,
            "rs": scores.get("robustness", 0),
            "rm": 25,
            "as_": 0,
        },
    )

    conn.commit()
    try:
        conn.close()
    except Exception:
        pass
    return session_id


def _publish(redis_client, job_id: str, data: dict) -> None:
    """Publish status update for endurance job progress."""
    redis_client.set(f"endurance:status:{job_id}", json.dumps(data), ex=7200)
