"""Setup-to-physics mapping -- translates car setup changes into
VehicleParams modifications.

Maps high-level setup parameters (wing angles, spring rates, camber,
pressures, etc.) to the low-level physics model parameters used by
the OCP solver.
"""
from __future__ import annotations

import copy
import logging

from telemetry_tool.lap_oracle.config import (
    PacejkaParams,
    SetupParams,
    VehicleParams,
)

logger = logging.getLogger(__name__)

# -- Sensitivity coefficients ----------------------------------------------
# These are simplified linear sensitivities.  A real model would use
# lookup tables or non-linear curves from wind-tunnel / sim data.

# Wing angle -> aero coefficients (per degree of angle change)
_CLA_PER_WING_DEG = 0.05   # downforce coefficient per degree
_CDA_PER_WING_DEG = 0.008  # drag coefficient per degree

# Camber -> lateral tyre grip (D parameter of Pacejka)
# Increasing negative camber improves lateral grip up to a point
_D_LAT_PER_CAMBER_DEG = 0.005

# Tyre pressure -> lateral stiffness (B parameter of Pacejka)
# Lower pressure = softer tyre = lower B (less sharp response)
_B_LAT_PER_PSI = 0.02

# Reference setup values for delta calculation
_REF_FRONT_WING = 5.0
_REF_REAR_WING = 5.0
_REF_FRONT_CAMBER = -3.0
_REF_REAR_CAMBER = -1.5
_REF_FRONT_PRESSURE = 26.0
_REF_REAR_PRESSURE = 25.0


def apply_setup_delta(
    vehicle: VehicleParams,
    setup: SetupParams,
) -> VehicleParams:
    """Apply setup changes to a vehicle model, returning a new instance.

    Modifies aero coefficients from wing angles, tyre grip from camber,
    and tyre stiffness from pressures.  Spring rates, ARBs, toe, brake
    bias, and differential are acknowledged but do not directly affect
    the current simplified physics model.

    Parameters
    ----------
    vehicle : VehicleParams
        Base vehicle model.
    setup : SetupParams
        Setup to apply.

    Returns
    -------
    VehicleParams
        New vehicle with modified physics parameters.
    """
    # Deep copy to avoid mutating the original
    v = copy.deepcopy(vehicle)
    v.setup = copy.deepcopy(setup)

    # -- Aerodynamics (wing angles) ----------------------------------------
    front_delta = setup.front_wing - _REF_FRONT_WING
    rear_delta = setup.rear_wing - _REF_REAR_WING
    total_wing_delta = front_delta + rear_delta

    v.cla = max(0.0, v.cla + total_wing_delta * _CLA_PER_WING_DEG)
    v.cda = max(0.1, v.cda + total_wing_delta * _CDA_PER_WING_DEG)

    # -- Tyre lateral grip (camber) ----------------------------------------
    # Average camber effect across axles
    front_camber_delta = setup.front_camber - _REF_FRONT_CAMBER
    rear_camber_delta = setup.rear_camber - _REF_REAR_CAMBER
    avg_camber_delta = (front_camber_delta + rear_camber_delta) / 2.0

    new_d = v.tyre_lat.D + avg_camber_delta * _D_LAT_PER_CAMBER_DEG
    new_d = max(0.5, min(2.0, new_d))  # clamp to reasonable range

    v.tyre_lat = PacejkaParams(
        B=v.tyre_lat.B,
        C=v.tyre_lat.C,
        D=new_d,
        E=v.tyre_lat.E,
    )

    # -- Tyre stiffness (pressure) -----------------------------------------
    front_press_delta = setup.front_pressure_psi - _REF_FRONT_PRESSURE
    rear_press_delta = setup.rear_pressure_psi - _REF_REAR_PRESSURE
    avg_press_delta = (front_press_delta + rear_press_delta) / 2.0

    new_b = v.tyre_lat.B + avg_press_delta * _B_LAT_PER_PSI
    new_b = max(5.0, min(20.0, new_b))

    v.tyre_lat = PacejkaParams(
        B=new_b,
        C=v.tyre_lat.C,
        D=v.tyre_lat.D,
        E=v.tyre_lat.E,
    )

    # -- Future: spring rates, ARBs, ride height, toe, brake bias, diff ----
    # These do not directly map to the current simplified bicycle model.
    # They would affect:
    #   - Roll stiffness distribution (springs, ARBs)
    #   - Aero platform (ride height)
    #   - Tyre slip angles at axle level (toe)
    #   - Braking force distribution (brake bias)
    #   - Traction/coast behaviour (differential)
    # Logged for future implementation.

    return v
