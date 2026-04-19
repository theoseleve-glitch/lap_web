"""Suspension spring-rate identification from shock deflection + lateral accel."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

_G = 9.80665
_DEFAULT_SPRING_RATE = 50000.0  # N/m fallback


@dataclass
class SuspensionModel:
    """Identified per-corner spring rates and static deflection."""

    spring_rate_lf: float  # N/m
    spring_rate_rf: float
    spring_rate_lr: float
    spring_rate_rr: float
    static_defl_m: float

    # ------------------------------------------------------------------
    def wheel_load_n(self, corner: str, shock_defl_m: float) -> float:
        """Return spring force for *corner* at given deflection.

        ``spring_rate * shock_defl_m``
        """
        rate_map = {
            "lf": self.spring_rate_lf,
            "rf": self.spring_rate_rf,
            "lr": self.spring_rate_lr,
            "rr": self.spring_rate_rr,
        }
        rate = rate_map[corner.lower()]
        return rate * shock_defl_m

    def load_transfer_lateral_n(
        self,
        lat_accel_mps2: float,
        mass_kg: float,
        cg_height_m: float = 0.35,
        track_width_m: float = 1.5,
    ) -> float:
        """Lateral load transfer: ``mass * |lat_accel| * cg_height / track_width``."""
        return mass_kg * abs(lat_accel_mps2) * cg_height_m / track_width_m

    def to_dict(self) -> dict[str, Any]:
        return {
            "spring_rate_lf": self.spring_rate_lf,
            "spring_rate_rf": self.spring_rate_rf,
            "spring_rate_lr": self.spring_rate_lr,
            "spring_rate_rr": self.spring_rate_rr,
            "static_defl_m": self.static_defl_m,
        }


# ======================================================================
# Identification helpers
# ======================================================================


def _estimate_spring_rate(
    shock_defl: np.ndarray,
    lat_accel: np.ndarray,
    mass_kg: float,
    sign: float,
    config,
) -> float:
    """Estimate spring rate for one corner via least-squares.

    Parameters
    ----------
    shock_defl : array of shock deflection (m)
    lat_accel : array of lateral acceleration (m/s^2)
    mass_kg : vehicle mass
    sign : +1 for outer wheels (RF, RR), -1 for inner (LF, LR)
    config : SimOptimizerConfig with clamp bounds

    Returns
    -------
    Estimated spring rate in N/m, clamped to config range.
    """
    median_defl = float(np.median(shock_defl))
    delta_defl = shock_defl - median_defl

    # Load proxy: lateral load transfer seen at this corner
    load_proxy = sign * lat_accel * mass_kg * 0.35 / 1.5

    # Filter: only samples where load is significant
    valid = np.abs(load_proxy) > 200.0
    if valid.sum() < 10:
        return _DEFAULT_SPRING_RATE

    x = delta_defl[valid]
    y = load_proxy[valid]

    # Further filter: deflection must be non-trivial
    nontrivial = np.abs(x) > 0.0005
    if nontrivial.sum() < 10:
        return _DEFAULT_SPRING_RATE

    x = x[nontrivial]
    y = y[nontrivial]

    # OLS through origin: rate = sum(x*y) / sum(x^2)
    denom = float(np.sum(x * x))
    if denom < 1e-15:
        return _DEFAULT_SPRING_RATE

    rate = float(np.sum(x * y) / denom)

    # Clamp to physical range
    rate = float(
        np.clip(
            rate,
            config.suspension_spring_rate_clamp_lo_npm,
            config.suspension_spring_rate_clamp_hi_npm,
        )
    )
    return rate


# ======================================================================
# Public entry point
# ======================================================================


def identify_suspension_model(
    *,
    shock_defl_lf: Optional[np.ndarray],
    shock_defl_rf: Optional[np.ndarray],
    shock_defl_lr: Optional[np.ndarray],
    shock_defl_rr: Optional[np.ndarray],
    lat_accel: np.ndarray,
    long_accel: np.ndarray,
    mass_kg: float,
    config,
) -> SuspensionModel:
    """Identify per-corner spring rates from shock deflection arrays.

    sign_map: LF=-1, RF=+1, LR=-1, RR=+1  (inner/outer convention for
    a right-hand turn with positive lat_accel).

    If a deflection array is ``None`` or too short, that corner gets
    the default spring rate.
    """
    sign_map = {"lf": -1.0, "rf": 1.0, "lr": -1.0, "rr": 1.0}
    defl_map = {
        "lf": shock_defl_lf,
        "rf": shock_defl_rf,
        "lr": shock_defl_lr,
        "rr": shock_defl_rr,
    }

    min_samples = config.suspension_min_quasi_static_samples
    rates: dict[str, float] = {}

    for corner, defl in defl_map.items():
        if defl is None or len(defl) < min_samples:
            rates[corner] = _DEFAULT_SPRING_RATE
        else:
            rates[corner] = _estimate_spring_rate(
                defl, lat_accel, mass_kg, sign_map[corner], config
            )

    # Static deflection from median of LF (or default 0.05 m)
    if shock_defl_lf is not None and len(shock_defl_lf) >= min_samples:
        static_defl = float(np.median(shock_defl_lf))
    else:
        static_defl = 0.05

    return SuspensionModel(
        spring_rate_lf=rates["lf"],
        spring_rate_rf=rates["rf"],
        spring_rate_lr=rates["lr"],
        spring_rate_rr=rates["rr"],
        static_defl_m=static_defl,
    )
