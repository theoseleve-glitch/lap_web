"""Vehicle parameter bridge -- converts sim_optimizer output and AC data
to VehicleParams for the Lap Oracle physics engine.

This module bridges the gap between the identified parameters from the
sim_optimizer pipeline and the VehicleParams dataclass used by the OCP
solver and bicycle model.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from telemetry_tool.lap_oracle.config import PacejkaParams, VehicleParams

log = logging.getLogger(__name__)


def from_sim_optimizer_result(
    result_dict: Dict[str, Any],
    sim: str,
    car_name: str,
) -> VehicleParams:
    """Build VehicleParams from a sim_optimizer pipeline result dict.

    The *result_dict* is expected to contain serialized sub-model dicts
    (as returned by ``VehicleModel.to_dict()`` or the pipeline summary).

    Expected keys (all optional -- missing keys use VehicleParams defaults):
        - ``mass`` -> ``base_mass_kg``
        - ``aero`` -> ``cda``, ``cla``
        - ``tyre`` -> ``mu_lat``, ``b_lat``, ``c_lat``, ``mu_long``, ``b_long``, ``c_long``
        - ``brake`` -> ``max_decel_mps2``
        - ``powertrain`` -> ``gear_torque_maps`` (used for max power estimate)

    Parameters
    ----------
    result_dict : dict
        Serialized vehicle model from the sim_optimizer pipeline.
    sim : str
        Simulator identifier (e.g. ``"ac"``, ``"iracing"``).
    car_name : str
        Car name / identifier.

    Returns
    -------
    VehicleParams
        Oracle-format vehicle parameters.
    """
    vp = VehicleParams(sim=sim, car_name=car_name)

    # -- Mass --------------------------------------------------------------
    mass_d = result_dict.get("mass", {})
    if isinstance(mass_d, dict):
        base = mass_d.get("base_mass_kg")
        bop = mass_d.get("bop_penalty_kg", 0.0)
        if base is not None:
            vp.mass_kg = float(base) + float(bop)

    # -- Aero --------------------------------------------------------------
    aero_d = result_dict.get("aero", {})
    if isinstance(aero_d, dict):
        if "cda" in aero_d:
            vp.cda = float(aero_d["cda"])
        if "cla" in aero_d:
            vp.cla = float(aero_d["cla"])

    # -- Tyre (lateral) ----------------------------------------------------
    tyre_d = result_dict.get("tyre", {})
    if isinstance(tyre_d, dict):
        vp.tyre_lat = PacejkaParams(
            B=float(tyre_d.get("b_lat", vp.tyre_lat.B)),
            C=float(tyre_d.get("c_lat", vp.tyre_lat.C)),
            D=float(tyre_d.get("mu_lat", vp.tyre_lat.D)),
            E=vp.tyre_lat.E,  # E is not identified by sim_optimizer
        )
        vp.tyre_long = PacejkaParams(
            B=float(tyre_d.get("b_long", vp.tyre_long.B)),
            C=float(tyre_d.get("c_long", vp.tyre_long.C)),
            D=float(tyre_d.get("mu_long", vp.tyre_long.D)),
            E=vp.tyre_long.E,
        )

    # -- Brake -------------------------------------------------------------
    brake_d = result_dict.get("brake", {})
    if isinstance(brake_d, dict):
        if "max_decel_mps2" in brake_d:
            vp.max_brake_decel = float(brake_d["max_decel_mps2"])

    # -- Powertrain (estimate max power) -----------------------------------
    pt_d = result_dict.get("powertrain", {})
    if isinstance(pt_d, dict):
        estimated_power = _estimate_power(pt_d)
        if estimated_power > 0:
            vp.max_power_w = estimated_power

    return vp


def from_ac_car_ini(ini_data: dict) -> VehicleParams:
    """Build VehicleParams from parsed Assetto Corsa car.ini data.

    The *ini_data* dict mirrors the INI section/key structure of an AC
    car definition.  Keys are case-insensitive.

    Expected sections / keys:
        - ``[CAR]`` -> ``TOTALMASS``
        - ``[SUSPENSIONS]`` -> ``WHEELBASE``, ``FRONT_TRACK``, ``REAR_TRACK``,
          ``CG_HEIGHT``
        - ``[AERO]`` -> ``CD``, ``CL``, ``FRONTAL_AREA``
        - ``[BRAKES]`` -> ``MAX_DECEL``

    Parameters
    ----------
    ini_data : dict
        Parsed INI sections as nested dicts.

    Returns
    -------
    VehicleParams
        Oracle-format vehicle parameters.
    """
    vp = VehicleParams(sim="ac")

    # Normalise keys to uppercase for lookup
    data = _normalise_keys(ini_data)

    # -- CAR section -------------------------------------------------------
    car = data.get("CAR", {})
    if "TOTALMASS" in car:
        vp.mass_kg = float(car["TOTALMASS"])
    if "SCREEN_NAME" in car:
        vp.car_name = str(car["SCREEN_NAME"])

    # -- SUSPENSIONS -------------------------------------------------------
    susp = data.get("SUSPENSIONS", data.get("BASIC", {}))
    if "WHEELBASE" in susp:
        vp.wheelbase_m = float(susp["WHEELBASE"])
    if "FRONT_TRACK" in susp:
        vp.track_width_front_m = float(susp["FRONT_TRACK"])
    if "REAR_TRACK" in susp:
        vp.track_width_rear_m = float(susp["REAR_TRACK"])
    if "CG_HEIGHT" in susp:
        vp.cg_height_m = float(susp["CG_HEIGHT"])

    # Weight distribution (fraction on front axle)
    if "WHEELBASE" in susp and "CG_LOCATION" in susp:
        wb = float(susp["WHEELBASE"])
        if wb > 0:
            cg_loc = float(susp["CG_LOCATION"])
            vp.weight_dist_front = cg_loc / wb

    # -- AERO --------------------------------------------------------------
    aero = data.get("AERO", {})
    frontal_area = float(aero.get("FRONTAL_AREA", 2.0))
    if "CD" in aero:
        vp.cda = float(aero["CD"]) * frontal_area
    if "CL" in aero:
        vp.cla = abs(float(aero["CL"])) * frontal_area

    # -- BRAKES ------------------------------------------------------------
    brakes = data.get("BRAKES", {})
    if "MAX_DECEL" in brakes:
        vp.max_brake_decel = float(brakes["MAX_DECEL"])

    return vp


def _estimate_power(powertrain: dict) -> float:
    """Scan torque maps for maximum power output (Watts).

    Iterates over gear torque maps and finds the RPM/torque pair that
    yields the highest power: P = T * omega = T * (2*pi*RPM/60).

    Parameters
    ----------
    powertrain : dict
        Serialized PowertrainModel dict with ``gear_torque_maps``.

    Returns
    -------
    float
        Estimated peak power in Watts, or 0.0 if no data.
    """
    import math

    maps = powertrain.get("gear_torque_maps", {})
    if not maps:
        return 0.0

    max_power = 0.0
    for _gear_key, gear_data in maps.items():
        if not isinstance(gear_data, dict):
            continue
        rpm_list = gear_data.get("rpm", [])
        torque_list = gear_data.get("torque_nm", [])
        if not rpm_list or not torque_list:
            continue
        for rpm_val, torque_val in zip(rpm_list, torque_list):
            omega = 2.0 * math.pi * float(rpm_val) / 60.0
            power = float(torque_val) * omega
            if power > max_power:
                max_power = power

    return max_power


def _normalise_keys(d: dict) -> dict:
    """Recursively uppercase all dict keys."""
    out: dict = {}
    for k, v in d.items():
        key = str(k).upper()
        if isinstance(v, dict):
            out[key] = _normalise_keys(v)
        else:
            out[key] = v
    return out
