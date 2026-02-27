"""
pacejka.py
----------
Lightweight Magic Formula utilities and tire thermal state helpers.

These utilities are optional and designed to be conservative by default.
When disabled by config, the pipeline keeps using envelope-only behavior.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class PacejkaCoefficients:
    """Simplified MF coefficients for one force axis."""

    b: float = 10.0
    c: float = 1.6
    d: float = 1.0
    e: float = 0.97


@dataclass(frozen=True)
class CombinedPacejkaParams:
    """Longitudinal + lateral coefficient pack."""

    longi: PacejkaCoefficients = PacejkaCoefficients(b=11.0, c=1.65, d=1.0, e=0.98)
    lat: PacejkaCoefficients = PacejkaCoefficients(b=8.5, c=1.35, d=1.0, e=0.97)


@dataclass
class TireThermalState:
    """Minimal thermal/pressure state for online simulation."""

    temp_c: float = 35.0
    pressure_kpa: float = 70.0
    wear: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "temp_c": float(self.temp_c),
            "pressure_kpa": float(self.pressure_kpa),
            "wear": float(self.wear),
        }


def magic_formula(mu_peak: float, slip: float, coeffs: PacejkaCoefficients) -> float:
    """
    Evaluate a normalized Pacejka-like force multiplier.

    Returns a signed force coefficient in [-mu_peak, +mu_peak].
    """
    x = float(slip)
    b = float(coeffs.b)
    c = float(coeffs.c)
    d = float(coeffs.d) * float(mu_peak)
    e = float(coeffs.e)
    bx = b * x
    term = bx - e * (bx - math.atan(bx))
    return float(d * math.sin(c * math.atan(term)))


def temperature_grip_scale(
    temp_c: float,
    *,
    temp_optimal_c: float,
    temp_sigma_c: float,
) -> float:
    """Gaussian-like grip falloff around optimal temperature."""
    sigma = max(float(temp_sigma_c), 1e-6)
    z = (float(temp_c) - float(temp_optimal_c)) / sigma
    return float(np.clip(math.exp(-0.5 * z * z), 0.55, 1.10))


def evolve_thermal_state(
    state: TireThermalState,
    *,
    accel_long_mps2: float,
    accel_lat_mps2: float,
    speed_mps: float,
    dt_s: float,
    ambient_c: float,
    heat_gain_coeff: float,
    cool_coeff: float,
    pressure_gain_per_c_kpa: float,
    nominal_pressure_kpa: float,
) -> TireThermalState:
    """
    One-step thermal evolution model.

    Heuristic model:
    - heat source from combined acceleration utilization and speed
    - cooling proportional to delta from ambient
    - pressure rises with temperature
    """
    dt = max(float(dt_s), 0.0)
    if dt <= 0:
        return TireThermalState(
            temp_c=float(state.temp_c),
            pressure_kpa=float(state.pressure_kpa),
            wear=float(state.wear),
        )

    a_comb = float(math.hypot(float(accel_long_mps2), float(accel_lat_mps2)))
    speed = max(float(speed_mps), 0.0)
    heat = float(heat_gain_coeff) * (0.35 + 0.65 * min(a_comb / 12.0, 2.0)) * (0.4 + speed / 40.0)
    cool = float(cool_coeff) * (float(state.temp_c) - float(ambient_c))
    temp_next = float(state.temp_c) + dt * (heat - cool)
    temp_next = float(np.clip(temp_next, ambient_c - 10.0, ambient_c + 130.0))

    dp = float(pressure_gain_per_c_kpa) * (temp_next - float(ambient_c))
    pressure_next = float(nominal_pressure_kpa) + dp
    pressure_next = float(np.clip(pressure_next, 40.0, 140.0))

    wear_inc = dt * (0.0005 + 0.0005 * min(a_comb / 10.0, 2.0))
    wear_next = float(np.clip(float(state.wear) + wear_inc, 0.0, 1.0))

    return TireThermalState(
        temp_c=temp_next,
        pressure_kpa=pressure_next,
        wear=wear_next,
    )


def combined_tire_scales_from_session(
    speed_mps: np.ndarray,
    accel_long_mps2: np.ndarray,
    accel_lat_mps2: np.ndarray,
    *,
    temp_initial_c: float,
    ambient_c: float,
    nominal_pressure_kpa: float,
    temp_optimal_c: float,
    temp_sigma_c: float,
    heat_gain_coeff: float,
    cool_coeff: float,
    pressure_gain_per_c_kpa: float,
    camber_deg: float = 0.0,
    camber_sensitivity_per_deg: float = 0.01,
) -> dict[str, Any]:
    """
    Roll thermal state along session arrays and return conservative grip scalars.
    """
    v = np.asarray(speed_mps, dtype=float)
    ax = np.asarray(accel_long_mps2, dtype=float)
    ay = np.asarray(accel_lat_mps2, dtype=float)
    n = int(min(len(v), len(ax), len(ay)))
    if n <= 1:
        state = TireThermalState(temp_c=temp_initial_c, pressure_kpa=nominal_pressure_kpa, wear=0.0)
        s = temperature_grip_scale(state.temp_c, temp_optimal_c=temp_optimal_c, temp_sigma_c=temp_sigma_c)
        camber_scale = float(np.clip(1.0 - abs(camber_deg) * camber_sensitivity_per_deg, 0.85, 1.05))
        return {
            "state": state.to_dict(),
            "thermal_scale": s,
            "pressure_scale": 1.0,
            "camber_scale": camber_scale,
            "combined_scale": float(np.clip(s * camber_scale, 0.70, 1.10)),
        }

    state = TireThermalState(temp_c=temp_initial_c, pressure_kpa=nominal_pressure_kpa, wear=0.0)
    scales: list[float] = []
    dt = 0.05
    for i in range(n):
        state = evolve_thermal_state(
            state,
            accel_long_mps2=float(ax[i]),
            accel_lat_mps2=float(ay[i]),
            speed_mps=float(v[i]),
            dt_s=dt,
            ambient_c=ambient_c,
            heat_gain_coeff=heat_gain_coeff,
            cool_coeff=cool_coeff,
            pressure_gain_per_c_kpa=pressure_gain_per_c_kpa,
            nominal_pressure_kpa=nominal_pressure_kpa,
        )
        s = temperature_grip_scale(
            state.temp_c,
            temp_optimal_c=temp_optimal_c,
            temp_sigma_c=temp_sigma_c,
        )
        # Pressure away from nominal reduces effective grip.
        pressure_dev = abs(state.pressure_kpa - nominal_pressure_kpa) / max(nominal_pressure_kpa, 1.0)
        pressure_scale = float(np.clip(1.0 - 0.25 * pressure_dev, 0.80, 1.02))
        # Mild wear penalty.
        wear_scale = float(np.clip(1.0 - 0.10 * state.wear, 0.85, 1.0))
        camber_scale = float(np.clip(1.0 - abs(camber_deg) * camber_sensitivity_per_deg, 0.85, 1.05))
        scales.append(float(np.clip(s * pressure_scale * wear_scale * camber_scale, 0.65, 1.10)))

    combined = float(np.clip(np.nanmedian(np.asarray(scales, dtype=float)), 0.65, 1.10))
    return {
        "state": state.to_dict(),
        "thermal_scale": float(np.clip(temperature_grip_scale(state.temp_c, temp_optimal_c=temp_optimal_c, temp_sigma_c=temp_sigma_c), 0.55, 1.10)),
        "pressure_scale": float(np.clip(1.0 - 0.25 * abs(state.pressure_kpa - nominal_pressure_kpa) / max(nominal_pressure_kpa, 1.0), 0.80, 1.02)),
        "camber_scale": float(np.clip(1.0 - abs(camber_deg) * camber_sensitivity_per_deg, 0.85, 1.05)),
        "combined_scale": combined,
    }

