"""Pacejka-based tyre model identification from telemetry slip data."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

_G = 9.80665


def pacejka_force(
    slip: float, b: float, c: float, d: float, mu: float, fz: float
) -> float:
    """Simplified Pacejka magic-formula lateral/longitudinal force.

    ``mu * fz * d * sin(c * atan(b * slip))``
    """
    return mu * fz * d * math.sin(c * math.atan(b * slip))


@dataclass
class TyreModel:
    """Identified tyre grip parameters (lateral + longitudinal)."""

    b_lat: float = 8.5
    c_lat: float = 1.35
    d_lat: float = 1.0
    mu_lat: float = 1.2
    b_long: float = 11.0
    c_long: float = 1.65
    d_long: float = 1.0
    mu_long: float = 1.2
    source: str = "default"

    # ------------------------------------------------------------------
    def max_lateral_force(self, fz: float) -> float:
        """Peak lateral force: ``mu_lat * fz * d_lat``."""
        return self.mu_lat * fz * self.d_lat

    def max_longitudinal_force(self, fz: float) -> float:
        """Peak longitudinal force: ``mu_long * fz * d_long``."""
        return self.mu_long * fz * self.d_long

    def lateral_force(self, slip_angle: float, fz: float) -> float:
        """Lateral force at given slip angle (rad) and normal load."""
        return pacejka_force(
            slip_angle, self.b_lat, self.c_lat, self.d_lat, self.mu_lat, fz
        )

    def longitudinal_force(self, slip_ratio: float, fz: float) -> float:
        """Longitudinal force at given slip ratio and normal load."""
        return pacejka_force(
            slip_ratio, self.b_long, self.c_long, self.d_long, self.mu_long, fz
        )

    def inverse_lateral_slip(self, target_force: float, fz: float) -> float:
        """Bisection search for slip angle producing *target_force*.

        Searches in the range [0, 0.3] rad over 30 iterations.
        Returns the slip angle (rad) whose lateral force is closest to
        *target_force*.
        """
        lo, hi = 0.0, 0.3
        for _ in range(30):
            mid = 0.5 * (lo + hi)
            f_mid = abs(self.lateral_force(mid, fz))
            if f_mid < abs(target_force):
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def clamped(self, config) -> TyreModel:
        """Return a copy with *mu_lat* / *mu_long* clipped to config range."""
        return TyreModel(
            b_lat=self.b_lat,
            c_lat=self.c_lat,
            d_lat=self.d_lat,
            mu_lat=float(
                np.clip(self.mu_lat, config.tyre_mu_clamp_lo, config.tyre_mu_clamp_hi)
            ),
            b_long=self.b_long,
            c_long=self.c_long,
            d_long=self.d_long,
            mu_long=float(
                np.clip(self.mu_long, config.tyre_mu_clamp_lo, config.tyre_mu_clamp_hi)
            ),
            source=self.source,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "b_lat": self.b_lat,
            "c_lat": self.c_lat,
            "d_lat": self.d_lat,
            "mu_lat": self.mu_lat,
            "b_long": self.b_long,
            "c_long": self.c_long,
            "d_long": self.d_long,
            "mu_long": self.mu_long,
            "source": self.source,
        }


# ======================================================================
# Identification
# ======================================================================


def _fit_axis(
    slip: np.ndarray,
    force: np.ndarray,
    load: np.ndarray,
    slip_cap: float,
    min_samples: int,
    c_init: float,
) -> tuple[float, float, float] | None:
    """Fit B and mu for one axis (lateral or longitudinal).

    Returns ``(b, c, mu)`` or *None* if insufficient data.
    """
    mask = (
        (np.abs(slip) > 0.001)
        & (np.abs(slip) < slip_cap)
        & (load > 500.0)
        & np.isfinite(force)
    )
    if mask.sum() < min_samples:
        return None

    slip_f = slip[mask]
    force_f = force[mask]
    load_f = load[mask]

    # Normalise force by load
    fx_norm = force_f / load_f

    # mu = 98th percentile of |normalised force|
    mu = float(np.percentile(np.abs(fx_norm), 98))
    if mu < 1e-6:
        return None

    c = c_init

    # Grid search B to minimise MSE
    best_b = 10.0
    best_mse = float("inf")
    for b_candidate_10x in range(50, 201):  # 5.0 to 20.0 step 0.5
        b_cand = b_candidate_10x / 10.0
        pred = mu * np.sin(c * np.arctan(b_cand * slip_f))
        mse = float(np.mean((pred - fx_norm) ** 2))
        if mse < best_mse:
            best_mse = mse
            best_b = b_cand

    return best_b, c, mu


def identify_tyre_model(
    *,
    slip_ratio: np.ndarray | None = None,
    longitudinal_force: np.ndarray | None = None,
    lateral_slip: np.ndarray | None = None,
    lateral_force: np.ndarray | None = None,
    tyre_load: np.ndarray | None = None,
    config,
) -> TyreModel:
    """Identify a :class:`TyreModel` from telemetry arrays.

    All inputs may be *None*.  When *None* or when there are fewer than
    ``config.tyre_min_slip_samples`` valid points the corresponding axis
    keeps default values.
    """
    model = TyreModel(source="default")

    # -- Longitudinal --------------------------------------------------
    if (
        slip_ratio is not None
        and longitudinal_force is not None
        and tyre_load is not None
    ):
        result = _fit_axis(
            slip=slip_ratio,
            force=longitudinal_force,
            load=tyre_load,
            slip_cap=config.tyre_slip_ratio_cap,
            min_samples=config.tyre_min_slip_samples,
            c_init=config.tyre_pacejka_c_init,
        )
        if result is not None:
            b, c, mu = result
            model = TyreModel(
                b_lat=model.b_lat,
                c_lat=model.c_lat,
                d_lat=model.d_lat,
                mu_lat=model.mu_lat,
                b_long=b,
                c_long=c,
                d_long=model.d_long,
                mu_long=mu,
                source="identified",
            )

    # -- Lateral -------------------------------------------------------
    if (
        lateral_slip is not None
        and lateral_force is not None
        and tyre_load is not None
    ):
        slip_cap_rad = math.radians(config.tyre_slip_angle_cap_deg)
        result = _fit_axis(
            slip=lateral_slip,
            force=lateral_force,
            load=tyre_load,
            slip_cap=slip_cap_rad,
            min_samples=config.tyre_min_slip_samples,
            c_init=config.tyre_pacejka_c_init,
        )
        if result is not None:
            b, c, mu = result
            model = TyreModel(
                b_lat=b,
                c_lat=c,
                d_lat=model.d_lat,
                mu_lat=mu,
                b_long=model.b_long,
                c_long=model.c_long,
                d_long=model.d_long,
                mu_long=model.mu_long,
                source="identified",
            )

    return model.clamped(config)
