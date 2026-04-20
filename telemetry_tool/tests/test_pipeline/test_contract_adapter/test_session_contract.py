from __future__ import annotations

import pytest
from pydantic import ValidationError

from telemetry_tool.pipeline.contract_adapter.session import build_session_contract
from telemetry_tool.web.schemas.contracts import ChannelTag, SessionCapabilities
from telemetry_tool.web.schemas.contracts.common import SourceLiteral


def test_full_session_contract_smoke(ctx, minimal_summary):
    caps = SessionCapabilities(channels=frozenset({ChannelTag.GPS}))
    contract = build_session_contract(minimal_summary, ctx, caps)
    assert contract.source is SourceLiteral.REAL_LIFE
    assert contract.session_id == ctx.session_id
    assert contract.workspace_id == ctx.workspace_id
    assert len(contract.laps) == 3
    assert contract.laps[1].is_best
    assert contract.sidecar is None


def test_real_life_rejects_throttle_capability(ctx, minimal_summary):
    # If capabilities pipeline misbehaves and declares THROTTLE, the contract
    # validator must reject — adapter MUST NOT silently strip it at this layer.
    bad_caps = SessionCapabilities(
        channels=frozenset({ChannelTag.GPS, ChannelTag.THROTTLE})
    )
    with pytest.raises(ValidationError):
        build_session_contract(minimal_summary, ctx, bad_caps)


def test_missing_session_datetime_defaults_to_utc(ctx, minimal_summary):
    del minimal_summary["session_meta"]["session_datetime"]
    del minimal_summary["session_meta"]["date"]
    caps = SessionCapabilities(channels=frozenset({ChannelTag.GPS}))
    c = build_session_contract(minimal_summary, ctx, caps)
    assert c.session_start.tzinfo is not None
