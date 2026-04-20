from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter import to_contracts
from telemetry_tool.web.schemas.contracts import (
    CoachingContract,
    OptimizerContract,
    SessionContract,
)


def test_to_contracts_returns_named_triple(ctx, minimal_summary):
    out = to_contracts(minimal_summary, ctx)
    assert isinstance(out.session, SessionContract)
    assert isinstance(out.coaching, CoachingContract)
    assert isinstance(out.optimizer, OptimizerContract)


def test_to_contracts_source_is_real_life(ctx, minimal_summary):
    out = to_contracts(minimal_summary, ctx)
    assert out.session.source.value == "real_life"


def test_to_contracts_trajectory_only(ctx, minimal_summary):
    out = to_contracts(minimal_summary, ctx)
    assert out.optimizer.depth.value == "trajectory_only"
