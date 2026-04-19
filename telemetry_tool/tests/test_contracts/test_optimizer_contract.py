import pytest
from pydantic import ValidationError

from telemetry_tool.web.schemas.contracts import (
    OptimizerContract,
    OptimizerDepth,
    CornerDelta,
    ReconstructedInputs,
    TrajectoryDelta,
)


def _minimal_optimizer(**overrides) -> OptimizerContract:
    base = {
        "depth": OptimizerDepth.TRAJECTORY_ONLY,
        "method": "trajectory",
        "theoretical_lap_time_s": 90.123,
        "confidence": 0.82,
        "corner_deltas": [],
        "total_time_loss_s": 0.0,
    }
    base.update(overrides)
    return OptimizerContract(**base)


def test_optimizer_minimal():
    o = _minimal_optimizer()
    assert o.depth is OptimizerDepth.TRAJECTORY_ONLY
    assert o.reconstructed_inputs is None


def test_optimizer_confidence_range():
    _minimal_optimizer(confidence=0.0)
    _minimal_optimizer(confidence=1.0)
    with pytest.raises(ValidationError):
        _minimal_optimizer(confidence=1.5)
    with pytest.raises(ValidationError):
        _minimal_optimizer(confidence=-0.1)


def test_full_fidelity_requires_reconstructed_inputs():
    """If depth is FULL_FIDELITY, reconstructed_inputs must be provided."""
    with pytest.raises(ValidationError):
        _minimal_optimizer(depth=OptimizerDepth.FULL_FIDELITY, reconstructed_inputs=None)

    _minimal_optimizer(
        depth=OptimizerDepth.FULL_FIDELITY,
        method="qss_enhanced",
        reconstructed_inputs=ReconstructedInputs(
            throttle=[], brake=[], steer=[], distance_m=[]
        ),
    )


def test_corner_delta_fields():
    cd = CornerDelta(corner_id="3", time_loss_s=0.42, root_cause="late_brake_release",
                    coaching_text="Release the brake ~10m earlier")
    assert cd.time_loss_s == 0.42


def test_trajectory_only_rejects_reconstructed_inputs():
    """TRAJECTORY_ONLY sessions cannot carry reconstructed driver inputs."""
    with pytest.raises(ValidationError):
        _minimal_optimizer(
            depth=OptimizerDepth.TRAJECTORY_ONLY,
            reconstructed_inputs=ReconstructedInputs(throttle=[], brake=[], steer=[], distance_m=[]),
        )


def test_reconstructed_inputs_rejects_length_mismatch():
    """All 4 input arrays must have the same length as distance_m."""
    with pytest.raises(ValidationError):
        ReconstructedInputs(
            distance_m=[0.0, 10.0, 20.0],
            throttle=[0.5, 0.8],            # shorter
            brake=[0.0, 0.0, 0.0],
            steer=[0.0, 0.0, 0.0],
        )


def test_optimizer_contract_json_roundtrip():
    """FULL_FIDELITY contract with nested payload survives JSON roundtrip."""
    o = OptimizerContract(
        depth=OptimizerDepth.FULL_FIDELITY,
        method="qss_enhanced",
        theoretical_lap_time_s=85.5,
        confidence=0.93,
        corner_deltas=[
            CornerDelta(corner_id="1", time_loss_s=0.12, root_cause="late_brake"),
        ],
        total_time_loss_s=0.12,
        trajectory_delta=TrajectoryDelta(distance_m=[0.0, 10.0], speed_delta_ms=[0.0, -0.5]),
        reconstructed_inputs=ReconstructedInputs(
            distance_m=[0.0, 10.0], throttle=[1.0, 1.0], brake=[0.0, 0.0], steer=[0.0, 0.1],
        ),
    )
    payload = o.model_dump_json()
    restored = OptimizerContract.model_validate_json(payload)
    assert restored == o
    assert restored.depth is OptimizerDepth.FULL_FIDELITY
