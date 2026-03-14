"""Per-plan compute budget enforcement.

Limits concurrent jobs and max job duration based on the user's plan tier.
Checks are performed before dispatching new Celery tasks.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

COMPUTE_BUDGETS: dict[str, dict] = {
    "free": {"max_concurrent_jobs": 1, "max_job_duration_minutes": 10},
    "demo": {"max_concurrent_jobs": 1, "max_job_duration_minutes": 10},
    "racer": {"max_concurrent_jobs": 2, "max_job_duration_minutes": 30},
    "world-class": {"max_concurrent_jobs": 5, "max_job_duration_minutes": 60},
    "world_class": {"max_concurrent_jobs": 5, "max_job_duration_minutes": 60},
    "b2b": {"max_concurrent_jobs": 10, "max_job_duration_minutes": 120},
}


def get_budget(plan_tier: str) -> dict:
    """Get compute budget for a plan tier. Falls back to demo."""
    return COMPUTE_BUDGETS.get(plan_tier, COMPUTE_BUDGETS["demo"])


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
            "plan_tier", "demo"
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
