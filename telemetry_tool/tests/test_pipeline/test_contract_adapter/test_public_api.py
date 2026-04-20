"""Smoke test for the W3 adapter public surface.

Executes before any implementation — forces us to settle the public API
before we start filling in mapping logic.
"""
from __future__ import annotations


def test_to_contracts_is_importable():
    from telemetry_tool.pipeline.contract_adapter import to_contracts  # noqa: F401


def test_context_ref_carries_ids():
    from telemetry_tool.pipeline.contract_adapter import ContextRef

    ctx = ContextRef(session_id="sid-1", workspace_id="wid-1")
    assert ctx.session_id == "sid-1"
    assert ctx.workspace_id == "wid-1"


def test_contract_tuple_shape():
    from telemetry_tool.pipeline.contract_adapter import ContractTuple

    assert set(ContractTuple._fields) == {"session", "coaching", "optimizer"}
