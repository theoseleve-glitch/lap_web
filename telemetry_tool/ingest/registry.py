"""Engine handler registry (W2.T2.3).

Sessions #4 and #5 replace the stubs via `register_handler()` when their
adapter packages import. Keep this interface stable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from telemetry_tool.ingest.profiler import DataProfile
from telemetry_tool.web.schemas.contracts import SourceLiteral


class DuplicateHandlerError(ValueError):
    """Two handlers registered for the same SOURCE."""


class NoHandlerResolvableError(LookupError):
    """No registered handler can handle the profile."""


@runtime_checkable
class EngineHandler(Protocol):
    SOURCE: SourceLiteral
    PRIORITY: int

    def can_handle(self, profile: DataProfile) -> bool: ...
    def enqueue(self, *, session_id: UUID, workspace_id: str, file_path: Path,
                profile: DataProfile, session_meta: dict) -> str: ...


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: list[EngineHandler] = []

    def register(self, handler: EngineHandler) -> None:
        for existing in self._handlers:
            if existing.SOURCE == handler.SOURCE:
                raise DuplicateHandlerError(
                    f"Handler for {handler.SOURCE} already registered "
                    f"({type(existing).__name__})"
                )
        self._handlers.append(handler)

    def resolve(self, profile: DataProfile) -> EngineHandler:
        """Pick one handler for `profile`.

        Tie-break when multiple `can_handle(profile) == True`:
            1. Handlers with `SOURCE == profile.source` beat others.
            2. Higher `PRIORITY` wins within the same source-match bucket.
            3. Registration order breaks remaining ties (stable sort).
        """
        candidates = [h for h in self._handlers if h.can_handle(profile)]
        if not candidates:
            raise NoHandlerResolvableError(
                f"No registered handler accepts profile {profile.source.value} "
                f"(parser={profile.parser}, registered={[h.SOURCE.value for h in self._handlers]})"
            )
        candidates.sort(
            key=lambda h: (1 if h.SOURCE is profile.source else 0, getattr(h, "PRIORITY", 0)),
            reverse=True,
        )
        return candidates[0]

    def unregister(self, source: SourceLiteral) -> None:
        self._handlers = [h for h in self._handlers if h.SOURCE is not source]


# Global singleton — sessions #4/#5 register into this at import time.
_registry: HandlerRegistry = HandlerRegistry()


def get_registry() -> HandlerRegistry:
    return _registry
