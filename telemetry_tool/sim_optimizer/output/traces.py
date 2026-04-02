"""Serialize theoretical traces for API/frontend consumption."""
from __future__ import annotations

from typing import Any

import numpy as np


def _to_list(arr: np.ndarray | list, decimals: int = 3) -> list:
    """Convert numpy array to rounded Python list."""
    a = np.asarray(arr, dtype=float)
    return [round(float(v), decimals) for v in a]


def serialize_theoretical_trace(trace) -> dict[str, Any]:
    """Convert TheoreticalInputTrace to JSON-serializable dict.

    numpy arrays -> lists, round floats to 3 decimals.
    Keys: distance_m, speed_mps, speed_kph, throttle_pct, brake_pct,
          steering_deg, gear, limit_type
    """
    speed_mps = np.asarray(trace.speed_mps, dtype=float)
    return {
        "distance_m": _to_list(trace.distance_m),
        "speed_mps": _to_list(speed_mps),
        "speed_kph": _to_list(speed_mps * 3.6),
        "throttle_pct": _to_list(trace.throttle_pct),
        "brake_pct": _to_list(trace.brake_pct),
        "steering_deg": _to_list(trace.steering_deg),
        "gear": [int(g) for g in np.asarray(trace.gear)],
        "limit_type": [int(lt) for lt in np.asarray(trace.limit_type)],
    }


def serialize_lap_delta(delta) -> dict[str, Any]:
    """Convert LapDelta to JSON-serializable dict.

    Keys: distance_m, time_delta_s, speed_delta_mps, throttle_delta_pct,
          brake_delta_pct, steering_delta_deg, total_time_loss_s
    """
    return {
        "distance_m": _to_list(delta.distance_m),
        "time_delta_s": _to_list(delta.time_delta_s),
        "speed_delta_mps": _to_list(delta.speed_delta_mps),
        "throttle_delta_pct": _to_list(delta.throttle_delta_pct),
        "brake_delta_pct": _to_list(delta.brake_delta_pct),
        "steering_delta_deg": _to_list(delta.steering_delta_deg),
        "total_time_loss_s": round(float(delta.total_time_loss_s), 3),
    }
