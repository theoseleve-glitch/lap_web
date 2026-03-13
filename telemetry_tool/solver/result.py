# telemetry_tool/solver/result.py
"""OCP solver result dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class TheoreticalResult:
    """Result from the optimal control solver."""

    lap_time_s: float
    speed_profile: np.ndarray       # speed at each node (m/s)
    distance_profile: np.ndarray    # distance at each node (m)
    a_long_profile: np.ndarray      # longitudinal accel (m/s^2)
    a_lat_profile: np.ndarray       # lateral accel (m/s^2)
    corner_times: list[dict]        # per-corner breakdown
    vehicle_params_used: dict       # snapshot of params
    calibration: dict               # calibration metadata
    solver_meta: dict               # IPOPT convergence info
    tier: int                       # data tier (1, 2, or 3)
    converged: bool = True

    @staticmethod
    def _safe_float(v: float, default: float = 0.0) -> float:
        """Convert to float, replacing NaN/Inf with default (JSON-safe)."""
        import math
        f = float(v)
        return f if math.isfinite(f) else default

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage in analysis_json (NaN-safe for valid JSON)."""
        sf = self._safe_float
        speed_profile_list = [
            {
                "distance_m": round(sf(self.distance_profile[i]), 2),
                "speed_mps": round(sf(self.speed_profile[i]), 3),
                "a_long": round(sf(self.a_long_profile[i]), 3),
                "a_lat": round(sf(self.a_lat_profile[i]), 3),
            }
            for i in range(len(self.speed_profile))
        ]
        return {
            "lap_time_s": round(sf(self.lap_time_s), 3),
            "speed_profile": speed_profile_list,
            "corner_times": self.corner_times,
            "vehicle_params_used": self.vehicle_params_used,
            "calibration": self.calibration,
            "solver_meta": self.solver_meta,
            "tier": self.tier,
            "converged": self.converged,
        }
