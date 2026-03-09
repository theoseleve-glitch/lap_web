"""
tire_stack.py
-------------
Cycle-A tire runtime stack:
- optional Pacejka-informed utilization scaling
- optional thermal and pressure state scaling
- conservative condition/tire penalties

All outputs are multiplicative scalars that can be applied to a
CapabilityEnvelope. If disabled or data is missing, scale defaults to 1.0.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.envelope.capability import CapabilityEnvelope
from kart_envelope.envelope.pacejka import (
    CombinedPacejkaParams,
    combined_tire_scales_from_session,
    magic_formula,
)
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.ingest.columns import COL_ACCEL_LAT, COL_ACCEL_LONG, COL_SPEED
from kart_envelope.ingest.metadata import SessionMetadata


@dataclass
class TireRuntimeMeta:
    """Runtime tire metadata used for solver and reporting."""

    enabled: bool = False
    pacejka_enabled: bool = False
    thermal_enabled: bool = False
    pressure_enabled: bool = False
    pacejka_scale: float = 1.0
    thermal_scale: float = 1.0
    pressure_scale: float = 1.0
    condition_scale: float = 1.0
    camber_scale: float = 1.0
    lateral_scale: float = 1.0
    drive_scale: float = 1.0
    brake_scale: float = 1.0
    sample_count: int = 0
    final_state: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "pacejka_enabled": bool(self.pacejka_enabled),
            "thermal_enabled": bool(self.thermal_enabled),
            "pressure_enabled": bool(self.pressure_enabled),
            "pacejka_scale": round(float(self.pacejka_scale), 4),
            "thermal_scale": round(float(self.thermal_scale), 4),
            "pressure_scale": round(float(self.pressure_scale), 4),
            "condition_scale": round(float(self.condition_scale), 4),
            "camber_scale": round(float(self.camber_scale), 4),
            "lateral_scale": round(float(self.lateral_scale), 4),
            "drive_scale": round(float(self.drive_scale), 4),
            "brake_scale": round(float(self.brake_scale), 4),
            "sample_count": int(self.sample_count),
            "final_state": self.final_state or {},
        }


def build_tire_runtime_meta(
    filtered_laps: dict[int, pd.DataFrame],
    metadata: SessionMetadata,
    scalars: SessionScalars,
    config: KartEnvelopeConfig,
) -> TireRuntimeMeta:
    """Compute tire runtime scalars from session telemetry + config toggles."""
    pacejka_on = bool(config.tire_enable_pacejka)
    thermal_on = bool(config.tire_enable_thermal)
    pressure_on = bool(config.tire_enable_pressure)
    enabled = bool(pacejka_on or thermal_on or pressure_on)

    speed, ax, ay = _collect_arrays(filtered_laps)
    n = int(min(len(speed), len(ax), len(ay)))
    if n <= 1:
        return TireRuntimeMeta(
            enabled=enabled,
            pacejka_enabled=pacejka_on,
            thermal_enabled=thermal_on,
            pressure_enabled=pressure_on,
            condition_scale=_condition_scale(metadata, scalars),
        )

    speed = speed[:n]
    ax = ax[:n]
    ay = ay[:n]

    pacejka_scale = 1.0
    if pacejka_on:
        pacejka_scale = _pacejka_scale(speed, ax, ay)

    thermal_scale = 1.0
    pressure_scale = 1.0
    camber_scale = 1.0
    final_state: dict[str, float] | None = None
    if thermal_on or pressure_on:
        thermal = combined_tire_scales_from_session(
            speed_mps=speed,
            accel_long_mps2=ax,
            accel_lat_mps2=ay,
            temp_initial_c=float(config.tire_initial_temp_c),
            ambient_c=float(config.tire_ambient_temp_c),
            nominal_pressure_kpa=float(config.tire_nominal_pressure_kpa),
            temp_optimal_c=float(config.tire_temp_optimal_c),
            temp_sigma_c=float(config.tire_temp_sigma_c),
            heat_gain_coeff=float(config.tire_heat_gain_coeff),
            cool_coeff=float(config.tire_cool_coeff),
            pressure_gain_per_c_kpa=float(config.tire_pressure_gain_per_c_kpa),
            camber_deg=0.0,
            camber_sensitivity_per_deg=float(config.tire_camber_sensitivity_per_deg),
        )
        thermal_scale = float(np.clip(thermal.get("thermal_scale", 1.0), 0.55, 1.10))
        pressure_scale = float(np.clip(thermal.get("pressure_scale", 1.0), 0.80, 1.05))
        camber_scale = float(np.clip(thermal.get("camber_scale", 1.0), 0.85, 1.05))
        state = thermal.get("state")
        if isinstance(state, dict):
            final_state = {k: float(v) for k, v in state.items() if _is_num(v)}

    cond_scale = _condition_scale(metadata, scalars)
    # Combined but conservative to avoid unrealistic optimism.
    combined = pacejka_scale * thermal_scale * pressure_scale * cond_scale * camber_scale
    combined = float(np.clip(combined, 0.60, 1.08))

    # Longitudinal is usually more condition-sensitive than lateral in wet/greasy.
    lateral_scale = float(np.clip(combined, 0.60, 1.10))
    drive_scale = float(np.clip(combined * min(cond_scale, 1.0), 0.55, 1.08))
    brake_scale = float(np.clip(0.98 * combined + 0.02, 0.58, 1.10))

    return TireRuntimeMeta(
        enabled=enabled,
        pacejka_enabled=pacejka_on,
        thermal_enabled=thermal_on,
        pressure_enabled=pressure_on,
        pacejka_scale=pacejka_scale,
        thermal_scale=thermal_scale,
        pressure_scale=pressure_scale,
        condition_scale=cond_scale,
        camber_scale=camber_scale,
        lateral_scale=lateral_scale,
        drive_scale=drive_scale,
        brake_scale=brake_scale,
        sample_count=n,
        final_state=final_state,
    )


def apply_tire_runtime_to_envelope(
    envelope: CapabilityEnvelope,
    tire_meta: TireRuntimeMeta | None,
) -> CapabilityEnvelope:
    """Apply tire runtime scales to a capability envelope."""
    if tire_meta is None or not tire_meta.enabled:
        return envelope
    return envelope.scaled(
        mu=float(tire_meta.lateral_scale),
        p_drive=float(tire_meta.drive_scale),
        b_brake=float(tire_meta.brake_scale),
    )


def _collect_arrays(filtered_laps: dict[int, pd.DataFrame]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    v_parts: list[np.ndarray] = []
    ax_parts: list[np.ndarray] = []
    ay_parts: list[np.ndarray] = []
    for lap_df in filtered_laps.values():
        if COL_SPEED not in lap_df.columns:
            continue
        v = pd.to_numeric(lap_df[COL_SPEED], errors="coerce").to_numpy(dtype=float)
        ax = (
            pd.to_numeric(lap_df[COL_ACCEL_LONG], errors="coerce").to_numpy(dtype=float)
            if COL_ACCEL_LONG in lap_df.columns
            else np.zeros_like(v)
        )
        ay = (
            pd.to_numeric(lap_df[COL_ACCEL_LAT], errors="coerce").to_numpy(dtype=float)
            if COL_ACCEL_LAT in lap_df.columns
            else np.zeros_like(v)
        )
        m = np.isfinite(v) & np.isfinite(ax) & np.isfinite(ay)
        if np.any(m):
            v_parts.append(v[m])
            ax_parts.append(ax[m])
            ay_parts.append(ay[m])
    if not v_parts:
        return np.array([], dtype=float), np.array([], dtype=float), np.array([], dtype=float)
    return (
        np.concatenate(v_parts).astype(float),
        np.concatenate(ax_parts).astype(float),
        np.concatenate(ay_parts).astype(float),
    )


def _pacejka_scale(speed: np.ndarray, ax: np.ndarray, ay: np.ndarray) -> float:
    params = CombinedPacejkaParams()
    v = np.maximum(np.abs(speed), 1.0)
    slip_ratio = np.clip(ax / np.maximum(v * 8.0, 1e-6), -0.35, 0.35)
    slip_angle = np.clip(np.arctan2(ay, v), -0.45, 0.45)

    fx = np.abs(np.asarray([magic_formula(1.0, s, params.longi) for s in slip_ratio], dtype=float))
    fy = np.abs(np.asarray([magic_formula(1.0, a, params.lat) for a in slip_angle], dtype=float))
    util = np.sqrt(np.maximum(fx, 0.0) ** 2 + np.maximum(fy, 0.0) ** 2)
    if util.size == 0 or not np.isfinite(util).any():
        return 1.0
    u75 = float(np.nanpercentile(util, 75.0))
    # Utilization near 1.0 means tire was used close to limit.
    return float(np.clip(0.90 + 0.15 * u75, 0.75, 1.08))


def _condition_scale(metadata: SessionMetadata, scalars: SessionScalars) -> float:
    cond = str(metadata.condition_label or scalars.condition_label or "").strip().lower()
    tire = str(metadata.tire_type or "slick").strip().lower()
    if "wet" in cond:
        return 1.00 if "wet" in tire else 0.78
    if "damp" in cond:
        return 0.88 if "slick" in tire else 0.95
    if "greasy" in cond:
        return 0.84
    if "green" in cond:
        return 0.92
    return 1.0


def _is_num(value: object) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
