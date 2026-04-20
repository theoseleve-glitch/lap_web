"""End-to-end: real CSV -> orchestrator -> adapter -> contracts.

Marked `slow` so day-to-day unit runs skip it. CI runs this on merges.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


_FIXTURE = (
    Path(__file__).resolve().parents[3] / "fixtures" / "golden" / "OK_R3.csv"
)


@pytest.mark.skipif(not _FIXTURE.exists(), reason="OK_R3.csv fixture not present")
def test_real_csv_produces_valid_contracts():
    from telemetry_tool.pipeline.contract_adapter import ContextRef, to_contracts
    from telemetry_tool.pipeline.orchestrator import run_full_analysis

    summary = run_full_analysis(
        csv_path=str(_FIXTURE),
        session_meta={
            "session_id": "e2e-test",
            "workspace_id": "wid-e2e",
            "driver_name": "Smoke",
            "driver_id": 1,
            "session_datetime": "2026-04-19T10:00:00+00:00",
        },
        enable_ml=False,
        enable_report=False,
    )
    ctx = ContextRef(session_id="e2e-test", workspace_id="wid-e2e")
    out = to_contracts(summary, ctx)

    assert out.session.source.value == "real_life"
    assert len(out.session.laps) >= 1
    assert out.optimizer.depth.value == "trajectory_only"
    assert out.coaching.version == "1.0"
    # When workspace_id is present, orchestrator hook should have attached contracts
    if "contracts" in summary:
        assert summary["contracts"].session.source.value == "real_life"
