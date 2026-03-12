"""Load-sensitive tire model with friction ellipse.

Implements:
  mu(Fz) = mu_ref * (Fz / Fz_ref) ^ sensitivity
  Friction ellipse: (Fx/Fx_max)^2 + (Fy/Fy_max)^2 <= 1
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class LoadSensitiveTire:
    mu_ref: float
    Fz_ref: float
    sensitivity: float

    def mu(self, Fz: float) -> float:
        if Fz <= 0 or self.Fz_ref <= 0:
            return 0.0
        return self.mu_ref * (Fz / self.Fz_ref) ** self.sensitivity

    def max_force(self, Fz: float) -> float:
        if Fz <= 0:
            return 0.0
        return self.mu(Fz) * Fz

    def ellipse_utilisation(self, Fx: float, Fy: float, Fz: float) -> float:
        F_max = self.max_force(Fz)
        if F_max <= 0:
            return float("inf") if (abs(Fx) + abs(Fy)) > 0 else 0.0
        return math.sqrt((Fx / F_max) ** 2 + (Fy / F_max) ** 2)

    def a_max(self, Fz: float, mass: float) -> float:
        if mass <= 0:
            return 0.0
        return self.max_force(Fz) / mass
