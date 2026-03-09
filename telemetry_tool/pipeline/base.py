"""
pipeline.base
~~~~~~~~~~~~~
Abstract base class for pipeline stages, plus a compatibility adapter
that wraps existing ``run_*`` functions into the new interface.

New stages should subclass :class:`StageBase` directly.  Existing
``run_*`` functions can be wrapped via :class:`FunctionStage` for
incremental migration.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Stage result container ───────────────────────────────────────────

@dataclass
class StageResult:
    """Lightweight container returned by every stage's ``run()``."""

    output: Any = None
    """Primary output (DataFrame, dict, etc.)."""

    artifacts: dict[str, Any] = field(default_factory=dict)
    """Secondary outputs keyed by name (e.g. ``{"track_id": "spa"}``).
    Allows stages to emit multiple values without tuple-unpacking."""

    warnings: list[str] = field(default_factory=list)
    """Non-fatal warnings accumulated during the stage."""


# ── Abstract base ────────────────────────────────────────────────────

class StageBase(ABC):
    """Contract that every pipeline stage must satisfy.

    Lifecycle
    ---------
    1. ``validate(**ctx)`` — pre-flight check on inputs (may raise).
    2. ``run(**ctx)``      — execute the stage; return :class:`StageResult`.
    3. ``rollback(**ctx)`` — undo side-effects on failure (optional).

    The orchestrator calls these through ``_safe_step()``, so
    individual stages do not need to catch their own exceptions.
    """

    #: Human-readable stage name (used in logs / status tracker).
    name: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.name:
            # Default name from class: "IngestStage" → "ingest"
            cls.name = cls.__name__.removesuffix("Stage").lower()

    # -- required -------------------------------------------------------

    @abstractmethod
    def run(self, **ctx: Any) -> StageResult:
        """Execute the stage.

        Parameters are passed as keyword arguments from the pipeline
        context dict — each stage declares what it needs.

        Must return a :class:`StageResult`.
        """
        ...

    # -- optional hooks -------------------------------------------------

    def validate(self, **ctx: Any) -> None:
        """Pre-flight validation of inputs.

        Raise ``ValueError`` or ``TypeError`` if required inputs are
        missing or malformed.  The default implementation is a no-op.
        """

    def rollback(self, **ctx: Any) -> None:
        """Undo any side-effects produced by ``run()``.

        Called by the orchestrator when a downstream stage fails and
        the pipeline decides to roll back.  The default is a no-op
        (most stages are pure-functional and need no rollback).
        """

    # -- convenience ----------------------------------------------------

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"


# ── Adapter for existing run_* functions ─────────────────────────────

class FunctionStage(StageBase):
    """Wraps an existing ``run_*`` function as a :class:`StageBase`.

    Usage::

        from pipeline.stages.s05_track import run_track_detection

        track_stage = FunctionStage(
            "track_detection",
            run_track_detection,
            args=["trimmed_df", "meta"],
            kwargs={"context": "context", "output_dir": "output_dir"},
        )

    *args* lists context keys passed as positional arguments.
    *kwargs* maps function kwarg names to context keys.
    """

    def __init__(
        self,
        name: str,
        fn: Any,
        *,
        args: Optional[list[str]] = None,
        kwargs: Optional[dict[str, str]] = None,
    ) -> None:
        self.name = name
        self._fn = fn
        self._arg_keys = args or []
        self._kwarg_map = kwargs or {}

    def run(self, **ctx: Any) -> StageResult:
        positional = [ctx[k] for k in self._arg_keys]
        kw = {fn_param: ctx[ctx_key] for fn_param, ctx_key in self._kwarg_map.items() if ctx_key in ctx}
        result = self._fn(*positional, **kw)
        return StageResult(output=result)

    def __repr__(self) -> str:
        return f"<FunctionStage name={self.name!r} fn={self._fn.__name__}>"
