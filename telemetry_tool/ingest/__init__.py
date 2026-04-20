"""
telemetry_tool.ingest
---------------------
Streaming ingestion pipeline for large telemetry CSV files.

Gated behind the ``INGEST_V2`` feature flag (default OFF).  When the flag
is OFF, the legacy ``io_racechrono.read_racechrono_csv`` path is used
unchanged.

Public API
~~~~~~~~~~
- :func:`ingest_csv`          — size-aware entrypoint (routes to legacy or streaming)
- :class:`IngestionProgress`  — progress event dataclass
- :class:`IngestionConfig`    — tuning knobs (chunk size, memory limit, cache dir)
"""

from telemetry_tool.ingest.config import INGEST_V2, IngestionConfig, IngestionLimits
from telemetry_tool.ingest.profiler import DataProfile, Profiler, UnknownFormatError
from telemetry_tool.ingest.progress import IngestionProgress, ProgressCallback

__all__ = [
    "INGEST_V2",
    "IngestionConfig",
    "IngestionLimits",
    "IngestionProgress",
    "ProgressCallback",
    "DataProfile",
    "Profiler",
    "UnknownFormatError",
]
