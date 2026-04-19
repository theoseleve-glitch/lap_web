"""Aerodynamic drag & downforce identification from coast-down data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

_G = 9.80665


@dataclass
class AeroModel:
    """Identified aerodynamic parameters."""

    cda: float  # drag area m^2
    cla: float  # downforce area m^2
    air_density: float  # kg/m^3
    source: str = "identified"

    # ------------------------------------------------------------------
    def drag_accel(self, speed_mps: float, mass_kg: float) -> float:
        """Deceleration due to aerodynamic drag (m/s^2).

        ``0.5 * rho * CdA * v^2 / m``
        """
        return 0.5 * self.air_density * self.cda * speed_mps ** 2 / mass_kg

    def downforce_load_factor(self, speed_mps: float, mass_kg: float) -> float:
        """Normal-force multiplier from downforce.

        ``1 + (0.5 * rho * ClA * v^2) / (m * g)``

        Returns 1.0 when *cla* <= 0.
        """
        if self.cla <= 0.0:
            return 1.0
        return 1.0 + 0.5 * self.air_density * self.cla * speed_mps ** 2 / (
            mass_kg * _G
        )

    def clamped(self, config) -> AeroModel:
        """Return a copy with *cda* / *cla* clipped to *config* ranges."""
        return AeroModel(
            cda=float(np.clip(self.cda, config.aero_cda_clamp_lo, config.aero_cda_clamp_hi)),
            cla=float(np.clip(self.cla, config.aero_cla_clamp_lo, config.aero_cla_clamp_hi)),
            air_density=self.air_density,
            source=self.source,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cda": self.cda,
            "cla": self.cla,
            "air_density": self.air_density,
            "source": self.source,
        }


# ======================================================================
# Identification
# ======================================================================

def identify_aero_model(
    *,
    speed_mps: np.ndarray,
    long_accel: np.ndarray,
    throttle: np.ndarray,
    brake: np.ndarray,
    curvature: np.ndarray,
    air_density: np.ndarray,
    car_dist_ahead: np.ndarray,
    mass_kg: float,
    config,
) -> AeroModel:
    """Identify CdA from coast-down segments via least-squares.

    Coast-down criteria (all must hold):
        - throttle <= ``config.aero_coastdown_throttle_max``
        - brake <= ``config.aero_coastdown_brake_max``
        - |curvature| <= ``config.aero_coastdown_curvature_max``
        - car_dist_ahead >= ``config.aero_draft_distance_m``
        - speed > 10 m/s

    If fewer than 20 coast-down points exist the function returns
    default values from *config*.  After filtering for physically
    valid regression inputs (positive drag residual and positive
    regressor), at least 10 points are required; otherwise defaults
    are returned.
    """
    rho = float(np.median(air_density))

    # -- default model ------------------------------------------------
    default = AeroModel(
        cda=config.aero_cda_default,
        cla=config.aero_cla_default,
        air_density=rho,
        source="default",
    )

    # -- coast-down mask ----------------------------------------------
    mask = (
        (throttle <= config.aero_coastdown_throttle_max)
        & (brake <= config.aero_coastdown_brake_max)
        & (np.abs(curvature) <= config.aero_coastdown_curvature_max)
        & (car_dist_ahead >= config.aero_draft_distance_m)
        & (speed_mps > 10.0)
    )

    if mask.sum() < 20:
        return default

    v = speed_mps[mask]
    a = long_accel[mask]

    # Rolling-resistance deceleration subtracted from observed decel
    rr = config.powertrain_rr_c0  # simplified (c1*v term negligible)
    y = -a - rr * _G  # net aero drag deceleration
    x = 0.5 * rho * v ** 2 / mass_kg  # regressor: 0.5*rho*v^2/m

    # Keep only physically valid pairs (positive drag residual & regressor)
    valid = (y > 0) & (x > 0)
    if valid.sum() < 10:
        return default

    x = x[valid]
    y = y[valid]

    # OLS through origin: CdA = sum(x*y) / sum(x^2)
    cda_fit = float(np.sum(x * y) / np.sum(x * x))

    model = AeroModel(
        cda=cda_fit,
        cla=config.aero_cla_default,  # no downforce identification yet
        air_density=rho,
        source="identified",
    )
    return model.clamped(config)
