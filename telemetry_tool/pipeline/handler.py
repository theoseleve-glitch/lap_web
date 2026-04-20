"""W3 -- EngineHandler implementation for real-life RaceChrono/RaceBox sessions.

This is the object the W2 HandlerRegistry looks up when the profiler
classifies an upload as `source="real_life"`. It is a thin shell: run the
existing pipeline, then hand the summary to the contract adapter.

The concrete registration happens in `telemetry_tool/pipeline/__init__.py`
via a lazy try/except so this package can be installed/imported before
W2's router module exists.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from telemetry_tool.pipeline.contract_adapter import ContextRef, ContractTuple, to_contracts

logger = logging.getLogger(__name__)


class RealLifePipelineHandler:
    """Dispatches real-life uploads to the existing pipeline."""

    source: str = "real_life"

    def run(
        self,
        *,
        csv_path: str | Path,
        session_meta: dict[str, Any],
        ctx: ContextRef,
        **pipeline_kwargs: Any,
    ) -> ContractTuple:
        # Late-bind the orchestrator -- avoids circular import during package init
        import telemetry_tool.pipeline.orchestrator as orchestrator
        summary = orchestrator.run_full_analysis(
            csv_path=str(csv_path),
            session_meta=session_meta,
            **pipeline_kwargs,
        )
        return to_contracts(summary, ctx)
