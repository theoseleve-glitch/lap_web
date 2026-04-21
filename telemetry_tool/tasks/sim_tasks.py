"""Celery tasks that run on the `sim` queue.

Session #5 (iRacing + AC adapters) adds real tasks here. This placeholder
ensures the queue has at least one registered task so `celery inspect`
doesn't complain on an empty worker.
"""
from __future__ import annotations

from celery_app import celery


@celery.task(name="tasks.sim_tasks.noop", queue="sim")
def noop(session_id: str) -> str:
    """Health-probe no-op. Session #5 wires the real IBT/AC entrypoint."""
    return session_id
