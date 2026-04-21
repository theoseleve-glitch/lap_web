"""Stub handlers for iRacing and AC — sessions #5 replaces these."""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from telemetry_tool.ingest.profiler import DataProfile
from telemetry_tool.ingest.registry import get_registry
from telemetry_tool.web.schemas.contracts import SourceLiteral


class _Stub:
    PRIORITY = 0

    def can_handle(self, profile: DataProfile) -> bool:
        return profile.source is self.SOURCE

    def enqueue(self, *, session_id: UUID, workspace_id: str, file_path: Path,
                profile: DataProfile, session_meta: dict) -> str:
        raise NotImplementedError(
            f"{type(self).__name__} is a stub; session #5 must replace it "
            f"via `get_registry().unregister({self.SOURCE}); register(RealHandler())`."
        )


class IRacingStubHandler(_Stub):
    SOURCE = SourceLiteral.IRACING


class ACStubHandler(_Stub):
    SOURCE = SourceLiteral.AC


get_registry().register(IRacingStubHandler())
get_registry().register(ACStubHandler())
