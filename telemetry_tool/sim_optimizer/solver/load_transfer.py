"""Per-wheel load calculation from accelerations and vehicle geometry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

_G = 9.80665


@dataclass
class WheelLoads:
    """Per-wheel vertical load [N]."""

    lf: float
    rf: float
    lr: float
    rr: float

    def total(self) -> float:
        return self.lf + self.rf + self.lr + self.rr

    def to_dict(self) -> dict[str, Any]:
        return {
            "lf": round(self.lf, 1),
            "rf": round(self.rf, 1),
            "lr": round(self.lr, 1),
            "rr": round(self.rr, 1),
        }


def compute_wheel_loads(
    lat_accel_mps2: float,
    long_accel_mps2: float,
    mass_kg: float,
    *,
    cg_height_m: float = 0.35,
    track_width_m: float = 1.5,
    wheelbase_m: float = 2.5,
    weight_dist_front: float = 0.50,
) -> WheelLoads:
    """Compute per-wheel vertical loads from quasi-static load transfer.

    Positive lat_accel = turning right (load transfers to left wheels).
    Positive long_accel = accelerating (load transfers to rear).

    Static load:
      front_total = mass * g * weight_dist_front
      rear_total = mass * g * (1 - weight_dist_front)

    Lateral transfer (per axle):
      delta_lat = mass * |lat_accel| * cg_height / track_width
      If lat > 0 (right turn): left wheels gain, right lose

    Longitudinal transfer:
      delta_long = mass * long_accel * cg_height / wheelbase
      Positive accel: rear gains, front loses

    Per wheel (split 50/50 front, 50/50 rear for lateral):
      lf = front_total/2 + lat_sign * delta_lat/2 - delta_long/2
      etc.

    Clamp all loads >= 0 (wheel can't pull road).
    """
    weight = mass_kg * _G
    front_total = weight * weight_dist_front
    rear_total = weight * (1.0 - weight_dist_front)

    # Lateral load transfer (total, split equally front/rear)
    delta_lat = mass_kg * lat_accel_mps2 * cg_height_m / track_width_m
    # Positive lat_accel (right turn) -> positive delta_lat -> left gains
    lat_sign = 1.0  # left wheels gain when delta_lat > 0

    # Longitudinal load transfer
    # Positive long_accel (accelerating) -> positive delta_long -> rear gains, front loses
    delta_long = mass_kg * long_accel_mps2 * cg_height_m / wheelbase_m

    lf = front_total / 2.0 + lat_sign * delta_lat / 2.0 - delta_long / 2.0
    rf = front_total / 2.0 - lat_sign * delta_lat / 2.0 - delta_long / 2.0
    lr = rear_total / 2.0 + lat_sign * delta_lat / 2.0 + delta_long / 2.0
    rr = rear_total / 2.0 - lat_sign * delta_lat / 2.0 + delta_long / 2.0

    # Clamp: wheel can't pull the road
    lf = max(0.0, lf)
    rf = max(0.0, rf)
    lr = max(0.0, lr)
    rr = max(0.0, rr)

    return WheelLoads(lf=lf, rf=rf, lr=lr, rr=rr)
