"""Internal helper types for the W3 adapter.

ContractTuple packages the three contracts into one return value so callers
can destructure without positional ambiguity.

ContextRef carries the identifiers that live outside the pipeline summary
(session_id + workspace_id come from Celery PipelineContext, not the
orchestrator's in-memory dict).
"""
from __future__ import annotations

from typing import NamedTuple

from telemetry_tool.web.schemas.contracts import (
    CoachingContract,
    OptimizerContract,
    SessionContract,
)


class ContextRef(NamedTuple):
    """The Celery-provided IDs the adapter needs but the pipeline doesn't carry."""

    session_id: str
    workspace_id: str


class ContractTuple(NamedTuple):
    """Return value of `to_contracts()`."""

    session: SessionContract
    coaching: CoachingContract
    optimizer: OptimizerContract
