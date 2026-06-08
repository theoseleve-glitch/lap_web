"""
track_surface/vehicle_profile.py
--------------------------------
Vehicle model for the 2D optimizer when specs are absent.

Real users have at best kart+driver weight and engine power, often neither.
This module (a) holds a physically-sane VehicleParams per vehicle class, and
(b) resolves a complete model from {class, optional weight, optional power,
optional laps}: the driver's DEMONSTRATED longitudinal envelope (from their own
telemetry, the same best-observed p95 idea as the grip limit) is used where
laps exist; class defaults fill every gap.

The 2D grid stores ABSOLUTE road mu, so tyre_lat.D == 1.0 in every profile —
the solver multiplies tyre_lat.D * grip and the double-count guard warns if D
strays (solver_bridge.solve_optimal_line_2d).
"""
from __future__ import annotations

import copy as _copy
import logging
from dataclasses import dataclass

from telemetry_tool.lap_oracle.config import PacejkaParams, VehicleParams

logger = logging.getLogger(__name__)


def _profile(*, mass, wb, cda, cla, power, brake) -> VehicleParams:
    return VehicleParams(
        mass_kg=mass, wheelbase_m=wb, cda=cda, cla=cla,
        max_power_w=power, max_brake_decel=brake,
        tyre_lat=PacejkaParams(D=1.0),
        tyre_long=PacejkaParams(B=12.0, C=1.4, D=1.0, E=-0.3),
    )


CLASS_PROFILES: dict[str, VehicleParams] = {
    "kart":    _profile(mass=160.0,  wb=1.05, cda=0.65, cla=0.0, power=22_000.0,  brake=1.6),
    "gt3":     _profile(mass=1300.0, wb=2.65, cda=0.80, cla=2.5, power=400_000.0, brake=1.4),
    "gt4":     _profile(mass=1350.0, wb=2.65, cda=0.75, cla=1.5, power=320_000.0, brake=1.3),
    "formula": _profile(mass=700.0,  wb=3.00, cda=0.70, cla=3.0, power=560_000.0, brake=2.0),
    "lmp":     _profile(mass=950.0,  wb=2.95, cda=0.60, cla=3.5, power=480_000.0, brake=1.8),
    "touring": _profile(mass=1250.0, wb=2.65, cda=0.70, cla=0.3, power=240_000.0, brake=1.2),
    "road":    _profile(mass=1400.0, wb=2.70, cda=0.62, cla=0.0, power=180_000.0, brake=1.0),
    "generic": _profile(mass=1200.0, wb=2.60, cda=0.70, cla=0.5, power=300_000.0, brake=1.2),
}


@dataclass(frozen=True)
class ParamProvenance:
    """Where each part of the resolved vehicle model came from."""
    vehicle_class: str
    lateral_source: str         # "grip_grid"
    longitudinal_source: str    # "demonstrated" | "user_power" | "class_default"
    mass_source: str            # "user_weight" | "class_default"
    envelope_reliable: bool


# ---------------------------------------------------------------------------
# Task 2 — _envelope_to_caps
# ---------------------------------------------------------------------------

from telemetry_tool.friction_envelope import (
    FrictionEnvelope,
    _G,
    _MIN_SAMPLES_PER_BIN,
)


def _envelope_to_caps(env: FrictionEnvelope | None) -> dict | None:
    """Demonstrated FrictionEnvelope -> ocp_2d envelope_caps (v_grid + per-speed
    drive/brake accel limits in m/s^2). Only bins with sufficient samples AND
    BOTH axes demonstrated (accel AND brake) are included; this guarantees no
    0.0 cap ever reaches the solver (a 0.0 brake/drive cap collapses the
    corresponding solver constraint, making the problem infeasible or producing
    garbage lap times). Returns None unless >= 2 such bins (the CasADi
    interpolant needs >= 2 grid points), so the solver falls back to class
    scalars entirely."""
    if env is None or not env.is_reliable or not env.friction_bins:
        return None
    bins = [
        fb for fb in env.friction_bins
        if fb.sample_count >= _MIN_SAMPLES_PER_BIN
        and fb.accel_max_g > 0.0 and fb.brake_max_g > 0.0
    ]
    if len(bins) < 2:
        return None
    return {
        "v_grid": [float(fb.speed_center_mps) for fb in bins],
        "ax_drive_max": [float(fb.accel_max_g * _G) for fb in bins],
        "ax_brake_max": [float(fb.brake_max_g * _G) for fb in bins],
    }


# ---------------------------------------------------------------------------
# Task 3 — resolve_vehicle_params (3 tiers)
# ---------------------------------------------------------------------------

from telemetry_tool.friction_envelope import compute_friction_envelope


def resolve_vehicle_params(
    vehicle_class: str,
    laps: "dict | None" = None,
    weight_kg: float | None = None,
    power_w: float | None = None,
) -> tuple[VehicleParams, dict | None, ParamProvenance]:
    """Resolve (VehicleParams, envelope_caps | None, ParamProvenance).

    Tier A: laps present + reliable demonstrated envelope -> caps drive the
    solver's longitudinal limits. Tier B: no/sparse laps + optional
    weight/power overrides. Tier C: nothing -> pure class profile.
    """
    vp = _copy.deepcopy(CLASS_PROFILES.get(vehicle_class, CLASS_PROFILES["generic"]))

    mass_source = "class_default"
    if weight_kg is not None:
        vp.mass_kg = float(weight_kg)
        mass_source = "user_weight"

    caps = None
    envelope_reliable = False
    if laps:
        try:
            env = compute_friction_envelope(laps)
            caps = _envelope_to_caps(env)
            envelope_reliable = caps is not None
        except Exception as exc:
            logger.warning("friction envelope failed (%s); using class default", exc)
            caps = None

    if power_w is not None:
        vp.max_power_w = float(power_w)
        longitudinal_source = "user_power"
    elif envelope_reliable:
        longitudinal_source = "demonstrated"
    else:
        longitudinal_source = "class_default"

    prov = ParamProvenance(
        vehicle_class=vehicle_class,
        lateral_source="grip_grid",
        longitudinal_source=longitudinal_source,
        mass_source=mass_source,
        envelope_reliable=envelope_reliable,
    )
    return vp, caps, prov
