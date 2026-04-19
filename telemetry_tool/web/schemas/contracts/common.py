"""Shared primitives used across Session/Coaching/Optimizer contracts."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceLiteral(str, Enum):
    """Engine family that produced this session."""
    REAL_LIFE = "real_life"   # RaceChrono / RaceBox GPS+IMU
    IRACING = "iracing"       # iRacing IBT
    AC = "ac"                 # Assetto Corsa CSV/binary
    # Extend carefully — adding a value is a contract change.


class DriverRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    driver_id: int
    name: str


class TrackRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    track_id: int
    name: str
    layout: str | None = None


class VehicleRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    vehicle_id: int | None = None
    vehicle_class: str | None = None
    model: str | None = None


class TrajectorySample(BaseModel):
    """A single sample along the driven trajectory.

    The full trajectory array is typically stored in a sidecar Parquet
    file; the contract carries a reference + summary, not the full array.
    """
    model_config = ConfigDict(frozen=True)
    t_s: float = Field(..., description="Elapsed time since session start, seconds")
    s_m: float = Field(..., description="Distance travelled, metres")
    speed_ms: float = Field(..., description="Longitudinal speed, m/s")
    lat: float | None = None
    lon: float | None = None
    lat_g: float | None = None
    lon_g: float | None = None


class LapSummary(BaseModel):
    """Per-lap summary. Detailed per-sample data lives in sidecar storage."""
    model_config = ConfigDict(frozen=True)
    lap_number: int
    lap_time_s: float | None = Field(None, description="None for incomplete laps")
    is_valid: bool = True
    is_best: bool = False
    flags: list[str] = Field(default_factory=list)


class Event(BaseModel):
    """A detected incident or coaching-relevant moment during the session."""
    model_config = ConfigDict(frozen=True)
    event_type: str  # free-form for now; narrowed in W6
    lap_number: int | None = None
    t_s: float | None = None
    s_m: float | None = None
    severity: str | None = None
    detector: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class Scores(BaseModel):
    """Top-line session scoring. Each dimension is /100."""
    model_config = ConfigDict(frozen=True)
    pace: float
    consistency: float
    execution: float
    robustness: float
    overall: float

    @field_validator("pace", "consistency", "execution", "robustness", "overall")
    @classmethod
    def _range_0_100(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError(f"score must be in [0, 100], got {v}")
        return v


class SidecarRef(BaseModel):
    """Pointer to a raw-channel Parquet sidecar kept outside the contract."""
    model_config = ConfigDict(frozen=True)
    object_key: str
    format: str = "parquet"
    sha256: str | None = None
    size_bytes: int | None = None
