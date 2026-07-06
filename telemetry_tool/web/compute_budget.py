"""Per-plan compute budget enforcement.

Limits concurrent jobs and max job duration based on the user's plan tier.
Checks are performed before dispatching new Celery tasks.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

COMPUTE_BUDGETS: dict[str, dict] = {
    "locked": {"max_concurrent_jobs": 1, "max_job_duration_minutes": 10},
    "racer": {"max_concurrent_jobs": 2, "max_job_duration_minutes": 30},
    "world-class": {"max_concurrent_jobs": 5, "max_job_duration_minutes": 60},
    "world_class": {"max_concurrent_jobs": 5, "max_job_duration_minutes": 60},
    "b2b": {"max_concurrent_jobs": 10, "max_job_duration_minutes": 120},
}


def get_budget(plan_tier: str) -> dict:
    """Get compute budget for a plan tier. Falls back to locked."""
    return COMPUTE_BUDGETS.get(plan_tier, COMPUTE_BUDGETS["locked"])


def check_compute_budget(
    conn,
    user_id: int,
    workspace_id: int,
    plan_tier: str | None = None,
) -> tuple[bool, dict]:
    """Check if a user can launch another job.

    Args:
        conn: Database connection
        user_id: The user requesting the job
        workspace_id: The current workspace
        plan_tier: Override tier (otherwise looks up from user)

    Returns:
        (allowed, info) where info contains:
            running_jobs: int — current active jobs
            max_jobs: int — plan limit
            max_duration_minutes: int — plan limit
            oldest_job_started: str|None — ISO timestamp
    """
    if plan_tier is None:
        row = conn.execute(
            "SELECT plan_tier FROM users WHERE id = %(uid)s",
            {"uid": user_id},
        ).fetchone()
        plan_tier = (dict(row) if row and not isinstance(row, dict) else (row or {})).get(
            "plan_tier", "locked"
        )

    budget = get_budget(plan_tier)
    max_jobs = budget["max_concurrent_jobs"]
    max_duration = budget["max_job_duration_minutes"]

    # Count running/queued jobs for this workspace
    running_row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM ingestion_jobs "
        "WHERE workspace_id = %(wsid)s AND status IN ('pending', 'running', 'processing')",
        {"wsid": workspace_id},
    ).fetchone()
    running = (dict(running_row) if running_row and not isinstance(running_row, dict) else (running_row or {})).get(
        "cnt", 0
    )

    # Get oldest running job start time
    oldest_row = conn.execute(
        "SELECT MIN(started_at) AS oldest FROM ingestion_jobs "
        "WHERE workspace_id = %(wsid)s AND status = 'running'",
        {"wsid": workspace_id},
    ).fetchone()
    oldest = (dict(oldest_row) if oldest_row and not isinstance(oldest_row, dict) else (oldest_row or {})).get(
        "oldest"
    )

    info = {
        "running_jobs": running,
        "max_jobs": max_jobs,
        "max_duration_minutes": max_duration,
        "oldest_job_started": oldest.isoformat() if oldest else None,
        "plan_tier": plan_tier,
    }

    allowed = running < max_jobs
    if not allowed:
        logger.info(
            "Compute budget exceeded: user=%s workspace=%s running=%d max=%d tier=%s",
            user_id, workspace_id, running, max_jobs, plan_tier,
        )

    return allowed, info


# Heavy async-compute job sources counted toward the SHARED per-tier budget.
# Each entry: (table, active_status_values). Table names are hardcoded
# constants (no injection). ``analysis_runs`` may be absent on older lineages
# (its original migration 056 was orphaned) — counting is SAVEPOINT-guarded so
# a missing table contributes 0 without aborting the caller's transaction.
#
# NOTE: endurance jobs are NOT a PG source here — 2c5f508 isolated them onto
# their own Celery queue and their state lives entirely in Redis (see
# tasks.endurance_tasks), so they were invisible to this pool and the shared
# cap was a no-op for them. count_active_compute_jobs() folds them back in
# via the ``redis_client`` param instead of a fourth SQL source.
_ACTIVE_JOB_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ingestion_jobs", ("pending", "running", "processing")),
    ("exports", ("pending", "processing", "running")),
    ("analysis_runs", ("pending", "running", "processing")),
)


def _row_count(row) -> int:
    d = dict(row) if row and not isinstance(row, dict) else (row or {})
    return int(d.get("cnt", 0) or 0)


def count_active_endurance_jobs(redis_client, workspace_id) -> int:
    """Count in-flight endurance jobs for a workspace via the Redis active-set.

    Endurance jobs run on their own Celery queue and never write to
    ``ingestion_jobs``/``exports``/``analysis_runs``, so they are otherwise
    invisible to :func:`count_active_compute_jobs`'s PG scan.
    ``web.routes.endurance_upload.process_stints`` SADDs ``job_id`` into
    ``endurance:active:{workspace_id}`` at dispatch (see
    ``tasks.endurance_tasks.mark_endurance_dispatched``) and every terminal
    path (success, soft-timeout failure, redelivery-exhaustion failure, or
    the stuck-job reconciler's forced failure) SREMs it back out — see
    ``tasks.endurance_tasks._clear_endurance_active``.

    Fails open (returns 0) on any Redis error or when no client is supplied,
    matching the SAVEPOINT-guarded fail-open behaviour of the PG sources.
    """
    if redis_client is None:
        return 0
    try:
        return int(redis_client.scard(f"endurance:active:{workspace_id}"))
    except Exception:
        logger.debug("Endurance active-job count skipped", exc_info=True)
        return 0


def count_active_compute_jobs(conn, workspace_id, sources=_ACTIVE_JOB_SOURCES, redis_client=None) -> int:
    """Count active heavy-compute jobs for a workspace across ALL job tables.

    Backs the shared per-tier concurrency budget so analysis, export,
    track-surface, and (via ``redis_client``) endurance jobs draw from one
    pool. Each PG source is counted inside a SAVEPOINT: a missing table or a
    query error contributes 0 without aborting the caller's transaction
    (important — the caller is mid-request and will still INSERT its own job
    row after this check).
    """
    total = 0
    for table, statuses in sources:
        params: dict = {"wsid": workspace_id}
        for i, s in enumerate(statuses):
            params[f"s{i}"] = s
        placeholders = ", ".join(f"%(s{i})s" for i in range(len(statuses)))
        sql = (
            f"SELECT COUNT(*) AS cnt FROM {table} "
            f"WHERE workspace_id = %(wsid)s AND status IN ({placeholders})"
        )
        try:
            conn.execute("SAVEPOINT cb_count")
            row = conn.execute(sql, params).fetchone()
            conn.execute("RELEASE SAVEPOINT cb_count")
            total += _row_count(row)
        except Exception:
            try:
                conn.execute("ROLLBACK TO SAVEPOINT cb_count")
            except Exception:
                pass
            logger.debug("Active-job count skipped for table %s", table, exc_info=True)
    total += count_active_endurance_jobs(redis_client, workspace_id)
    return total


def check_shared_compute_budget(
    conn,
    user_id: int,
    workspace_id: int,
    plan_tier: str | None = None,
    redis_client=None,
) -> tuple[bool, dict]:
    """Shared per-tier concurrency budget across ALL heavy async job types.

    Mirrors :func:`check_compute_budget` but counts analysis + export +
    track-surface + endurance jobs in ONE pool (see
    :func:`count_active_compute_jobs`), so a single workspace cannot saturate
    the worker fleet by spreading load across job types — including onto the
    isolated endurance queue. Pass ``redis_client`` so the endurance signal is
    included; omitting it degrades gracefully to the pre-existing PG-only
    count. Returns ``(allowed, info)`` with the same shape.
    """
    if plan_tier is None:
        row = conn.execute(
            "SELECT plan_tier FROM users WHERE id = %(uid)s",
            {"uid": user_id},
        ).fetchone()
        plan_tier = (dict(row) if row and not isinstance(row, dict) else (row or {})).get(
            "plan_tier", "locked"
        )

    budget = get_budget(plan_tier)
    max_jobs = budget["max_concurrent_jobs"]
    running = count_active_compute_jobs(conn, workspace_id, redis_client=redis_client)

    info = {
        "running_jobs": running,
        "max_jobs": max_jobs,
        "max_duration_minutes": budget["max_job_duration_minutes"],
        "plan_tier": plan_tier,
    }

    allowed = running < max_jobs
    if not allowed:
        logger.info(
            "Shared compute budget exceeded: user=%s workspace=%s running=%d max=%d tier=%s",
            user_id, workspace_id, running, max_jobs, plan_tier,
        )

    return allowed, info
