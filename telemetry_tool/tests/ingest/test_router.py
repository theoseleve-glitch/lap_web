from pathlib import Path
from uuid import uuid4

from telemetry_tool.ingest.profiler import DataProfile, Profiler
from telemetry_tool.ingest.registry import HandlerRegistry
from telemetry_tool.ingest.router import route_upload
from telemetry_tool.web.schemas.contracts import ChannelTag, SourceLiteral


FIX = Path(__file__).parent / "fixtures"


class _SpyHandler:
    SOURCE = SourceLiteral.REAL_LIFE
    PRIORITY = 0
    enqueued: list[str] = []

    def can_handle(self, profile): return profile.source is self.SOURCE

    def enqueue(self, *, session_id, workspace_id, file_path, profile, session_meta):
        self.enqueued.append(str(session_id))
        return str(session_id)


def test_route_upload_dispatches_to_handler():
    reg = HandlerRegistry()
    spy = _SpyHandler()
    reg.register(spy)

    sid = uuid4()
    job_id = route_upload(
        file_path=FIX / "sample_racechrono.csv",
        session_id=sid,
        workspace_id="ws-1",
        session_meta={"driver_name": "Theo"},
        profiler=Profiler(),
        registry=reg,
    )
    assert job_id == str(sid)
    assert spy.enqueued == [str(sid)]
