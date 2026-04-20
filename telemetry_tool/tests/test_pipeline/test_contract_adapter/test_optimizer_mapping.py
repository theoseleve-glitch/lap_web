from __future__ import annotations

import pandas as pd

from telemetry_tool.pipeline.contract_adapter.optimizer import build_optimizer_contract
from telemetry_tool.web.schemas.contracts.optimizer import OptimizerDepth


def test_optimizer_depth_is_trajectory_only_for_real_life():
    summary = {
        "sim_method": "trajectory",
        "theoretical_metrics": {"best_s": 59.1},
        "theoretical_confidence": 0.72,
        "corner_coaching": [],
    }
    c = build_optimizer_contract(summary)
    assert c.depth is OptimizerDepth.TRAJECTORY_ONLY
    assert c.method == "trajectory"
    assert c.theoretical_lap_time_s == 59.1
    assert c.reconstructed_inputs is None  # real-life never has this


def test_optimizer_corner_deltas_carry_root_cause():
    summary = {
        "sim_method": "trajectory",
        "theoretical_metrics": {"best_s": 59.1},
        "theoretical_confidence": 0.72,
        "corner_coaching": [
            {"corner_id": 3, "time_loss_s": 0.28, "root_cause": "late_brake_release",
             "summary": "Brake released too late", "phase": "brake_release"},
            {"corner_id": 7, "time_loss_s": 0.18, "root_cause": "late_brake_release",
             "summary": "Smoother trail-brake needed", "phase": "brake_release"},
        ],
    }
    c = build_optimizer_contract(summary)
    assert [cd.corner_id for cd in c.corner_deltas] == ["3", "7"]
    assert c.corner_deltas[0].time_loss_s == 0.28
    assert abs(c.total_time_loss_s - 0.46) < 1e-9


def test_optimizer_trajectory_delta_from_delta_map():
    delta_df = pd.DataFrame({
        "distance_m": [0.0, 100.0, 200.0],
        "speed_delta_mps": [0.0, -0.4, -0.8],
    })
    summary = {
        "sim_method": "trajectory",
        "theoretical_metrics": {"best_s": 59.1},
        "theoretical_confidence": 0.72,
        "corner_coaching": [],
        "delta_map": delta_df,
    }
    c = build_optimizer_contract(summary)
    assert c.trajectory_delta is not None
    assert c.trajectory_delta.distance_m == [0.0, 100.0, 200.0]
    assert c.trajectory_delta.speed_delta_ms == [0.0, -0.4, -0.8]


def test_optimizer_confidence_clamped_to_unit_range():
    summary = {
        "sim_method": "trajectory",
        "theoretical_metrics": {"best_s": 59.1},
        "theoretical_confidence": 1.8,  # out-of-range upstream; must clamp
        "corner_coaching": [],
    }
    c = build_optimizer_contract(summary)
    assert 0.0 <= c.confidence <= 1.0
