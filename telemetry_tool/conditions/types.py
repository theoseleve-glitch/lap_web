"""Dataclasses for the conditions engine.

Per ``LAP_V1_CONDITIONS_ENGINE_SPEC.md`` §8. These are pure schema:
WeatherCondition is fully implemented (Day 11), SpatialMuModifier is
schema-only (Day 12 fills in the fields), SessionInputs is the minimal
input contract for classify_conditions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass(frozen=True)
class SessionInputs:
    """Minimum input contract for :func:`classify_conditions`.

    The classifier needs only the session start time + (optional) user
    metadata to do its job. Lat/lon come from track_id via the gt-geojson
    centroid resolver (see ``track_centroid.py``).

    ``user_condition`` is the value of ``meta["condition"]`` from the
    session metadata JSON file when present. Accepted values per spec
    §8: ``"dry" | "damp" | "wet" | "greasy"``. ``None`` means classify
    from weather inputs.
    """

    started_at_utc: datetime
    user_condition: str | None = None


@dataclass(frozen=True)
class SpatialMuModifier:
    """Per-arclength spatial μ-modifier (spec §7).

    SCHEMA ONLY in Day 11. Day 12 will populate factor_values + the
    three component arrays + the session-time solar/wind metadata.
    """

    arclength_samples: list[float]
    factor_values: list[float]
    drainage_components: list[float]
    sun_components: list[float]
    wind_components: list[float]
    sun_altitude_deg: float
    sun_azimuth_deg: float
    wind_direction_deg: float
    wind_speed_kmh: float
    mesh_source: Literal["hand_traced", "data_derived", "multihead"]
    spatial_version: str = "spatial-v1.0"


@dataclass(frozen=True)
class WeatherCondition:
    """Scalar conditions output (spec §8). The Day-11 deliverable.

    Field order mirrors the spec verbatim:

    Core scalar (§5/§6)
        label, mu_scale, confidence

    Derived diagnostics (§4 D-metrics)
        track_temp_estimate_c, water_film_estimate, hours_since_rain,
        days_since_significant_rain, drying_rate_estimate

    Explainability (§5, §2)
        dominant_factor, rationale, source

    Spatial layer (§7) — Day 12; Day 11 always sets ``None``
        spatial_modifier

    Debugging
        raw_inputs, classifier_version

    ``raw_inputs`` carries the entire P1-P10 + D1-D5 dict + ``winddirection_10m``
    so any classifier decision is reproducible from the persisted output.
    """

    # Core scalar output (§5/§6)
    label: Literal["dry", "damp", "wet", "greasy"]
    mu_scale: float
    confidence: float

    # Derived diagnostics
    track_temp_estimate_c: float | None
    water_film_estimate: Literal["none", "thin", "thick"] | None
    hours_since_rain: float | None
    days_since_significant_rain: int | None
    drying_rate_estimate: float | None

    # Explainability
    dominant_factor: str
    rationale: str
    source: Literal["weather", "user", "ml_fallback"]

    # Spatial layer (Day 12 fills; Day 11 always None)
    spatial_modifier: Optional[SpatialMuModifier] = None

    # Debugging
    raw_inputs: dict = field(default_factory=dict)
    classifier_version: str = "weather-v1.0"

    def to_dict(self) -> dict:
        """JSON-serializable view for analysis-JSON persistence.

        Used by the orchestrator integration (Day 11 Phase E2). Datetimes
        in raw_inputs are NOT auto-converted; callers must pass primitive
        types into raw_inputs.
        """
        from dataclasses import asdict
        out = asdict(self)
        # spatial_modifier may be None on Day 11; field-by-field is fine.
        return out
