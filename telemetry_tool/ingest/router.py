"""Router facade (W2.T2.3).

`route_upload()` profiles the file, picks a handler, and delegates.
The upload endpoint (T2.4) calls this and returns the job_id as-is.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from telemetry_tool.ingest.profiler import DataProfile, Profiler
from telemetry_tool.ingest.registry import HandlerRegistry, get_registry


def route_upload(
    *,
    file_path: Path,
    session_id: UUID,
    workspace_id: str,
    session_meta: dict,
    profiler: Profiler | None = None,
    registry: HandlerRegistry | None = None,
) -> str:
    profiler = profiler or Profiler()
    registry = registry or get_registry()
    profile: DataProfile = profiler.profile(file_path)
    handler = registry.resolve(profile)
    return handler.enqueue(
        session_id=session_id,
        workspace_id=workspace_id,
        file_path=file_path,
        profile=profile,
        session_meta=session_meta,
    )
