"""W3 — Real-life pipeline → unified contracts adapter.

Pure translation layer. Reads `orchestrator.run_full_analysis()`'s summary
dict plus a Celery ContextRef (session_id + workspace_id) and emits the
three unified contracts defined in W1.

No pipeline stage code is touched — this module is additive.
"""
from __future__ import annotations

from typing import Any

from telemetry_tool.pipeline.contract_adapter._types import ContextRef, ContractTuple

__all__ = ["ContextRef", "ContractTuple", "to_contracts"]


def to_contracts(summary: dict[str, Any], ctx: ContextRef) -> ContractTuple:
    """Produce the unified contract triple for one real-life session.

    Fills in later tasks — Tasks 2-8 wire each component. Task 1 only
    establishes the public surface so callers can type-check.
    """
    raise NotImplementedError("wired progressively in Tasks 2-8")
