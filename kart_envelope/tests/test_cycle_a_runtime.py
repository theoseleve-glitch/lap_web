"""Tests for Cycle-A powertrain, policy selection, and validation reports."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from kart_envelope.config import default_config
from kart_envelope.inference.policy import select_driver_policy
from kart_envelope.inference.validation import build_validation_report
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.solver.powertrain import build_powertrain_runtime


def test_powertrain_runtime_limits_drive_accel():
    cfg = replace(default_config(), powertrain_enable_map=True)
    meta = SessionMetadata(
        session_file="s.csv",
        driver_weight_kg=85.0,
        kart_weight_kg=95.0,
        engine_peak_power_kw=8.0,
    )
    pw = build_powertrain_runtime(meta, cfg)
    # With low power, high-speed accel should be capped below env request.
    a = pw.max_drive_accel(30.0, env_drive_accel_mps2=4.0)
    assert 0.0 <= a <= 4.0
    assert pw.resistance_accel(20.0, condition_label="wet") >= pw.resistance_accel(20.0, condition_label="dry")


def test_policy_selection_prefers_virtual_without_bundle(tmp_path: Path):
    cfg = replace(
        default_config(),
        policy_enable_virtual_driver=True,
        policy_enable_advanced_driver=True,
        policy_advanced_min_confidence=0.65,
    )
    sel = select_driver_policy(cfg, quality_score=0.8, bundle_dir=tmp_path / "missing_bundle")
    assert sel.selected_policy == "virtual_reference_policy"
    assert sel.advanced_available is False


def test_validation_report_gates():
    cfg = replace(
        default_config(),
        validation_enable=True,
        validation_mae_gate_s=1.5,
        validation_uq_coverage_gate=0.5,
    )
    lap_times = {1: 45.0, 2: 45.4, 3: 45.2, 4: 45.3}
    all_rows = [
        {"lap_number": 1, "gain_s": 0.40},
        {"lap_number": 2, "gain_s": 0.32},
    ]
    bundle_rows = [
        {"lap_number": 1, "predicted_gain_s": 0.35, "actual_lap_time_s": 45.0, "uncertainty_low_s": 44.8, "uncertainty_high_s": 45.3},
        {"lap_number": 2, "predicted_gain_s": 0.30, "actual_lap_time_s": 45.4, "uncertainty_low_s": 45.1, "uncertainty_high_s": 45.6},
    ]
    rep = build_validation_report(
        config=cfg,
        lap_times=lap_times,
        quality_metrics={"score": 0.8},
        calibration_report=None,
        all_lap_optimal_rows=all_rows,
        bundle_lap_rows=bundle_rows,
    )
    assert rep["enabled"] is True
    assert "gates" in rep
    assert "metrics" in rep
