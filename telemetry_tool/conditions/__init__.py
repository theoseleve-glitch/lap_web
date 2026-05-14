"""Day-11 — LAP V1 conditions engine (scalar layer).

Public API:
    classify_conditions(session_inputs, track_id, *, cache_dir=None) -> WeatherCondition
    WeatherCondition (frozen dataclass, see types.py)
    SpatialMuModifier (frozen dataclass — schema only, Day-12 implements)
    SessionInputs (frozen dataclass — minimum classifier inputs)

Spec: ``Telemetry/LAP_V1_CONDITIONS_ENGINE_SPEC.md``.

The classifier replaces the Day-3-falsified ML classifier (deterministic
μ ≈ 0.85 regardless of weather). It is weather-API-driven (Open-Meteo
historical archive) with explicit user-metadata override and a safe-dry
fallback when the API is unavailable.

Day 11 ships the **scalar** layer only (rules 1-9 + 5b, mu_scale lookup,
WeatherCondition dataclass with ``spatial_modifier=None``). Day 12 will
fill the SpatialMuModifier per spec §7.
"""
from __future__ import annotations

from .types import SessionInputs, SpatialMuModifier, WeatherCondition
from .classifier import classify_conditions
from .spatial_producer import attach_spatial_modifier, compute_spatial_modifier

__all__ = [
    "classify_conditions",
    "attach_spatial_modifier",
    "compute_spatial_modifier",
    "WeatherCondition",
    "SpatialMuModifier",
    "SessionInputs",
]
