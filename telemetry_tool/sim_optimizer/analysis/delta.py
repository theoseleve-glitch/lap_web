"""Distance-aligned delta comparison between actual and theoretical lap."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

_MIN_SPEED_MPS = 1.0  # clamp floor to avoid div-by-zero


@dataclass
class LapDelta:
    distance_m: np.ndarray
    time_delta_s: np.ndarray         # cumulative, positive = driver slower
    speed_delta_mps: np.ndarray      # theoretical - actual (positive = driver slower)
    throttle_delta_pct: np.ndarray   # theoretical - actual
    brake_delta_pct: np.ndarray      # theoretical - actual
    steering_delta_deg: np.ndarray   # theoretical - actual
    total_time_loss_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_time_loss_s": round(self.total_time_loss_s, 3),
            "distance_m": self.distance_m.tolist(),
            "time_delta_s": [round(x, 4) for x in self.time_delta_s.tolist()],
            "speed_delta_mps": [round(x, 2) for x in self.speed_delta_mps.tolist()],
        }


def compute_lap_delta(
    actual_distance_m: np.ndarray,
    actual_speed_mps: np.ndarray,
    actual_throttle: np.ndarray,
    actual_brake: np.ndarray,
    actual_steering_deg: np.ndarray,
    theoretical_distance_m: np.ndarray,
    theoretical_speed_mps: np.ndarray,
    theoretical_throttle: np.ndarray,
    theoretical_brake: np.ndarray,
    theoretical_steering_deg: np.ndarray,
) -> LapDelta:
    """Compute distance-aligned delta between actual and theoretical.

    Algorithm:
    1. Define common distance grid (intersection of both distance ranges,
       spacing from theoretical).
    2. Interpolate actual onto common grid.
    3. Interpolate theoretical onto common grid.
    4. speed_delta = theoretical - actual (positive means driver is slower).
    5. Time delta at each step: dt_actual = ds / v_actual,
       dt_theoretical = ds / v_theoretical.
       time_delta[i] = cumsum(dt_actual - dt_theoretical) -- cumulative loss.
    6. Input deltas: theoretical - actual for throttle/brake/steering.
    7. total_time_loss = time_delta[-1].
    """
    # 1. Common distance grid — intersection of both ranges
    d_min = max(actual_distance_m[0], theoretical_distance_m[0])
    d_max = min(actual_distance_m[-1], theoretical_distance_m[-1])

    if d_max <= d_min:
        log.warning("No overlapping distance range between actual and theoretical")
        empty = np.array([])
        return LapDelta(
            distance_m=empty,
            time_delta_s=empty,
            speed_delta_mps=empty,
            throttle_delta_pct=empty,
            brake_delta_pct=empty,
            steering_delta_deg=empty,
            total_time_loss_s=0.0,
        )

    # Use theoretical spacing to build common grid
    mask = (theoretical_distance_m >= d_min) & (theoretical_distance_m <= d_max)
    common_d = theoretical_distance_m[mask].copy()

    if len(common_d) < 2:
        log.warning("Common grid has fewer than 2 points")
        empty = np.array([])
        return LapDelta(
            distance_m=empty,
            time_delta_s=empty,
            speed_delta_mps=empty,
            throttle_delta_pct=empty,
            brake_delta_pct=empty,
            steering_delta_deg=empty,
            total_time_loss_s=0.0,
        )

    # 2. Interpolate actual onto common grid
    act_speed = np.interp(common_d, actual_distance_m, actual_speed_mps)
    act_throttle = np.interp(common_d, actual_distance_m, actual_throttle)
    act_brake = np.interp(common_d, actual_distance_m, actual_brake)
    act_steer = np.interp(common_d, actual_distance_m, actual_steering_deg)

    # 3. Interpolate theoretical onto common grid
    theo_speed = np.interp(common_d, theoretical_distance_m, theoretical_speed_mps)
    theo_throttle = np.interp(common_d, theoretical_distance_m, theoretical_throttle)
    theo_brake = np.interp(common_d, theoretical_distance_m, theoretical_brake)
    theo_steer = np.interp(common_d, theoretical_distance_m, theoretical_steering_deg)

    # 4. Speed delta
    speed_delta = theo_speed - act_speed

    # 5. Cumulative time delta
    ds = np.diff(common_d)
    v_act_mid = np.maximum(0.5 * (act_speed[:-1] + act_speed[1:]), _MIN_SPEED_MPS)
    v_theo_mid = np.maximum(0.5 * (theo_speed[:-1] + theo_speed[1:]), _MIN_SPEED_MPS)

    dt_act = ds / v_act_mid
    dt_theo = ds / v_theo_mid
    cum_delta = np.concatenate(([0.0], np.cumsum(dt_act - dt_theo)))

    # 6. Input deltas
    throttle_delta = theo_throttle - act_throttle
    brake_delta = theo_brake - act_brake
    steering_delta = theo_steer - act_steer

    # 7. Total time loss
    total_loss = float(cum_delta[-1])

    return LapDelta(
        distance_m=common_d,
        time_delta_s=cum_delta,
        speed_delta_mps=speed_delta,
        throttle_delta_pct=throttle_delta,
        brake_delta_pct=brake_delta,
        steering_delta_deg=steering_delta,
        total_time_loss_s=total_loss,
    )
