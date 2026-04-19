"""Mass model identification from telemetry data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from telemetry_tool.sim_optimizer.config import SimOptimizerConfig


@dataclass
class MassModel:
    """Vehicle mass model with fuel tracking and BOP penalty."""

    base_mass_kg: float
    fuel_density_kg_l: float
    bop_penalty_kg: float

    def total_mass_kg(self, fuel_level_l: float) -> float:
        """Return total mass: base + bop + fuel * density."""
        return self.base_mass_kg + self.bop_penalty_kg + fuel_level_l * self.fuel_density_kg_l

    def clamped(self, lo: float, hi: float) -> MassModel:
        """Return copy with base_mass_kg clipped to [lo, hi]."""
        return MassModel(
            base_mass_kg=float(np.clip(self.base_mass_kg, lo, hi)),
            fuel_density_kg_l=self.fuel_density_kg_l,
            bop_penalty_kg=self.bop_penalty_kg,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain dict."""
        return {
            "base_mass_kg": self.base_mass_kg,
            "fuel_density_kg_l": self.fuel_density_kg_l,
            "bop_penalty_kg": self.bop_penalty_kg,
        }


def identify_mass_model(
    *,
    speed_mps: np.ndarray,
    long_accel: np.ndarray,
    throttle: np.ndarray,
    fuel_level_l: np.ndarray,
    bop_penalty_kg: np.ndarray,
    config: SimOptimizerConfig,
) -> MassModel:
    """Identify a mass model from telemetry arrays.

    Strategy:
    - Extract median BOP penalty from the array.
    - Find full-throttle samples (throttle >= threshold, long_accel > 1.0).
    - If insufficient samples, return a default-mass model.
    - Otherwise use config.mass_default_kg as base (mass estimation from
      F=ma is circular without knowing engine force; the real value comes
      from fuel tracking + BOP).
    - Clamp to configured bounds.
    """
    median_bop = float(np.median(bop_penalty_kg))

    # Full-throttle mask
    ft_mask = (throttle >= config.powertrain_full_throttle_min) & (long_accel > 1.0)
    n_ft = int(np.sum(ft_mask))

    if n_ft < config.mass_min_full_throttle_samples:
        return MassModel(
            base_mass_kg=config.mass_default_kg,
            fuel_density_kg_l=config.mass_fuel_density_kg_l,
            bop_penalty_kg=median_bop,
        )

    # With sufficient full-throttle data we still use the default base mass
    # because estimating mass from F=ma requires knowing engine force (circular).
    # The value of this pipeline step is fuel-level tracking and BOP bookkeeping.
    base = config.mass_default_kg

    model = MassModel(
        base_mass_kg=base,
        fuel_density_kg_l=config.mass_fuel_density_kg_l,
        bop_penalty_kg=median_bop,
    )
    return model.clamped(config.mass_clamp_lo_kg, config.mass_clamp_hi_kg)
