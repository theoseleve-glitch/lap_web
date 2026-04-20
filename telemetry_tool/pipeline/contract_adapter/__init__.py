"""W3 -- Real-life pipeline -> unified contracts adapter.

Pure translation layer. Reads `orchestrator.run_full_analysis()`'s summary
dict plus a Celery ContextRef (session_id + workspace_id) and emits the
three unified contracts defined in W1.

No pipeline stage code is touched -- this module is additive.
"""
from __future__ import annotations

from typing import Any

from telemetry_tool.pipeline.contract_adapter._types import ContextRef, ContractTuple
from telemetry_tool.pipeline.contract_adapter.capabilities import build_capabilities
from telemetry_tool.pipeline.contract_adapter.coaching import build_coaching_contract
from telemetry_tool.pipeline.contract_adapter.optimizer import build_optimizer_contract
from telemetry_tool.pipeline.contract_adapter.session import build_session_contract

__all__ = ["ContextRef", "ContractTuple", "to_contracts"]


def to_contracts(summary: dict[str, Any], ctx: ContextRef) -> ContractTuple:
    """Produce the unified contract triple for one real-life session.

    Parameters
    ----------
    summary:
        The return value of `orchestrator.run_full_analysis(...)`.
    ctx:
        Session and workspace identifiers that live outside the pipeline
        (populated from Celery's PipelineContext in production; synthesised
        in tests).
    """
    caps = build_capabilities(summary)
    session = build_session_contract(summary, ctx, caps)
    coaching = build_coaching_contract(summary)
    optimizer = build_optimizer_contract(summary)
    return ContractTuple(session=session, coaching=coaching, optimizer=optimizer)
