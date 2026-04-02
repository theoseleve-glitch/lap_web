"""Reconstruct driver inputs (throttle, brake, steering) from a theoretical speed profile."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from kart_envelope.track.geometry import TrackGeometry
from telemetry_tool.sim_optimizer.param_id.vehicle_model import VehicleModel
from telemetry_tool.sim_optimizer.solver.qss_enhanced import SimTheoreticalResult

_G = 9.80665


@dataclass
class TheoreticalInputTrace:
    """Reconstructed driver inputs at each distance step."""

    distance_m: np.ndarray
    speed_mps: np.ndarray
    throttle_pct: np.ndarray      # 0.0-1.0
    brake_pct: np.ndarray         # 0.0-1.0
    steering_deg: np.ndarray      # signed, degrees
    gear: np.ndarray              # integer
    limit_type: np.ndarray        # object array: "traction"|"braking"|"cornering"

    def to_dict(self) -> dict[str, Any]:
        return {
            "distance_m": self.distance_m.tolist(),
            "speed_mps": self.speed_mps.tolist(),
            "throttle_pct": self.throttle_pct.tolist(),
            "brake_pct": self.brake_pct.tolist(),
            "steering_deg": self.steering_deg.tolist(),
            "gear": self.gear.tolist(),
            "limit_type": self.limit_type.tolist(),
        }


def reconstruct_inputs(
    theoretical: SimTheoreticalResult,
    vehicle: VehicleModel,
    geometry: TrackGeometry,
    *,
    fuel_level_l: float = 30.0,
    wheelbase_m: float = 2.5,
) -> TheoreticalInputTrace:
    """Reconstruct throttle/brake/steering from a solved speed profile.

    Parameters
    ----------
    theoretical : SimTheoreticalResult
        Output of the QSS solver (speed, accel, gear, limit flags).
    vehicle : VehicleModel
        Full vehicle model with inverse methods on sub-models.
    geometry : TrackGeometry
        Track curvature and distance grid.
    fuel_level_l : float
        Fuel level for mass calculation.
    wheelbase_m : float
        Wheelbase in metres (for Ackermann steering geometry).

    Returns
    -------
    TheoreticalInputTrace
    """
    n = len(theoretical.distance_m)
    mass = vehicle.total_mass_kg(fuel_level_l)

    throttle = np.zeros(n)
    brake = np.zeros(n)
    steering = np.zeros(n)
    gear = theoretical.gear_profile.copy()
    limit_type = np.empty(n, dtype=object)

    # Use signed curvature if available, otherwise unsigned
    has_signed = geometry.has_signed_curvature
    kappa_unsigned = geometry.curvature_1pm
    kappa_signed = geometry.signed_curvature_1pm if has_signed else kappa_unsigned

    for i in range(n):
        v = theoretical.speed_profile_mps[i]
        a = theoretical.accel_profile_mps2[i]
        kappa = kappa_unsigned[i]
        g = int(gear[i])

        # --- Steering ---
        ackermann = math.atan(kappa * wheelbase_m)
        a_lat = v * v * kappa
        fz_per_wheel = mass * _G / 4.0
        f_lat_per_wheel = a_lat * mass / 4.0
        slip_angle = vehicle.tyre.inverse_lateral_slip(f_lat_per_wheel, fz_per_wheel)
        steer_unsigned = math.degrees(ackermann + slip_angle)

        # Apply turn direction from signed curvature
        if has_signed:
            sign = 1.0 if kappa_signed[i] >= 0 else -1.0
        else:
            sign = 1.0
        steering[i] = sign * steer_unsigned

        # --- Throttle / Brake ---
        drag = vehicle.aero.drag_accel(v, mass)
        rr = vehicle.powertrain.rolling_resistance_accel(v)

        if a >= 0:
            # Accelerating: engine must overcome drag + rr + produce net accel
            a_wheel = a + drag + rr
            throttle[i] = float(np.clip(
                vehicle.powertrain.inverse_throttle(a_wheel, v, g, mass), 0.0, 1.0
            ))
            brake[i] = 0.0
        else:
            # Braking: drag and rr already help decelerate
            a_brake = abs(a) - drag - rr
            if a_brake > 0:
                brake[i] = float(np.clip(
                    vehicle.brake.inverse_brake_pct(a_brake, v), 0.0, 1.0
                ))
            else:
                brake[i] = 0.0
            throttle[i] = 0.0

        # --- Limit type ---
        if theoretical.cornering_limited[i]:
            limit_type[i] = "cornering"
        elif theoretical.braking_limited[i]:
            limit_type[i] = "braking"
        else:
            limit_type[i] = "traction"

    return TheoreticalInputTrace(
        distance_m=theoretical.distance_m.copy(),
        speed_mps=theoretical.speed_profile_mps.copy(),
        throttle_pct=throttle,
        brake_pct=brake,
        steering_deg=steering,
        gear=gear,
        limit_type=limit_type,
    )
