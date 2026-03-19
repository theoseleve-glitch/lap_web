"""Universal telemetry adapter infrastructure.

Re-exports the core public API:

- ``BaseAdapter``      — Abstract base class for format adapters.
- ``detect_format``    — Probe a file against all registered adapters.
- ``register_adapter`` — Add an adapter class to the global registry.
- ``parse_file``       — Detect format + parse in one call.

Automatically registers built-in adapters on import.
"""

from telemetry_tool.adapters.acc_adapter import ACCAdapter
from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.generic_csv_adapter import GenericCSVAdapter
from telemetry_tool.adapters.iracing_adapter import IRacingAdapter
from telemetry_tool.adapters.motec_adapter import MoTeCAdapter
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
    "GenericCSVAdapter",
]
