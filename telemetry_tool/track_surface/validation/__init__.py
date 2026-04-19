"""Cross-track validation harness for the friction estimation pipeline.

Honest, reproducible measurement of how well the calibrated stack
transfers to sessions and tracks beyond the Daytona baseline.

The harness has two passes:

  Pass 1 (default): frozen-parameter transfer
      The pipeline runs with the production calibration unchanged.
      No per-session retuning. This is the load-bearing measurement.

  Pass 2 (opt-in): adaptation sensitivity
      Re-runs with roll-compliance and tire-D scale fitting enabled.
      Writes to a separate output directory so frozen results are
      never overwritten.

Public entry points:

  - load_manifest(path)             : parse + validate cross-track manifest
  - run_validation_suite(...)        : execute one or both passes, write reports
  - compute_metrics(result, entry)   : turn a PipelineResult into SessionMetrics
  - classify_warnings(metrics, ...)  : produce categorized OK/WARN/FAIL flags
"""
from __future__ import annotations

from track_surface.validation.classifier import (
    ValidationWarning,
    WarningSeverity,
    classify_warnings,
)
from track_surface.validation.harness import (
    PipelineConfig,
    PipelineResult,
    run_pipeline,
)
from track_surface.validation.manifest import (
    DatasetEntry,
    ExpectedMetrics,
    SessionInfo,
    TrackSpec,
    ValidationManifest,
    VehicleSpec,
    load_manifest,
)
from track_surface.validation.metrics import (
    SessionMetrics,
    compute_metrics,
)
from track_surface.validation.reporter import (
    write_aggregate_report,
    write_session_report,
)
from track_surface.validation.suite import (
    SuiteResult,
    run_validation_suite,
)

__all__ = [
    "DatasetEntry",
    "ExpectedMetrics",
    "PipelineConfig",
    "PipelineResult",
    "SessionInfo",
    "SessionMetrics",
    "SuiteResult",
    "TrackSpec",
    "ValidationManifest",
    "ValidationWarning",
    "VehicleSpec",
    "WarningSeverity",
    "classify_warnings",
    "compute_metrics",
    "load_manifest",
    "run_pipeline",
    "run_validation_suite",
    "write_aggregate_report",
    "write_session_report",
]
