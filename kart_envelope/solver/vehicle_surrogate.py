"""
vehicle_surrogate.py
--------------------
Cycle-A lightweight vehicle-dynamics surrogates:
- chassis compliance/load-transfer correction
- smooth 4-wheel / 3-wheel contact-mode proxy
- distilled high-DOF runtime correction

These are conservative multiplicative scalars applied to the envelope.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.envelope.capability import CapabilityEnvelope
from kart_envelope.ingest.columns import COL_ACCEL_LAT, COL_SPEED
from kart_envelope.track.geometry import TrackGeometry

_G = 9.80665


@dataclass
class VehicleDynamicsMeta:
    """Runtime metadata for surrogate vehicle dynamics blocks."""

    enabled: bool = False
    chassis_enabled: bool = False
    contact_enabled: bool = False
    high_dof_enabled: bool = False
    chassis_scale: float = 1.0
    contact_scale: float = 1.0
    high_dof_scale: float = 1.0
    lateral_scale: float = 1.0
    drive_scale: float = 1.0
    brake_scale: float = 1.0
    three_wheel_ratio: float = 0.0
    sample_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "chassis_enabled": bool(self.chassis_enabled),
            "contact_enabled": bool(self.contact_enabled),
            "high_dof_enabled": bool(self.high_dof_enabled),
            "chassis_scale": round(float(self.chassis_scale), 4),
            "contact_scale": round(float(self.contact_scale), 4),
            "high_dof_scale": round(float(self.high_dof_scale), 4),
            "lateral_scale": round(float(self.lateral_scale), 4),
            "drive_scale": round(float(self.drive_scale), 4),
            "brake_scale": round(float(self.brake_scale), 4),
            "three_wheel_ratio": round(float(self.three_wheel_ratio), 4),
            "sample_count": int(self.sample_count),
        }


def build_vehicle_dynamics_meta(
    filtered_laps: dict[int, pd.DataFrame],
    geometry: TrackGeometry,
    config: KartEnvelopeConfig,
) -> VehicleDynamicsMeta:
    """Build runtime vehicle-surrogate scales from telemetry and geometry."""
    chassis_on = bool(config.vehicle_enable_chassis_surrogate)
    contact_on = bool(config.vehicle_enable_contact_mode)
    high_dof_on = bool(config.vehicle_enable_high_dof_surrogate)
    enabled = bool(chassis_on or contact_on or high_dof_on)

    speed, ay = _collect_speed_lat_accel(filtered_laps)
    n = int(min(len(speed), len(ay)))
    if n <= 1:
        return VehicleDynamicsMeta(
            enabled=enabled,
            chassis_enabled=chassis_on,
            contact_enabled=contact_on,
            high_dof_enabled=high_dof_on,
            sample_count=n,
        )
    speed = speed[:n]
    ay = ay[:n]
    lat_g = np.abs(ay) / _G

    chassis_scale = 1.0
    if chassis_on:
        # Compliance softens peak response when lateral load transfer rises.
        p90 = float(np.nanpercentile(lat_g, 90.0))
        gain = float(max(config.vehicle_chassis_compliance_gain, 0.0))
        chassis_scale = float(np.clip(1.0 - gain * max(0.0, p90 - 0.9), 0.88, 1.04))

    three_wheel_ratio = 0.0
    contact_scale = 1.0
    if contact_on:
        thr = float(max(config.vehicle_contact_lift_lat_threshold_g, 0.6))
        hys = float(max(config.vehicle_contact_hysteresis_g, 0.0))
        three_mask = lat_g >= (thr + 0.5 * hys)
        # If high lateral zones frequently exceed lift threshold, keep a small
        # stability penalty to avoid over-optimistic corner entry speeds.
        three_wheel_ratio = float(np.mean(three_mask))
        contact_scale = float(np.clip(1.0 - 0.08 * three_wheel_ratio, 0.90, 1.02))

    high_dof_scale = 1.0
    if high_dof_on:
        # Distilled correction proxy from curvature-weighted speed.
        curv = np.asarray(geometry.curvature_1pm, dtype=float)
        if curv.size > 2:
            k_rms = float(np.sqrt(np.mean(np.square(np.clip(curv, 0.0, None)))))
        else:
            k_rms = 0.0
        v_mean = float(np.nanmean(speed))
        lt_gain = float(max(config.vehicle_load_transfer_gain, 0.0))
        complexity = np.clip(v_mean * k_rms, 0.0, 1.5)
        high_dof_scale = float(np.clip(1.0 - lt_gain * 0.08 * complexity, 0.90, 1.03))

    combined = float(np.clip(chassis_scale * contact_scale * high_dof_scale, 0.85, 1.05))
    # Braking usually less sensitive than cornering to chassis/contact dynamics.
    brake_scale = float(np.clip(0.65 * combined + 0.35, 0.90, 1.05))

    return VehicleDynamicsMeta(
        enabled=enabled,
        chassis_enabled=chassis_on,
        contact_enabled=contact_on,
        high_dof_enabled=high_dof_on,
        chassis_scale=chassis_scale,
        contact_scale=contact_scale,
        high_dof_scale=high_dof_scale,
        lateral_scale=combined,
        drive_scale=combined,
        brake_scale=brake_scale,
        three_wheel_ratio=three_wheel_ratio,
        sample_count=n,
    )


def apply_vehicle_dynamics_to_envelope(
    envelope: CapabilityEnvelope,
    vehicle_meta: VehicleDynamicsMeta | None,
) -> CapabilityEnvelope:
    """Apply surrogate vehicle-dynamics scales to envelope."""
    if vehicle_meta is None or not vehicle_meta.enabled:
        return envelope
    return envelope.scaled(
        mu=float(vehicle_meta.lateral_scale),
        p_drive=float(vehicle_meta.drive_scale),
        b_brake=float(vehicle_meta.brake_scale),
    )


def _collect_speed_lat_accel(filtered_laps: dict[int, pd.DataFrame]) -> tuple[np.ndarray, np.ndarray]:
    speed_parts: list[np.ndarray] = []
    ay_parts: list[np.ndarray] = []
    for lap_df in filtered_laps.values():
        if COL_SPEED not in lap_df.columns:
            continue
        v = pd.to_numeric(lap_df[COL_SPEED], errors="coerce").to_numpy(dtype=float)
        ay = (
            pd.to_numeric(lap_df[COL_ACCEL_LAT], errors="coerce").to_numpy(dtype=float)
            if COL_ACCEL_LAT in lap_df.columns
            else np.zeros_like(v)
        )
        m = np.isfinite(v) & np.isfinite(ay)
        if np.any(m):
            speed_parts.append(v[m])
            ay_parts.append(ay[m])
    if not speed_parts:
        return np.array([], dtype=float), np.array([], dtype=float)
    return np.concatenate(speed_parts), np.concatenate(ay_parts)
