"""Composite vehicle model assembling all 6 sub-models for QSS solving."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from telemetry_tool.sim_optimizer.param_id.aero_model import AeroModel
from telemetry_tool.sim_optimizer.param_id.brake_model import BrakeModel
from telemetry_tool.sim_optimizer.param_id.mass_model import MassModel
from telemetry_tool.sim_optimizer.param_id.powertrain_model import PowertrainModel
from telemetry_tool.sim_optimizer.param_id.suspension_model import SuspensionModel
from telemetry_tool.sim_optimizer.param_id.tyre_model import TyreModel

_G = 9.80665


@dataclass
class VehicleModel:
    """Full vehicle model combining tyre, aero, powertrain, brake,
    suspension and mass sub-models.

    Provides grip-envelope queries used by the QSS lap-time solver and
    FrictionLike compatibility for the kart_envelope solver.
    """

    tyre: TyreModel
    aero: AeroModel
    powertrain: PowertrainModel
    brake: BrakeModel
    suspension: SuspensionModel
    mass: MassModel
    p_combined: float = 1.6  # combined-slip p-norm exponent

    # ------------------------------------------------------------------
    # Mass delegation
    # ------------------------------------------------------------------

    def total_mass_kg(self, fuel_level_l: float = 30.0) -> float:
        """Delegate to mass model."""
        return self.mass.total_mass_kg(fuel_level_l)

    # ------------------------------------------------------------------
    # Single-axis limits (returned in m/s^2, NOT g)
    # ------------------------------------------------------------------

    def max_lateral_g(self, speed_mps: float, fuel_level_l: float = 30.0) -> float:
        """Maximum lateral acceleration (m/s^2) at *speed_mps*."""
        m = self.total_mass_kg(fuel_level_l)
        aero_factor = self.aero.downforce_load_factor(speed_mps, m)
        fz_total = m * _G * aero_factor
        fz_per_wheel = fz_total / 4.0
        f_lat_total = 4.0 * self.tyre.max_lateral_force(fz_per_wheel)
        return f_lat_total / m

    def max_traction_g(
        self,
        speed_mps: float,
        gear: int,
        fuel_level_l: float = 30.0,
    ) -> float:
        """Maximum forward acceleration (m/s^2) at *speed_mps* in *gear*.

        Returns ``min(tyre_limit, power_limit) - drag - rr``, clamped >= 0.
        """
        m = self.total_mass_kg(fuel_level_l)
        aero_factor = self.aero.downforce_load_factor(speed_mps, m)
        fz_total = m * _G * aero_factor
        fz_per_wheel = fz_total / 4.0
        tyre_limit = 4.0 * self.tyre.max_longitudinal_force(fz_per_wheel) / m
        power_limit = self.powertrain.max_drive_accel(speed_mps, gear, m)
        drag = self.aero.drag_accel(speed_mps, m)
        rr = self.powertrain.rolling_resistance_accel(speed_mps)
        return max(min(tyre_limit, power_limit) - drag - rr, 0.0)

    def max_braking_g(self, speed_mps: float, fuel_level_l: float = 30.0) -> float:
        """Maximum braking deceleration (m/s^2, positive value).

        Drag and rolling resistance *assist* braking, so they are added.
        """
        m = self.total_mass_kg(fuel_level_l)
        aero_factor = self.aero.downforce_load_factor(speed_mps, m)
        fz_total = m * _G * aero_factor
        fz_per_wheel = fz_total / 4.0
        tyre_limit = 4.0 * self.tyre.max_longitudinal_force(fz_per_wheel) / m
        brake_limit = self.brake.max_braking_decel(speed_mps)
        drag = self.aero.drag_accel(speed_mps, m)
        rr = self.powertrain.rolling_resistance_accel(speed_mps)
        return min(tyre_limit, brake_limit) + drag + rr

    # ------------------------------------------------------------------
    # Combined grip envelope
    # ------------------------------------------------------------------

    def combined_limit(
        self,
        ax: float,
        ay: float,
        speed_mps: float,
        fuel_level_l: float = 30.0,
    ) -> bool:
        """Return *True* if (ax, ay) is within the grip envelope.

        Uses a p-norm friction ellipse:
        ``(|ax|/ax_max)^p + (|ay|/ay_max)^p <= 1``
        """
        if ax >= 0:
            ax_max = self.max_traction_g(speed_mps, gear=3, fuel_level_l=fuel_level_l)
        else:
            ax_max = self.max_braking_g(speed_mps, fuel_level_l=fuel_level_l)

        ay_max = self.max_lateral_g(speed_mps, fuel_level_l=fuel_level_l)

        if ax_max <= 0 or ay_max <= 0:
            return False

        p = self.p_combined
        utilization = (abs(ax) / ax_max) ** p + (abs(ay) / ay_max) ** p
        return utilization <= 1.0

    # ------------------------------------------------------------------
    # FrictionLike compatibility (kart_envelope QSS solver)
    # ------------------------------------------------------------------

    def max_cornering_speed(self, curvature: float) -> float:
        """Maximum speed through a corner of given *curvature* (1/m).

        If curvature <= 0 returns 100.0 (straight).
        """
        if curvature <= 0.0:
            return 100.0
        ay_max = self.max_lateral_g(50.0)  # seed at 50 m/s
        v = math.sqrt(ay_max / curvature)
        return min(v, 100.0)

    def max_longitudinal_accel(
        self,
        speed: float,
        a_lat: float,
        braking: bool = False,
    ) -> float:
        """Combined-slip limited longitudinal acceleration.

        Reduces available longitudinal grip by the fraction of lateral
        grip already consumed, using the p-norm model.
        """
        ay_max = self.max_lateral_g(speed)
        if ay_max <= 0:
            return 0.0

        lat_ratio = min(abs(a_lat) / ay_max, 0.99)
        p = self.p_combined
        remaining = max(1.0 - lat_ratio ** p, 0.0)
        fraction = remaining ** (1.0 / p)

        if braking:
            return self.max_braking_g(speed) * fraction
        return self.max_traction_g(speed, gear=3) * fraction

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Nest all sub-model dicts plus *p_combined*."""
        return {
            "tyre": self.tyre.to_dict(),
            "aero": self.aero.to_dict(),
            "powertrain": self.powertrain.to_dict(),
            "brake": self.brake.to_dict(),
            "suspension": self.suspension.to_dict(),
            "mass": self.mass.to_dict(),
            "p_combined": self.p_combined,
        }
