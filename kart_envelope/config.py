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

    # -- Schema / release metadata --
    model_version: str = "2.2.0-tiered"
    physics_stack_version: str = "cycle_b_v1"
    product_tier: str = "b2c"  # b2c | b2b_basic | b2b_premium
    tier_enforce_sensor_contract: bool = True
    tier_allow_sensor_fallback: bool = False
    b2b_whitelist_track_ids: str | None = None
    b2b_whitelist_kart_ids: str | None = None
    b2b_whitelist_layout_ids: str | None = None
    domain_soft_gate_enable: bool = True
    domain_soft_gate_warning_level: str = "high"

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
    track_enable_lidar_profile: bool = True
    track_lidar_fallback_to_telemetry: bool = True

    # -- Track grip maps --
    grip_enable_spatial_map: bool = True
    grip_map_blend: float = 0.35

    # -- FE load transfer maps --
    load_transfer_enable_fe_map: bool = True
    load_transfer_fallback_surrogate: bool = True

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
    solver_backend: str = "qss"  # qss | casadi_ocp
    solver_backend_fallback_to_qss: bool = True
    solver_max_speed_mps: float = 45.0
    solver_min_speed_mps: float = 1.0
    solver_wrap_iterations: int = 6
    solver_wrap_tol_mps: float = 0.02
    solver_apex_curvature_threshold: float = 0.005
    solver_casadi_max_iter: int = 600
    solver_casadi_tol: float = 1e-6
    solver_casadi_closed_loop: bool = True
    solver_casadi_warm_start: bool = True
    solver_casadi_accel_smooth_weight: float = 1e-4
    solver_casadi_speed_smooth_weight: float = 1e-6
    solver_casadi_print_level: int = 0
    solver_ocp_mesh_mode: str = "standard"  # coarse | standard | fine
    solver_ocp_retry_relax: bool = True
    solver_ocp_retry_relax_factor: float = 10.0
    solver_ocp_retry_max_attempts: int = 2

    # -- Tire model (Pacejka + thermal) --
    tire_enable_pacejka: bool = False
    tire_enable_thermal: bool = False
    tire_enable_pressure: bool = False
    tire_initial_temp_c: float = 35.0
    tire_ambient_temp_c: float = 25.0
    tire_nominal_pressure_kpa: float = 70.0
    tire_heat_gain_coeff: float = 0.015
    tire_cool_coeff: float = 0.003
    tire_pressure_gain_per_c_kpa: float = 0.08
    tire_temp_optimal_c: float = 70.0
    tire_temp_sigma_c: float = 25.0
    tire_camber_sensitivity_per_deg: float = 0.012

    # -- Vehicle dynamics surrogates --
    vehicle_enable_chassis_surrogate: bool = False
    vehicle_enable_contact_mode: bool = False
    vehicle_enable_high_dof_surrogate: bool = False
    vehicle_chassis_compliance_gain: float = 0.04
    vehicle_load_transfer_gain: float = 0.06
    vehicle_contact_lift_lat_threshold_g: float = 1.20
    vehicle_contact_hysteresis_g: float = 0.08

    # -- Powertrain / resistance --
    powertrain_enable_map: bool = True
    powertrain_enable_transmission: bool = True
    powertrain_transmission_efficiency: float = 0.93
    powertrain_enable_rolling_resistance: bool = True
    powertrain_rr_c0: float = 0.012
    powertrain_rr_c1: float = 0.00008
    powertrain_auto_shift: bool = True
    powertrain_wheel_radius_m: float = 0.135
    powertrain_shift_latency_s: float = 0.05

    # -- Aero --
    aero_enable_drag: bool = True
    aero_enable_downforce: bool = False
    aero_air_density_kg_m3: float = 1.20
    aero_default_cda: float = 0.80
    aero_default_cl: float = 0.0

    # -- Driver policy layers --
    policy_enable_virtual_driver: bool = True
    policy_enable_advanced_driver: bool = False
    policy_advanced_min_confidence: float = 0.65
    policy_advanced_bundle_dir: str = "data/models/kart_envelope/policies"
    policy_enable_mpc_imitation: bool = True
    policy_mpc_confidence_threshold: float = 0.70

    # -- Calibration / parameter identification --
    calibration_enable_telemetry_calibration: bool = True
    calibration_enable_param_id: bool = True
    calibration_param_id_method: str = "ridge"
    calibration_max_adjustment_pct: float = 12.0

    # -- Validation gates --
    validation_enable: bool = True
    validation_group_kfold_splits: int = 5
    validation_holdout_min_rows: int = 30
    validation_mae_gate_s: float = 1.50
    validation_uq_coverage_gate: float = 0.70

    # -- Record calibration --
    cal_alpha_lo: float = 0.8
    cal_alpha_hi: float = 1.2
    cal_regularisation: float = 0.5

    # -- Coaching --
    coaching_n_segments: int = 20
    coaching_top_corners: int = 10
    coaching_speed_tol_mps: float = 0.5
    coaching_accel_tol_mps2: float = 0.10

    # -- Corner sensitivity optimizer --
    sensitivity_enable: bool = True
    sensitivity_brake_shift_s: float = 0.40
    sensitivity_turn_shift_m: float = 8.0
    sensitivity_apex_shift_m: float = 3.0
    sensitivity_grid_size: int = 13
    sensitivity_apex_grid_size: int = 3
    sensitivity_line_curvature_gain: float = 0.12
    sensitivity_line_grid_size: int = 3
    sensitivity_line_path_penalty: float = 0.22
    sensitivity_accept_gain_s: float = 0.003
    sensitivity_entry_margin_m: float = 40.0
    sensitivity_exit_margin_m: float = 10.0
    sensitivity_coast_decel_mps2: float = 0.5
    sensitivity_max_overspeed_ratio: float = 1.05
    sensitivity_lat_force_gain: float = 0.28
    sensitivity_brake_force_gain: float = 0.32
    sensitivity_force_grid_size: int = 3
    sensitivity_underdrive_only: bool = True
    sensitivity_use_session_envelope: bool = True
    sensitivity_session_envelope_blend: float = 0.55
    sensitivity_target_lap_time_s: float | None = 43.4
    sensitivity_target_tolerance_s: float = 0.15
    sensitivity_target_max_force_scale: float = 1.30
    sensitivity_target_grid_size: int = 9
    sensitivity_target_align_enable: bool = True
    sensitivity_target_align_max_gain_scale: float = 1.20
    sensitivity_consistency_iterations: int = 3
    sensitivity_apply_global_consistency_after_corner: bool = False
    sensitivity_patch_blend_m: float = 2.0
    sensitivity_n_sectors: int = 3
    sensitivity_top_recommendations: int = 3
    sensitivity_ml_enable: bool = True
    sensitivity_ml_min_samples: int = 6
    sensitivity_ml_k_neighbors: int = 5
    sensitivity_ml_blend: float = 0.35
    sensitivity_ml_max_correction_s: float = 0.15
    sensitivity_acd_power_blend: float = 0.70
    sensitivity_acd_traction_floor_ratio: float = 0.90
    sensitivity_kart_quality_scale: float = 1.00
    sensitivity_condition_targets_csv: str | None = "data/condition_targets.csv"
    sensitivity_two_stage_search: bool = True
    sensitivity_two_stage_coarse_grid_size: int = 7
    sensitivity_two_stage_refine_grid_size: int = 3
    sensitivity_two_stage_top_n: int = 2
    sensitivity_force_penalty_wet: float = 0.90
    sensitivity_force_penalty_damp: float = 0.94
    sensitivity_force_penalty_green: float = 0.96
    sensitivity_force_penalty_greasy: float = 0.92
    sensitivity_ml_robust_trim_q: float = 0.05
    sensitivity_ml_enable_outlier_filter: bool = True
    sensitivity_ml_enable_ensemble: bool = True
    sensitivity_ml_ensemble_reference_weight: float = 0.15
    sensitivity_gain_shrinkage_csv: str | None = "data/models/kart_envelope/gain_shrinkage.csv"
    sensitivity_gain_shrinkage_default: float = 0.90
    sensitivity_gain_shrinkage_min: float = 0.60
    sensitivity_gain_shrinkage_max: float = 1.00
    sensitivity_uncertainty_enable: bool = True
    sensitivity_uncertainty_bootstrap_n: int = 32
    sensitivity_uncertainty_sigma_floor_s: float = 0.05
    sensitivity_hierarchical_enable: bool = True
    sensitivity_hierarchical_prior_laps: int = 20
    sensitivity_parallel_laps: bool = True
    sensitivity_parallel_workers: int = 0  # 0 -> auto
    sensitivity_numba_enable: bool = True

    # -- Optimal profile post-processing (all simulation outputs) --
    optimal_profile_smoothing_enable: bool = True
    optimal_profile_smoothing_window_m: float = 7.0
    optimal_profile_smoothing_passes: int = 3
    optimal_profile_smoothing_preserve_lap_time: bool = True

    # -- Output --
    output_decimal_places: int = 4

    # -- Defaults for missing metadata --
    default_kart_class: str = "4t"
    default_driver_weight_kg: float = 85.0
    default_kart_weight_kg_4t: float = 95.0
    default_kart_weight_kg_2t: float = 80.0

    # -- Robustness / runtime --
    quality_min_speed_coverage: float = 0.65
    quality_min_accel_coverage: float = 0.55
    quality_min_yaw_coverage: float = 0.30
    quality_min_laps_for_ml: int = 4
    confidence_gate_enable: bool = True
    confidence_gate_threshold: float = 0.55
    confidence_gate_disable_ml: bool = True
    confidence_gate_force_gain_scale: float = 0.70
    drift_detection_enable: bool = True
    drift_detection_sigma_threshold: float = 2.5
    drift_detection_history_min_sessions: int = 3
    drift_retrain_trigger_file: str | None = "data/models/kart_envelope/retrain_triggers.json"
    auto_retrain_on_drift: bool = False
    reliability_history_csv: str | None = "data/outputs/batch_all_laps_optimal.csv"

    # -- Fast inference / caching --
    fast_inference_mode: bool = False
    fast_inference_skip_all_laps: bool = True
    fast_inference_disable_ml: bool = False
    fast_inference_grid_size: int = 7
    fast_inference_force_grid_size: int = 3
    fast_inference_consistency_iterations: int = 2
    reuse_cached_session_outputs: bool = True
    cache_staleness_grace_s: float = 1.0
    runtime_online_slowdown_budget: float = 1.6

    # -- Bundle v2 (offline heavy, online light) --
    bundle_v2_enable: bool = True
    bundle_v2_dir: str = "data/models/kart_envelope/bundles"
    bundle_v2_tier_subdirs: bool = True
    bundle_v2_use_legacy_fallback: bool = True
    bundle_v2_min_laps: int = 3
    bundle_v2_confidence_floor: float = 0.25
    bundle_v2_uncertainty_alpha: float = 0.10
    bundle_v2_max_gain_pct: float = 12.0
    bundle_v2_default_optimization_method: str = "student_distilled"

    # -- Offline training / distillation --
    offline_dataset_path: str = "data/models/kart_envelope/offline/training_dataset.parquet"
    offline_counterfactual_path: str = "data/models/kart_envelope/offline/counterfactual_dataset.parquet"
    offline_training_report_path: str = "data/models/kart_envelope/offline/training_report.json"
    offline_min_rows_per_bundle: int = 40
    offline_counterfactual_samples_per_row: int = 6
    offline_counterfactual_noise_scale: float = 0.08
    offline_teacher_random_state: int = 42
    offline_student_random_state: int = 42
    offline_student_max_depth: int = 4
    offline_student_n_estimators: int = 120
    offline_publish_global_fallback_bundle: bool = True
    offline_premium_teacher_dir: str = "data/models/kart_envelope/offline/premium_teacher"


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
