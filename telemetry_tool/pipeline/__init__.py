"""
pipeline
~~~~~~~~
Modular telemetry analysis pipeline.

Backward-compatible re-exports so that existing code using
``from pipeline import run_full_analysis`` continues to work.
"""
from pipeline.helpers import (
    PipelineError,
    _safe_step,
)
from pipeline.helpers import compute_robustness_metrics as _compute_robustness_metrics
from pipeline.helpers import extract_track_layout_for_picker as _extract_track_layout_for_picker
from pipeline.helpers import lazy_import as _import
from pipeline.helpers import theoretical_metrics_from_lap as _theoretical_metrics_from_lap
from pipeline.helpers import (
    validate_lap_consistency,
)
from pipeline.orchestrator import run_full_analysis

__all__ = [
    "run_full_analysis",
    "PipelineError",
    "_safe_step",
    "validate_lap_consistency",
    "_compute_robustness_metrics",
    "_theoretical_metrics_from_lap",
    "_extract_track_layout_for_picker",
    "_import",
]


# --- W3 handler auto-registration ------------------------------------------
# Deferred import so pipeline/ loads even if W2 hasn't shipped router yet.
try:
    from telemetry_tool.ingest.router import register_handler as _w2_register
    from telemetry_tool.pipeline.handler import RealLifePipelineHandler as _RealLifeHandler

    _w2_register(_RealLifeHandler())
except ImportError:
    # W2 not yet merged -- this is expected during Wave 2. Registration
    # will activate once `telemetry_tool.ingest.router` lands.
    pass
except Exception:  # pragma: no cover - defensive
    import logging as _log
    _log.getLogger(__name__).exception("W3 handler registration failed (non-fatal)")
