"""Universal telemetry adapter infrastructure.

Re-exports the core public API:

- ``BaseAdapter``      — Abstract base class for format adapters.
- ``detect_format``    — Probe a file against all registered adapters.
- ``register_adapter`` — Add an adapter class to the global registry.
- ``parse_file``       — Detect format + parse in one call.

Automatically registers built-in adapters on import.
"""

from telemetry_tool.adapters.acc_adapter import ACCAdapter
from telemetry_tool.adapters.aim_adapter import AiMAdapter
from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.f1_adapter import F1Adapter
from telemetry_tool.adapters.generic_csv_adapter import GenericCSVAdapter
from telemetry_tool.adapters.fit_adapter import FITAdapter
from telemetry_tool.adapters.gpx_adapter import GPXAdapter
from telemetry_tool.adapters.nmea_adapter import NMEAAdapter
from telemetry_tool.adapters.iracing_adapter import IRacingAdapter
from telemetry_tool.adapters.trackaddict_adapter import TrackAddictAdapter
from telemetry_tool.adapters.lmu_adapter import LMUAdapter
from telemetry_tool.adapters.motec_adapter import MoTeCAdapter
from telemetry_tool.adapters.qstarz_binary_stub import QstarzBinaryStub
from telemetry_tool.adapters.qstarz_csv_adapter import QstarzCSVAdapter
from telemetry_tool.adapters.racechrono_rcz_adapter import RaceChronoRCZAdapter
from telemetry_tool.adapters.racebox_adapter import RaceBoxCSVAdapter

# -- Auto-register built-in adapters --------------------------------------
from telemetry_tool.adapters.racechrono_adapter import RaceChronoAdapter
from telemetry_tool.adapters.registry import (
    detect_format,
    parse_file,
    register_adapter,
)
from telemetry_tool.adapters.vbox_adapter import VboxAdapter

register_adapter(RaceChronoAdapter)
register_adapter(IRacingAdapter)
register_adapter(ACCAdapter)
register_adapter(MoTeCAdapter)
register_adapter(VboxAdapter)
register_adapter(RaceBoxCSVAdapter)
register_adapter(QstarzCSVAdapter)
register_adapter(AiMAdapter)
register_adapter(RaceChronoRCZAdapter)
register_adapter(QstarzBinaryStub)

try:
    from telemetry_tool.adapters.iracing_binary_adapter import IRacingBinaryAdapter
    register_adapter(IRacingBinaryAdapter)
except ImportError:
    pass

try:
    from telemetry_tool.adapters.motec_binary_adapter import MoTeCBinaryAdapter
    register_adapter(MoTeCBinaryAdapter)
except ImportError:
    pass

register_adapter(LMUAdapter)
register_adapter(F1Adapter)

register_adapter(GPXAdapter)
register_adapter(NMEAAdapter)

register_adapter(TrackAddictAdapter)
register_adapter(FITAdapter)

register_adapter(GenericCSVAdapter)

__all__ = [
    "BaseAdapter",
    "detect_format",
    "parse_file",
    "register_adapter",
    "RaceChronoAdapter",
    "IRacingAdapter",
    "ACCAdapter",
    "MoTeCAdapter",
    "VboxAdapter",
    "RaceBoxCSVAdapter",
    "QstarzCSVAdapter",
    "AiMAdapter",
    "RaceChronoRCZAdapter",
    "QstarzBinaryStub",
    "LMUAdapter",
    "F1Adapter",
    "GPXAdapter",
    "NMEAAdapter",
    "TrackAddictAdapter",
    "FITAdapter",
    "GenericCSVAdapter",
]
