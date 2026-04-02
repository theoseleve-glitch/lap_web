"""SimOptimizer configuration — frozen dataclass with physics tunables."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimOptimizerConfig:
    """All tunables for the sim-optimizer pipeline.

    Grouped by subsystem.  Every field has a sensible default so
    ``SimOptimizerConfig()`` is always valid.
    """

    # ── Tyre ──────────────────────────────────────────────────────────
    tyre_pacejka_b_init: float = 10.0
    tyre_pacejka_c_init: float = 1.5
    tyre_pacejka_d_init: float = 1.0
    tyre_mu_clamp_lo: float = 0.8
    tyre_mu_clamp_hi: float = 1.8
    tyre_temp_optimal_c: float = 85.0
    tyre_temp_sigma_c: float = 25.0
    tyre_pressure_optimal_kpa: float = 172.0
    tyre_pressure_sigma_kpa: float = 20.0
    tyre_min_slip_samples: int = 200
    tyre_slip_ratio_cap: float = 0.15
    tyre_slip_angle_cap_deg: float = 12.0

    # ── Aero ──────────────────────────────────────────────────────────
    aero_cda_default: float = 0.80
    aero_cla_default: float = 0.0
    aero_cda_clamp_lo: float = 0.3
    aero_cda_clamp_hi: float = 3.0
    aero_cla_clamp_lo: float = 0.0
    aero_cla_clamp_hi: float = 5.0
    aero_coastdown_throttle_max: float = 0.02
    aero_coastdown_brake_max: float = 0.02
    aero_coastdown_curvature_max: float = 0.005
    aero_draft_distance_m: float = 50.0

    # ── Powertrain ────────────────────────────────────────────────────
    powertrain_full_throttle_min: float = 0.95
    powertrain_min_samples_per_gear: int = 50
    powertrain_rr_c0: float = 0.012
    powertrain_rr_c1: float = 0.00008
    powertrain_transmission_efficiency: float = 0.93

    # ── Brake ─────────────────────────────────────────────────────────
    brake_min_decel_mps2: float = 2.0
    brake_min_samples: int = 100
    brake_fade_temp_threshold_c: float = 400.0

    # ── Suspension ────────────────────────────────────────────────────
    suspension_min_quasi_static_samples: int = 100
    suspension_spring_rate_clamp_lo_npm: float = 10000.0
    suspension_spring_rate_clamp_hi_npm: float = 200000.0

    # ── Mass ──────────────────────────────────────────────────────────
    mass_fuel_density_kg_l: float = 0.75
    mass_default_kg: float = 1200.0
    mass_clamp_lo_kg: float = 500.0
    mass_clamp_hi_kg: float = 2500.0
    mass_min_full_throttle_samples: int = 20

    # ── Filter ────────────────────────────────────────────────────────
    filter_min_speed_mps: float = 5.0
    filter_yellow_flag_bits: int = 0x10

    # ── General ───────────────────────────────────────────────────────
    resample_ds_m: float = 0.5
    highrate_tick_hz: float = 360.0
    samples_per_tick: int = 6


def default_config() -> SimOptimizerConfig:
    """Return a default ``SimOptimizerConfig``."""
    return SimOptimizerConfig()
