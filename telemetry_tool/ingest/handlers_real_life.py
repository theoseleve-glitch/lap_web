"""Real-life engine handler — wraps the existing 14-stage Celery pipeline.

Registered on import; sessions #4 and #5 replace the iRacing / AC stubs
by importing their own adapter modules which in turn call `register()`.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import UUID

import redis

# Imported at module scope so tests can patch them via
# `@patch("telemetry_tool.ingest.handlers_real_life.build_pipeline_chain")`.
from pipeline_context import PipelineContext
from tasks.pipeline_tasks import build_pipeline_chain
from web.config import Config

from telemetry_tool.ingest.profiler import DataProfile
from telemetry_tool.ingest.registry import get_registry
from telemetry_tool.web.schemas.contracts import SourceLiteral

logger = logging.getLogger(__name__)


def _redis_from_url(url: str) -> redis.Redis:
    """Thin wrapper so tests can monkeypatch the redis client factory."""
    return redis.Redis.from_url(url)


class RealLifeHandler:
    SOURCE = SourceLiteral.REAL_LIFE
    PRIORITY = 10  # canonical match for real_life profiles

    def can_handle(self, profile: DataProfile) -> bool:
        return profile.source is SourceLiteral.REAL_LIFE

    def enqueue(self, *, session_id: UUID, workspace_id: str, file_path: Path,
                profile: DataProfile, session_meta: dict) -> str:
        job_id = str(session_id)  # sessions_v2 treats job_id as opaque
        r = _redis_from_url(Config.REDIS_URL)
        PipelineContext.create(
            redis_client=r,
            job_id=job_id,
            workspace_id=workspace_id,
            session_id=job_id,
            file_path=str(file_path),
        )
        meta = dict(session_meta)
        # mode="json" coerces frozenset[ChannelTag] → list[str] so json.dumps doesn't trip.
        meta["data_profile"] = profile.model_dump(mode="json")
        meta["capabilities"] = sorted(t.value for t in profile.channels_available)
        meta["source"] = profile.source.value
        r.set(f"pipeline:meta:{job_id}", json.dumps(meta), ex=7200)

        build_pipeline_chain(job_id).apply_async(
            soft_time_limit=meta.get("_soft_timeout_s", 600),
        )
        logger.info("Real-life pipeline dispatched: job_id=%s ws=%s", job_id, workspace_id)
        return job_id


# Register on import.
get_registry().register(RealLifeHandler())
