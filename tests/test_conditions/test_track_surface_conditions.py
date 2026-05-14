"""Day-13 Phase B — TrackSurfaceResponse.conditions Pydantic schema tests.

Tests the API contract that joins WeatherCondition (Day-11 scalar) +
SpatialMuModifier (Day-12 spatial) to TrackSurfaceResponse. Synthetic
payload anchored on OK_R4 Day-12 Phase H numbers:

    label=greasy, source=user, mu_scale=0.82, mesh hand_traced
    spatial factor_values spread 0.736..1.457 (1.979×)
    sun uniform 0.950, sun_az 157.5°/el 23.5°
    drainage [0.85, 1.30], wind [0.85, 1.10] @ 179°/26 km/h

Validates the contract that lands in the production API response (the
TrackSurfaceResponse the frontend reads, including the conditions
field). Catches: enum drift, array-vs-ndarray drift, exclude_none
behavior at the response boundary.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from web.schemas.track_surface import (
    SpatialMuModifierResponse,
    TrackSurfaceResponse,
    WeatherConditionResponse,
)


# ── Synthetic OK_R4 Day-12 anchored fixture ──────────────────────────


def _ok_r4_spatial_payload() -> dict:
    """5-segment synthetic anchored on OK_R4 Phase-H numbers."""
    return {
        "arclength_samples": [0.0, 200.0, 400.0, 600.0, 800.0],
        "factor_values": [1.457, 1.039, 0.736, 1.039, 1.457],
        "drainage_components": [1.30, 1.05, 0.85, 1.05, 1.30],
        "sun_components": [0.95, 0.95, 0.95, 0.95, 0.95],
        "wind_components": [1.10, 0.98, 0.85, 0.98, 1.10],
        "sun_altitude_deg": 23.5,
        "sun_azimuth_deg": 157.5,
        "wind_direction_deg": 179.0,
        "wind_speed_kmh": 26.0,
        "mesh_source": "hand_traced",
        "spatial_version": "spatial-v1.0",
    }


def _ok_r4_conditions_payload(*, with_spatial: bool = True) -> dict:
    spatial = _ok_r4_spatial_payload() if with_spatial else None
    return {
        "label": "greasy",
        "mu_scale": 0.82,
        "confidence": 1.0,
        "track_temp_estimate_c": None,
        "water_film_estimate": None,
        "hours_since_rain": None,
        "days_since_significant_rain": None,
        "drying_rate_estimate": None,
        "dominant_factor": "user_override",
        "rationale": "User-supplied condition='greasy'; spec §2 user-override wins over weather.",
        "source": "user",
        "spatial_modifier": spatial,
        "classifier_version": "weather-v1.0+spatial-v1.0" if with_spatial else "weather-v1.0",
    }


def _surface_payload(conditions: dict | None) -> dict:
    return {
        "bins": [
            {"distance_m": 0.0, "grip_mu": 1.00, "elevation_m": 0.0},
            {"distance_m": 200.0, "grip_mu": 0.98, "elevation_m": 0.5},
        ],
        "quality_tier": "silver",
        "boundary_source": "hand_traced",
        "conditions": conditions,
    }


# ── Tests ─────────────────────────────────────────────────────────────


def test_full_roundtrip_via_model_dump_json():
    """Synthetic OK_R4 payload survives Pydantic → JSON → Pydantic."""
    surface = TrackSurfaceResponse.model_validate(_surface_payload(_ok_r4_conditions_payload()))
    blob = surface.model_dump_json()
    decoded = json.loads(blob)
    rehydrated = TrackSurfaceResponse.model_validate(decoded)
    assert rehydrated.conditions is not None
    assert rehydrated.conditions.label == "greasy"
    assert rehydrated.conditions.mu_scale == 0.82
    assert rehydrated.conditions.spatial_modifier is not None
    assert rehydrated.conditions.spatial_modifier.mesh_source == "hand_traced"


def test_factor_arrays_serialize_as_json_lists():
    """No ndarray-in-API: arrays must round-trip as plain list[float]."""
    surface = TrackSurfaceResponse.model_validate(_surface_payload(_ok_r4_conditions_payload()))
    decoded = json.loads(surface.model_dump_json())
    arr = decoded["conditions"]["spatial_modifier"]["factor_values"]
    assert isinstance(arr, list)
    assert all(isinstance(x, float) for x in arr)
    assert len(arr) == 5


def test_spatial_spread_anchored_on_phase_h_numbers():
    """Phase H captured spread 1.979× on OK_R4; the fixture preserves it."""
    sm = SpatialMuModifierResponse.model_validate(_ok_r4_spatial_payload())
    spread = max(sm.factor_values) / min(sm.factor_values)
    assert spread == pytest.approx(1.979, abs=0.01)
    # Sun uniformity on flat kart tracks (Day-12 finding)
    assert min(sm.sun_components) == max(sm.sun_components) == 0.95


def test_conditions_none_degrades_cleanly():
    """Pre-Day-11 sessions: conditions is None → TrackSurface still valid."""
    surface = TrackSurfaceResponse.model_validate(_surface_payload(None))
    assert surface.conditions is None
    decoded = json.loads(surface.model_dump_json(exclude_none=True))
    assert "conditions" not in decoded, (
        "exclude_none=True must omit conditions=null from JSON output"
    )


def test_conditions_present_but_spatial_none():
    """Pre-Day-12 sessions: scalar layer ran, spatial did not."""
    cond = _ok_r4_conditions_payload(with_spatial=False)
    surface = TrackSurfaceResponse.model_validate(_surface_payload(cond))
    assert surface.conditions is not None
    assert surface.conditions.spatial_modifier is None
    decoded = json.loads(surface.model_dump_json(exclude_none=True))
    # spatial_modifier=None is dropped, but conditions itself remains
    assert "conditions" in decoded
    assert "spatial_modifier" not in decoded["conditions"]


def test_enum_rejects_bad_label():
    cond = _ok_r4_conditions_payload()
    cond["label"] = "soaking"
    with pytest.raises(ValidationError, match="label"):
        WeatherConditionResponse.model_validate(cond)


def test_enum_rejects_bad_source():
    cond = _ok_r4_conditions_payload()
    cond["source"] = "vibes"
    with pytest.raises(ValidationError, match="source"):
        WeatherConditionResponse.model_validate(cond)


def test_enum_rejects_bad_mesh_source():
    sm = _ok_r4_spatial_payload()
    sm["mesh_source"] = "guessed"
    with pytest.raises(ValidationError, match="mesh_source"):
        SpatialMuModifierResponse.model_validate(sm)


def test_water_film_enum_accepts_none_and_valid_values():
    """water_film_estimate is Optional[Literal] — None and valid strings ok."""
    for value in (None, "none", "thin", "thick"):
        cond = _ok_r4_conditions_payload()
        cond["water_film_estimate"] = value
        wc = WeatherConditionResponse.model_validate(cond)
        assert wc.water_film_estimate == value

    cond = _ok_r4_conditions_payload()
    cond["water_film_estimate"] = "puddly"
    with pytest.raises(ValidationError, match="water_film_estimate"):
        WeatherConditionResponse.model_validate(cond)


def test_raw_inputs_silently_dropped():
    """LenientSchema extra='ignore': raw_inputs in input → dropped from model.

    The producer's to_dict() includes raw_inputs (debug-only). API contract
    excludes it. Schema must silently ignore it, not raise.
    """
    cond = _ok_r4_conditions_payload()
    cond["raw_inputs"] = {"P1": 18.5, "fallback_reason": None, "winddirection_10m": 179}
    wc = WeatherConditionResponse.model_validate(cond)
    # raw_inputs not in the schema; model_dump won't emit it
    assert "raw_inputs" not in wc.model_dump()


def test_spatial_array_lengths_must_match_arclength():
    """Each per-segment array should have the same length as arclength_samples.

    Phase-G producer guarantees N_s alignment; the schema documents the
    contract via test, not via Pydantic constraint (variable-length per
    session).
    """
    sm_dict = _ok_r4_spatial_payload()
    sm = SpatialMuModifierResponse.model_validate(sm_dict)
    n = len(sm.arclength_samples)
    assert len(sm.factor_values) == n
    assert len(sm.drainage_components) == n
    assert len(sm.sun_components) == n
    assert len(sm.wind_components) == n
