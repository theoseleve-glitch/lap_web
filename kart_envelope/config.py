"""
config.py
---------
Single frozen dataclass holding every tunable parameter for the
kart_envelope pipeline.  Loads from YAML with sane defaults.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KartEnvelopeConfig:
    """Immutable configuration for the kart-envelope pipeline."""

    # -- GPS filtering --
    gps_min_satellites: int = 5
    gps_max_accuracy_m: float = 3.0
    gps_max_speed_mps: float = 45.0
    gps_max_accel_mps2: float = 40.0

    # -- Derived channels --
    smooth_window_samples: int = 5

    # -- Resampling --
    resample_ds_m: float = 0.5
    resample_min_points: int = 200

    # -- Lap selection --
    outlap_ratio: float = 1.5
    min_lap_distance_m: float = 100.0
    max_missing_ratio: float = 0.20
    min_clean_laps: int = 3

    # -- Outlier filtering --
    outlier_mad_threshold: float = 5.0
    outlier_min_bin_size: int = 10

    # -- Track geometry --
    curvature_smooth_hw: int = 7
    reference_line_method: str = "median"

    # -- Envelope learning --
    envelope_speed_bins: int = 15
    envelope_quantile_lat: float = 0.95
    envelope_quantile_trac: float = 0.98
    envelope_quantile_brake: float = 0.95
    envelope_min_samples_per_bin: int = 8
    envelope_smooth_hw: int = 2
    envelope_combined_p_init: float = 1.6
    envelope_combined_p_lo: float = 1.2
    envelope_combined_p_hi: float = 2.4
    envelope_gps_correction: float = 1.20
    envelope_traction_floor_mps2: float = 1.47  # 0.15 g (rental karts: ~0.2-0.3g traction)
    envelope_lateral_floor_mps2: float = 2.94   # 0.30 g (rental karts: ~0.5-1.0g lateral)

    # -- Session scalar inference --
    scalar_mu_lo: float = 0.5
    scalar_mu_hi: float = 1.5
    scalar_p_lo: float = 0.3
    scalar_p_hi: float = 2.0
    scalar_b_lo: float = 0.5
    scalar_b_hi: float = 1.5
    scalar_regularisation: float = 0.10
    scalar_outlier_percentile: float = 5.0
    scalar_obs_quantile_lat: float = 0.95
    scalar_obs_quantile_trac: float = 0.98
    scalar_obs_quantile_brake: float = 0.95

    # -- Solver --
    solver_max_speed_mps: float = 45.0
    solver_min_speed_mps: float = 1.0
    solver_wrap_iterations: int = 6
    solver_wrap_tol_mps: float = 0.02
    solver_apex_curvature_threshold: float = 0.005

    # -- Record calibration --
    cal_alpha_lo: float = 0.8
    cal_alpha_hi: float = 1.2
    cal_regularisation: float = 0.5

    # -- Coaching --
    coaching_n_segments: int = 20
    coaching_top_corners: int = 10
    coaching_speed_tol_mps: float = 0.5
    coaching_accel_tol_mps2: float = 0.10

    # -- Output --
    output_decimal_places: int = 4

    # -- Defaults for missing metadata --
    default_kart_class: str = "4t"
    default_driver_weight_kg: float = 80.0
    default_kart_weight_kg_4t: float = 95.0
    default_kart_weight_kg_2t: float = 80.0


def load_config(path: Path | None = None) -> KartEnvelopeConfig:
    """Load config from a YAML file, falling back to defaults for missing keys."""
    if path is None or not path.exists():
        logger.info("No config file supplied; using all defaults.")
        return KartEnvelopeConfig()

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("PyYAML not installed; using all defaults.")
        return KartEnvelopeConfig()

    with open(path, encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    flat: dict[str, Any] = {}
    for section in raw.values():
        if isinstance(section, dict):
            flat.update(section)
        # top-level scalars are also accepted
    # keep only keys that are actual fields
    valid = {f.name for f in KartEnvelopeConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in flat.items() if k in valid}
    logger.info("Loaded config with %d overrides from %s", len(filtered), path)
    return KartEnvelopeConfig(**filtered)


def default_config() -> KartEnvelopeConfig:
    """Return the all-defaults configuration."""
    return KartEnvelopeConfig()
