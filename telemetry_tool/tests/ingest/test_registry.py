from pathlib import Path
from uuid import UUID, uuid4

import pytest

from telemetry_tool.ingest.profiler import DataProfile
from telemetry_tool.ingest.registry import (
    HandlerRegistry, EngineHandler, NoHandlerResolvableError,
    DuplicateHandlerError,
)
from telemetry_tool.web.schemas.contracts import ChannelTag, SourceLiteral


class _FakeHandler:
    SOURCE = SourceLiteral.REAL_LIFE
    PRIORITY = 0
    last_job: str | None = None

    def can_handle(self, profile: DataProfile) -> bool:
        return profile.source is self.SOURCE

    def enqueue(self, *, session_id: UUID, workspace_id: str, file_path: Path,
                profile: DataProfile, session_meta: dict) -> str:
        self.last_job = str(session_id)
        return self.last_job


def _rc_profile() -> DataProfile:
    return DataProfile(
        source=SourceLiteral.REAL_LIFE, parser="racechrono",
        channels_available=frozenset({ChannelTag.GPS}),
        suggested_engine="real_life_pipeline", confidence=0.95,
    )


def test_register_then_resolve_roundtrip():
    reg = HandlerRegistry()
    h = _FakeHandler()
    reg.register(h)
    assert reg.resolve(_rc_profile()) is h


def test_duplicate_register_rejects():
    reg = HandlerRegistry()
    reg.register(_FakeHandler())
    with pytest.raises(DuplicateHandlerError):
        reg.register(_FakeHandler())


def test_resolve_raises_when_empty():
    with pytest.raises(NoHandlerResolvableError):
        HandlerRegistry().resolve(_rc_profile())


def test_tiebreak_source_match_wins():
    """A handler whose SOURCE matches profile.source beats a generic accept-all."""
    reg = HandlerRegistry()

    class _GenericFallback:
        SOURCE = SourceLiteral.AC
        PRIORITY = 100  # high priority but different source
        def can_handle(self, profile): return True  # accepts anything
        def enqueue(self, **kw): return "generic"

    class _IRacingSpecific:
        SOURCE = SourceLiteral.IRACING
        PRIORITY = 0
        def can_handle(self, profile): return profile.source is SourceLiteral.IRACING
        def enqueue(self, **kw): return "iracing"

    reg.register(_GenericFallback())
    reg.register(_IRacingSpecific())

    ibt = DataProfile(
        source=SourceLiteral.IRACING, parser="iracing_ibt",
        channels_available=frozenset({ChannelTag.GPS}),
        suggested_engine="sim_optimizer", confidence=0.95,
    )
    picked = reg.resolve(ibt)
    # Source-match beats higher PRIORITY on a different source.
    assert picked.__class__.__name__ == "_IRacingSpecific"


def test_tiebreak_priority_breaks_when_no_source_match():
    """When no registered handler matches profile.source, higher PRIORITY wins."""
    reg = HandlerRegistry()

    class _AcAcceptAll:
        SOURCE = SourceLiteral.AC
        PRIORITY = 0
        def can_handle(self, p): return True  # accepts any profile
        def enqueue(self, **kw): return "ac"

    class _IracingAcceptAll:
        SOURCE = SourceLiteral.IRACING
        PRIORITY = 10  # higher priority
        def can_handle(self, p): return True  # accepts any profile
        def enqueue(self, **kw): return "iracing"

    reg.register(_AcAcceptAll())
    reg.register(_IracingAcceptAll())

    rc = DataProfile(
        source=SourceLiteral.REAL_LIFE, parser="racechrono",
        channels_available=frozenset({ChannelTag.GPS}),
        suggested_engine="real_life_pipeline", confidence=0.95,
    )
    # Neither handler's SOURCE matches the profile (both accept anyway);
    # PRIORITY 10 beats PRIORITY 0.
    assert reg.resolve(rc).__class__.__name__ == "_IracingAcceptAll"
