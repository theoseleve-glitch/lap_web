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

# Auto-register handlers. Order: real-life first, sim stubs second.
# Sessions #4/#5 replace stubs via their own adapter modules.
from telemetry_tool.ingest import handlers_real_life  # noqa: F401,E402
from telemetry_tool.ingest import handlers_sim_stubs  # noqa: F401,E402

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
