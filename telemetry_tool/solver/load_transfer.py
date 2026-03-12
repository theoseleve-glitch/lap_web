"""Load transfer calculations for the OCP lap solver.

Provides longitudinal and lateral weight transfer functions used by the
tyre model and OCP cost function.

All units SI (N, m, m/s²).
"""
from __future__ import annotations

from typing import Tuple

from solver.vehicle_params import OCPVehicleParams


def compute_load_transfer(
    params: OCPVehicleParams,
    a_long: float,
    a_lat: float,
) -> Tuple[float, float]:
    """Compute longitudinal load transfer between front and rear axles.

    Under braking (a_long < 0) weight shifts forward; under acceleration
    (a_long > 0) weight shifts rearward.

    Parameters
    ----------
    params:
        Vehicle physical parameters.
    a_long:
        Longitudinal acceleration [m/s²].  Negative = braking.
    a_lat:
        Lateral acceleration [m/s²].  (Unused in longitudinal calc but
        included for a consistent signature.)

    Returns
    -------
    (dFz_front, dFz_rear) :
        Load transfer increments [N].  ``dFz_front`` is positive under
        braking (more load on front); ``dFz_rear`` is negative.
    """
    # dFz = m * |a_long| * h_cg / wheelbase  (signed by braking direction)
    # Convention: braking → a_long < 0 → dFz_front > 0
    dFz = params.mass * (-a_long) * params.h_cg / params.wheelbase
    return dFz, -dFz


def compute_lateral_load_transfer(
    params: OCPVehicleParams,
    a_lat: float,
) -> Tuple[float, float]:
    """Compute lateral load transfer between outer and inner wheels.

    Under right-hand cornering (a_lat > 0) weight shifts to the left
    (outer) wheels; under left-hand cornering the reverse.

    Parameters
    ----------
    params:
        Vehicle physical parameters.
    a_lat:
        Lateral acceleration [m/s²].  Positive = cornering right (load
        shifts to left/outer wheels).

    Returns
    -------
    (dFz_outer, dFz_inner) :
        Load transfer increments [N].  ``dFz_outer`` is positive when
        ``a_lat > 0``.
    """
    dFz = params.mass * a_lat * params.h_cg / params.track_width
    return dFz, -dFz


def compute_total_grip_factor(
    params: OCPVehicleParams,
    a_long: float,
    a_lat: float,
) -> float:
    """Return a dimensionless grip factor accounting for load-sensitivity.

    Uses the Pacejka-inspired load sensitivity model:
        mu_eff = mu_ref * (1 + load_sensitivity * dFz_norm)

    where ``dFz_norm`` is the combined load transfer normalised by the
    static axle load [kN].

    A value < 1.0 indicates net grip reduction; > 1.0 would indicate grip
    increase (only possible with very low loads).

    Parameters
    ----------
    params:
        Vehicle physical parameters.
    a_long:
        Longitudinal acceleration [m/s²].
    a_lat:
        Lateral acceleration [m/s²].

    Returns
    -------
    float
        Effective friction coefficient relative to reference (≥ 0).
    """
    Fz_static = params.Fz_static_per_axle  # N

    dFz_long, _ = compute_load_transfer(params, a_long, a_lat)
    dFz_lat, _ = compute_lateral_load_transfer(params, a_lat)

    # Combined normalised load transfer [kN]
    dFz_combined = (abs(dFz_long) + abs(dFz_lat)) / 1000.0

    # Normalise by static axle load [kN]
    Fz_static_kN = Fz_static / 1000.0
    dFz_norm = dFz_combined / max(Fz_static_kN, 1e-6)

    mu_eff = params.mu_ref * (1.0 + params.load_sensitivity * dFz_norm)
    return max(mu_eff, 0.0)
