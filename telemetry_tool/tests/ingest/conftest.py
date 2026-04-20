"""Register all adapters so profiler tests see the full registry.

The ``telemetry_tool.adapters.__init__`` module already auto-registers the
built-in adapters on import, but we re-register explicitly here so the
test suite remains robust if that side-effect is ever removed.
"""
from __future__ import annotations

from telemetry_tool.adapters.registry import register_adapter
from telemetry_tool.adapters.racechrono_adapter import RaceChronoAdapter
from telemetry_tool.adapters.iracing_binary_adapter import IRacingBinaryAdapter
from telemetry_tool.adapters.acc_adapter import ACCAdapter


def _register_once() -> None:
    for cls in (RaceChronoAdapter, IRacingBinaryAdapter, ACCAdapter):
        register_adapter(cls)


_register_once()
