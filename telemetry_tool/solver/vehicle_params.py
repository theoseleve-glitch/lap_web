"""OCP vehicle parameters — physical constants for the optimal control solver.

Provides ``OCPVehicleParams`` dataclass and ``params_for_class()`` factory.
All values are SI units unless noted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Class-level default tables
# ---------------------------------------------------------------------------

_KART_DEFAULTS: dict[str, Any] = {
    "mass": 160.0,          # kg (driver + kart)
    "h_cg": 0.25,           # m  centre-of-gravity height
    "wheelbase": 1.05,      # m
    "track_width": 1.2,     # m
    "A": 0.6,               # m² frontal area
    "Cd": 0.5,              # drag coefficient
    "Cl": 0.0,              # lift coefficient (no downforce)
    "rho": 1.225,           # kg/m³ air density (ISA sea level)
    "Cr": 0.015,            # rolling resistance coefficient
    "mu_ref": 1.4,          # reference friction coefficient
    "load_sensitivity": -0.08,   # d(mu)/d(Fz_norm)  [1/kN]
    "P_max": 18_000.0,      # W  peak engine power
    "F_brake_max": 3_500.0, # N  max braking force
    "F_drive_max": 1_200.0, # N  max drive force at wheel
}

_CAR_DEFAULTS: dict[str, Any] = {
    "mass": 1200.0,
    "h_cg": 0.45,
    "wheelbase": 2.6,
    "track_width": 1.55,
    "A": 2.0,
    "Cd": 0.35,
    "Cl": 0.1,
    "rho": 1.225,
    "Cr": 0.012,
    "mu_ref": 1.1,
    "load_sensitivity": -0.15,
    "P_max": 150_000.0,
    "F_brake_max": 15_000.0,
    "F_drive_max": 8_000.0,
}

_FORMULA_DEFAULTS: dict[str, Any] = {
    "mass": 740.0,
    "h_cg": 0.30,
    "wheelbase": 3.6,
    "track_width": 1.8,
    "A": 1.5,
    "Cd": 0.8,
    "Cl": 2.5,
    "rho": 1.225,
    "Cr": 0.010,
    "mu_ref": 1.8,
    "load_sensitivity": -0.10,
    "P_max": 600_000.0,
    "F_brake_max": 30_000.0,
    "F_drive_max": 12_000.0,
}

_GT_DEFAULTS: dict[str, Any] = {
    "mass": 1300.0,         # GT3-class with driver
    "h_cg": 0.42,
    "wheelbase": 2.7,
    "track_width": 1.65,
    "A": 2.1,
    "Cd": 0.40,
    "Cl": 1.2,              # significant aero but less than formula
    "rho": 1.225,
    "Cr": 0.010,
    "mu_ref": 1.35,          # slick compound, wide tires
    "load_sensitivity": -0.12,
    "P_max": 400_000.0,     # ~540 hp typical GT3
    "F_brake_max": 25_000.0,
    "F_drive_max": 10_000.0,
}

_TOURING_DEFAULTS: dict[str, Any] = {
    "mass": 1285.0,         # TCR/BTCC-class with ballast
    "h_cg": 0.42,
    "wheelbase": 2.65,
    "track_width": 1.55,
    "A": 2.0,
    "Cd": 0.38,
    "Cl": 0.4,              # modest aero package
    "rho": 1.225,
    "Cr": 0.012,
    "mu_ref": 1.2,           # control slick, narrower than GT3
    "load_sensitivity": -0.12,
    "P_max": 260_000.0,     # ~350 hp TCR-class
    "F_brake_max": 18_000.0,
    "F_drive_max": 8_500.0,
}

# Map VehicleClass enum value strings to default tables
_CLASS_MAP: dict[str, dict[str, Any]] = {
    "kart": _KART_DEFAULTS,
    "formula": _FORMULA_DEFAULTS,
    "gt": _GT_DEFAULTS,
    "touring": _TOURING_DEFAULTS,
    "road_car": _CAR_DEFAULTS,
    # Aliases
    "car": _CAR_DEFAULTS,
}


# ---------------------------------------------------------------------------
# OCPVehicleParams dataclass
# ---------------------------------------------------------------------------


@dataclass
class OCPVehicleParams:
    """Physical parameters consumed by the OCP lap solver.

    All units SI (kg, m, N, W, kg/m³).
    """

    mass: float             # kg
    h_cg: float             # m  CG height
    wheelbase: float        # m
    track_width: float      # m  (average front/rear)
    A: float                # m² frontal area
    Cd: float               # aerodynamic drag coefficient
    Cl: float               # aerodynamic lift coefficient (positive = downforce)
    rho: float              # kg/m³ air density
    Cr: float               # rolling resistance coefficient
    mu_ref: float           # reference peak friction coefficient
    load_sensitivity: float # d(mu)/d(Fz_norm)  [1/kN]  (negative → degrades with load)
    P_max: float            # W  peak power at wheel
    F_brake_max: float      # N  maximum total braking force
    F_drive_max: float      # N  maximum total drive force

    # -----------------------------------------------------------------
    # Class-methods
    # -----------------------------------------------------------------

    @classmethod
    def from_defaults(cls, defaults: dict[str, Any]) -> "OCPVehicleParams":
        """Construct from a defaults dictionary."""
        return cls(**defaults)

    @classmethod
    def from_vehicle_params(cls, vp: Any) -> "OCPVehicleParams":
        """Construct from a ``vehicle_model.VehicleParameters`` instance.

        Merges the measured/estimated values from the classifier output with
        the appropriate class-level defaults for fields not estimated.
        """
        class_str = _map_vehicle_class(vp.vehicle_class)
        base = dict(_CLASS_MAP.get(class_str, _CAR_DEFAULTS))

        # Override with measured values where available
        if vp.estimated_mass_kg is not None:
            base["mass"] = float(vp.estimated_mass_kg)

        base["Cr"] = float(vp.rolling_resistance_est)
        base["mu_ref"] = float(vp.peak_lateral_g)

        # Aerodynamic drag: aero_drag_factor_est = Cd·A·rho/(2·m)
        # We recover Cd·A from the factor and the mass.
        if vp.aero_drag_factor_est > 0.0:
            # Cd·A = factor * 2 * m / rho
            CdA = vp.aero_drag_factor_est * 2.0 * base["mass"] / base["rho"]
            base["Cd"] = CdA / base["A"]

        if vp.has_downforce and hasattr(vp, "downforce_coeff_est") and vp.downforce_coeff_est > 0.0:
            ClA = vp.downforce_coeff_est * 2.0 * base["mass"] / base["rho"]
            base["Cl"] = ClA / base["A"]
        elif not vp.has_downforce:
            base["Cl"] = 0.0

        logger.debug(
            "OCPVehicleParams.from_vehicle_params: class=%s mass=%.1f mu_ref=%.2f",
            class_str, base["mass"], base["mu_ref"],
        )
        return cls(**base)

    # -----------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------

    @property
    def Fz_static_per_axle(self) -> float:
        """Static normal force per axle [N] (assumes 50/50 distribution)."""
        return 0.5 * self.mass * 9.80665

    # -----------------------------------------------------------------
    # Serialisation
    # -----------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "mass": self.mass,
            "h_cg": self.h_cg,
            "wheelbase": self.wheelbase,
            "track_width": self.track_width,
            "A": self.A,
            "Cd": self.Cd,
            "Cl": self.Cl,
            "rho": self.rho,
            "Cr": self.Cr,
            "mu_ref": self.mu_ref,
            "load_sensitivity": self.load_sensitivity,
            "P_max": self.P_max,
            "F_brake_max": self.F_brake_max,
            "F_drive_max": self.F_drive_max,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _map_vehicle_class(vehicle_class: Any) -> str:
    """Return a lowercase string key for a VehicleClass enum value or string."""
    if hasattr(vehicle_class, "value"):
        return vehicle_class.value.lower()
    return str(vehicle_class).lower()


def params_for_class(class_str: str) -> OCPVehicleParams:
    """Return ``OCPVehicleParams`` using built-in defaults for *class_str*.

    Falls back to car defaults for unrecognised strings.

    Parameters
    ----------
    class_str:
        One of ``"kart"``, ``"car"``, ``"formula"``, ``"gt"``, ``"touring"``,
        ``"road_car"``.  Case-insensitive.
    """
    key = class_str.lower()
    defaults = _CLASS_MAP.get(key, _CAR_DEFAULTS)
    return OCPVehicleParams.from_defaults(defaults)
